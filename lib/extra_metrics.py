"""Twelve strong-but-simple metrics surfaced on Stock Pro Deep-dive.

All compute from data already pulled by diagnose() — no extra network calls
except the one SPY benchmark fetch (cached 5min).

Returns dict of {key: {value, label, tone, sub, format}} that the page renders
directly with ui.kpi_tile.
"""
from __future__ import annotations

from typing import Any

import streamlit as st
import yfinance as yf

from lib import fmt as _fmt


@st.cache_data(ttl=300, show_spinner=False)
def _spy_returns() -> dict[str, float]:
    """Cached SPY returns for 1M/3M/6M/1Y windows. Used for RS comparison."""
    try:
        t = yf.Ticker("SPY")
        h = t.history(period="2y", auto_adjust=False)
        if h.empty:
            return {}
        last = float(h["Close"].iloc[-1])
        out = {}
        for label, days in (("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252), ("3Y", 756)):
            if len(h) > days:
                past = float(h["Close"].iloc[-days])
                out[label] = (last / past) - 1
        return out
    except Exception:
        return {}


def _period_returns(price_history, periods=("1M", "3M", "6M", "1Y", "3Y")) -> dict[str, float]:
    """Compute returns over each period from a price_history DataFrame."""
    if price_history is None or price_history.empty:
        return {}
    closes = price_history["Close"] if "Close" in price_history.columns else price_history.iloc[:, 0]
    last = float(closes.iloc[-1])
    out = {}
    period_days = {"1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260}
    for p in periods:
        d = period_days[p]
        if len(closes) > d:
            past = float(closes.iloc[-d])
            out[p] = (last / past) - 1
    return out


@st.cache_data(ttl=900, show_spinner=False)
def _eps_surprise_streak(symbol: str, n: int = 8) -> dict[str, Any]:
    """Last N quarterly earnings: count beats. Cached so the Deep-dive tab doesn't
    re-hit Yahoo's earnings_dates endpoint on every rerun."""
    try:
        t = yf.Ticker(symbol)
        df = t.earnings_dates
        if df is None or df.empty:
            return {"available": False}
        import pandas as pd
        past = df[df.index < pd.Timestamp.now(tz=df.index.tz)]
        recent = past.head(n)
        if recent.empty or "Surprise(%)" not in recent.columns:
            return {"available": False}
        surprises = recent["Surprise(%)"].dropna()
        if surprises.empty:
            return {"available": False}
        beats = (surprises > 0).sum()
        misses = (surprises < 0).sum()
        return {
            "available": True,
            "beats": int(beats),
            "misses": int(misses),
            "n_quarters": len(surprises),
            "avg_surprise": float(surprises.mean()),
            "last": float(surprises.iloc[0]),
        }
    except Exception:
        return {"available": False}


_format_dollars_compact = _fmt.fmt_money  # canonical formatter (lib/fmt.py)


def compute_all(quote: dict, trends: dict, price_history=None) -> dict[str, dict]:
    """Compute all 12 extra metrics. Returns {metric_id: {value, label, tone, sub}}.

    tone: '' (neutral) | 'pos' | 'neg' | 'warn'
    """
    out: dict[str, dict] = {}
    metrics = (trends or {}).get("metrics", {})
    symbol = quote.get("symbol", "")
    price = quote.get("price")

    # ----- 1. Total Shareholder Yield -----
    div_y = quote.get("div_yield") or 0
    sh_change = metrics.get("shares_change", [])
    recent_sh = [v for v in sh_change[:3] if v is not None]
    bb_yield = -sum(recent_sh) / len(recent_sh) if recent_sh else 0
    tsy = div_y + bb_yield
    out["tsy"] = {
        "label": "Total Shareholder Yield",
        "value": f"{tsy*100:+.2f}%",
        "tone": "pos" if tsy > 0.04 else ("warn" if tsy > 0 else "neg"),
        "sub": f"Div {div_y*100:.2f}% + Buyback {bb_yield*100:+.2f}%",
    }

    # ----- 2. Buyback Yield (standalone) -----
    out["bb_yield"] = {
        "label": "Buyback Yield (3y avg)",
        "value": f"{bb_yield*100:+.2f}%",
        "tone": "pos" if bb_yield > 0.02 else ("warn" if bb_yield > 0 else "neg"),
        "sub": "Negative = dilution. >2%/yr = real per-share growth.",
    }

    # ----- 3. Capex Intensity -----
    capex_vals = [abs(v) for v in metrics.get("capex", [])[:1] if v is not None]
    rev_vals = [v for v in metrics.get("revenue", [])[:1] if v is not None]
    if capex_vals and rev_vals and rev_vals[0]:
        ci = capex_vals[0] / rev_vals[0]
        out["capex_intensity"] = {
            "label": "Capex Intensity",
            "value": f"{ci*100:.1f}%",
            "tone": "pos" if ci < 0.05 else ("warn" if ci < 0.15 else "neg"),
            "sub": "Capex / Revenue. <5% = asset-light. >15% = heavy.",
        }
    else:
        out["capex_intensity"] = {"label": "Capex Intensity", "value": "—",
                                  "tone": "", "sub": "Capex / Revenue (data missing)"}

    # ----- 4. ROIC Improvement -----
    roic_vals = [v for v in metrics.get("roic", []) if v is not None]
    if len(roic_vals) >= 3:
        latest = roic_vals[0]
        avg5 = sum(roic_vals[:5]) / min(5, len(roic_vals))
        delta = latest - avg5
        out["roic_delta"] = {
            "label": "ROIC Trajectory",
            "value": f"{latest*100:.1f}% ({delta*100:+.1f}pp vs 5y avg)",
            "tone": "pos" if delta > 0.02 else ("warn" if delta > -0.02 else "neg"),
            "sub": f"Latest ROIC vs 5-year avg ({avg5*100:.1f}%). Rising = quality improving.",
        }
    else:
        out["roic_delta"] = {"label": "ROIC Trajectory", "value": "—",
                             "tone": "", "sub": "Need 3+ years of ROIC history"}

    # ----- 5. Gross Margin Direction -----
    gm_vals = [v for v in metrics.get("gross_margin", []) if v is not None]
    if len(gm_vals) >= 3:
        latest = gm_vals[0]
        avg5 = sum(gm_vals[:5]) / min(5, len(gm_vals))
        delta = latest - avg5
        out["gm_delta"] = {
            "label": "Gross Margin Direction",
            "value": f"{latest*100:.1f}% ({delta*100:+.1f}pp vs 5y avg)",
            "tone": "pos" if delta > 0.01 else ("warn" if delta > -0.01 else "neg"),
            "sub": f"Pricing power signal. 5y avg {avg5*100:.1f}%. Rising = mix shift / scale.",
        }
    else:
        out["gm_delta"] = {"label": "Gross Margin Direction", "value": "—",
                           "tone": "", "sub": "Need 3+ years of margin history"}

    # ----- 6. Interest Coverage -----
    ic_vals = [v for v in metrics.get("interest_coverage", []) if v is not None]
    if ic_vals:
        ic = ic_vals[0]
        if ic > 1000:
            display = ">1000x"; tone = "pos"
        elif ic > 5:
            display = f"{ic:.1f}x"; tone = "pos"
        elif ic > 2:
            display = f"{ic:.1f}x"; tone = "warn"
        else:
            display = f"{ic:.1f}x"; tone = "neg"
        out["interest_coverage"] = {
            "label": "Interest Coverage",
            "value": display,
            "tone": tone,
            "sub": "EBIT / interest. >5x safe. <2x stressed. Matters at 4.5% rates.",
        }
    else:
        out["interest_coverage"] = {"label": "Interest Coverage", "value": "—",
                                    "tone": "", "sub": "Likely net-cash company or data missing"}

    # ----- 7. Net Cash Position -----
    cash = quote.get("total_cash") or 0
    debt = quote.get("total_debt") or 0
    net_cash = cash - debt
    mc = quote.get("market_cap")
    nc_pct = (net_cash / mc) if mc else None
    out["net_cash"] = {
        "label": "Net Cash Position",
        "value": _format_dollars_compact(net_cash),
        "tone": "pos" if net_cash > 0 else "warn",
        "sub": f"Cash {_format_dollars_compact(cash)} - Debt {_format_dollars_compact(debt)}"
               + (f". {nc_pct*100:+.1f}% of mkt cap." if nc_pct is not None else ""),
    }

    # ----- 8. 52-Week High Distance -----
    yh = quote.get("year_high")
    if price and yh:
        pct = (price / yh) - 1
        tone = "pos" if pct > -0.05 else ("warn" if pct > -0.20 else "neg")
        out["from_52w_high"] = {
            "label": "Distance From 52w High",
            "value": f"{pct*100:+.2f}%",
            "tone": tone,
            "sub": f"Price ${price:.2f} vs 52w high ${yh:.2f}. Within 5% = momentum. >20% off = falling knife risk.",
        }
    else:
        out["from_52w_high"] = {"label": "Distance From 52w High", "value": "—",
                                "tone": "", "sub": "Insufficient data"}

    # ----- 9. Multi-period Returns + RS vs SPY -----
    rets = _period_returns(price_history)
    spy_rets = _spy_returns()
    rets_str = []
    for p in ("1M", "3M", "6M", "1Y"):
        if p in rets:
            rets_str.append(f"{p} {rets[p]*100:+.1f}%")
    out["returns"] = {
        "label": "Returns (price)",
        "value": " · ".join(rets_str) if rets_str else "—",
        "tone": "pos" if (rets.get("1Y") or 0) > 0.10 else ("warn" if (rets.get("1Y") or 0) > -0.10 else "neg"),
        "sub": "Multi-period total return. Strong 1Y = leadership.",
    }
    # RS vs SPY (1Y)
    if "1Y" in rets and "1Y" in spy_rets:
        rs = rets["1Y"] - spy_rets["1Y"]
        out["rs_vs_spy"] = {
            "label": "RS vs SPY (1Y)",
            "value": f"{rs*100:+.2f}pp",
            "tone": "pos" if rs > 0.05 else ("warn" if rs > -0.05 else "neg"),
            "sub": f"Stock 1Y {rets['1Y']*100:+.1f}% vs SPY {spy_rets['1Y']*100:+.1f}%. Leaders stay leaders.",
        }
    else:
        out["rs_vs_spy"] = {"label": "RS vs SPY (1Y)", "value": "—",
                            "tone": "", "sub": "Need 1Y price history"}

    # ----- 10. EPS Surprise Streak -----
    streak = _eps_surprise_streak(symbol)
    if streak.get("available"):
        beats = streak["beats"]; n = streak["n_quarters"]
        avg = streak["avg_surprise"]
        tone = "pos" if beats / n >= 0.75 else ("warn" if beats / n >= 0.5 else "neg")
        out["eps_streak"] = {
            "label": "EPS Surprise Streak",
            "value": f"Beat {beats} of {n}",
            "tone": tone,
            "sub": f"Avg surprise: {avg:+.1f}%. PEAD: stocks beating consistently drift up.",
        }
    else:
        out["eps_streak"] = {"label": "EPS Surprise Streak", "value": "—",
                             "tone": "", "sub": "Earnings history unavailable"}

    # ----- 11. Forward EPS Revision (using Finviz-style proxy) -----
    # We don't have a direct API for 60-day forward revisions, but we can
    # use yfinance recommendation trend OR earnings growth direction
    eg = quote.get("earnings_growth")
    if eg is not None:
        tone = "pos" if eg > 0.15 else ("warn" if eg > 0 else "neg")
        out["forward_eps_growth"] = {
            "label": "TTM Earnings Growth",
            "value": f"{eg*100:+.2f}%",
            "tone": tone,
            "sub": "Proxy for forward EPS momentum. >15% = quality growth.",
        }
    else:
        out["forward_eps_growth"] = {"label": "TTM Earnings Growth", "value": "—",
                                     "tone": "", "sub": "Often N/A for unprofitable companies"}

    # ----- 12. Cash Burn / Runway (for unprofitable companies) -----
    # OR Operating Leverage (for profitable ones)
    fcf = quote.get("fcf")
    if fcf is not None and fcf < 0:
        # Burn metric — months of cash left
        if cash > 0 and fcf < 0:
            months = abs(fcf) / 12  # monthly burn
            runway_months = cash / months if months > 0 else None
            out["runway"] = {
                "label": "Cash Runway",
                "value": f"{runway_months:.0f} months" if runway_months else "—",
                "tone": "pos" if runway_months and runway_months > 36 else ("warn" if runway_months and runway_months > 18 else "neg"),
                "sub": f"Months at current burn (${-fcf/1e6:.0f}M/yr). Pre-profit companies need runway.",
            }
        else:
            out["runway"] = {"label": "Cash Runway", "value": "—", "tone": "", "sub": ""}
    else:
        # Operating Leverage — revenue growth vs op expense growth
        rev_growth = quote.get("rev_growth") or 0
        # Approximate opex growth from op margin direction
        out["op_leverage"] = {
            "label": "Operating Leverage",
            "value": "Profitable",
            "tone": "pos",
            "sub": f"Rev growth {rev_growth*100:+.1f}%, generating cash. Margin expansion = scale benefits.",
        }

    return out
