"""Options-chain data via yfinance (free, no API key).

Surfaces the data points investors actually use:
  - ATM implied volatility
  - Expected move to an expiry (from the ATM straddle price)
  - Put/Call ratios (open interest + volume) as a sentiment read
  - Max-pain strike
  - The near-the-money chain (calls + puts) for viewing / paper trading
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st
import yfinance as yf

from lib import http as _http


@st.cache_data(ttl=900, show_spinner=False)
def get_expirations(symbol: str) -> list[str]:
    try:
        return list(_http.with_retry(lambda: yf.Ticker(symbol).options, attempts=2, backoff=0.4) or [])
    except Exception:
        return []


def _dte(exp: str) -> int:
    try:
        return (datetime.strptime(exp, "%Y-%m-%d").date() - date.today()).days
    except Exception:
        return 0


def pick_default_expiry(expirations: list[str], min_dte: int = 14) -> str | None:
    """Nearest expiry at least `min_dte` days out (so 'expected move' is meaningful);
    falls back to the nearest available."""
    if not expirations:
        return None
    for e in expirations:
        if _dte(e) >= min_dte:
            return e
    return expirations[0]


@st.cache_data(ttl=600, show_spinner=False)
def _raw_chain(symbol: str, expiry: str) -> dict:
    """Return calls/puts as list-of-dicts (cacheable)."""
    try:
        ch = yf.Ticker(symbol).option_chain(expiry)
        cols = ["strike", "lastPrice", "bid", "ask", "volume", "openInterest",
                "impliedVolatility", "inTheMoney"]
        calls = ch.calls[cols].to_dict("records") if ch.calls is not None else []
        puts = ch.puts[cols].to_dict("records") if ch.puts is not None else []
        return {"calls": calls, "puts": puts}
    except Exception:
        return {"calls": [], "puts": []}


def _nearest(rows: list[dict], spot: float) -> dict | None:
    if not rows:
        return None
    return min(rows, key=lambda r: abs((r.get("strike") or 0) - spot))


def _max_pain(calls: list[dict], puts: list[dict]) -> float | None:
    strikes = sorted({r["strike"] for r in calls + puts if r.get("strike")})
    if not strikes:
        return None
    best, best_val = None, None
    for s in strikes:
        # total intrinsic value paid out to holders if price settles at s
        call_pay = sum((r.get("openInterest") or 0) * max(0, s - r["strike"]) for r in calls if r.get("strike"))
        put_pay = sum((r.get("openInterest") or 0) * max(0, r["strike"] - s) for r in puts if r.get("strike"))
        total = call_pay + put_pay
        if best_val is None or total < best_val:
            best_val, best = total, s
    return best


@st.cache_data(ttl=600, show_spinner=False)
def get_summary(symbol: str, expiry: str | None = None, spot: float | None = None) -> dict[str, Any]:
    """Derived options metrics for the chosen (or default) expiry. {} if unavailable."""
    exps = get_expirations(symbol)
    if not exps:
        return {}
    if expiry is None or expiry not in exps:
        expiry = pick_default_expiry(exps)
    if spot is None:
        from lib import data as _data
        spot = _data.get_last_price(symbol)
    if not spot:
        return {}

    chain = _raw_chain(symbol, expiry)
    calls, puts = chain["calls"], chain["puts"]
    if not calls and not puts:
        return {"expirations": exps, "expiry": expiry, "err": "no chain"}

    atm_c = _nearest(calls, spot)
    atm_p = _nearest(puts, spot)
    iv_atm = None
    ivs = [v for v in [(atm_c or {}).get("impliedVolatility"), (atm_p or {}).get("impliedVolatility")] if v]
    if ivs:
        iv_atm = sum(ivs) / len(ivs)

    expected_move_abs = expected_move_pct = None
    if atm_c and atm_p and atm_c.get("lastPrice") and atm_p.get("lastPrice"):
        straddle = float(atm_c["lastPrice"]) + float(atm_p["lastPrice"])
        expected_move_abs = straddle
        expected_move_pct = straddle / spot

    call_oi = sum(r.get("openInterest") or 0 for r in calls)
    put_oi = sum(r.get("openInterest") or 0 for r in puts)
    call_vol = sum(r.get("volume") or 0 for r in calls)
    put_vol = sum(r.get("volume") or 0 for r in puts)

    # Near-the-money rows (within ~12% of spot) for display
    def near(rows):
        out = [r for r in rows if r.get("strike") and abs(r["strike"] / spot - 1) <= 0.12]
        return sorted(out, key=lambda r: r["strike"])

    return {
        "expirations": exps,
        "expiry": expiry,
        "dte": _dte(expiry),
        "spot": spot,
        "atm_iv": iv_atm,
        "expected_move_abs": expected_move_abs,
        "expected_move_pct": expected_move_pct,
        "pc_oi_ratio": (put_oi / call_oi) if call_oi else None,
        "pc_vol_ratio": (put_vol / call_vol) if call_vol else None,
        "call_oi": call_oi, "put_oi": put_oi,
        "max_pain": _max_pain(calls, puts),
        "calls_near": near(calls),
        "puts_near": near(puts),
        "atm_strike": (atm_c or {}).get("strike"),
        "err": None,
    }


@st.cache_data(ttl=600, show_spinner=False)
def get_contract_price(symbol: str, expiry: str, opt_type: str, strike: float) -> dict | None:
    """Look up the current mid/last price for a specific contract (for paper-trading P&L)."""
    chain = _raw_chain(symbol, expiry)
    rows = chain["calls"] if opt_type.lower().startswith("c") else chain["puts"]
    match = next((r for r in rows if abs((r.get("strike") or 0) - strike) < 1e-6), None)
    if not match:
        return None
    bid, ask, last = match.get("bid") or 0, match.get("ask") or 0, match.get("lastPrice") or 0
    mid = (bid + ask) / 2 if (bid and ask) else last
    return {"last": last, "bid": bid, "ask": ask, "mid": mid,
            "iv": match.get("impliedVolatility"), "oi": match.get("openInterest")}


# ---------------------------------------------------------------------------
# Black-Scholes pricing engine (for P&L simulation)
# ---------------------------------------------------------------------------

import math

try:
    from scipy.stats import norm as _norm
except ImportError:
    _norm = None  # graceful fallback — BS functions will error with a clear message


def _require_scipy():
    if _norm is None:
        raise ImportError("scipy is required for Black-Scholes pricing. Install with: pip install scipy")
    return _norm

def bs_price(S, K, T, r, sigma, opt_type='call'):
    """Black-Scholes option price.
    S=spot, K=strike, T=years to expiry, r=risk-free rate, sigma=IV, opt_type='call'|'put'
    """
    norm = _require_scipy()
    if T <= 0:
        # At expiry: intrinsic value only
        if opt_type == 'call':
            return max(S - K, 0)
        return max(K - S, 0)
    d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == 'call':
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def bs_greeks(S, K, T, r, sigma, opt_type='call'):
    """Return dict of greeks: delta, gamma, theta (per day), vega (per 1% IV move)."""
    norm = _require_scipy()
    if T <= 0:
        delta = 1.0 if (opt_type == 'call' and S > K) else (-1.0 if (opt_type == 'put' and S < K) else 0.0)
        return {"delta": delta, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    sqrt_T = math.sqrt(T)
    pdf_d1 = norm.pdf(d1)

    gamma = pdf_d1 / (S * sigma * sqrt_T)
    vega = S * pdf_d1 * sqrt_T / 100  # per 1% IV move

    if opt_type == 'call':
        delta = norm.cdf(d1)
        theta = (-(S * pdf_d1 * sigma) / (2 * sqrt_T) - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365
    else:
        delta = norm.cdf(d1) - 1
        theta = (-(S * pdf_d1 * sigma) / (2 * sqrt_T) + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365

    return {"delta": round(delta, 4), "gamma": round(gamma, 6),
            "theta": round(theta, 4), "vega": round(vega, 4)}

def simulate_pnl_grid(S_now, K, T_total, r, sigma, opt_type, entry_premium, contracts=1,
                       price_steps=50, time_steps=20, price_lo=None, price_hi=None):
    """Build a 2D P&L grid: price scenarios x dates to expiry.

    Returns: {
        prices: list of floats (underlying prices, X axis),
        dates_remaining: list of floats (days remaining, Y axis),
        pnl: list of lists (pnl[time_idx][price_idx] = dollar P&L),
        breakevens: list of floats (breakeven price at each time step),
    }
    """
    multiplier = contracts * 100
    cost = entry_premium * multiplier

    # Price range: +/-40% from current (or caller-supplied bounds)
    lo = price_lo if price_lo is not None else S_now * 0.60
    hi = price_hi if price_hi is not None else S_now * 1.40
    prices = [lo + (hi - lo) * i / (price_steps - 1) for i in range(price_steps)]

    # Time range: from now to expiry
    total_days = max(int(T_total * 365), 1)
    if time_steps > total_days:
        time_steps = total_days
    day_step = max(1, total_days // time_steps)
    days_remaining = list(range(total_days, 0, -day_step))
    if days_remaining and days_remaining[-1] != 0:
        days_remaining.append(0)  # include expiry

    pnl = []
    breakevens = []
    for d in days_remaining:
        T_rem = d / 365.0
        row = []
        be_price = None
        prev_pnl = None
        for p in prices:
            theo = bs_price(p, K, T_rem, r, sigma, opt_type)
            position_value = theo * multiplier
            pl = position_value - cost
            row.append(round(pl, 2))
            # Track breakeven (where P&L crosses zero)
            if prev_pnl is not None and prev_pnl * pl < 0:
                be_price = p
            prev_pnl = pl
        pnl.append(row)
        breakevens.append(be_price)

    return {
        "prices": prices,
        "days_remaining": days_remaining,
        "pnl": pnl,
        "breakevens": breakevens,
        "cost": cost,
    }


def get_risk_free_rate() -> float:
    """Pull the 10-year Treasury yield from FRED as the risk-free rate proxy.
    Returns decimal (e.g., 0.045 for 4.5%). Falls back to 4.5% on failure."""
    try:
        from lib import data as _data
        series = _data.get_fred_series("DGS10")
        if series and "value" in series and series["value"] is not None:
            return float(series["value"]) / 100.0
    except Exception:
        pass
    return 0.045  # sensible fallback
