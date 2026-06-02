"""Alert engine — turns the dormant alerts table into an active monitor.

Scans your OPEN THESES and your WATCHLIST against live (cached) quotes and fires
alerts into the alerts table when something you said you'd watch for actually
happens. Dedupes against still-unseen alerts so the same condition doesn't spam.

Signals (all derived from the cached get_quote, so the scan is cheap):
  Open theses : stop hit, target reached, key quality-metric fell below its target
  Watchlist   : price dropped below the 200-day MA, earnings within 5 days,
                near 52-week high / low
"""
from __future__ import annotations

from datetime import date, datetime

from lib import db, data


# Free-text key_metric (as typed in the thesis form) -> (quote field, kind).
# Only "higher is better" metrics: falling below the target = thesis weakening.
_METRIC_MAP = {
    "roic": ("roe", "pct"), "roe": ("roe", "pct"), "roa": ("roa", "pct"),
    "gross margin": ("gross_margin", "pct"), "operating margin": ("operating_margin", "pct"),
    "profit margin": ("profit_margin", "pct"),
    "revenue growth": ("rev_growth", "pct"), "rev growth": ("rev_growth", "pct"),
    "fcf": ("fcf", "money"),
}


def _q(symbol: str) -> dict | None:
    try:
        q = data.get_quote(symbol)
        return q if q and not q.get("error") else None
    except Exception:
        return None


def check_all() -> int:
    """Run every check, fire new alerts, return the count fired this run."""
    unseen = db.get_alerts(seen=False)
    fired = 0
    fired_keys: set = set()

    def fire(sym: str, cat: str, condition: str, value=None):
        """Fire unless an unseen alert of this category already exists for this
        symbol. Dedup is by condition PREFIX (the category), which every condition
        string below begins with — so the '(short)', key-metric, and earnings
        variants no longer slip past and spam a duplicate on every scan."""
        nonlocal fired
        if (sym, cat) in fired_keys:
            return
        if any(a["symbol"] == sym and (a.get("condition") or "").startswith(cat) for a in unseen):
            return
        db.fire_alert(sym, condition, value)
        fired_keys.add((sym, cat))
        fired += 1

    # ---- Open theses ----
    for t in db.get_theses("open"):
        sym = t["symbol"]
        q = _q(sym)
        if not q:
            continue
        px = q.get("price")
        if px is None:
            continue
        side = (t.get("side") or "long").lower()
        stop = t.get("stop_price")
        target = t.get("target_price")

        if side == "long":
            if stop and px <= stop:
                fire(sym, "Stop hit", f"Stop hit: ${px:.2f} ≤ stop ${stop:.2f}", px)
            if target and px >= target:
                fire(sym, "Target reached", f"Target reached: ${px:.2f} ≥ target ${target:.2f}", px)
        else:
            if stop and px >= stop:
                fire(sym, "Stop hit", f"Stop hit (short): ${px:.2f} ≥ stop ${stop:.2f}", px)
            if target and px <= target:
                fire(sym, "Target reached", f"Target reached (short): ${px:.2f} ≤ target ${target:.2f}", px)

        km = (t.get("key_metric") or "").strip().lower()
        kt = t.get("key_metric_target")
        if km in _METRIC_MAP and kt is not None:
            field, kind = _METRIC_MAP[km]
            val = q.get(field)
            if val is not None:
                cur = val * 100 if kind == "pct" else val
                if cur < float(kt):
                    label = t.get("key_metric") or km
                    fire(sym, f"{label} below",
                         f"{label} below target: {cur:.1f} < {float(kt):.1f}", cur)

    # ---- Watchlist ----
    for sym in db.get_watchlist():
        q = _q(sym)
        if not q:
            continue
        px = q.get("price")
        d200 = q.get("dma_200")
        hi = q.get("year_high")
        lo = q.get("year_low")
        ne = q.get("next_earnings")

        if px and d200 and px < d200:
            fire(sym, "Below 200DMA",
                 f"Below 200DMA: ${px:.2f} < ${d200:.2f} (trend risk)", px)
        if px and hi and px >= hi * 0.98:
            fire(sym, "Near 52w high", f"Near 52w high: ${px:.2f} (hi ${hi:.2f})", px)
        if px and lo and px <= lo * 1.03:
            fire(sym, "Near 52w low", f"Near 52w low: ${px:.2f} (lo ${lo:.2f})", px)
        if ne:
            try:
                ned = datetime.strptime(str(ne)[:10], "%Y-%m-%d").date()
                dd = (ned - date.today()).days
                if 0 <= dd <= 5:
                    fire(sym, "Earnings", f"Earnings in {dd}d ({ne})", None)
            except Exception:
                pass

    return fired


def unseen_count() -> int:
    try:
        return len(db.get_alerts(seen=False))
    except Exception:
        return 0
