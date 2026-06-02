"""Historical financial trends (5-10 years) via yfinance annual statements.

This is where alpha hides. A 15% ROE this year is meaningless. A 15% ROE for
10 straight years is a Buffett stock. A 15% ROE trending down from 28% is a
falling business priced like a winner.

Pulls Ticker.income_stmt, .balance_sheet, .cashflow (annual; up to ~5 years from yfinance).
Computes per-year metrics + a trajectory classification.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

from lib import fmt as _fmt


# ---------------------------------------------------------------------------
# Row-name lookup helpers — yfinance varies field naming, so we try aliases.
# ---------------------------------------------------------------------------

def _row(df: pd.DataFrame, *names: str) -> pd.Series | None:
    if df is None or df.empty:
        return None
    for n in names:
        if n in df.index:
            return df.loc[n]
    # Try case-insensitive contains-match as fallback
    lower_index = {str(i).lower(): i for i in df.index}
    for n in names:
        nl = n.lower()
        if nl in lower_index:
            return df.loc[lower_index[nl]]
    return None


def _safe_div(a, b):
    try:
        if a is None or b is None:
            return None
        if pd.isna(a) or pd.isna(b) or b == 0:
            return None
        return float(a) / float(b)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main fetcher
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def get_annual_trends(symbol: str, _financials: dict | None = None) -> dict[str, Any]:
    """Return per-year history (5 yrs typical) of key fundamentals.

    Optionally pass `_financials` from financials.get_all(symbol) to avoid
    a redundant yfinance fetch. Underscore prefix tells Streamlit's cache
    decorator not to hash this argument.

    Returned dict:
      {
        "years": ["FY2025", "FY2024", ...],   # most recent first
        "metrics": { ... },
        "trends": { ... },
        "error": str | None,
      }
    """
    if _financials is not None:
        inc = _financials.get("income")
        bal = _financials.get("balance")
        cf = _financials.get("cashflow")
        if _financials.get("error"):
            return {"error": _financials["error"], "years": [], "metrics": {}, "trends": {}}
    else:
        try:
            t = yf.Ticker(symbol)
            inc = t.income_stmt
            bal = t.balance_sheet
            cf = t.cashflow
        except Exception as e:
            return {"error": f"yfinance fetch failed: {e}", "years": [], "metrics": {}, "trends": {}}

    if inc is None or inc.empty:
        return {"error": "No annual income statement", "years": [], "metrics": {}, "trends": {}}

    # Columns are dates, most recent first
    dates = list(inc.columns)
    years = [d.strftime("FY%Y") if hasattr(d, "strftime") else str(d) for d in dates]

    rev = _row(inc, "Total Revenue", "Operating Revenue", "Revenue")
    gross_profit = _row(inc, "Gross Profit")
    op_income = _row(inc, "Operating Income", "Total Operating Income As Reported")
    net_income = _row(inc, "Net Income", "Net Income Common Stockholders",
                       "Net Income From Continuing Operation Net Minority Interest")
    ebitda = _row(inc, "EBITDA", "Normalized EBITDA")
    ebit = _row(inc, "EBIT")
    int_exp = _row(inc, "Interest Expense", "Interest Expense Non Operating")

    # Balance sheet
    assets = _row(bal, "Total Assets")
    equity = _row(bal, "Stockholders Equity", "Common Stock Equity",
                   "Total Equity Gross Minority Interest")
    debt = _row(bal, "Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt")
    cash = _row(bal, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
    invested_cap = _row(bal, "Invested Capital")
    shares = _row(bal, "Ordinary Shares Number", "Share Issued")

    # Cash flow
    fcf = _row(cf, "Free Cash Flow")
    ocf = _row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex = _row(cf, "Capital Expenditure")

    def series_for(date_col) -> dict:
        """Compute metrics for one column (one fiscal year)."""
        rv = lambda s: float(s[date_col]) if s is not None and date_col in s.index and not pd.isna(s[date_col]) else None
        r = rv(rev); gp = rv(gross_profit); oi = rv(op_income); ni = rv(net_income)
        eb = rv(ebitda); ei = rv(ebit); ie = rv(int_exp)
        a = rv(assets); e = rv(equity); d = rv(debt); c = rv(cash); ic = rv(invested_cap)
        s = rv(shares); f = rv(fcf); o = rv(ocf); cx = rv(capex)

        net_debt = (d - c) if (d is not None and c is not None) else None

        return {
            "revenue": r,
            "gross_margin": _safe_div(gp, r),
            "operating_margin": _safe_div(oi, r),
            "net_margin": _safe_div(ni, r),
            "fcf_margin": _safe_div(f, r),
            "roe": _safe_div(ni, e),
            "roa": _safe_div(ni, a),
            "roic": _safe_div(ni, ic) if ic else _safe_div(ni, (e or 0) + (d or 0)) if (e and d) else None,
            "ebitda": eb,
            "ebit": ei,
            "fcf": f,
            "ocf": o,
            "capex": cx,
            "fcf_conv": _safe_div(f, o),
            "interest_coverage": _safe_div(ei, abs(ie)) if ie else None,
            "net_debt": net_debt,
            "nd_ebitda": _safe_div(net_debt, eb) if eb and eb > 0 else None,
            "shares_diluted": s,
            "eps": _safe_div(ni, s) if s else None,
            "net_income": ni,
        }

    # Build per-year metrics
    per_year = [series_for(d) for d in dates]

    metric_ids = ["revenue", "net_income", "gross_margin", "operating_margin", "net_margin",
                  "fcf_margin", "roe", "roa", "roic", "ebitda", "ebit",
                  "fcf", "ocf", "capex", "fcf_conv", "interest_coverage",
                  "net_debt", "nd_ebitda", "shares_diluted", "eps"]

    metrics = {mid: [py.get(mid) for py in per_year] for mid in metric_ids}

    # Compute YoY growth series (most recent first → reverse for chronological diff)
    def yoy_series(vals):
        # vals is most-recent-first. Compute (vals[i]/vals[i+1] - 1) for i = 0..n-2.
        out = []
        for i in range(len(vals)):
            if i + 1 >= len(vals):
                out.append(None)
                continue
            cur, prev = vals[i], vals[i + 1]
            if cur is None or prev is None or prev == 0:
                out.append(None)
            else:
                try:
                    out.append((cur / prev) - 1)
                except (TypeError, ZeroDivisionError):
                    out.append(None)
        return out

    metrics["revenue_growth"] = yoy_series(metrics["revenue"])
    metrics["eps_growth"] = yoy_series(metrics["eps"])

    # Shares change YoY (negative = buybacks)
    metrics["shares_change"] = yoy_series(metrics["shares_diluted"])

    # Classify trajectory for each metric
    trends = {}
    for mid, vals in metrics.items():
        trends[mid] = _classify_trend(mid, vals, years)

    return {
        "symbol": symbol.upper(),
        "years": years,
        "metrics": metrics,
        "trends": trends,
        "n_years": len(years),
        "error": None,
    }


def _classify_trend(metric_id: str, vals: list, years: list) -> dict:
    """Classify a metric trajectory across years (most-recent-first).

    Returns dict with direction, first, last, change, label.
    """
    clean = [(y, v) for y, v in zip(years, vals) if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if len(clean) < 2:
        return {"direction": "insufficient_data", "first": None, "last": None,
                "change": None, "cagr": None, "label": "—"}

    # clean is most-recent-first
    last_y, last_v = clean[0]  # most recent
    first_y, first_v = clean[-1]  # oldest available

    # Direction: fit a line through CHRONOLOGICAL points.
    # Previous bug: xs and ys were each reversed independently, so xs decreased
    # as time progressed forward, flipping the slope sign on every metric.
    # Now xs = [0,1,2,...,n-1] with 0=oldest, n-1=newest. Slope > 0 means
    # the metric truly rose over time.
    chrono = clean[::-1]  # reorder oldest -> newest
    xs = np.arange(len(chrono))
    ys = np.array([c[1] for c in chrono], dtype=float)
    try:
        slope, intercept = np.polyfit(xs, ys, 1)
    except Exception:
        slope = 0.0

    # Erratic detection: coefficient of variation > 50% AND no clear slope
    mean = ys.mean() if len(ys) else 0.0
    std = ys.std() if len(ys) > 1 else 0.0
    cv = abs(std / mean) if mean else float("inf")

    # Cross-check polyfit slope against simple first->last delta. If they
    # disagree (which happens when middle years are noisy), trust the
    # simple direction since the table label shows first->last anyway.
    simple_delta = last_v - first_v
    if slope * simple_delta < 0 and abs(simple_delta) > abs(mean * 0.02):
        # disagreement and the simple delta is non-trivial → use simple sign
        slope = simple_delta

    # Direction
    if abs(slope) < abs(mean * 0.01):  # tiny slope relative to magnitude
        direction = "flat"
    elif cv > 0.5 and abs(slope * len(xs)) < abs(mean * 0.2):
        direction = "erratic"
    elif slope > 0:
        direction = "rising"
    else:
        direction = "falling"

    # CAGR for positive series
    cagr = None
    n_years = len(clean) - 1
    if first_v and last_v and n_years > 0 and first_v > 0 and last_v > 0:
        try:
            cagr = (last_v / first_v) ** (1 / n_years) - 1
        except Exception:
            cagr = None

    # Magnitude qualifier: add "strongly" or "slightly" to rising/falling
    if direction in ("rising", "falling"):
        is_pct_metric = metric_id in (
            "gross_margin", "operating_margin", "net_margin", "fcf_margin",
            "roe", "roa", "roic", "fcf_conv", "revenue_growth", "eps_growth",
            "shares_change",
        )
        if is_pct_metric:
            pp_change = abs(last_v - first_v) * 100
            if pp_change > 3:
                direction = f"{direction} strongly" if direction == "rising" else "falling sharply"
            elif pp_change < 1:
                direction = f"{direction} slightly"
        else:
            abs_cagr = abs(cagr) if cagr is not None else 0
            if abs_cagr > 0.15:
                direction = f"{direction} strongly" if direction == "rising" else "falling sharply"
            elif abs_cagr < 0.03:
                direction = f"{direction} slightly"

    # Label string
    if metric_id in ("revenue", "ebitda", "ebit", "fcf", "ocf", "net_debt", "net_income", "shares_diluted"):
        label = f"{first_y} → {last_y}: {_fmt_money(first_v)} → {_fmt_money(last_v)}"
        if cagr is not None:
            label += f" ({cagr*100:+.1f}% CAGR)"
    elif metric_id in ("gross_margin", "operating_margin", "net_margin", "fcf_margin",
                       "roe", "roa", "roic", "fcf_conv", "revenue_growth", "eps_growth", "shares_change"):
        label = f"{first_y} → {last_y}: {first_v*100:.1f}% → {last_v*100:.1f}%"
    elif metric_id == "nd_ebitda":
        label = f"{first_y} → {last_y}: {first_v:.2f}x → {last_v:.2f}x"
    elif metric_id == "eps":
        label = f"{first_y} → {last_y}: ${first_v:.2f} → ${last_v:.2f}"
        if cagr is not None:
            label += f" ({cagr*100:+.1f}% CAGR)"
    elif metric_id == "interest_coverage":
        label = f"{first_y} → {last_y}: {first_v:.1f}x → {last_v:.1f}x"
    else:
        label = f"{first_y} → {last_y}: {first_v:.2f} → {last_v:.2f}"

    return {
        "direction": direction,
        "first": first_v,
        "last": last_v,
        "change": last_v - first_v if (first_v is not None and last_v is not None) else None,
        "cagr": cagr,
        "label": label,
        "n_obs": len(clean),
    }


_fmt_money = _fmt.fmt_money  # canonical formatter (lib/fmt.py)
