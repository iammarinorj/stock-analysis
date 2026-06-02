"""One-shot cached financials fetcher.

Pulls annual + quarterly income statements, balance sheet, and cash flow in a
single cached call. Consumers (trends, quality_flags, key-metric tiles) all
share this so we don't hammer yfinance.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st
import yfinance as yf

from lib import http as _http


@st.cache_data(ttl=3600, show_spinner=False)
def get_all(symbol: str) -> dict[str, Any]:
    """Pull all financial statements in one cached read.

    Returns:
      {symbol, income, balance, cashflow, q_income (quarterly income, best-effort),
       info (always {}), error}
    """
    try:
        t = yf.Ticker(symbol)
        # Retry the first (network) read; the rest are served from yf per-Ticker cache.
        income = _http.with_retry(lambda: t.income_stmt, attempts=3, backoff=0.5)
        balance = t.balance_sheet
        cashflow = t.cashflow
        try:
            q_income = t.quarterly_income_stmt
        except Exception:
            q_income = None
        return {
            "symbol": symbol.upper(),
            "income": income if income is not None and not income.empty else None,
            "balance": balance if balance is not None and not balance.empty else None,
            "cashflow": cashflow if cashflow is not None and not cashflow.empty else None,
            "q_income": q_income if q_income is not None and not q_income.empty else None,
            "info": {},
            "error": None,
        }
    except Exception as e:
        return {
            "symbol": symbol.upper(),
            "income": None, "balance": None, "cashflow": None, "q_income": None,
            "info": {}, "error": str(e),
        }


@st.cache_data(ttl=3600, show_spinner=False)
def get_price_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    """Cached price history (separate function so cache works independently)."""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, auto_adjust=False)
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def get_period_snapshot(financials: dict, quote: dict | None = None) -> dict:
    """Extract most recent quarterly + annual revenue and net income.

    When quarterly statements are missing (common for foreign ADRs like NTDOY),
    falls back to TTM values from the quote dict (sourced from yfinance .info).

    Returns dict with keys: q_rev, q_rev_period, q_ni, q_ni_period,
    fy_rev, fy_rev_period, fy_ni, fy_ni_period. Missing values are None.
    """
    out = {
        "q_rev": None, "q_rev_period": None,
        "q_ni": None, "q_ni_period": None,
        "fy_rev": None, "fy_rev_period": None,
        "fy_ni": None, "fy_ni_period": None,
    }
    if not financials:
        return out

    rev_names = ("Total Revenue", "Operating Revenue", "Revenue")
    ni_names = (
        "Net Income",
        "Net Income Common Stockholders",
        "Net Income From Continuing Operation Net Minority Interest",
    )

    def _first_value(df, row_names):
        if df is None or df.empty:
            return None, None
        for col in df.columns:
            for name in row_names:
                if name in df.index:
                    v = df.loc[name, col]
                    if v is not None and not (isinstance(v, float) and v != v):
                        try:
                            return float(v), col
                        except (TypeError, ValueError):
                            continue
        return None, None

    def _fmt_q(col):
        if col is None or not hasattr(col, "month"):
            return None
        q = (col.month - 1) // 3 + 1
        return f"Q{q} FY{col.year}"

    def _fmt_fy(col):
        if col is None or not hasattr(col, "year"):
            return None
        return f"FY{col.year}"

    q_inc = financials.get("q_income")
    qr_val, qr_col = _first_value(q_inc, rev_names)
    qn_val, qn_col = _first_value(q_inc, ni_names)
    out["q_rev"], out["q_rev_period"] = qr_val, _fmt_q(qr_col)
    out["q_ni"], out["q_ni_period"] = qn_val, _fmt_q(qn_col)

    # Fallback: when quarterly statements are missing or empty (foreign ADRs,
    # newly-listed), use TTM values from the quote (yfinance .info).
    q = quote or {}
    if out["q_rev"] is None and q.get("revenue"):
        out["q_rev"] = q["revenue"]
        out["q_rev_period"] = "TTM"
    if out["q_ni"] is None and q.get("net_income"):
        out["q_ni"] = q["net_income"]
        out["q_ni_period"] = "TTM"

    a_inc = financials.get("income")
    ar_val, ar_col = _first_value(a_inc, rev_names)
    an_val, an_col = _first_value(a_inc, ni_names)
    out["fy_rev"], out["fy_rev_period"] = ar_val, _fmt_fy(ar_col)
    out["fy_ni"], out["fy_ni_period"] = an_val, _fmt_fy(an_col)

    return out
