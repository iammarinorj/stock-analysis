"""Backtest the multi-style scorecard against historical returns.

Two modes:

1. **Historical point-in-time** (the real backtest):
   For each ticker, for each year of annual financials yfinance has (~5 yrs),
   build an approximated scorecard using that year-end's financial data and
   that year-end's price. Compute forward 1-year price return. Aggregate
   across tickers to answer: does the score actually predict returns?

   Caveats: yfinance provides current PE/PB/PEG only (no point-in-time market
   ratios). So we score on the *fundamental* components (ROIC, margins, debt,
   FCF) using the actual yr-end financials, and treat the price-based items as
   N/A for that historical point. The fundamental signal is still real.

2. **Forward-tracking** (truly out-of-sample, accumulates over time):
   Every diagnose silently snapshots the score+price into the snapshots table.
   Once a snapshot is 30+ days old, compare its score bucket to the realized
   forward return. No hindsight bias. Best signal of all, takes months to fill.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd
import streamlit as st
import yfinance as yf

from lib import financials, trends, profiles, db, data


# ---------------------------------------------------------------------------
# Historical point-in-time backtest
# ---------------------------------------------------------------------------

def _approx_quote_from_financials(symbol: str, fin: dict, year_end: pd.Timestamp,
                                  price_at: float,
                                  close_series: "pd.Series | None" = None,
                                  live: dict | None = None) -> dict:
    """Build a quote dict for a SPECIFIC fiscal year. Now includes computed
    market-based fields (P/E, P/B, P/S, mkt cap, DMAs, 52w hi/lo, div yield,
    current ratio, debt/eq) derived from financials + price history at that point.

    Without these enrichments, many profile checks fail uniformly across all
    profiles in the backtest, making results look identical regardless of profile.
    """
    inc = fin.get("income")
    bal = fin.get("balance")
    cf = fin.get("cashflow")
    info = fin.get("info") or {}
    if inc is None or bal is None or cf is None:
        return {}
    if year_end not in inc.columns:
        return {}

    def v(df, *names):
        for n in names:
            if n in df.index and year_end in df.columns:
                try:
                    val = df.loc[n, year_end]
                    if pd.notna(val):
                        return float(val)
                except Exception:
                    pass
        return None

    # ---- From income statement
    rev = v(inc, "Total Revenue", "Operating Revenue")
    op_income = v(inc, "Operating Income", "Total Operating Income As Reported")
    net_income = v(inc, "Net Income", "Net Income Common Stockholders")
    gross_profit = v(inc, "Gross Profit")
    ebitda = v(inc, "EBITDA", "Normalized EBITDA")
    ebit = v(inc, "EBIT")
    int_exp = v(inc, "Interest Expense", "Interest Expense Non Operating")

    # ---- From balance sheet
    total_debt = v(bal, "Total Debt", "Long Term Debt And Capital Lease Obligation")
    cash = v(bal, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
    equity = v(bal, "Stockholders Equity", "Common Stock Equity")
    invested_cap = v(bal, "Invested Capital")
    shares = v(bal, "Ordinary Shares Number", "Share Issued")
    total_assets = v(bal, "Total Assets")
    current_assets = v(bal, "Current Assets")
    current_liab = v(bal, "Current Liabilities")

    # ---- From cash flow
    fcf = v(cf, "Free Cash Flow")
    ocf = v(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    dividends_paid = v(cf, "Cash Dividends Paid")

    # ---- Computed market-based fields (the BIG fix)
    mkt_cap = (price_at * shares) if (price_at and shares) else None
    eps = (net_income / shares) if (net_income and shares) else None
    book_per_share = (equity / shares) if (equity and shares) else None
    sales_per_share = (rev / shares) if (rev and shares) else None
    div_per_share = (abs(dividends_paid) / shares) if (dividends_paid and shares) else 0

    pe = (price_at / eps) if (price_at and eps and eps > 0) else None
    pb = (price_at / book_per_share) if (price_at and book_per_share and book_per_share > 0) else None
    ps = (price_at / sales_per_share) if (price_at and sales_per_share and sales_per_share > 0) else None
    div_yield = (div_per_share / price_at) if (div_per_share and price_at) else 0

    # Net cash, ND/EBITDA
    net_debt = (total_debt - cash) if (total_debt is not None and cash is not None) else None
    nd_ebitda = (net_debt / ebitda) if (net_debt is not None and ebitda and ebitda > 0) else None

    # Debt/Equity
    debt_eq = (total_debt / equity) if (total_debt is not None and equity and equity > 0) else None
    # Current ratio
    current_ratio = (current_assets / current_liab) if (current_assets and current_liab) else None

    # ---- Price-history derived (DMAs, 52w hi/lo, RSI proxy)
    dma_50 = dma_200 = year_high = year_low = rsi_14 = None
    if close_series is not None and not close_series.empty:
        try:
            # Align cutoff with year_end (timezone-safe)
            ce = year_end
            if close_series.index.tz is not None and ce.tz is None:
                ce = ce.tz_localize(close_series.index.tz)
            elif close_series.index.tz is None and ce.tz is not None:
                ce = ce.tz_localize(None)
            window = close_series[close_series.index <= ce]
            if len(window) >= 50:
                dma_50 = float(window.tail(50).mean())
            if len(window) >= 200:
                dma_200 = float(window.tail(200).mean())
            if len(window) >= 252:
                year = window.tail(252)
                year_high = float(year.max())
                year_low = float(year.min())
            # Crude RSI(14) — Wilder's smoothing
            if len(window) >= 15:
                delta = window.tail(15).diff().dropna()
                up = delta.clip(lower=0).mean()
                down = (-delta.clip(upper=0)).mean()
                if down > 0:
                    rs = up / down
                    rsi_14 = float(100 - 100 / (1 + rs))
                elif up > 0:
                    rsi_14 = 100.0
        except Exception:
            pass

    # ---- Sector / industry / name from the live quote (stable across history).
    # financials.get_all() no longer carries `.info`, so these come from the live
    # quote passed in by backtest_ticker; fall back to info for any direct caller.
    lq = live or {}
    sector = lq.get("sector") or info.get("sector") or ""
    industry = lq.get("industry") or info.get("industry") or ""
    name = lq.get("name") or info.get("longName") or info.get("shortName") or symbol

    return {
        "symbol": symbol,
        "name": name,
        "price": price_at,
        # Income / margins
        "revenue": rev,
        "ebitda": ebitda,
        "ebit": ebit,
        # Cash flow
        "fcf": fcf, "ocf": ocf,
        # Balance sheet
        "total_debt": total_debt, "total_cash": cash,
        "shares_out": shares,
        "total_assets": total_assets,
        # Returns
        "roe": (net_income / equity) if (net_income and equity and equity > 0) else None,
        "roa": (net_income / total_assets) if (net_income and total_assets) else None,
        # Margins
        "operating_margin": (op_income / rev) if (op_income and rev) else None,
        "gross_margin": (gross_profit / rev) if (gross_profit and rev) else None,
        "profit_margin": (net_income / rev) if (net_income and rev) else None,
        # Market-based (NEW — the fix)
        "pe_trailing": pe,
        "pe_forward": None,  # genuinely unavailable historically
        "peg": None,  # needs analyst growth estimates — also unavailable
        "pb": pb,
        "ps": ps,
        "ev_ebitda": ((mkt_cap + (total_debt or 0) - (cash or 0)) / ebitda)
                     if (mkt_cap and ebitda and ebitda > 0) else None,
        "div_yield": div_yield,
        "market_cap": mkt_cap,
        # Leverage / liquidity
        "debt_eq": debt_eq,
        "current_ratio": current_ratio,
        "interest_coverage": (ebit / abs(int_exp)) if (ebit and int_exp) else None,
        # Insider / analyst — genuinely N/A historically
        "insider_cluster_buy": False, "insider_buys_6mo": 0, "insider_sells_6mo": 0,
        "held_insiders": (lq.get("held_insiders") if lq.get("held_insiders") is not None
                          else info.get("heldPercentInsiders")),  # current ownership — stable proxy
        "recommend": None,
        # Trend / momentum (NEW)
        "dma_50": dma_50, "dma_200": dma_200,
        "year_high": year_high, "year_low": year_low,
        "rsi_14": rsi_14,
        # Profile / sector (NEW)
        "sector": sector, "industry": industry,
        # Earnings growth — not directly available historically; approximate from
        # this year's net_income vs prior year's net_income
        "earnings_growth": None,
        "rev_growth": None,
    }


def _build_historical_trends_subset(fin: dict, up_to_year_end: pd.Timestamp) -> dict:
    """Build a `trends` dict but truncated to data <= up_to_year_end.

    Each statement's columns are filtered independently — fiscal year-ends often
    differ slightly across income/balance/cashflow statements (e.g., 9/30 vs 12/31).
    """
    inc = fin.get("income")
    if inc is None:
        return {"years": [], "metrics": {}, "trends": {}}
    inc_cols = sorted([c for c in inc.columns if c <= up_to_year_end], reverse=True)
    if not inc_cols:
        return {"years": [], "metrics": {}, "trends": {}}

    def _filter_cols(df, cutoff):
        if df is None:
            return None
        keep = sorted([c for c in df.columns if c <= cutoff], reverse=True)
        return df[keep] if keep else None

    sub_fin = {
        "income": inc[inc_cols],
        "balance": _filter_cols(fin.get("balance"), up_to_year_end),
        "cashflow": _filter_cols(fin.get("cashflow"), up_to_year_end),
        "info": {}, "error": None,
    }
    return trends.get_annual_trends(fin.get("symbol", ""), _financials=sub_fin)


def _yearly_price_lookup(symbol: str) -> pd.Series | None:
    """Pull daily close prices for the past 6 years (enough for 5yr backtest)."""
    try:
        t = yf.Ticker(symbol)
        h = t.history(period="6y", auto_adjust=False)
        if h is None or h.empty:
            return None
        return h["Close"]
    except Exception:
        return None


def _nearest_price(close_series: pd.Series, target_date: pd.Timestamp) -> float | None:
    """Closest trading-day close on or before target_date."""
    if close_series is None or close_series.empty:
        return None
    try:
        # Ensure tz match
        td = target_date
        if close_series.index.tz is not None and td.tz is None:
            td = td.tz_localize(close_series.index.tz)
        elif close_series.index.tz is None and td.tz is not None:
            td = td.tz_localize(None)
        sub = close_series[close_series.index <= td]
        if sub.empty:
            return None
        return float(sub.iloc[-1])
    except Exception:
        return None


def backtest_ticker(symbol: str, profile_id: str = "buffett",
                    forward_days: int = 365) -> list[dict]:
    """Run the historical backtest for one ticker, one profile.

    Returns a list of dicts, one per fiscal year tested:
      {symbol, year_end, score, max_score, pct, price_at_year_end,
       price_forward, forward_return, profile_id}
    """
    fin = financials.get_all(symbol)
    if fin.get("error") or fin.get("income") is None:
        return []
    fin["symbol"] = symbol

    # Sector/industry/name/insider-ownership are "stable across history" proxies —
    # pull them once from the live quote (financials no longer carries .info).
    live_q = data.get_quote(symbol) or {}

    close_series = _yearly_price_lookup(symbol)
    if close_series is None:
        return []

    inc_cols = sorted(fin["income"].columns, reverse=True)
    if len(inc_cols) < 2:
        return []

    results = []
    # Skip the most recent year (no forward data yet) and the very oldest
    # (insufficient trend history)
    for i, year_end in enumerate(inc_cols[1:], start=1):
        price_at = _nearest_price(close_series, year_end)
        if price_at is None:
            continue

        # Build approximated quote with price+financials+history at this date
        q = _approx_quote_from_financials(symbol, fin, year_end, price_at,
                                          close_series=close_series, live=live_q)
        if not q:
            continue

        # Compute trailing rev_growth & earnings_growth from this year vs prior year
        if i + 1 < len(inc_cols):
            prior_year_end = inc_cols[i + 1]
            inc_df = fin["income"]
            def _v_at(name, col):
                if name in inc_df.index and col in inc_df.columns:
                    val = inc_df.loc[name, col]
                    return float(val) if pd.notna(val) else None
                return None
            cur_rev = _v_at("Total Revenue", year_end) or _v_at("Operating Revenue", year_end)
            pri_rev = _v_at("Total Revenue", prior_year_end) or _v_at("Operating Revenue", prior_year_end)
            cur_ni = _v_at("Net Income", year_end) or _v_at("Net Income Common Stockholders", year_end)
            pri_ni = _v_at("Net Income", prior_year_end) or _v_at("Net Income Common Stockholders", prior_year_end)
            if cur_rev and pri_rev and pri_rev > 0:
                q["rev_growth"] = (cur_rev / pri_rev) - 1
            if cur_ni and pri_ni and pri_ni > 0:
                q["earnings_growth"] = (cur_ni / pri_ni) - 1

        tr = _build_historical_trends_subset(fin, year_end)
        if not tr.get("metrics"):
            continue

        # Score with the requested profile (only fundamental items will pass — market-based items missing)
        try:
            score = profiles.score_profile(profile_id, q, tr)
        except Exception:
            continue

        # Forward return
        fwd_date = year_end + pd.Timedelta(days=forward_days)
        price_fwd = _nearest_price(close_series, fwd_date)
        if price_fwd is None:
            continue
        fwd_ret = (price_fwd / price_at) - 1

        results.append({
            "symbol": symbol,
            "year_end": year_end.strftime("%Y-%m-%d"),
            "score": score["total"],
            "max_score": score["max"],
            "pct": score["pct"],
            "price_at": price_at,
            "price_fwd": price_fwd,
            "forward_return": fwd_ret,
            "profile_id": profile_id,
            "verdict": score["verdict"]["head"],
        })

    return results


@st.cache_data(ttl=3600, show_spinner=False)
def backtest_universe(symbols: tuple, profile_id: str = "buffett",
                      forward_days: int = 365, max_workers: int = 8) -> dict:
    """Run historical backtest across a universe of tickers, concurrently.

    Returns:
      {
        "rows": list of per-observation dicts,
        "summary": {
          "n_observations": int,
          "n_tickers": int,
          "avg_return_overall": float,
          "by_quartile": {1: avg_return, 2: ..., 3: ..., 4: avg_return},
          "hit_rate_by_quartile": {1: pct_positive, ...},
          "correlation": float,    # pct vs forward_return Pearson
        },
        "elapsed_s": float,
      }
    """
    t0 = time.time()
    all_rows = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(backtest_ticker, s, profile_id, forward_days): s for s in symbols}
        for fut in as_completed(futs):
            try:
                all_rows.extend(fut.result())
            except Exception:
                pass

    elapsed = time.time() - t0

    if not all_rows:
        return {"rows": [], "summary": {}, "elapsed_s": elapsed,
                "error": "No backtest observations produced. Tickers may lack history."}

    df = pd.DataFrame(all_rows)
    # Bucket into quartiles by pct score — handle the case where many obs share
    # the same pct (common for Lynch/Graham profiles where most stocks score 0%).
    # pd.qcut with duplicates='drop' may return fewer than q bins, so we use
    # labels=False and add 1 to get 1-indexed bin numbers.
    n_unique_pct = df["pct"].nunique()
    if n_unique_pct < 2:
        # All observations same score — single bucket
        df["quartile"] = 1
        by_q = {1: float(df["forward_return"].mean())}
        hit_q = {1: float((df["forward_return"] > 0).mean())}
    else:
        try:
            n_bins = min(4, n_unique_pct)
            df["quartile"] = pd.qcut(df["pct"], q=n_bins, labels=False, duplicates="drop") + 1
            by_q = df.groupby("quartile", observed=True)["forward_return"].mean().to_dict()
            hit_q = df.groupby("quartile", observed=True)["forward_return"].apply(
                lambda s: (s > 0).mean()
            ).to_dict()
            # Coerce keys to int
            by_q = {int(k): float(v) for k, v in by_q.items()}
            hit_q = {int(k): float(v) for k, v in hit_q.items()}
        except (ValueError, Exception) as e:
            # Last-resort fallback — no quartile breakdown but stats still work
            df["quartile"] = 1
            by_q = {1: float(df["forward_return"].mean())}
            hit_q = {1: float((df["forward_return"] > 0).mean())}

    corr = df["pct"].corr(df["forward_return"]) if len(df) >= 5 else None

    summary = {
        "n_observations": len(df),
        "n_tickers": df["symbol"].nunique(),
        "avg_return_overall": float(df["forward_return"].mean()),
        "median_return_overall": float(df["forward_return"].median()),
        "hit_rate_overall": float((df["forward_return"] > 0).mean()),
        "by_quartile": by_q,
        "hit_rate_by_quartile": hit_q,
        "correlation": float(corr) if corr is not None and not pd.isna(corr) else None,
        "forward_days": forward_days,
        "profile_id": profile_id,
    }

    return {"rows": all_rows, "summary": summary, "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# Forward-tracking (uses snapshots table accumulated over time)
# ---------------------------------------------------------------------------

def forward_tracking_report(min_age_days: int = 30) -> dict:
    """Compare scores you saved >= min_age_days ago to today's actual prices.

    Out-of-sample: no hindsight, no fitting. The most honest test possible.
    Takes weeks to accumulate enough data to be meaningful.
    """
    snaps = db.get_snapshots(older_than_days=min_age_days)
    if not snaps:
        return {"summary": {}, "rows": [],
                "message": f"No snapshots older than {min_age_days} days yet. "
                           f"Diagnose stocks to start building the dataset."}

    rows = []
    for snap in snaps:
        sym = snap["symbol"]
        old_price = snap.get("price")
        if not old_price:
            continue
        # Get current price
        try:
            t = yf.Ticker(sym)
            h = t.history(period="5d", auto_adjust=False)
            if h.empty:
                continue
            current = float(h["Close"].iloc[-1])
        except Exception:
            continue
        ret = (current / old_price) - 1
        snapped_at = pd.to_datetime(snap["snapped_at"])
        age_days = (pd.Timestamp.utcnow() - snapped_at).days
        rows.append({
            "symbol": sym,
            "snapped_at": snap["snapped_at"][:10],
            "age_days": age_days,
            "old_price": old_price,
            "current_price": current,
            "actual_return": ret,
            "buffett_pct": snap.get("buffett_pct", 0),
            "graham_pct": snap.get("graham_pct", 0),
            "lynch_pct": snap.get("lynch_pct", 0),
            "fisher_pct": snap.get("fisher_pct", 0),
            "best_profile": snap.get("best_profile"),
            "best_pct": snap.get("best_pct", 0),
        })

    if not rows:
        return {"summary": {}, "rows": [], "message": "No snapshots could be evaluated."}

    df = pd.DataFrame(rows)
    summary = {}
    for profile in ["buffett", "graham", "lynch", "fisher"]:
        col = f"{profile}_pct"
        if df[col].std() > 0:
            corr = df[col].corr(df["actual_return"])
        else:
            corr = None
        summary[profile] = {
            "correlation": float(corr) if corr is not None and not pd.isna(corr) else None,
        }
    summary["n_observations"] = len(df)
    summary["avg_actual_return"] = float(df["actual_return"].mean())
    summary["hit_rate"] = float((df["actual_return"] > 0).mean())

    return {"summary": summary, "rows": df.to_dict("records")}


# ---------------------------------------------------------------------------
# Default universes (curated for backtest)
# ---------------------------------------------------------------------------

DEFAULT_UNIVERSES = {
    "Dow 30 (large cap blue chips)": (
        "AAPL", "MSFT", "JPM", "V", "JNJ", "WMT", "PG", "MA", "HD", "CVX",
        "MRK", "ABBV", "KO", "PEP", "CSCO", "MCD", "CRM", "BAC", "AMGN", "DIS",
        "TMO", "DHR", "VZ", "NKE", "INTC", "AXP", "BA", "GS", "CAT", "TRV",
    ),
    "Tech mega caps": (
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
        "ADBE", "NFLX", "CSCO", "AMD", "QCOM", "INTC", "TXN", "INTU", "PYPL", "SHOP",
    ),
    "Quality compounders watchlist": (
        "AAPL", "MSFT", "GOOGL", "META", "V", "MA", "COST", "WMT", "HD", "MCD",
        "NKE", "SBUX", "DIS", "MRK", "TMO", "DHR", "ASML", "TSM", "NVDA", "AVGO",
    ),
    "Value / dividend names": (
        "JPM", "BAC", "WFC", "XOM", "CVX", "VZ", "T", "PFE", "MRK", "JNJ",
        "PG", "KO", "PEP", "MO", "PM", "F", "GM", "C", "INTC", "IBM",
    ),
}


# Map each profile to a Finviz screen that captures its philosophy.
# Used by get_auto_universe() to "let the profile pick its own tickers".
PROFILE_SCREEN_FILTERS = {
    "buffett": {
        "Return on Equity": "Over +20%",
        "Return on Investment": "Over +15%",
        "Gross Margin": "Over 40%",
        "Operating Margin": "Over 15%",
        "Debt/Equity": "Under 0.5",
    },
    "graham": {
        "P/E": "Under 15",
        "P/B": "Under 2",
        "Debt/Equity": "Under 1",
        "Current Ratio": "Over 2",
    },
    "lynch": {
        "PEG": "Under 1",
        "EPS growthpast 5 years": "Over 15%",
        "EPS growthnext 5 years": "Over 15%",
        "Return on Equity": "Over +15%",
    },
    "fisher": {
        "EPS growthnext 5 years": "Over 20%",
        "Sales growthpast 5 years": "Over 15%",
        "Gross Margin": "Over 40%",
        "Return on Investment": "Over +15%",
    },
    "inflection": {
        "Sales growthqtr over qtr": "Over 20%",
    },
    "canslim": {
        "EPS growthqtr over qtr": "Over 25%",
        "EPS growthnext 5 years": "Over 20%",
        "200-Day Simple Moving Average": "Price above SMA200",
        "50-Day Simple Moving Average": "SMA50 above SMA200",
        "InstitutionalOwnership": "Over 30%",
    },
    "magic_formula": {
        "P/E": "Under 10",
        "Return on Investment": "Over +20%",
    },
    "dividend": {
        "Dividend Yield": "Over 3%",
        "Payout Ratio": "Under 70%",
        "Debt/Equity": "Under 1",
    },
    "minervini": {
        "200-Day Simple Moving Average": "Price 10% above SMA200",
        "50-Day Simple Moving Average": "SMA50 above SMA200",
        # 52w high filter not used — Finviz only has 0-3/5/10% below High (too strict)
        # or 20%+ below High (wrong direction). SMA filters carry the trend test.
        "EPS growthqtr over qtr": "Over 20%",
        "RSI (14)": "Not Overbought (<60)",
    },
}


@st.cache_data(ttl=3600, show_spinner=False)
def get_auto_universe(profile_id: str, include_foreign: bool = False,
                     min_mkt_cap: str = "+Small (over $300mln)",
                     limit: int = 1000,
                     _progress_cb=None) -> tuple:
    """Run a Finviz screen matching the profile, return a LARGE candidate pool.

    Pulls from many sort orders to overcome alphabetical bias and to span the
    quality + momentum + size + value dimensions. With limit=1000 and 6 sort
    orders pulling ~250 each, we typically get 800-1500+ unique tickers.

    _progress_cb: optional callable(stage_label, pct_complete) for UI feedback.
                  Underscore prefix tells Streamlit's cache to skip hashing it.

    Takes 1-3 minutes due to finvizfinance's 1-second-per-page polite delay.
    Result is cached for an hour so repeat calls are instant.
    """
    filt = PROFILE_SCREEN_FILTERS.get(profile_id, {}).copy()
    filt["Market Cap."] = min_mkt_cap
    filt["Average Volume"] = "Over 200K"
    if not include_foreign:
        filt["Country"] = "USA"

    from finvizfinance.screener.overview import Overview

    # Six sort dimensions covering quality, momentum, value, growth, size, yield.
    # Union of top-N from each = a broad, unbiased candidate pool.
    sort_orders = [
        ("Market Cap.",                False),  # largest first (cap rank)
        ("Return on Equity",           False),  # most profitable first (quality)
        ("Performance (Year)",         False),  # best 1Y momentum
        ("EPS growth past 5 years",    False),  # best historical earnings growth
        ("Sales growth past 5 years",  False),  # best revenue growth
        ("Operating Margin",           False),  # best margins
    ]
    per_order = max(150, limit // len(sort_orders))
    tickers: set = set()
    total_orders = len(sort_orders)

    for i, (order, ascend) in enumerate(sort_orders):
        if _progress_cb:
            _progress_cb(
                f"Pulling top {per_order} by '{order}' ({i+1}/{total_orders})",
                i / total_orders,
            )
        try:
            ov = Overview()
            ov.set_filter(filters_dict=filt)
            df = ov.screener_view(order=order, limit=per_order,
                                  ascend=ascend, verbose=0)
            if df is not None and not df.empty and "Ticker" in df.columns:
                tickers.update(df["Ticker"].tolist())
        except Exception:
            continue
        # Safety cap so we don't pull forever
        if len(tickers) >= limit * 2:
            break

    if _progress_cb:
        _progress_cb(f"Pulled {len(tickers)} unique tickers", 1.0)

    return tuple(sorted(tickers))
