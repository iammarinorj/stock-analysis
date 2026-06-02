"""14-criterion weighted scorecard. Pure functions - takes data dict, returns scorecard."""
from __future__ import annotations

from typing import Any

from lib import fmt as _fmt


# Each item: id, category, weight, label, note
SCORECARD_ITEMS = [
    # Valuation (max 7 weighted points)
    {"id": "fcf_yield", "cat": "val", "w": 2, "label": "FCF yield > 5%",
     "note": "Cash-on-cash return for owners."},
    {"id": "fwd_pe", "cat": "val", "w": 2, "label": "Forward P/E < 20x",
     "note": "Reasonable forward multiple."},
    {"id": "peg", "cat": "val", "w": 1, "label": "PEG < 1.0",
     "note": "Growth-adjusted cheap."},
    {"id": "ev_ebitda", "cat": "val", "w": 1, "label": "EV/EBITDA < 15x",
     "note": "Capital-structure-neutral cheapness."},
    {"id": "pb", "cat": "val", "w": 1, "label": "P/B < 4x or ROE > 15% (quality premium)",
     "note": "Asset/quality-justified valuation."},
    # Quality (max 7)
    {"id": "roic", "cat": "qual", "w": 2, "label": "ROIC/ROE > 15%",
     "note": "Single best quality filter (yfinance gives ROE not ROIC)."},
    {"id": "leverage", "cat": "qual", "w": 2, "label": "Net Debt/EBITDA < 2x",
     "note": "Balance sheet strength."},
    {"id": "fcf_conv", "cat": "qual", "w": 1, "label": "FCF / OCF > 70%",
     "note": "Real cash conversion."},
    {"id": "op_margin", "cat": "qual", "w": 1, "label": "Operating margin > 15%",
     "note": "Pricing power and discipline."},
    {"id": "gross_margin", "cat": "qual", "w": 1, "label": "Gross margin > 40%",
     "note": "Munger's moat test."},
    # Catalyst (max 4)
    {"id": "insider_own", "cat": "cat", "w": 2, "label": "Insider ownership > 3%",
     "note": "Founder/management alignment proxy (yfinance limit - actual buying needs separate check)."},
    {"id": "rev_growth", "cat": "cat", "w": 1, "label": "Revenue growth > 10% YoY",
     "note": "Top-line growth."},
    {"id": "analyst", "cat": "cat", "w": 1, "label": "Consensus Buy or Strong Buy",
     "note": "Sell-side conviction."},
    # Technical / sentiment (max 3)
    {"id": "tech_ok", "cat": "tech", "w": 1, "label": "Price above 200 DMA",
     "note": "Avoid the falling-knife trap."},
    {"id": "rsi_ok", "cat": "tech", "w": 1, "label": "RSI (14) in healthy zone (30-70)",
     "note": "<30 = oversold (could be falling-knife), >70 = overbought (chase risk)."},
    {"id": "short_int", "cat": "tech", "w": 1, "label": "Short interest < 10% of float",
     "note": "Low SI = no bearish overhang. 10-20% elevated. >20% = strong short conviction or squeeze setup."},
]

CATS = {
    "val": {"name": "Valuation", "desc": "is it cheap"},
    "qual": {"name": "Quality", "desc": "is it good"},
    "cat": {"name": "Catalyst", "desc": "why now"},
    "tech": {"name": "Technical", "desc": "not a falling knife"},
}

MAX_SCORE = sum(item["w"] for item in SCORECARD_ITEMS)


def score(quote: dict[str, Any], sector_medians: dict | None = None) -> dict[str, Any]:
    """Take a quote dict (from data.get_quote), return per-item evaluation + totals.

    Args:
        quote: enriched quote dict from data.get_enriched_quote().
        sector_medians: optional dict from lib.sector_medians.compute_sector_medians().
            When provided, comparable criteria use the sector median as threshold
            instead of the hardcoded absolute value. Falls back to absolute for any
            field missing from the medians.

    Returns:
        {
          "items": {id: {"pass": bool, "actual": str, "note": str, ...}},
          "by_cat": {cat: {"s": passed_weight, "m": max_weight, "pct": float}},
          "total": int, "max": int, "pct": float,
          "verdict": {"head": str, "explain": str, "color": str},
          "mode": "sector" | "absolute",
          "sector": str | None,
        }
    """
    if not quote or quote.get("error"):
        return {"items": {}, "by_cat": {}, "total": 0, "max": MAX_SCORE, "pct": 0,
                "verdict": {"head": "No data", "explain": "Quote data unavailable.", "color": "gray"},
                "mode": "absolute", "sector": None}

    items: dict[str, dict] = {}

    # ---- Threshold resolver: sector median if available, else absolute ----
    medians = (sector_medians or {}).get("medians", {}) if sector_medians else {}
    sector_name = (sector_medians or {}).get("sector") if sector_medians else None

    # Generous bounds for sector medians — if the median is outside these
    # ranges it's likely bad data and we fall back to the absolute threshold.
    _MEDIAN_BOUNDS: dict[str, tuple[float, float]] = {
        "pe_forward": (0, 500), "ev_ebitda": (0, 500), "peg": (0, 500),
        "roe": (-1.0, 5.0), "operating_margin": (-1.0, 5.0),
        "gross_margin": (-1.0, 5.0), "fcf_yield": (-1.0, 5.0),
        "fcf_conv": (-1.0, 5.0), "rev_growth": (-1.0, 5.0),
        "nd_ebitda": (-10, 50),
        "pb": (0, 100),
    }

    def _thr(field: str, absolute: float) -> tuple[float, bool]:
        """Return (threshold_value, is_sector_relative)."""
        if medians and medians.get(field) is not None:
            median = float(medians[field])
            lo, hi = _MEDIAN_BOUNDS.get(field, (None, None))
            if lo is not None and (median <= lo or median > hi):
                return absolute, False
            return median, True
        return absolute, False

    def _tag(is_sector: bool, threshold_val: float, fmt: str = "x") -> str:
        """Produce ' vs sector median X' or ' (>X abs)' suffix."""
        if is_sector:
            if fmt == "pct":
                return f" vs {sector_name or 'sector'} median {threshold_val*100:.1f}%"
            return f" vs {sector_name or 'sector'} median {threshold_val:.1f}{fmt}"
        return ""

    # FCF yield = FCF / market_cap (higher better)
    fcf = quote.get("fcf")
    mc = quote.get("market_cap")
    fcf_yield = (fcf / mc) if (fcf and mc) else None
    fcfy_thr, fcfy_is_sec = _thr("fcf_yield", 0.05)
    items["fcf_yield"] = _judge(
        actual=(_pct(fcf_yield) + f" (FCF {_money(fcf)} / MC {_money(mc)})" + _tag(fcfy_is_sec, fcfy_thr, "pct")) if fcf_yield is not None else "—",
        passed=(fcf_yield is not None and fcf_yield > fcfy_thr),
        note=(f"Need > {fcfy_thr*100:.1f}% ({sector_name or 'sector'} median)" if fcfy_is_sec else "Need > 5%"),
    )

    # Forward P/E (fallback to trailing if forward missing) - lower better
    fwd_pe = quote.get("pe_forward") or quote.get("pe_trailing")
    pe_thr, pe_is_sec = _thr("pe_forward", 20.0)
    items["fwd_pe"] = _judge(
        actual=(f"{fwd_pe:.1f}x" + _tag(pe_is_sec, pe_thr, "x")) if fwd_pe else "—",
        passed=(fwd_pe is not None and 0 < fwd_pe < pe_thr),
        note=(f"Need < {pe_thr:.1f}x ({sector_name or 'sector'} median)" if pe_is_sec else "Need < 20x. Below 15 = absolute cheap."),
    )

    # PEG - lower better, only positive counts
    peg = quote.get("peg")
    peg_thr, peg_is_sec = _thr("peg", 1.0)
    items["peg"] = _judge(
        actual=(f"{peg:.2f}" + _tag(peg_is_sec, peg_thr, "")) if peg else "—",
        passed=(peg is not None and 0 < peg < peg_thr),
        note=(f"Need < {peg_thr:.2f} ({sector_name or 'sector'} median)" if peg_is_sec else "Lynch: PEG < 1 = cheap on growth."),
    )

    # EV/EBITDA - lower better
    eb = quote.get("ev_ebitda")
    ev_thr, ev_is_sec = _thr("ev_ebitda", 15.0)
    items["ev_ebitda"] = _judge(
        actual=(f"{eb:.1f}x" + _tag(ev_is_sec, ev_thr, "x")) if eb else "—",
        passed=(eb is not None and 0 < eb < ev_thr),
        note=(f"Need < {ev_thr:.1f}x ({sector_name or 'sector'} median)" if ev_is_sec else "Need < 15x. < 8x = cheap."),
    )

    # P/B with quality override (override only in absolute mode)
    pb = quote.get("pb")
    roe = quote.get("roe")
    pb_thr, pb_is_sec = _thr("pb", 4.0)
    if pb_is_sec:
        pb_pass = pb is not None and 0 < pb < pb_thr
        pb_note = f"Need < {pb_thr:.1f}x ({sector_name or 'sector'} median)"
    else:
        pb_pass = False
        if pb is not None:
            if pb < 4:
                pb_pass = True
            elif roe is not None and roe > 0.15:
                pb_pass = True
        pb_note = "P/B < 4 or quality justified."
    items["pb"] = _judge(
        actual=(f"P/B {pb:.1f}x" + (f", ROE {_pct(roe, 1)}" if roe else "") + _tag(pb_is_sec, pb_thr, "x")) if pb else "—",
        passed=pb_pass,
        note=pb_note,
    )

    # ROIC proxy via ROE (higher better)
    roe_thr, roe_is_sec = _thr("roe", 0.15)
    items["roic"] = _judge(
        actual=(f"ROE {_pct(roe, 1)}" + _tag(roe_is_sec, roe_thr, "pct")) if roe else "—",
        passed=(roe is not None and roe > roe_thr),
        note=(f"Need > {roe_thr*100:.1f}% ({sector_name or 'sector'} median)" if roe_is_sec else "Need > 15%. ROIC would be better but ROE is the yfinance proxy."),
    )

    # Net Debt / EBITDA - lower better
    debt = quote.get("total_debt") or 0
    cash = quote.get("total_cash") or 0
    ebitda = quote.get("ebitda")
    nde = None
    if ebitda and ebitda > 0:
        nde = (debt - cash) / ebitda
    nde_thr, nde_is_sec = _thr("nd_ebitda", 2.0)
    items["leverage"] = _judge(
        actual=(f"Net Debt/EBITDA {nde:.2f}x" + (" (net cash)" if nde is not None and nde < 0 else "") + _tag(nde_is_sec, nde_thr, "x")) if nde is not None else "—",
        passed=(nde is not None and nde < nde_thr),
        note=(f"Need < {nde_thr:.2f}x ({sector_name or 'sector'} median)" if nde_is_sec else "Need < 2x. Negative = net cash position."),
    )

    # FCF conversion - higher better
    ocf = quote.get("ocf")
    conv = (fcf / ocf) if (fcf and ocf) else None
    fcf_conv_thr, fcf_conv_is_sec = _thr("fcf_conv", 0.70)
    items["fcf_conv"] = _judge(
        actual=(f"{_pct(conv, 0)}" + _tag(fcf_conv_is_sec, fcf_conv_thr, "pct")) if conv is not None else "—",
        passed=(conv is not None and conv > fcf_conv_thr),
        note=(f"Need > {fcf_conv_thr*100:.0f}% ({sector_name or 'sector'} median)" if fcf_conv_is_sec else "Need > 70%. Below = heavy capex or earnings ≠ cash."),
    )

    # Operating margin - higher better
    om = quote.get("operating_margin")
    om_thr, om_is_sec = _thr("operating_margin", 0.15)
    items["op_margin"] = _judge(
        actual=(_pct(om, 1) + _tag(om_is_sec, om_thr, "pct")) if om is not None else "—",
        passed=(om is not None and om > om_thr),
        note=(f"Need > {om_thr*100:.1f}% ({sector_name or 'sector'} median)" if om_is_sec else "Need > 15%. > 30% = elite."),
    )

    # Gross margin - higher better
    gm = quote.get("gross_margin")
    gm_thr, gm_is_sec = _thr("gross_margin", 0.40)
    items["gross_margin"] = _judge(
        actual=(_pct(gm, 1) + _tag(gm_is_sec, gm_thr, "pct")) if gm is not None else "—",
        passed=(gm is not None and gm > gm_thr),
        note=(f"Need > {gm_thr*100:.1f}% ({sector_name or 'sector'} median)" if gm_is_sec else "Munger: > 50% = moat. > 40% = healthy."),
    )

    # Insider — prefer cluster-buy signal if available, fall back to ownership %
    cluster = quote.get("insider_cluster_buy")
    buy_count = quote.get("insider_buys_6mo", 0) or 0
    sell_count = quote.get("insider_sells_6mo", 0) or 0
    insider_trans = quote.get("insider_trans")  # Finviz "Insider Trans" - net % of float over 6mo
    ins_own = quote.get("held_insiders") or quote.get("insider_own")

    if cluster is not None or buy_count or insider_trans is not None:
        # We have transaction data - use the higher-quality signal
        passed = bool(cluster) or (insider_trans is not None and insider_trans > 0)
        if cluster:
            actual = f"Cluster buying: {buy_count} buys / {sell_count} sells last 6mo"
        elif buy_count > sell_count and buy_count > 0:
            actual = f"Net buying: {buy_count} buys / {sell_count} sells"
        elif insider_trans is not None and insider_trans > 0:
            actual = f"Net buying ({insider_trans*100:+.2f}% of float)"
        elif insider_trans is not None and insider_trans < 0:
            actual = f"Net selling ({insider_trans*100:+.2f}% of float)"
        else:
            actual = f"{buy_count} buys / {sell_count} sells last 6mo"
        items["insider_own"] = _judge(
            actual=actual,
            passed=passed,
            note="Cluster buying or net positive insider transactions = strongest signal.",
        )
    else:
        # Fall back to ownership %
        items["insider_own"] = _judge(
            actual=_pct(ins_own, 2) if ins_own is not None else "—",
            passed=(ins_own is not None and ins_own > 0.03),
            note="Founder/exec alignment proxy. >3% OK, >10% strong.",
        )

    # Revenue growth - higher better
    rg = quote.get("rev_growth")
    rg_thr, rg_is_sec = _thr("rev_growth", 0.10)
    items["rev_growth"] = _judge(
        actual=(_pct(rg, 1) + _tag(rg_is_sec, rg_thr, "pct")) if rg is not None else "—",
        passed=(rg is not None and rg > rg_thr),
        note=(f"Need > {rg_thr*100:.1f}% YoY ({sector_name or 'sector'} median)" if rg_is_sec else "Need > 10% YoY."),
    )

    # Analyst consensus
    rec = (quote.get("recommend") or "").lower()
    items["analyst"] = _judge(
        actual=f"{rec.upper()}" + (f" (n={quote.get('n_analysts')})" if quote.get('n_analysts') else "") if rec else "—",
        passed=("buy" in rec or "strong_buy" in rec),
        note="Sell-side conviction.",
    )

    # Price above 200 DMA
    px = quote.get("price")
    d200 = quote.get("dma_200")
    techok = px is not None and d200 is not None and px > d200
    if px and d200:
        delta_pct = (px / d200 - 1) * 100
        actual_str = f"${px:.2f} vs 200DMA ${d200:.2f} ({delta_pct:+.1f}%)"
    else:
        actual_str = "—"
    items["tech_ok"] = _judge(
        actual=actual_str,
        passed=techok,
        note="Avoid falling-knife pattern.",
    )

    # RSI (14) - from Finviz
    rsi = quote.get("rsi_14")
    if rsi is not None:
        rsi_ok = 30 <= rsi <= 70
        if rsi < 30:
            rsi_note = f"Oversold ({rsi:.1f}). Could be falling-knife or bounce setup."
        elif rsi > 70:
            rsi_note = f"Overbought ({rsi:.1f}). Chase risk - wait for pullback."
        else:
            rsi_note = f"Healthy ({rsi:.1f}). Neither overbought nor oversold."
        items["rsi_ok"] = _judge(
            actual=f"RSI {rsi:.1f}",
            passed=rsi_ok,
            note=rsi_note,
        )
    else:
        items["rsi_ok"] = _judge(actual="—", passed=False, note="RSI not available")

    # Short interest - prefer Finviz short_float (more current), fall back to yfinance
    short_pct = quote.get("short_float")
    if short_pct is None:
        short_pct = quote.get("short_pct_float")
    if short_pct is not None:
        if short_pct < 0.05:
            si_note = f"Very low ({short_pct*100:.2f}%). No bearish overhang."
        elif short_pct < 0.10:
            si_note = f"Healthy ({short_pct*100:.2f}%). No meaningful short pressure."
        elif short_pct < 0.20:
            si_note = f"Elevated ({short_pct*100:.2f}%). Shorts taking a position - know why."
        else:
            si_note = f"High ({short_pct*100:.2f}%). Strong bearish conviction OR squeeze setup."
        items["short_int"] = _judge(
            actual=f"{short_pct*100:.2f}% of float",
            passed=(short_pct < 0.10),
            note=si_note,
        )
    else:
        items["short_int"] = _judge(actual="—", passed=False, note="Short interest not available")

    # Roll up
    by_cat = {c: {"s": 0, "m": 0} for c in CATS}
    total_s = 0
    for it in SCORECARD_ITEMS:
        ev = items[it["id"]]
        ev["weight"] = it["w"]
        ev["category"] = it["cat"]
        ev["label"] = it["label"]
        by_cat[it["cat"]]["m"] += it["w"]
        if ev["pass"]:
            by_cat[it["cat"]]["s"] += it["w"]
            total_s += it["w"]
    for c in by_cat:
        m = by_cat[c]["m"]
        by_cat[c]["pct"] = (by_cat[c]["s"] / m) if m else 0

    pct = total_s / MAX_SCORE if MAX_SCORE else 0
    verdict = _diagnose(by_cat, total_s, pct)

    mode = "sector" if medians else "absolute"
    return {
        "items": items,
        "by_cat": by_cat,
        "total": total_s,
        "max": MAX_SCORE,
        "pct": pct,
        "verdict": verdict,
        "mode": mode,
        "sector": sector_name,
        "n_peers": (sector_medians or {}).get("n") if sector_medians else None,
        "peers_used": (sector_medians or {}).get("peers_used") if sector_medians else None,
    }


def _judge(actual: str, passed: bool, note: str) -> dict:
    return {"actual": actual, "pass": bool(passed), "note": note}


# Delegate to the canonical formatters (lib/fmt.py).
_pct = _fmt.fmt_pct
_money = _fmt.fmt_money


def _diagnose(by_cat: dict, total: int, pct: float) -> dict:
    v = by_cat["val"]["pct"]
    q = by_cat["qual"]["pct"]
    c = by_cat["cat"]["pct"]
    t = by_cat["tech"]["pct"]

    if total == 0:
        return {"head": "No data", "explain": "Run a ticker first.", "color": "gray"}

    if pct < 0.15:
        return {"head": "Probably overvalued or distressed",
                "explain": "Very few items checked. Either work hasn't been done or this fails most tests. Pass or short watchlist.",
                "color": "red"}

    if v >= 0.6 and q >= 0.6 and c >= 0.6:
        return {"head": "Strong undervalued case",
                "explain": "All three legs support the thesis - cheap, quality, catalysts present. Classic value setup. Size up with discipline.",
                "color": "darkgreen"}

    if v >= 0.8 and q >= 0.8:
        return {"head": "Quality compounder on sale",
                "explain": "Cheap AND high quality. Buy and be patient - catalyst gap would accelerate but isn't required.",
                "color": "green"}

    if v >= 0.6 and q < 0.4:
        gap = by_cat["qual"]["m"] - by_cat["qual"]["s"]
        return {"head": "Value trap risk - cheap but quality weak",
                "explain": f"Statistically cheap but quality fails - missing {gap} of {by_cat['qual']['m']} quality points. Cheap stocks stay cheap when business deteriorates. Need at least 3 quality items before buying.",
                "color": "red"}

    if q >= 0.6 and v < 0.4:
        return {"head": "Quality but full price",
                "explain": f"Good business, not undervalued. Quality strong ({by_cat['qual']['s']}/{by_cat['qual']['m']}) but valuation only {by_cat['val']['s']}/{by_cat['val']['m']}. Compound at trend rate, no multiple expansion. Watchlist for pullback.",
                "color": "amber"}

    if v >= 0.5 and q >= 0.5 and c < 0.3:
        return {"head": "Cheap and good, no catalyst yet",
                "explain": f"Decent setup but no catalyst visible ({by_cat['cat']['s']}/{by_cat['cat']['m']}). Build small, add on the catalyst.",
                "color": "yellow"}

    if pct >= 0.5:
        return {"head": "Moderate undervalued case",
                "explain": f"Mixed. Val {by_cat['val']['s']}/{by_cat['val']['m']}, Qual {by_cat['qual']['s']}/{by_cat['qual']['m']}, Cat {by_cat['cat']['s']}/{by_cat['cat']['m']}. Need one category to upgrade to strong.",
                "color": "yellow"}

    # Weak
    gaps = []
    if v < 0.5:
        gaps.append(f"Valuation ({by_cat['val']['s']}/{by_cat['val']['m']})")
    if q < 0.5:
        gaps.append(f"Quality ({by_cat['qual']['s']}/{by_cat['qual']['m']})")
    if c < 0.5:
        gaps.append(f"Catalyst ({by_cat['cat']['s']}/{by_cat['cat']['m']})")
    tech_warn = ""
    if t == 0 and total >= 4:
        tech_warn = " Technical sanity also missing - could be a falling knife."

    return {"head": "Weak case - work the gaps",
            "explain": "Biggest gaps: " + ", ".join(gaps) + "." + tech_warn,
            "color": "red"}
