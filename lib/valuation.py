"""Valuation models: Reverse DCF, owner earnings, Greenwald EPV, fair-price bands.

The single most useful valuation question is NOT "what is this worth" — it's
"what does this need to do to justify today's price?" That's reverse DCF.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Forward DCF (2-stage)
# ---------------------------------------------------------------------------

def forward_dcf(
    fcf_base: float,
    growth_high: float,
    high_years: int,
    growth_terminal: float,
    discount: float,
    shares: float,
    net_cash: float = 0,
) -> dict[str, Any]:
    """Standard 2-stage DCF.

    Returns: fair_value_per_share, equity_value, pv_high, pv_terminal.
    """
    if not all([fcf_base > 0, shares > 0, discount > growth_terminal]):
        return {"error": "Invalid inputs (FCF > 0, shares > 0, discount > terminal growth required)"}

    pv_high = 0
    fcf = fcf_base
    for y in range(1, high_years + 1):
        fcf = fcf * (1 + growth_high)
        pv_high += fcf / ((1 + discount) ** y)

    # Terminal value (Gordon growth)
    terminal_fcf = fcf * (1 + growth_terminal)
    terminal_value = terminal_fcf / (discount - growth_terminal)
    pv_terminal = terminal_value / ((1 + discount) ** high_years)

    enterprise_pv = pv_high + pv_terminal
    equity_value = enterprise_pv + net_cash
    per_share = equity_value / shares

    return {
        "fair_value_per_share": per_share,
        "equity_value": equity_value,
        "pv_high_stage": pv_high,
        "pv_terminal": pv_terminal,
        "terminal_pct_of_value": pv_terminal / enterprise_pv if enterprise_pv else 0,
    }


# ---------------------------------------------------------------------------
# Reverse DCF — the killer feature
# ---------------------------------------------------------------------------

def projection_dcf(
    price: float,
    revenue_today: float,
    rev_growth_high: float,
    high_years: int,
    target_fcf_margin: float,
    margin_ramp_years: int,
    discount: float,
    growth_terminal: float,
    shares: float,
    net_cash: float = 0,
) -> dict[str, Any]:
    """DCF for pre-profit / inflection companies.

    Instead of starting from today's FCF (often negative or tiny), we project:
      1. Revenue grows at rev_growth_high for high_years
      2. FCF margin ramps linearly from 0% to target_fcf_margin over margin_ramp_years
      3. After high_years, terminal Gordon-growth at growth_terminal
      4. Discount everything back to today

    This is how analysts actually value AAOI / CRDO / ALAB types.
    """
    if not all([price > 0, revenue_today > 0, shares > 0, discount > growth_terminal]):
        return {"error": "Inputs invalid (price, revenue, shares positive; discount > terminal growth)"}

    pv_high = 0
    rev = revenue_today
    last_fcf = 0
    for y in range(1, high_years + 1):
        rev = rev * (1 + rev_growth_high)
        # Linear margin ramp
        if margin_ramp_years <= 0:
            margin_y = target_fcf_margin
        else:
            margin_y = target_fcf_margin * min(1.0, y / margin_ramp_years)
        fcf_y = rev * margin_y
        last_fcf = fcf_y
        pv_high += fcf_y / ((1 + discount) ** y)

    # Terminal value from last year's FCF
    terminal_fcf = last_fcf * (1 + growth_terminal)
    terminal_value = terminal_fcf / (discount - growth_terminal)
    pv_terminal = terminal_value / ((1 + discount) ** high_years)

    enterprise_pv = pv_high + pv_terminal
    equity_value = enterprise_pv + net_cash
    per_share = equity_value / shares
    mos = (per_share - price) / per_share if per_share > 0 else 0

    return {
        "fair_value_per_share": per_share,
        "equity_value": equity_value,
        "pv_high_stage": pv_high,
        "pv_terminal": pv_terminal,
        "terminal_pct_of_value": pv_terminal / enterprise_pv if enterprise_pv else 0,
        "last_year_revenue": rev,
        "last_year_fcf": last_fcf,
        "margin_of_safety": mos,
        "assumptions": {
            "revenue_today": revenue_today,
            "rev_growth_high": rev_growth_high,
            "high_years": high_years,
            "target_fcf_margin": target_fcf_margin,
            "margin_ramp_years": margin_ramp_years,
            "discount": discount,
            "growth_terminal": growth_terminal,
        },
    }


def reverse_dcf(
    price: float,
    fcf_base: float,
    shares: float,
    high_years: int = 10,
    growth_terminal: float = 0.025,
    discount: float = 0.09,
    net_cash: float = 0,
) -> dict[str, Any]:
    """Solve for the high-stage growth rate implied by today's price.

    Bisection between -10% and +50% annual growth.
    Returns implied growth + a verdict.
    """
    if not all([price > 0, fcf_base > 0, shares > 0]):
        return {"error": "Inputs must all be positive."}

    target_equity = price * shares
    target_enterprise = target_equity - net_cash

    def dcf_at(g):
        pv_high = 0
        fcf = fcf_base
        for y in range(1, high_years + 1):
            fcf = fcf * (1 + g)
            pv_high += fcf / ((1 + discount) ** y)
        terminal_fcf = fcf * (1 + growth_terminal)
        terminal_value = terminal_fcf / (discount - growth_terminal)
        pv_terminal = terminal_value / ((1 + discount) ** high_years)
        return pv_high + pv_terminal

    # Bisection
    lo, hi = -0.10, 0.50
    for _ in range(60):
        mid = (lo + hi) / 2
        v = dcf_at(mid)
        if v < target_enterprise:
            lo = mid
        else:
            hi = mid
        if abs(hi - lo) < 1e-5:
            break

    implied_g = (lo + hi) / 2

    # Verdict
    if implied_g < 0.04:
        verdict = "Pricing assumes near-zero growth — potential value setup if business is healthy"
        color = "green"
    elif implied_g < 0.08:
        verdict = "Pricing assumes modest growth (4-8%) — reasonable"
        color = "green"
    elif implied_g < 0.15:
        verdict = "Pricing assumes solid growth (8-15%) — defensible for quality compounders"
        color = "amber"
    elif implied_g < 0.25:
        verdict = "Pricing assumes high growth (15-25%) — needs strong continued execution"
        color = "amber"
    else:
        verdict = "Pricing assumes hypergrowth (>25%) — perfection pricing, asymmetric downside"
        color = "red"

    return {
        "implied_growth": implied_g,
        "implied_growth_pct": implied_g * 100,
        "verdict": verdict,
        "color": color,
        "assumptions": {
            "high_years": high_years,
            "discount": discount,
            "terminal_growth": growth_terminal,
            "fcf_base": fcf_base,
            "shares": shares,
            "net_cash": net_cash,
            "price": price,
        },
    }


# ---------------------------------------------------------------------------
# Margin of safety bands (Buffett / Klarman)
# ---------------------------------------------------------------------------

def valuation_percentile(price_df, fin: dict, current_pe: float | None) -> dict[str, Any]:
    """Where does today's P/E sit within the stock's OWN multi-year P/E range?

    Builds a daily historical P/E path = close / (trailing annual EPS as-of that day),
    using annual diluted EPS (net income / shares) stepped forward from each fiscal
    period end. Returns the current multiple's percentile plus the low/median/high so
    you can see "expensive vs its own history" — a cheap, powerful mean-reversion read.

    Returns {} when there isn't enough data (needs price history + ≥2 profitable years).
    """
    try:
        import numpy as np
        import pandas as pd
        if price_df is None or getattr(price_df, "empty", True) or current_pe is None or current_pe <= 0:
            return {}
        inc = fin.get("income")
        bal = fin.get("balance")
        if inc is None or bal is None:
            return {}
        from lib.trends import _row
        ni = _row(inc, "Net Income", "Net Income Common Stockholders")
        sh = _row(bal, "Ordinary Shares Number", "Share Issued")
        if ni is None or sh is None:
            return {}

        # (fiscal_date, annual_eps) pairs, oldest first, positive EPS only
        eps_points = []
        for col in inc.columns:
            try:
                n = float(ni[col]); s = float(sh[col]) if col in sh.index else None
            except (KeyError, TypeError, ValueError):
                continue
            if s and s > 0 and n is not None and not pd.isna(n) and not pd.isna(s) and n > 0:
                eps_points.append((pd.Timestamp(col), n / s))
        if len(eps_points) < 2:
            return {}
        eps_points.sort(key=lambda x: x[0])
        eps_dates = [p[0] for p in eps_points]
        eps_vals = [p[1] for p in eps_points]

        closes = price_df["Close"] if "Close" in price_df.columns else price_df.iloc[:, 0]
        idx = closes.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        closes = pd.Series([float(v) for v in closes.tolist()], index=idx)

        pe_series = []
        for dt, px in closes.items():
            # most recent fiscal EPS on/before this date
            eps_asof = None
            for d, e in zip(eps_dates, eps_vals):
                if d <= dt:
                    eps_asof = e
                else:
                    break
            if eps_asof and eps_asof > 0:
                pe = px / eps_asof
                if 0 < pe < 1000:  # drop nonsense
                    pe_series.append(pe)
        if len(pe_series) < 30:
            return {}
        arr = np.array(pe_series, dtype=float)
        # Rank the CURRENT multiple on the same (annual-EPS) basis as the series —
        # the series' most recent point — so it's apples-to-apples and always lands
        # within [low, high]. (Comparing the quote's TTM P/E against an annual-EPS
        # distribution put "current" below the historical low for growing companies.)
        current = pe_series[-1]
        pct = float((arr < current).mean() * 100)
        return {
            "metric": "P/E",
            "current": current,
            "percentile": pct,
            "low": float(arr.min()),
            "median": float(np.median(arr)),
            "high": float(arr.max()),
            "n_obs": len(pe_series),
        }
    except Exception:
        return {}


def mos_bands(fair_value: float) -> dict[str, float]:
    """Standard margin-of-safety price bands from a fair value estimate."""
    return {
        "fair_value": fair_value,
        "25_pct_mos": fair_value * 0.75,    # 25% MoS = buy below this
        "33_pct_mos": fair_value * 0.67,    # 33% MoS = Buffett's traditional zone
        "50_pct_mos": fair_value * 0.50,    # 50% MoS = Klarman / cigar butt zone
    }
