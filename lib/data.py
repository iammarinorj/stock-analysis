"""Data fetchers for yfinance (stock data) and FRED (macro data).

All functions are cached via Streamlit's cache_data so we don't hammer the APIs.
TTL is 5 minutes for stock data and 60 minutes for macro (macro updates slowly).
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st
import yfinance as yf

from lib import http as _http


# ---------------------------------------------------------------------------
# yfinance cloud-deployment fix: Yahoo Finance aggressively blocks datacenter
# IPs (Streamlit Cloud, Heroku, AWS, etc.). yfinance 1.4+ uses curl_cffi to
# impersonate Chrome, which bypasses the block. If curl_cffi isn't installed,
# yfinance falls back to plain requests — which gets blocked, causing .info
# to return empty dicts and all fundamentals to show "—".
#
# Fix: ensure curl_cffi is in requirements.txt. As a belt-and-suspenders
# fallback, also set the UA on yfinance's fallback path.
# ---------------------------------------------------------------------------
try:
    _BROWSER_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    if hasattr(yf, "_http"):
        # Patch the fallback UA used when curl_cffi is not available
        if hasattr(yf._http, "_FALLBACK_USER_AGENT"):
            yf._http._FALLBACK_USER_AGENT = _BROWSER_UA
except Exception:
    pass

# ---------------------------------------------------------------------------
# Stock data via yfinance
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def resolve_ticker(query: str) -> dict[str, Any]:
    """Resolve a user query to a stock ticker.

    Accepts tickers (AAPL), company names (Apple), partial names (hims & hers),
    or mistyped variations. Uses yfinance.Search internally.

    Returns:
      {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "confidence": "exact_ticker" | "name_match" | "fuzzy" | "none",
        "alternatives": [{"symbol": ..., "name": ...}, ...],  # other matches
        "original_query": "Apple",
        "error": str | None,
      }
    """
    q_raw = (query or "").strip()
    if not q_raw:
        return {"error": "empty query", "original_query": query}

    q_upper = q_raw.upper()

    # Path 1: looks like a ticker (1-6 chars, alphanumeric + . - allowed). Try direct first.
    is_tickerish = (
        len(q_upper) <= 6 and
        all(c.isalnum() or c in ".-" for c in q_upper) and
        " " not in q_upper
    )
    if is_tickerish:
        try:
            t = yf.Ticker(q_upper)
            info = t.info or {}
            # If yfinance returns a real price or name, this IS a valid ticker
            if (info.get("regularMarketPrice") is not None
                or info.get("longName") or info.get("shortName")):
                return {
                    "symbol": q_upper,
                    "name": info.get("longName") or info.get("shortName") or q_upper,
                    "confidence": "exact_ticker",
                    "alternatives": [],
                    "original_query": query,
                    "error": None,
                }
        except Exception:
            pass  # fall through to search

    # Path 2: search by name / fuzzy
    try:
        search = yf.Search(q_raw, max_results=8)
        quotes = getattr(search, "quotes", []) or []
    except Exception as e:
        return {"error": f"Search failed: {e}", "original_query": query}

    if not quotes:
        return {"error": f"No matches found for '{q_raw}'", "original_query": query}

    # Filter to US equities first (most likely what user wants)
    def is_us_equity(q):
        return (q.get("quoteType") == "EQUITY"
                and "." not in (q.get("symbol") or "")  # exclude foreign listings
                and q.get("exchange") not in ("MEX", "STU", "SGO"))

    us_equities = [q for q in quotes if is_us_equity(q)]
    pool = us_equities if us_equities else [q for q in quotes if q.get("quoteType") == "EQUITY"]
    if not pool:
        pool = quotes

    best = pool[0]
    alternatives = [
        {"symbol": q["symbol"], "name": q.get("longname") or q.get("shortname") or q["symbol"]}
        for q in pool[1:5]
    ]

    confidence = "name_match" if us_equities else "fuzzy"
    return {
        "symbol": best.get("symbol"),
        "name": best.get("longname") or best.get("shortname") or best.get("symbol"),
        "confidence": confidence,
        "alternatives": alternatives,
        "original_query": query,
        "error": None,
    }


@st.cache_data(ttl=1800, show_spinner=False)
def get_news(symbol: str, limit: int = 8) -> list[dict]:
    """Recent headlines for a ticker: [{title, link, source, date}].
    Tries yfinance.news (handles its shifting shape), falls back to Finviz."""
    items: list[dict] = []
    try:
        news = yf.Ticker(symbol).news or []
        for n in news:
            content = n.get("content") or n
            title = content.get("title") or n.get("title")
            link = ((content.get("canonicalUrl") or content.get("clickThroughUrl") or {}) or {}).get("url") or n.get("link")
            prov = ((content.get("provider") or {}) or {}).get("displayName") or n.get("publisher")
            pub = content.get("pubDate") or n.get("providerPublishTime")
            if isinstance(pub, (int, float)):
                pub = datetime.fromtimestamp(pub, tz=timezone.utc).strftime("%Y-%m-%d")
            elif isinstance(pub, str):
                pub = pub[:10]
            if title:
                items.append({"title": title, "link": link, "source": prov or "", "date": pub or ""})
            if len(items) >= limit:
                break
    except Exception:
        pass
    if items:
        return items
    # Fallback: Finviz news scrape
    try:
        from finvizfinance.quote import finvizfinance
        df = _http.with_retry(lambda: finvizfinance(symbol).ticker_news(), attempts=2, backoff=0.4)
        if df is not None and not getattr(df, "empty", True):
            for _, r in df.head(limit).iterrows():
                items.append({
                    "title": r.get("Title") or r.get("title"),
                    "link": r.get("Link") or r.get("link"),
                    "source": r.get("Source") or r.get("source") or "",
                    "date": str(r.get("Date") or r.get("date") or "")[:16],
                })
    except Exception:
        pass
    return items


@st.cache_data(ttl=300, show_spinner=False)
def get_last_price(symbol: str) -> float | None:
    """Cheap last price via yfinance fast_info (avoids the expensive multi-request
    .info). Used for lightweight needs like the watchlist 'since added' readout."""
    if not symbol:
        return None
    try:
        fi = yf.Ticker(symbol).fast_info
        # FastInfo: attribute is snake_case (last_price); .get() key is camelCase (lastPrice).
        px = getattr(fi, "last_price", None)
        if px is None and hasattr(fi, "get"):
            px = fi.get("lastPrice") or fi.get("previousClose")
        return float(px) if px else None
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def get_quote(symbol: str) -> dict[str, Any]:
    """Return latest quote + key fundamentals for a single symbol.

    Returns dict with: price, change, change_pct, market_cap, volume, 52w high/low,
    50/200 DMA, P/E, P/B, P/S, EV/EBITDA, dividend yield, beta, sector, industry,
    company name, description, country, CEO, employees, ipo date, website.
    """
    if not symbol:
        return {}
    try:
        t = yf.Ticker(symbol)
        # .info is the rate-limit-prone call; retry transient failures with backoff.
        info = _http.with_retry(lambda: t.info, attempts=3, backoff=0.5) or {}
        hist = t.history(period="2d", auto_adjust=False)
        if hist.empty:
            return {"error": f"No data for {symbol}"}

        price = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[0]) if len(hist) > 1 else info.get("previousClose", price)
        change = price - prev
        change_pct = (change / prev * 100) if prev else 0.0

        # Dividend yield: yfinance 1.x reports `dividendYield` as a PERCENT number
        # (e.g. 2.64 for 2.64%), while the rest of the app expects a decimal (0.0264).
        # `trailingAnnualDividendYield` is a stable decimal, so prefer it and fall
        # back to dividendYield/100. Without this the Dividend profile + TSY tile are
        # off by ~100x ("264.00% yield").
        _tady = info.get("trailingAnnualDividendYield")
        if _tady is not None and _tady < 1.0:
            # trailingAnnualDividendYield is a stable decimal (0.026 = 2.6%).
            # Sanity: > 100% is corrupt (common with foreign ADRs due to
            # currency mismatch in the dividend rate). Fall through to
            # dividendYield which is usually correct in those cases.
            div_yield = _tady
        elif info.get("dividendYield") is not None:
            dy_raw = info["dividendYield"]
            # dividendYield can be a percent (2.64) or a decimal (0.0264)
            # depending on yfinance version. Normalize to decimal.
            div_yield = dy_raw / 100.0 if dy_raw > 1.0 else dy_raw
        else:
            div_yield = None

        return {
            "symbol": symbol.upper(),
            "name": info.get("longName") or info.get("shortName"),
            "price": price,
            "change": change,
            "change_pct": change_pct,
            "market_cap": info.get("marketCap"),
            "volume": info.get("volume") or info.get("averageVolume"),
            "avg_volume": info.get("averageVolume"),
            "year_high": info.get("fiftyTwoWeekHigh"),
            "year_low": info.get("fiftyTwoWeekLow"),
            "dma_50": info.get("fiftyDayAverage"),
            "dma_200": info.get("twoHundredDayAverage"),
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "peg": info.get("trailingPegRatio") or info.get("pegRatio"),
            "pb": info.get("priceToBook"),
            "ps": info.get("priceToSalesTrailing12Months"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "ev_revenue": info.get("enterpriseToRevenue"),
            "div_yield": div_yield,
            "beta": info.get("beta"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "gross_margin": info.get("grossMargins"),
            "fcf": info.get("freeCashflow"),
            "ocf": info.get("operatingCashflow"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "ebitda": info.get("ebitda"),
            "revenue": info.get("totalRevenue"),
            "net_income": info.get("netIncomeToCommon"),
            "rev_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "rev_per_share": info.get("revenuePerShare"),
            "book_value": info.get("bookValue"),
            "shares_out": info.get("sharesOutstanding"),
            "shares_short": info.get("sharesShort"),
            "short_pct_float": info.get("shortPercentOfFloat"),
            "held_insiders": info.get("heldPercentInsiders"),
            "held_institutions": info.get("heldPercentInstitutions"),
            "currency": info.get("currency", "USD"),
            "exchange": info.get("exchange"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "ceo": _get_ceo(info),
            "employees": info.get("fullTimeEmployees"),
            "ipo_date": _parse_date(info.get("firstTradeDateEpochUtc")),
            "website": info.get("website"),
            "description": info.get("longBusinessSummary"),
            "next_earnings": _next_earnings(t),
            # Analyst
            "recommend": info.get("recommendationKey"),
            "recommend_mean": info.get("recommendationMean"),
            "n_analysts": info.get("numberOfAnalystOpinions"),
            "target_mean": info.get("targetMeanPrice"),
            "target_median": info.get("targetMedianPrice"),
            "target_high": info.get("targetHighPrice"),
            "target_low": info.get("targetLowPrice"),
            # Forward consensus estimates
            "eps_forward": info.get("forwardEps"),
            "eps_trailing": info.get("trailingEps"),
            "revenue_estimate": info.get("revenueEstimate"),
            "target_mean_price": info.get("targetMeanPrice"),
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@st.cache_data(ttl=900, show_spinner=False)
def get_peers(symbol: str) -> list[str]:
    """Return peer tickers for the symbol.

    Order of resolution:
      1. A curated map for the mega-caps (hand-picked cross-sector comparables).
      2. Otherwise, auto-discover the largest same-industry names via the Finviz
         screener. This means the peer table and sector-relative scoring now work
         for *every* ticker, not just the dozen below.

    Returns [] only if discovery fails — callers handle an empty list gracefully.
    """
    try:
        # Hardcoded peer maps for common cases — curated cross-sector comparables.
        peer_map = {
            "NVDA": ["AMD", "AVGO", "TSM", "INTC", "MU", "QCOM"],
            "AAPL": ["MSFT", "GOOGL", "AMZN", "META", "TSLA"],
            "META": ["GOOGL", "SNAP", "PINS", "AMZN", "MSFT"],
            "GOOGL": ["META", "MSFT", "AMZN", "AAPL"],
            "MSFT": ["GOOGL", "AAPL", "ORCL", "CRM", "AMZN"],
            "AMZN": ["MSFT", "GOOGL", "WMT", "EBAY", "SHOP"],
            "TSLA": ["GM", "F", "RIVN", "LCID", "NIO"],
            "COST": ["WMT", "BJ", "TGT", "KR"],
            "BRK-B": ["JPM", "BAC", "WFC", "C", "MS"],
            "JPM": ["BAC", "WFC", "C", "GS", "MS"],
            "XOM": ["CVX", "BP", "SHEL", "TTE", "COP"],
            "ORCL": ["MSFT", "SAP", "CRM", "IBM"],
            "ACN": ["IBM", "CTSH", "INFY", "WIT"],
        }
        if symbol.upper() in peer_map:
            return peer_map[symbol.upper()]
        # Auto-discover largest same-industry peers via Finviz (lazy import to
        # avoid any import cycle). Returns [] on failure → callers degrade cleanly.
        try:
            from lib import screener
            return screener.get_industry_peers(symbol, limit=8)
        except Exception:
            return []
    except Exception:
        return []


@st.cache_data(ttl=900, show_spinner=False)
def get_earnings_history(symbol: str, quarters: int = 6) -> pd.DataFrame:
    """Last N quarterly earnings: date, EPS est/actual/surprise, revenue est/actual/surprise.

    yfinance exposes some of this via Ticker.earnings_dates.
    """
    try:
        t = yf.Ticker(symbol)
        df = t.earnings_dates
        if df is None or df.empty:
            return pd.DataFrame()
        # Filter to past earnings (not future)
        df = df[df.index < pd.Timestamp.now(tz=df.index.tz)]
        df = df.head(quarters).copy()
        df = df.reset_index()
        # Normalize columns
        rename_map = {
            "Earnings Date": "date",
            "EPS Estimate": "eps_est",
            "Reported EPS": "eps_act",
            "Surprise(%)": "eps_surp_pct",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def get_price_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    """OHLCV history for charting."""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, auto_adjust=False)
        return df
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Macro data via FRED CSV endpoints (no API key required)
# ---------------------------------------------------------------------------

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


@st.cache_data(ttl=3600, show_spinner=False)
def get_fred_series(series_id: str, days: int = 30) -> dict[str, Any]:
    """Return latest value + date for a FRED series.

    Returns: {value, date, prev_value, prev_date, change, change_pct, trend}
    where trend is "rising" | "falling" | "flat".
    """
    try:
        url = FRED_CSV.format(series_id=series_id)
        r = _http.get_session().get(url, timeout=10)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", "value"]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"]).sort_values("date")
        if df.empty:
            return {}

        latest = df.iloc[-1]
        # Find prior reading days ago
        cutoff = latest["date"] - timedelta(days=days)
        prior = df[df["date"] <= cutoff]
        if not prior.empty:
            prev = prior.iloc[-1]
        else:
            prev = df.iloc[-2] if len(df) > 1 else latest

        latest_value = float(latest["value"])
        prev_value = float(prev["value"])
        change = latest_value - prev_value
        change_pct = (change / prev_value * 100) if prev_value else 0.0
        trend = "rising" if change > 0 else ("falling" if change < 0 else "flat")

        return {
            "series_id": series_id,
            "value": latest_value,
            "date": latest["date"].strftime("%Y-%m-%d"),
            "prev_value": prev_value,
            "prev_date": prev["date"].strftime("%Y-%m-%d"),
            "change": change,
            "change_pct": change_pct,
            "trend": trend,
        }
    except Exception as e:
        return {"error": str(e), "series_id": series_id}


@st.cache_data(ttl=3600, show_spinner=False)
def get_fred_history(series_id: str, years: int = 5) -> pd.DataFrame:
    """Multi-year history for a FRED series (for charting)."""
    try:
        url = FRED_CSV.format(series_id=series_id)
        r = _http.get_session().get(url, timeout=10)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", "value"]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna()
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        return df[df["date"] >= cutoff].sort_values("date")
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ceo(info: dict) -> str | None:
    officers = info.get("companyOfficers") or []
    for o in officers:
        title = (o.get("title") or "").lower()
        if "ceo" in title or "chief executive" in title:
            return o.get("name")
    if officers:
        return officers[0].get("name")
    return None


def _parse_date(epoch: int | None) -> str | None:
    if not epoch:
        return None
    try:
        # firstTradeDateEpochUtc is a UTC epoch — interpret it as UTC so the
        # date doesn't shift by a day on machines west of Greenwich.
        return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return None


def _next_earnings(ticker) -> str | None:
    try:
        cal = ticker.calendar
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed and len(ed) > 0:
                d = ed[0]
                if hasattr(d, "strftime"):
                    return d.strftime("%Y-%m-%d")
                return str(d)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Composite getter: yfinance + Finviz combined
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_enriched_quote(symbol: str) -> dict[str, Any]:
    """Pull yfinance + Finviz + insider transactions, return a single merged quote.

    The merged dict has everything from get_quote(), PLUS:
      rsi_14, perf_week/month/quarter/year, sma_20/50/200 distance,
      volatility_w/m, short_float, short_ratio, recommendation (1-5 from Finviz),
      insider_buys_6mo, insider_sells_6mo, insider_cluster_buy, insider_net_value
    """
    base = get_quote(symbol)
    if "error" in base:
        return base
    try:
        from lib import finviz as fv_mod
        fv = fv_mod.get_finviz_fundament(symbol)
        merged = fv_mod.merge_into_quote(base, fv)
        # Also fetch insider transactions and summarize
        ins_df = fv_mod.get_finviz_insider(symbol, limit=20)
        ins_summary = fv_mod.has_recent_insider_buys(ins_df, months=6)
        # If Finviz is down (error flag set), fall back to authoritative SEC EDGAR
        # Form 4 data so the insider signal still works. Only triggers on a Finviz
        # outage — no cost on the common path — and EDGAR's summary has the same shape.
        if isinstance(fv, dict) and fv.get("error"):
            try:
                from lib import edgar as _edgar
                ed = _edgar.get_insider_summary(symbol)
                if ed.get("buy_count") or ed.get("sell_count"):
                    ins_summary = ed
                    merged["_insider_source"] = "SEC EDGAR (Finviz unavailable)"
            except Exception:
                pass
        merged["insider_buys_6mo"] = ins_summary["buy_count"]
        merged["insider_sells_6mo"] = ins_summary["sell_count"]
        merged["insider_cluster_buy"] = ins_summary["has_cluster_buy"]
        merged["insider_net_value"] = ins_summary["net_value"]
        merged["insider_last_buy"] = ins_summary["last_buy_date"]
        return merged
    except Exception as e:
        # Finviz unavailable - return yfinance base
        base["_finviz_error"] = str(e)
        return base


@st.cache_data(ttl=900, show_spinner=False)
def get_insider_transactions(symbol: str) -> pd.DataFrame:
    """Pass-through to Finviz insider transactions DataFrame for display."""
    try:
        from lib import finviz as fv_mod
        return fv_mod.get_finviz_insider(symbol, limit=20)
    except Exception:
        return pd.DataFrame()




