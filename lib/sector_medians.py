"""Sector-relative scoring engine.

For a given ticker, pull its peers (from lib.data.get_peers), fetch each peer's
quote dict, and compute the median of each scorecard-relevant field. Cache
the result per sector for 7 days.

Used by lib.scoring.score() when mode='sector'.
"""
from __future__ import annotations

from statistics import median
from typing import Any

import streamlit as st

from lib import data as data_mod


# Fields the scorecard cares about, keyed by the threshold key used in scoring.
# direction: 'gt' = higher passes, 'lt' = lower passes.
# Items not in this map stay absolute (analyst, insider, technical signals).
SECTOR_FIELDS = [
    ("fcf_yield", "gt"),
    ("pe_forward", "lt"),      # P/E forward
    ("peg", "lt"),
    ("ev_ebitda", "lt"),
    ("pb", "lt"),
    ("roe", "gt"),             # ROIC proxy
    ("nd_ebitda", "lt"),       # computed
    ("fcf_conv", "gt"),        # computed
    ("operating_margin", "gt"),
    ("gross_margin", "gt"),
    ("rev_growth", "gt"),
]


def _derive_peer_fields(q: dict) -> dict:
    """Compute the same derived fields the scorecard uses from a peer quote."""
    out = dict(q)
    # FCF yield
    fcf = q.get("fcf")
    mc = q.get("market_cap")
    out["fcf_yield"] = (fcf / mc) if (fcf and mc) else None
    # Net Debt / EBITDA
    debt = q.get("total_debt") or 0
    cash = q.get("total_cash") or 0
    ebitda = q.get("ebitda")
    out["nd_ebitda"] = ((debt - cash) / ebitda) if (ebitda and ebitda > 0) else None
    # FCF conversion
    ocf = q.get("ocf")
    out["fcf_conv"] = (fcf / ocf) if (fcf and ocf) else None
    return out


def compute_sector_medians(symbol: str) -> dict[str, Any]:
    """For the given subject ticker, pull peers and compute sector medians.

    Successes are cached 7 days (peers rarely change). FAILURES are NOT cached —
    `_medians_or_raise` raises, and Streamlit's cache doesn't store exceptions, so a
    transient outage that yields too few peers gets retried on the next view instead
    of disabling sector-relative scoring for a week.

    Returns the success dict, or {"err": str, "n": ..., "medians": {}, ...} on failure.
    """
    try:
        return _medians_or_raise(symbol)
    except _SectorDataError as e:
        return {"err": str(e), "n": getattr(e, "n", 0), "medians": {},
                "peers_used": getattr(e, "peers_used", []), "sector": None}


class _SectorDataError(Exception):
    def __init__(self, msg, n=0, peers_used=None):
        super().__init__(msg)
        self.n = n
        self.peers_used = peers_used or []


@st.cache_data(ttl=86400, show_spinner=False)
def _medians_or_raise(symbol: str) -> dict[str, Any]:
    """Heavy worker. Raises _SectorDataError on insufficient data so the failure
    isn't cached. On success returns the medians dict (cached 7 days)."""
    from datetime import datetime
    peers = data_mod.get_peers(symbol)
    if not peers:
        raise _SectorDataError("no peers available", n=0)

    rows: list[dict] = []
    for p in peers[:10]:
        try:
            q = data_mod.get_quote(p)
            if q and not q.get("error"):
                rows.append(_derive_peer_fields(q))
        except Exception:
            continue

    if len(rows) < 3:
        raise _SectorDataError(
            f"only {len(rows)} peer(s) with data, need >=3",
            n=len(rows), peers_used=[r.get("symbol", "?") for r in rows],
        )

    medians: dict[str, float | None] = {}
    for field, _direction in SECTOR_FIELDS:
        vals = []
        for r in rows:
            v = r.get(field)
            if v is None:
                continue
            try:
                fv = float(v)
                # Reject nonsense outliers per field
                if field in ("pe_forward",) and not (0 < fv < 200):
                    continue
                if field == "peg" and not (0 < fv < 5):
                    continue
                if field == "ev_ebitda" and not (0 < fv < 100):
                    continue
                if field == "pb" and not (0 < fv < 50):
                    continue
                if field == "nd_ebitda" and not (-10 < fv < 20):
                    continue
                vals.append(fv)
            except (TypeError, ValueError):
                continue
        medians[field] = median(vals) if vals else None

    return {
        "sector": rows[0].get("sector"),
        "peers_used": [r.get("symbol") for r in rows if r.get("symbol")],
        "n": len(rows),
        "medians": medians,
        "asOf": datetime.utcnow().isoformat(),
    }
