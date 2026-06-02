"""Technical analysis computed from daily price history (no extra network calls).

Produces moving averages, RSI(14), MACD, multi-period momentum, ATR, distance
from the 52-week high/low, a trend-stage classification, and rough support /
resistance — plus a one-line plain-English read.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _rsi(closes: pd.Series, period: int = 14) -> float | None:
    delta = closes.diff().dropna()
    if len(delta) < period + 1:
        return None
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    last_up, last_down = up.iloc[-1], down.iloc[-1]
    if last_down == 0:
        return 100.0
    rs = last_up / last_down
    return float(100 - 100 / (1 + rs))


def _macd(closes: pd.Series) -> dict:
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return {"macd": float(macd.iloc[-1]), "signal": float(signal.iloc[-1]),
            "hist": float(hist.iloc[-1]),
            "bullish": bool(macd.iloc[-1] > signal.iloc[-1])}


def _returns(closes: pd.Series) -> dict:
    last = float(closes.iloc[-1])
    out = {}
    for label, days in (("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252)):
        if len(closes) > days:
            out[label] = last / float(closes.iloc[-days]) - 1
    return out


def compute(symbol: str, price_df, quote: dict) -> dict[str, Any]:
    """Return a dict of technical readings + a 'summary' read string. {} if no data."""
    try:
        if price_df is None or getattr(price_df, "empty", True):
            return {}
        closes = price_df["Close"] if "Close" in price_df.columns else price_df.iloc[:, 0]
        closes = closes.dropna()
        if len(closes) < 30:
            return {}
        price = float(closes.iloc[-1])
        sma20 = float(closes.tail(20).mean())
        sma50 = float(closes.tail(50).mean()) if len(closes) >= 50 else None
        sma200 = float(closes.tail(200).mean()) if len(closes) >= 200 else None
        rsi = quote.get("rsi_14") or _rsi(closes)
        macd = _macd(closes)
        rets = _returns(closes)

        hi52 = quote.get("year_high") or float(closes.max())
        lo52 = quote.get("year_low") or float(closes.min())
        from_high = (price / hi52 - 1) if hi52 else None
        from_low = (price / lo52 - 1) if lo52 else None

        # Trend stage from price vs SMAs
        if sma50 and sma200:
            if price > sma50 > sma200:
                stage = "Uptrend (Stage 2)"
            elif price < sma50 < sma200:
                stage = "Downtrend (Stage 4)"
            elif price > sma200:
                stage = "Recovering / basing"
            else:
                stage = "Topping / weakening"
        elif sma200:
            stage = "Above 200DMA" if price > sma200 else "Below 200DMA"
        else:
            stage = "Insufficient history"

        # Rough support/resistance from recent swing extremes (last ~3 months)
        window = closes.tail(63)
        support = float(window.min())
        resistance = float(window.max())

        # One-line read
        bits = [stage]
        if rsi is not None:
            if rsi >= 70:
                bits.append(f"RSI {rsi:.0f} (overbought)")
            elif rsi <= 30:
                bits.append(f"RSI {rsi:.0f} (oversold)")
            else:
                bits.append(f"RSI {rsi:.0f} (neutral)")
        bits.append("MACD bullish" if macd["bullish"] else "MACD bearish")
        if from_high is not None:
            bits.append(f"{from_high*100:+.0f}% vs 52w high")
        summary = " · ".join(bits)

        return {
            "price": price, "sma20": sma20, "sma50": sma50, "sma200": sma200,
            "rsi": rsi, "macd": macd, "returns": rets,
            "from_52w_high": from_high, "from_52w_low": from_low,
            "trend_stage": stage, "support": support, "resistance": resistance,
            "atr": quote.get("atr"),
            "above_200dma": (sma200 is not None and price > sma200),
            "summary": summary,
        }
    except Exception:
        return {}
