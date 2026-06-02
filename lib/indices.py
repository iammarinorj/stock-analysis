"""Live snapshots of major indices, rates, FX, commodities, and crypto.

Uses yfinance free-tier symbols. Cached for 5 minutes during market hours.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st
import yfinance as yf


# Maps range labels to yfinance period strings + month windows for FRED slicing.
# "YTD" and "MAX" are handled specially.
RANGE_OPTIONS = ["5D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX"]

RANGE_TO_YF_PERIOD = {
    "5D":  "5d",
    "1M":  "1mo",
    "3M":  "3mo",
    "6M":  "6mo",
    "YTD": "ytd",
    "1Y":  "1y",
    "2Y":  "2y",
    "5Y":  "5y",
    "10Y": "10y",
    "MAX": "max",
}

# Months of FRED history to slice for the sparkline. None = special (YTD/MAX).
RANGE_TO_FRED_MONTHS = {
    "5D":  1,    # FRED is monthly; show last 1 month
    "1M":  1,
    "3M":  3,
    "6M":  6,
    "YTD": None, # slice from Jan 1 of current year
    "1Y":  12,
    "2Y":  24,
    "5Y":  60,
    "10Y": 120,
    "MAX": None, # pull all available (use very large years value)
}

# Years to PULL from FRED (must cover the slice window + YoY lookback if needed).
# Pull more than we slice — slicing happens in the page.
RANGE_TO_FRED_FETCH_YEARS = {
    "5D":  1,
    "1M":  1,
    "3M":  1,
    "6M":  1,
    "YTD": 2,
    "1Y":  2,
    "2Y":  3,
    "5Y":  5,
    "10Y": 10,
    "MAX": 100,  # FRED returns whatever exists up to this
}


def fred_cutoff_for_range(range_label: str):
    """Return a pd.Timestamp cutoff for slicing FRED history by selected range.

    Returns None for MAX (no slicing).
    """
    import pandas as pd
    from datetime import datetime
    if range_label == "MAX":
        return None
    if range_label == "YTD":
        return pd.Timestamp(datetime.now().year, 1, 1)
    months = RANGE_TO_FRED_MONTHS.get(range_label, 12)
    if months is None:
        return None
    return pd.Timestamp.now() - pd.DateOffset(months=months)


# Ticker, display name, category, format hint
INDICES = [
    # US Equity indices
    ("^GSPC", "S&P 500", "equity", "index"),
    ("^DJI", "Dow Jones", "equity", "index"),
    ("^IXIC", "Nasdaq Composite", "equity", "index"),
    ("^NDX", "Nasdaq 100", "equity", "index"),
    ("^RUT", "Russell 2000", "equity", "index"),
    # Volatility
    ("^VIX", "VIX", "volatility", "vol"),
    # Rates
    ("^TNX", "10Y Treasury", "rates", "pct"),
    ("^TYX", "30Y Treasury", "rates", "pct"),
    ("^FVX", "5Y Treasury", "rates", "pct"),
    # FX
    ("DX-Y.NYB", "Dollar Index (DXY)", "fx", "fx"),
    ("EURUSD=X", "EUR/USD", "fx", "fx"),
    ("USDJPY=X", "USD/JPY", "fx", "fx"),
    # Commodities
    ("GC=F", "Gold", "commodity", "price"),
    ("SI=F", "Silver", "commodity", "price"),
    ("CL=F", "Crude Oil (WTI)", "commodity", "price"),
    ("NG=F", "Natural Gas", "commodity", "price"),
    ("HG=F", "Copper", "commodity", "price"),
    # Crypto
    ("BTC-USD", "Bitcoin", "crypto", "price"),
    ("ETH-USD", "Ethereum", "crypto", "price"),
]


@st.cache_data(ttl=300, show_spinner=False)
def get_index_snapshot(symbol: str) -> dict[str, Any]:
    """Pull current level + day change + vs 50/200 DMA + YTD for one ticker."""
    try:
        t = yf.Ticker(symbol)
        # Use 1-year history for DMA calcs + YTD
        hist = t.history(period="1y", auto_adjust=False)
        if hist.empty:
            return {"error": "No history", "symbol": symbol}

        close = hist["Close"]
        latest = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else latest
        day_change = latest - prev
        day_pct = (day_change / prev) if prev else 0

        dma_50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        dma_200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
        vs_50 = ((latest / dma_50) - 1) if dma_50 else None
        vs_200 = ((latest / dma_200) - 1) if dma_200 else None

        # YTD
        ytd_start = pd.Timestamp(year=datetime.now().year, month=1, day=2, tz=close.index.tz)
        ytd_hist = close[close.index >= ytd_start]
        if not ytd_hist.empty and len(ytd_hist) > 0:
            ytd_open = float(ytd_hist.iloc[0])
            ytd_pct = (latest / ytd_open) - 1
        else:
            ytd_pct = None

        # 1mo, 3mo
        def lookback(days):
            cutoff = close.index[-1] - pd.Timedelta(days=days)
            past = close[close.index <= cutoff]
            if past.empty:
                return None
            past_v = float(past.iloc[-1])
            return (latest / past_v) - 1
        mtd = lookback(30)
        qtd = lookback(90)

        high_52 = float(close.max())
        low_52 = float(close.min())
        from_high = (latest / high_52) - 1
        from_low = (latest / low_52) - 1

        # Sparkline series — last ~252 trading days, downsampled to ~60 points
        # for a compact inline SVG
        sparkline = []
        if len(close) > 0:
            sample_n = min(60, len(close))
            step = max(1, len(close) // sample_n)
            sparkline = [float(v) for v in close.iloc[::step].tolist()]
            # Always include the last point
            if close.iloc[-1] != sparkline[-1]:
                sparkline.append(float(close.iloc[-1]))

        return {
            "symbol": symbol,
            "level": latest,
            "day_change": day_change,
            "day_pct": day_pct,
            "dma_50": dma_50,
            "dma_200": dma_200,
            "vs_50": vs_50,
            "vs_200": vs_200,
            "ytd_pct": ytd_pct,
            "mtd_pct": mtd,
            "qtd_pct": qtd,
            "high_52": high_52,
            "low_52": low_52,
            "from_high": from_high,
            "from_low": from_low,
            "as_of": close.index[-1].strftime("%Y-%m-%d") if not close.empty else None,
            "sparkline": sparkline,
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}


def fmt_index_level(symbol: str, level: float, fmt_hint: str) -> str:
    """Format a level appropriately by index type."""
    if level is None:
        return "—"
    if fmt_hint == "pct":  # ^TNX returns yield * 10 (e.g. 4.5% shown as 45)
        # ^TNX is reported as the yield directly in older yfinance; in newer it's pct*100
        # Standard practice: ^TNX = 10Y yield as a number (4.5 = 4.5%)
        return f"{level:.2f}%"
    if fmt_hint == "vol":
        return f"{level:.1f}"
    if fmt_hint == "fx":
        return f"{level:.4f}" if level < 10 else f"{level:.2f}"
    if fmt_hint == "price":
        return f"${level:,.2f}"
    # Index numbers
    return f"{level:,.2f}"


def all_snapshots(categories: list[str] | None = None) -> list[dict]:
    """Return enriched snapshots for all (or filtered) indices.

    Snapshots are fetched concurrently (each get_index_snapshot is an independent
    cached yfinance call), so the Macro page loads in ~1 round-trip's time instead
    of ~19 serial fetches. Output order is preserved to match INDICES.
    """
    from concurrent.futures import ThreadPoolExecutor

    wanted = [(s, n, c, f) for (s, n, c, f) in INDICES if not (categories and c not in categories)]
    if not wanted:
        return []

    with ThreadPoolExecutor(max_workers=min(8, len(wanted))) as ex:
        snaps = list(ex.map(lambda row: get_index_snapshot(row[0]), wanted))

    out = []
    for (symbol, name, cat, fmt_hint), snap in zip(wanted, snaps):
        snap.update({"name": name, "category": cat, "fmt_hint": fmt_hint})
        out.append(snap)
    return out


@st.cache_data(ttl=900, show_spinner=False)
def get_full_history(symbol: str, period: str = "max") -> dict:
    """Pull full history with dates + closes + 50/200 DMAs for interactive chart.

    Default period='max' so the in-chart range buttons can zoom into any window.
    """
    try:
        t = yf.Ticker(symbol)
        h = t.history(period=period, auto_adjust=False)
        if h is None or h.empty:
            return {"error": "no data"}
        close = h["Close"]
        dma_50 = close.rolling(50).mean()
        dma_200 = close.rolling(200).mean()
        return {
            "dates": [d.to_pydatetime() if hasattr(d, "to_pydatetime") else d for d in close.index],
            "closes": [float(v) if v == v else None for v in close.tolist()],
            "dma_50":  [float(v) if v == v else None for v in dma_50.tolist()],
            "dma_200": [float(v) if v == v else None for v in dma_200.tolist()],
            "symbol": symbol,
            "error": None,
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}


@st.cache_data(ttl=900, show_spinner=False)
def get_fred_full_history(series_id: str, years: int = 50) -> dict:
    """FRED history with dates + values for interactive chart. Pull ALL by default."""
    from lib import data as _data
    df = _data.get_fred_history(series_id, years=years)
    if df is None or df.empty:
        return {"error": "no data"}
    df = df.sort_values("date")
    return {
        "dates": [d.to_pydatetime() if hasattr(d, "to_pydatetime") else d for d in df["date"].tolist()],
        "values": [float(v) if v == v else None for v in df["value"].tolist()],
        "series_id": series_id,
        "error": None,
    }


@st.cache_data(ttl=300, show_spinner=False)
def get_sparkline_series(symbol: str, range_label: str = "1Y") -> list:
    """Pull close series only for the requested range. Used for sparkline charts.

    Snapshot stats stay computed from full 1y in `get_index_snapshot` — this
    function is for charts only so they can be range-controlled independently.
    """
    period = RANGE_TO_YF_PERIOD.get(range_label, "1y")
    try:
        t = yf.Ticker(symbol)
        h = t.history(period=period, auto_adjust=False)
        if h is None or h.empty:
            return []
        close = h["Close"]
        sample_n = min(60, len(close))
        step = max(1, len(close) // sample_n)
        out = [float(v) for v in close.iloc[::step].tolist()]
        if close.iloc[-1] != out[-1]:
            out.append(float(close.iloc[-1]))
        return out
    except Exception:
        return []
