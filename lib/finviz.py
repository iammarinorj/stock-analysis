"""Finviz data fetchers via finvizfinance (scrapes finviz.com public pages).

Fills the gaps yfinance doesn't cover:
  - RSI (14)
  - Insider transactions (actual buys/sells, not just % ownership)
  - Performance windows (week, month, quarter, YTD, year)
  - Sector P/E for relative valuation
  - Volatility (week, month)
  - Short ratio + short float (cleaner than yfinance)
  - SMA distance (% from 20/50/200 DMA)
  - Earnings dates
  - Analyst recommendation score (1-5)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from lib import http as _http


@st.cache_data(ttl=600, show_spinner=False)
def get_finviz_fundament(symbol: str) -> dict[str, Any]:
    """Pull the Finviz fundamental snapshot - the table that shows on finviz.com/quote.ashx.

    Returns a dict of all fields. Keys match Finviz column names.
    Numeric fields are parsed where possible (e.g. "21.5%" → 0.215; "1.23B" → 1.23e9).
    """
    def _fetch():
        from finvizfinance.quote import finvizfinance
        return finvizfinance(symbol).ticker_fundament()

    try:
        # Finviz scrapes finviz.com and is the flakiest source — retry transient
        # failures with backoff instead of silently dropping all enrichment.
        raw = _http.with_retry(_fetch, attempts=3, backoff=0.4)
        if not raw:
            return {}

        out = {"symbol": symbol.upper(), "_raw": raw}

        # Parse common fields we care about
        out["rsi_14"] = _parse_number(raw.get("RSI (14)"))
        out["beta"] = _parse_number(raw.get("Beta"))
        out["sma_20"] = _parse_pct(raw.get("SMA20"))
        out["sma_50"] = _parse_pct(raw.get("SMA50"))
        out["sma_200"] = _parse_pct(raw.get("SMA200"))
        out["perf_week"] = _parse_pct(raw.get("Perf Week"))
        out["perf_month"] = _parse_pct(raw.get("Perf Month"))
        out["perf_quarter"] = _parse_pct(raw.get("Perf Quarter"))
        out["perf_half_y"] = _parse_pct(raw.get("Perf Half Y"))
        out["perf_year"] = _parse_pct(raw.get("Perf Year"))
        out["perf_ytd"] = _parse_pct(raw.get("Perf YTD"))
        out["volatility_w"] = _parse_pct(raw.get("Volatility W"))
        out["volatility_m"] = _parse_pct(raw.get("Volatility M"))
        out["short_float"] = _parse_pct(raw.get("Short Float"))
        out["short_ratio"] = _parse_number(raw.get("Short Ratio"))
        out["insider_own"] = _parse_pct(raw.get("Insider Own"))
        out["insider_trans"] = _parse_pct(raw.get("Insider Trans"))
        out["inst_own"] = _parse_pct(raw.get("Inst Own"))
        out["inst_trans"] = _parse_pct(raw.get("Inst Trans"))
        out["recommendation"] = _parse_number(raw.get("Recom"))  # 1=Strong Buy, 5=Strong Sell
        out["target_price"] = _parse_number(raw.get("Target Price"))
        out["earnings_date"] = raw.get("Earnings")
        out["pe"] = _parse_number(raw.get("P/E"))
        out["forward_pe"] = _parse_number(raw.get("Forward P/E"))
        out["peg"] = _parse_number(raw.get("PEG"))
        out["pb"] = _parse_number(raw.get("P/B"))
        out["ps"] = _parse_number(raw.get("P/S"))
        out["p_fcf"] = _parse_number(raw.get("P/FCF"))
        out["eps_growth_this_y"] = _parse_pct(raw.get("EPS this Y"))
        out["eps_growth_next_y"] = _parse_pct(raw.get("EPS next Y"))
        out["eps_growth_5y"] = _parse_pct(raw.get("EPS next 5Y"))
        out["eps_growth_past_5y"] = _parse_pct(raw.get("EPS past 5Y"))
        out["sales_growth_5y"] = _parse_pct(raw.get("Sales past 5Y"))
        out["sales_qoq"] = _parse_pct(raw.get("Sales Q/Q"))
        out["eps_qoq"] = _parse_pct(raw.get("EPS Q/Q"))
        out["roa"] = _parse_pct(raw.get("ROA"))
        out["roe"] = _parse_pct(raw.get("ROE"))
        out["roi"] = _parse_pct(raw.get("ROI"))
        out["gross_margin"] = _parse_pct(raw.get("Gross Margin"))
        out["oper_margin"] = _parse_pct(raw.get("Oper. Margin"))
        out["profit_margin"] = _parse_pct(raw.get("Profit Margin"))
        out["debt_eq"] = _parse_number(raw.get("Debt/Eq"))
        out["lt_debt_eq"] = _parse_number(raw.get("LT Debt/Eq"))
        out["current_ratio"] = _parse_number(raw.get("Current Ratio"))
        out["quick_ratio"] = _parse_number(raw.get("Quick Ratio"))
        out["payout"] = _parse_pct(raw.get("Payout"))
        out["dividend_yield"] = _parse_pct(raw.get("Dividend %"))
        out["eps_ttm"] = _parse_number(raw.get("EPS (ttm)"))
        out["book_per_share"] = _parse_number(raw.get("Book/sh"))
        out["cash_per_share"] = _parse_number(raw.get("Cash/sh"))
        out["price"] = _parse_number(raw.get("Price"))
        out["change"] = _parse_pct(raw.get("Change"))
        out["volume"] = _parse_number(raw.get("Volume"))
        out["avg_volume"] = _parse_number(raw.get("Avg Volume"))
        out["market_cap"] = _parse_number(raw.get("Market Cap"))
        out["sector"] = raw.get("Sector")
        out["industry"] = raw.get("Industry")
        out["country"] = raw.get("Country")
        out["high_52w"] = _parse_number(raw.get("52W High"))
        out["low_52w"] = _parse_number(raw.get("52W Low"))
        out["shs_outstand"] = _parse_number(raw.get("Shs Outstand"))
        out["shs_float"] = _parse_number(raw.get("Shs Float"))
        out["atr"] = _parse_number(raw.get("ATR (14)") or raw.get("ATR"))
        return out
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@st.cache_data(ttl=900, show_spinner=False)
def get_finviz_insider(symbol: str, limit: int = 12) -> pd.DataFrame:
    """Recent insider transactions for the ticker.

    Columns vary by Finviz response. Typical: Insider Trading, Relationship, Date, Transaction, Cost, #Shares, Value ($), #Shares Total, SEC Form 4.
    """
    def _fetch():
        from finvizfinance.quote import finvizfinance
        return finvizfinance(symbol).ticker_inside_trader()

    try:
        df = _http.with_retry(_fetch, attempts=3, backoff=0.4)
        if df is None or df.empty:
            return pd.DataFrame()
        return df.head(limit).copy()
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Composite quote: merge yfinance + Finviz
# ---------------------------------------------------------------------------

def merge_into_quote(yf_quote: dict, fv: dict) -> dict:
    """Merge Finviz fields into the yfinance quote dict.

    yfinance is the source of truth for most numeric fundamentals (it's API-clean).
    Finviz fills gaps:
      - RSI 14
      - Performance windows
      - Distance from SMA 20/50/200 (% form)
      - Volatility window
      - Recom (analyst score 1-5)
      - Insider Trans (% net 6mo)
      - Inst Trans (% net 3mo)
      - Earnings date (often more reliable than yfinance .calendar)
      - ATR (14)
    """
    if not fv or "error" in fv:
        return yf_quote
    merged = dict(yf_quote)
    finviz_only = [
        "rsi_14", "sma_20", "sma_50", "sma_200",
        "perf_week", "perf_month", "perf_quarter", "perf_half_y", "perf_year", "perf_ytd",
        "volatility_w", "volatility_m",
        "short_float", "short_ratio",
        "insider_trans", "inst_trans",
        "recommendation",  # 1-5 from Finviz
        "atr",
        "eps_growth_this_y", "eps_growth_next_y", "eps_growth_5y", "eps_growth_past_5y",
        "sales_qoq", "eps_qoq",
        "p_fcf",
        # Balance-sheet ratios yfinance doesn't expose cleanly. Without these the
        # Graham (current ratio, debt) and Lynch (debt/equity) checks always failed.
        "debt_eq", "lt_debt_eq", "current_ratio", "quick_ratio",
        "payout", "dividend_yield", "insider_own", "inst_own",
        "book_per_share", "cash_per_share", "eps_ttm",
    ]
    for k in finviz_only:
        if fv.get(k) is not None:
            merged[k] = fv[k]
    # Use Finviz earnings date if yfinance is missing
    if not merged.get("next_earnings") and fv.get("earnings_date"):
        merged["next_earnings"] = fv["earnings_date"]
    # Stash a flag so the UI knows enrichment ran
    merged["_finviz_enriched"] = True
    return merged


def has_recent_insider_buys(insider_df: pd.DataFrame, months: int = 6) -> dict:
    """Analyze the insider transactions table.

    Returns:
      {
        has_cluster_buy: bool,  # 2+ insiders buying in last `months`
        buy_count: int,
        sell_count: int,
        net_value: float,  # buys minus sells in $
        last_buy_date: str | None,
      }
    """
    if insider_df is None or insider_df.empty:
        return {"has_cluster_buy": False, "buy_count": 0, "sell_count": 0,
                "net_value": 0, "last_buy_date": None}

    df = insider_df.copy()
    # Identify transaction type column
    txn_col = None
    for cand in ["Transaction", "transaction", "Type"]:
        if cand in df.columns:
            txn_col = cand
            break
    if not txn_col:
        return {"has_cluster_buy": False, "buy_count": 0, "sell_count": 0,
                "net_value": 0, "last_buy_date": None}

    # Date column
    date_col = None
    for cand in ["Date", "date", "Trade Date"]:
        if cand in df.columns:
            date_col = cand
            break

    # Value column
    val_col = None
    for cand in ["Value ($)", "Value", "value"]:
        if cand in df.columns:
            val_col = cand
            break

    # Identify name column (for cluster check)
    name_col = None
    for cand in ["Insider Trading", "Insider", "Name"]:
        if cand in df.columns:
            name_col = cand
            break

    # Parse date if present, filter to last N months
    if date_col:
        df[date_col] = df[date_col].astype(str)
        df["_date_parsed"] = pd.to_datetime(df[date_col], errors="coerce")
        cutoff = pd.Timestamp.now() - pd.DateOffset(months=months)
        df = df[df["_date_parsed"].isna() | (df["_date_parsed"] >= cutoff)]

    df["_txn_lc"] = df[txn_col].astype(str).str.lower()
    buys = df[df["_txn_lc"].str.contains("buy") | df["_txn_lc"].str.contains("purchase")]
    sells = df[df["_txn_lc"].str.contains("sale") | df["_txn_lc"].str.contains("sell")]

    # Cluster = 2+ unique insiders buying
    cluster = False
    if name_col and len(buys) >= 2:
        cluster = buys[name_col].nunique() >= 2

    # Net value
    def parse_val(s):
        try:
            return float(str(s).replace("$", "").replace(",", ""))
        except Exception:
            return 0.0

    net_value = 0.0
    if val_col:
        net_value = sum(parse_val(v) for v in buys[val_col]) - sum(parse_val(v) for v in sells[val_col])

    last_buy = None
    if not buys.empty and date_col:
        last_buy = str(buys[date_col].iloc[0])

    return {
        "has_cluster_buy": cluster,
        "buy_count": len(buys),
        "sell_count": len(sells),
        "net_value": net_value,
        "last_buy_date": last_buy,
    }


# ---------------------------------------------------------------------------
# Market-wide insider buys (not per-ticker — scans whole market)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def get_market_insider_buys() -> list[dict]:
    """Pull latest insider PURCHASES across the entire market from Finviz.

    Returns a list of dicts: {symbol, owner, title, date, cost, shares, value,
    shares_total, sec_link, filing_date}.  Sorted newest first.
    """
    def _fetch():
        from finvizfinance.insider import Insider
        ins = Insider(option="latest buys")
        return ins.get_insider()

    try:
        df = _http.with_retry(_fetch, attempts=2, backoff=1.0)
        if df is None or df.empty:
            return []
    except Exception:
        return []

    out = []
    for _, row in df.iterrows():
        try:
            cost = float(str(row.get("Cost", 0)).replace(",", "").replace("$", "") or 0)
        except (TypeError, ValueError):
            cost = 0.0
        try:
            shares = float(row.get("#Shares", 0) or 0)
        except (TypeError, ValueError):
            shares = 0.0
        try:
            value = float(str(row.get("Value ($)", 0)).replace(",", "").replace("$", "") or 0)
        except (TypeError, ValueError):
            value = 0.0
        try:
            shares_total = float(row.get("#Shares Total", 0) or 0)
        except (TypeError, ValueError):
            shares_total = 0.0
        out.append({
            "symbol": str(row.get("Ticker", "")).upper(),
            "owner": str(row.get("Owner", "—")),
            "title": str(row.get("Relationship", "—")),
            "date": str(row.get("Date", "")),
            "cost": cost,
            "shares": shares,
            "value": value,
            "shares_total": shares_total,
            "sec_link": str(row.get("SEC Form 4 Link", "")),
            "filing_date": str(row.get("SEC Form 4", "")),
        })
    return out


# ---------------------------------------------------------------------------
# Number parsing helpers
# ---------------------------------------------------------------------------

def _parse_number(v):
    """Parse strings like '1.23B', '21.5', '-' into floats. Returns None on failure."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s in ("-", "—", "N/A", "NA"):
        return None
    # Strip $ and ,
    s = s.replace("$", "").replace(",", "")
    # Magnitude suffixes
    mult = 1.0
    if s.endswith("K"):
        mult = 1e3
        s = s[:-1]
    elif s.endswith("M"):
        mult = 1e6
        s = s[:-1]
    elif s.endswith("B"):
        mult = 1e9
        s = s[:-1]
    elif s.endswith("T"):
        mult = 1e12
        s = s[:-1]
    elif s.endswith("%"):
        s = s[:-1]
        try:
            return float(s) / 100.0
        except ValueError:
            return None
    try:
        return float(s) * mult
    except ValueError:
        return None


def _parse_pct(v):
    """Parse percentage strings. Returns a decimal (5% → 0.05) or None.

    Always returns decimal form so callers can multiply by 100 if they want to display.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        # Heuristic: if value is between -1 and 1, assume it's already a decimal
        if -1 <= v <= 1:
            return float(v)
        return float(v) / 100.0
    s = str(v).strip()
    if not s or s in ("-", "—", "N/A", "NA"):
        return None
    s = s.replace(",", "")
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return None
    # Try as decimal
    try:
        f = float(s)
        if -1 <= f <= 1:
            return f
        return f / 100.0
    except ValueError:
        return None
