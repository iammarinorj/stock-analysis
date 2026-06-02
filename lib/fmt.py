"""Canonical number formatters — the single source of truth for money/percent
display across the whole app.

Previously six near-duplicate copies lived in ui.py, data.py, scoring.py,
trends.py, calendar_events.py and extra_metrics.py. They disagreed (some used a
bogus "TH" suffix for thousands, some 1 decimal vs 2), so the same value rendered
differently depending on which page you were on. Everything now delegates here.

Dependency-free on purpose, so any module can import it without cycles.
"""
from __future__ import annotations

from typing import Any


def is_nan(v: Any) -> bool:
    """True for a float NaN (the `v != v` trick), False otherwise."""
    try:
        return isinstance(v, float) and v != v
    except Exception:
        return False


def fmt_money(v: float | None, decimals: int = 2) -> str:
    """Dollar amount with K/M/B/T suffixes. Default 2 decimals everywhere."""
    if v is None or is_nan(v):
        return "—"
    av = abs(v)
    sign = "-" if v < 0 else ""
    if av >= 1e12:
        return f"{sign}${av/1e12:.{decimals}f}T"
    if av >= 1e9:
        return f"{sign}${av/1e9:.{decimals}f}B"
    if av >= 1e6:
        return f"{sign}${av/1e6:.{decimals}f}M"
    if av >= 1e3:
        return f"{sign}${av/1e3:.{decimals}f}K"
    return f"{sign}${av:.{decimals}f}"


def fmt_pct(v: float | None, decimals: int = 2) -> str:
    """Decimal fraction → percent string (0.215 → '21.50%')."""
    if v is None or is_nan(v):
        return "—"
    return f"{v*100:.{decimals}f}%"


def fmt_delta_pct(v: float | None, decimals: int = 2) -> str:
    """Signed percent (always shows + for non-negative)."""
    if v is None or is_nan(v):
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v*100:.{decimals}f}%"


def fmt_num(v: float | None, decimals: int = 2) -> str:
    if v is None or is_nan(v):
        return "—"
    return f"{v:.{decimals}f}"
