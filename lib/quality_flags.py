"""Quality-of-earnings flags: Piotroski F-score, Altman Z-score, Beneish M-score.

These are famous academic factors for sniffing out earnings manipulation and
financial distress. Computed from yfinance annual statements (last 2 years
required for the YoY pieces).

References:
  Piotroski (2000): F-score 8-9 beat F-score 0-2 by 7.5% annualized in
                   value-stock universe.
  Altman (1968):   Z-score < 1.81 = high bankruptcy risk; > 2.99 = safe.
  Beneish (1999):  M-score > -1.78 → likely earnings manipulator (caveat).
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st
import yfinance as yf

from lib.trends import _row, _safe_div


# ---------------------------------------------------------------------------
# Piotroski F-Score (9 binary points)
# ---------------------------------------------------------------------------

PIOTROSKI_CHECKS = [
    ("ni_positive", "Profitable (Net Income > 0)"),
    ("ocf_positive", "Operating cash flow > 0"),
    ("roa_up", "ROA rising YoY"),
    ("ocf_gt_ni", "OCF > Net Income (cash quality)"),
    ("ltd_down", "Long-term debt declining"),
    ("current_ratio_up", "Current ratio improving"),
    ("no_dilution", "Shares not increasing"),
    ("gross_margin_up", "Gross margin improving"),
    ("asset_turnover_up", "Asset turnover improving"),
]


def compute_piotroski(symbol: str, _financials: dict | None = None) -> dict[str, Any]:
    """Compute Piotroski F-Score (0-9). Higher = healthier.

    Optionally pass `_financials` from financials.get_all(symbol) to avoid
    redundant yfinance fetch.
    """
    if _financials is not None:
        inc = _financials.get("income")
        bal = _financials.get("balance")
        cf = _financials.get("cashflow")
    else:
        try:
            t = yf.Ticker(symbol)
            inc = t.income_stmt
            bal = t.balance_sheet
            cf = t.cashflow
        except Exception as e:
            return {"error": str(e), "score": None, "checks": {}, "max": 9}

    if any(x is None or (hasattr(x, "empty") and x.empty) for x in (inc, bal, cf)):
        return {"error": "Missing annual statements", "score": None, "checks": {}, "max": 9}

    cols = inc.columns
    if len(cols) < 2:
        return {"error": "Need 2 years of data", "score": None, "checks": {}, "max": 9}

    cur, prev = cols[0], cols[1]

    ni_r = _row(inc, "Net Income", "Net Income Common Stockholders")
    ocf_r = _row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    assets_r = _row(bal, "Total Assets")
    ltd_r = _row(bal, "Long Term Debt", "Long Term Debt And Capital Lease Obligation")
    ca_r = _row(bal, "Current Assets")
    cl_r = _row(bal, "Current Liabilities")
    shares_r = _row(bal, "Ordinary Shares Number", "Share Issued")
    gp_r = _row(inc, "Gross Profit")
    rev_r = _row(inc, "Total Revenue", "Operating Revenue")

    def v(s, col):
        if s is None or col not in s.index:
            return None
        x = s[col]
        return float(x) if pd.notna(x) else None

    ni_c, ni_p = v(ni_r, cur), v(ni_r, prev)
    ocf_c, ocf_p = v(ocf_r, cur), v(ocf_r, prev)
    a_c, a_p = v(assets_r, cur), v(assets_r, prev)
    ltd_c, ltd_p = v(ltd_r, cur), v(ltd_r, prev)
    ca_c, ca_p = v(ca_r, cur), v(ca_r, prev)
    cl_c, cl_p = v(cl_r, cur), v(cl_r, prev)
    sh_c, sh_p = v(shares_r, cur), v(shares_r, prev)
    gp_c, gp_p = v(gp_r, cur), v(gp_r, prev)
    rev_c, rev_p = v(rev_r, cur), v(rev_r, prev)

    checks = {}

    # 1. Net income positive
    checks["ni_positive"] = (ni_c is not None and ni_c > 0)

    # 2. OCF positive
    checks["ocf_positive"] = (ocf_c is not None and ocf_c > 0)

    # 3. ROA rising
    roa_c = _safe_div(ni_c, a_c)
    roa_p = _safe_div(ni_p, a_p)
    checks["roa_up"] = (roa_c is not None and roa_p is not None and roa_c > roa_p)

    # 4. OCF > NI (quality of earnings)
    checks["ocf_gt_ni"] = (ocf_c is not None and ni_c is not None and ocf_c > ni_c)

    # 5. Long-term debt declining
    checks["ltd_down"] = (ltd_c is not None and ltd_p is not None and ltd_c < ltd_p)

    # 6. Current ratio up
    cr_c = _safe_div(ca_c, cl_c)
    cr_p = _safe_div(ca_p, cl_p)
    checks["current_ratio_up"] = (cr_c is not None and cr_p is not None and cr_c > cr_p)

    # 7. No share dilution
    checks["no_dilution"] = (sh_c is not None and sh_p is not None and sh_c <= sh_p)

    # 8. Gross margin improving
    gm_c = _safe_div(gp_c, rev_c)
    gm_p = _safe_div(gp_p, rev_p)
    checks["gross_margin_up"] = (gm_c is not None and gm_p is not None and gm_c > gm_p)

    # 9. Asset turnover improving
    at_c = _safe_div(rev_c, a_c)
    at_p = _safe_div(rev_p, a_p)
    checks["asset_turnover_up"] = (at_c is not None and at_p is not None and at_c > at_p)

    score = sum(1 for v in checks.values() if v)
    grade = "Strong" if score >= 7 else ("OK" if score >= 5 else "Weak")
    color = "green" if score >= 7 else ("amber" if score >= 5 else "red")

    return {
        "score": score, "max": 9, "grade": grade, "color": color,
        "checks": checks,
        "labels": dict(PIOTROSKI_CHECKS),
        "interpretation": (
            f"Piotroski F-Score: {score}/9 ({grade}). "
            f"Originally found 8-9 names outperformed 0-2 names by 7.5% annualized in value universe."
        ),
    }


# ---------------------------------------------------------------------------
# Altman Z-Score (bankruptcy risk)
# ---------------------------------------------------------------------------

def compute_altman_z(symbol: str, _financials: dict | None = None,
                     _quote: dict | None = None) -> dict[str, Any]:
    """Original Altman Z (1968) for manufacturers.

    Z = 1.2A + 1.4B + 3.3C + 0.6D + 1.0E
    Z > 2.99 = safe; 1.81-2.99 = grey; < 1.81 = distress.
    Less reliable for financials / REITs / asset-light tech.
    """
    if _financials is not None:
        inc = _financials.get("income")
        bal = _financials.get("balance")
        info = _financials.get("info") or {}
    else:
        try:
            t = yf.Ticker(symbol)
            inc = t.income_stmt
            bal = t.balance_sheet
            info = t.info or {}
        except Exception as e:
            return {"error": str(e), "score": None}

    if any(x is None or (hasattr(x, "empty") and x.empty) for x in (inc, bal)):
        return {"error": "Missing annual statements", "score": None}

    cur = inc.columns[0]

    rev = _row(inc, "Total Revenue", "Operating Revenue")
    ebit = _row(inc, "EBIT", "Operating Income")
    assets = _row(bal, "Total Assets")
    wc = _row(bal, "Working Capital")
    re = _row(bal, "Retained Earnings")
    tot_liab = _row(bal, "Total Liabilities Net Minority Interest")

    def v(s, col):
        if s is None or col not in s.index:
            return None
        x = s[col]
        return float(x) if pd.notna(x) else None

    r = v(rev, cur); e = v(ebit, cur); a = v(assets, cur)
    w = v(wc, cur); ret = v(re, cur); tl = v(tot_liab, cur)
    # Market cap + sector come from the already-fetched quote when available, so we
    # don't pay for a second yfinance .info call in the diagnose path. Fall back to
    # the info dict for standalone callers.
    q = _quote or {}
    mve = q.get("market_cap") or info.get("marketCap")

    if not all([r, e, a, mve, tl]) or w is None or ret is None:
        return {"error": "Missing required fields", "score": None}

    A = w / a
    B = ret / a
    C = e / a
    D = mve / tl if tl else None
    E = r / a

    if D is None:
        return {"error": "Total liabilities zero?", "score": None}

    z = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E

    if z > 2.99:
        grade = "Safe"; color = "green"
    elif z > 1.81:
        grade = "Grey zone"; color = "amber"
    else:
        grade = "Distress risk"; color = "red"

    sector = (q.get("sector") or info.get("sector") or "").lower()
    caveat = ""
    if "financial" in sector or "real estate" in sector:
        caveat = " (less reliable for banks/REITs)"

    return {
        "score": round(z, 2), "grade": grade, "color": color,
        "components": {"WC/Assets": A, "RE/Assets": B, "EBIT/Assets": C,
                       "MVE/Liab": D, "Sales/Assets": E},
        "interpretation": f"Altman Z = {z:.2f} ({grade}{caveat}). Z>2.99 safe, 1.81-2.99 grey, <1.81 distress.",
    }


# ---------------------------------------------------------------------------
# Beneish M-Score (earnings manipulation flag — requires 2 years)
# ---------------------------------------------------------------------------

def compute_beneish_m(symbol: str, _financials: dict | None = None) -> dict[str, Any]:
    """Beneish M-score. M > -1.78 → flagged as possible manipulator.

    Screening tool. A flag is NOT proof of manipulation.
    """
    if _financials is not None:
        inc = _financials.get("income")
        bal = _financials.get("balance")
        cf = _financials.get("cashflow")
    else:
        try:
            t = yf.Ticker(symbol)
            inc = t.income_stmt
            bal = t.balance_sheet
            cf = t.cashflow
        except Exception as e:
            return {"error": str(e), "score": None}

    if any(x is None or (hasattr(x, "empty") and x.empty) for x in (inc, bal, cf)) or len(inc.columns) < 2:
        return {"error": "Need 2 years of financials", "score": None}

    cur, prev = inc.columns[0], inc.columns[1]

    rev = _row(inc, "Total Revenue", "Operating Revenue")
    cogs = _row(inc, "Cost Of Revenue", "Reconciled Cost Of Revenue")
    sga = _row(inc, "Selling General And Administration")
    da = _row(cf, "Depreciation Amortization Depletion", "Depreciation And Amortization")
    ar = _row(bal, "Accounts Receivable")
    assets = _row(bal, "Total Assets")
    current_assets = _row(bal, "Current Assets")
    ppe = _row(bal, "Net PPE", "Net Property Plant And Equipment")
    cash = _row(bal, "Cash And Cash Equivalents")
    securities = _row(bal, "Other Short Term Investments")
    ltd = _row(bal, "Long Term Debt", "Long Term Debt And Capital Lease Obligation")
    cl = _row(bal, "Current Liabilities")
    ni = _row(inc, "Net Income", "Net Income Common Stockholders")
    ocf = _row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")

    def v(s, col):
        if s is None or col not in s.index:
            return None
        x = s[col]
        return float(x) if pd.notna(x) else None

    try:
        # DSRI = (AR_t / Sales_t) / (AR_{t-1} / Sales_{t-1})
        dsri = (v(ar, cur) / v(rev, cur)) / (v(ar, prev) / v(rev, prev))
        # GMI = GM_{t-1} / GM_t
        gm_cur = (v(rev, cur) - v(cogs, cur)) / v(rev, cur)
        gm_prev = (v(rev, prev) - v(cogs, prev)) / v(rev, prev)
        gmi = gm_prev / gm_cur if gm_cur else None
        # AQI = 1 - (CA + PPE + Cash + Securities)/Assets
        def aqi_for(col):
            ca = v(current_assets, col) or 0
            p = v(ppe, col) or 0
            csh = v(cash, col) or 0
            sec = v(securities, col) or 0
            a = v(assets, col)
            return 1 - (ca + p + csh + sec) / a if a else None
        aqi = aqi_for(cur) / aqi_for(prev) if aqi_for(prev) else None
        # SGI = Sales_t / Sales_{t-1}
        sgi = v(rev, cur) / v(rev, prev)
        # DEPI = Dep_{t-1}/(Dep+PPE)_{t-1} / Dep_t/(Dep+PPE)_t
        def dep_rate(col):
            d = v(da, col); p = v(ppe, col)
            return d / (d + p) if (d and p) else None
        depi = dep_rate(prev) / dep_rate(cur) if dep_rate(cur) else None
        # SGAI = SGA_t/Sales_t / SGA_{t-1}/Sales_{t-1}
        if v(sga, cur) and v(sga, prev):
            sgai = (v(sga, cur) / v(rev, cur)) / (v(sga, prev) / v(rev, prev))
        else:
            sgai = 1
        # LVGI = leverage_t / leverage_{t-1}
        def lev(col):
            ltd_v = v(ltd, col) or 0
            cl_v = v(cl, col) or 0
            a = v(assets, col)
            return (ltd_v + cl_v) / a if a else None
        lvgi = lev(cur) / lev(prev) if lev(prev) else None
        # TATA = (NI - OCF) / Assets
        tata = (v(ni, cur) - v(ocf, cur)) / v(assets, cur)

        m = (-4.84 + 0.92*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi
             + 0.115*depi - 0.172*sgai + 4.679*tata - 0.327*lvgi)
    except (TypeError, ZeroDivisionError):
        return {"error": "Insufficient/zero values for Beneish calc", "score": None}

    flagged = m > -1.78
    grade = "FLAGGED — possible manipulator" if flagged else "Clean"
    color = "red" if flagged else "green"

    return {
        "score": round(m, 2), "grade": grade, "color": color,
        "flagged": flagged,
        "interpretation": (
            f"Beneish M = {m:.2f}. " +
            ("Above -1.78 threshold — screen for accounting red flags." if flagged
             else "Below -1.78 — no manipulation flag.")
        ),
    }


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def all_quality_flags(symbol: str, _financials: dict | None = None,
                      _quote: dict | None = None) -> dict[str, Any]:
    """Run all three scores. Returns dict keyed by name.

    If `_financials` is passed, all three computations use the same pre-fetched
    statements. `_quote` (the enriched quote) supplies Altman's market cap + sector
    so we don't trigger a second yfinance .info fetch.
    """
    return {
        "piotroski": compute_piotroski(symbol, _financials),
        "altman": compute_altman_z(symbol, _financials, _quote),
        "beneish": compute_beneish_m(symbol, _financials),
    }
