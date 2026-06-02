# -*- coding: utf-8 -*-
"""Full-market calendar data layer.

Replaces the old yfinance-per-ticker approach (which could only cover a curated
~100-name universe) with Nasdaq's public calendar API. This gives the *entire*
market on each date — the same data behind Yahoo's three calendar pages:

  - Earnings:  https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD
  - Economic:  https://api.nasdaq.com/api/calendar/economicevents?date=YYYY-MM-DD
  - IPOs:      https://api.nasdaq.com/api/ipo/calendar?date=YYYY-MM

No API key required. Nasdaq blocks requests without a browser-like User-Agent,
so we send one. Every day/month is cached so range navigation is cheap, and a
date range is fetched concurrently.
"""
from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any, Callable

import streamlit as st

from lib import db
from lib import fmt as _fmt
from lib import http as _http


# ---------------------------------------------------------------------------
# Low-level Nasdaq fetch
# ---------------------------------------------------------------------------

_NASDAQ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}

MAX_RANGE_DAYS = 31  # guardrail: don't let a range fan out into hundreds of calls


def _nasdaq_get(url: str, timeout: int = 15) -> dict[str, Any] | None:
    """GET a Nasdaq API URL with browser headers. Returns parsed JSON or None.

    Transient HTTP failures (timeouts, 429, 5xx) are retried with backoff by the
    shared session's adapter; we add one extra try here to cover a non-200 or a
    JSON-decode failure (e.g. an HTML challenge page), which the adapter won't retry.
    """
    session = _http.get_session()
    for _attempt in range(2):
        try:
            r = session.get(url, headers=_NASDAQ_HEADERS, timeout=timeout)
            if r.status_code != 200:
                continue
            return r.json()
        except Exception:  # noqa: BLE001 — best-effort fetch
            continue
    return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _to_float(v: Any) -> float | None:
    """Parse '$441,523,007,808', '$4.93', '1.07', ' ' → float or None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    if not s or s.upper() in ("N/A", "NA", "—", "-", "UNCH"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _clean_text(v: Any) -> str:
    """Trim and normalise a cell that may be blank or a single space."""
    if v is None:
        return "—"
    s = str(v).strip()
    return s if s else "—"


def _strip_html(v: Any) -> str:
    """Unescape entities and remove tags from Nasdaq's description blobs."""
    if not v:
        return ""
    s = html.unescape(str(v))
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _earnings_time_label(raw: str | None) -> str:
    m = (raw or "").lower()
    if "pre" in m or "before" in m:
        return "Before open"
    if "after" in m or "post" in m:
        return "After close"
    return "—"


# Canonical formatter (lib/fmt.py). Kept under this name for existing call sites.
fmt_money_short = _fmt.fmt_money


# ---------------------------------------------------------------------------
# Earnings (per day, full market)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_earnings_day(date_str: str) -> list[dict[str, Any]]:
    """All companies reporting on `date_str` (YYYY-MM-DD), full market.

    Each row:
      {symbol, name, market_cap (float|None), eps_forecast, eps_actual,
       surprise_pct, time_label, num_ests, fiscal_quarter}
    """
    data = _nasdaq_get(f"https://api.nasdaq.com/api/calendar/earnings?date={date_str}")
    rows = (((data or {}).get("data") or {}).get("rows")) or []
    out: list[dict[str, Any]] = []
    for r in rows:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        out.append({
            "symbol": sym,
            "name": _clean_text(r.get("name")),
            "market_cap": _to_float(r.get("marketCap")),
            "eps_forecast": _to_float(r.get("epsForecast")),
            "eps_actual": _to_float(r.get("eps")),
            "surprise_pct": _to_float(r.get("surprise")),
            "time_label": _earnings_time_label(r.get("time")),
            "num_ests": _clean_text(r.get("noOfEsts")),
            "fiscal_quarter": _clean_text(r.get("fiscalQuarterEnding")),
        })
    return out


# ---------------------------------------------------------------------------
# Economic events (per day)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_economic_day(date_str: str) -> list[dict[str, Any]]:
    """All economic releases on `date_str` (YYYY-MM-DD).

    Each row: {time, country, event, actual, consensus, previous, description}
    """
    data = _nasdaq_get(f"https://api.nasdaq.com/api/calendar/economicevents?date={date_str}")
    rows = (((data or {}).get("data") or {}).get("rows")) or []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "time": _clean_text(r.get("gmt")),
            "country": _clean_text(r.get("country")),
            "event": _clean_text(r.get("eventName")),
            "actual": _clean_text(r.get("actual")),
            "consensus": _clean_text(r.get("consensus")),
            "previous": _clean_text(r.get("previous")),
            "description": _strip_html(r.get("description")),
        })
    return out


# ---------------------------------------------------------------------------
# IPOs (per month)
# ---------------------------------------------------------------------------

# (section key in API response, label, date field used for that section)
_IPO_SECTIONS = [
    ("priced", "Priced", "pricedDate"),
    ("upcoming", "Upcoming", "expectedPriceDate"),
    ("filed", "Filed", "filedDate"),
    ("withdrawn", "Withdrawn", "withdrawDate"),
]


def _parse_us_date(s: Any) -> date | None:
    """Parse Nasdaq's M/D/YYYY date strings to a date object."""
    if not s:
        return None
    txt = str(s).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def fetch_ipos_month(year_month: str) -> dict[str, list[dict[str, Any]]]:
    """IPO activity for a calendar month (year_month = 'YYYY-MM').

    Returns {section_key: [rows]} for priced/upcoming/filed/withdrawn. Each row:
      {symbol, company, exchange, price, shares, value (float|None),
       value_str, date (date|None), date_str}
    """
    data = _nasdaq_get(f"https://api.nasdaq.com/api/ipo/calendar?date={year_month}")
    block = (data or {}).get("data") or {}
    out: dict[str, list[dict[str, Any]]] = {}
    for key, _label, date_field in _IPO_SECTIONS:
        rows = ((block.get(key) or {}).get("rows")) or []
        parsed: list[dict[str, Any]] = []
        for r in rows:
            d = _parse_us_date(r.get(date_field) or r.get("pricedDate")
                               or r.get("expectedPriceDate") or r.get("filedDate"))
            value = _to_float(r.get("dollarValueOfSharesOffered"))
            parsed.append({
                "symbol": (r.get("proposedTickerSymbol") or "").strip().upper() or "—",
                "company": _clean_text(r.get("companyName")),
                "exchange": _clean_text(r.get("proposedExchange")),
                "price": _clean_text(r.get("proposedSharePrice")),
                "shares": _clean_text(r.get("sharesOffered")),
                "value": value,
                "value_str": fmt_money_short(value),
                "date": d,
                "date_str": d.strftime("%Y-%m-%d") if d else "—",
            })
        out[key] = parsed
    return out


# ---------------------------------------------------------------------------
# Range aggregation
# ---------------------------------------------------------------------------

def _daterange(start: date, end: date) -> list[date]:
    if end < start:
        start, end = end, start
    span = (end - start).days
    if span > MAX_RANGE_DAYS:
        end = start + timedelta(days=MAX_RANGE_DAYS)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _fetch_days_concurrent(days: list[date], fetcher: Callable[[str], Any],
                           progress_cb: Callable[[int, int, str], None] | None = None
                           ) -> dict[date, Any]:
    """Run a per-day fetcher across a date range concurrently, keyed by date."""
    results: dict[date, Any] = {}
    done = 0
    total = len(days)
    with ThreadPoolExecutor(max_workers=min(8, max(1, total))) as ex:
        futs = {ex.submit(fetcher, d.strftime("%Y-%m-%d")): d for d in days}
        for fut in futs:
            d = futs[fut]
            try:
                results[d] = fut.result()
            except Exception:
                results[d] = []
            done += 1
            if progress_cb:
                try:
                    progress_cb(done, total, d.strftime("%b %d"))
                except Exception:
                    pass
    return results


def get_earnings_range(start: date, end: date,
                       progress_cb: Callable[[int, int, str], None] | None = None
                       ) -> dict[date, list[dict]]:
    """{date: [earnings rows]} for every day in the range that has events."""
    days = _daterange(start, end)
    raw = _fetch_days_concurrent(days, fetch_earnings_day, progress_cb)
    return {d: rows for d, rows in sorted(raw.items()) if rows}


def get_economic_range(start: date, end: date,
                       progress_cb: Callable[[int, int, str], None] | None = None
                       ) -> dict[date, list[dict]]:
    """{date: [economic rows]} for every day in the range that has events."""
    days = _daterange(start, end)
    raw = _fetch_days_concurrent(days, fetch_economic_day, progress_cb)
    return {d: rows for d, rows in sorted(raw.items()) if rows}


def get_ipos_range(start: date, end: date) -> dict[str, Any]:
    """IPOs touching the range. Pulls every month the range spans, then buckets:

      {
        "priced":   {date: [rows]},   # priced within range
        "upcoming": {date: [rows]},   # expected to price within range
        "filed":    [rows],           # filed in spanned months (context)
        "withdrawn":[rows],           # withdrawn in spanned months (context)
      }
    """
    if end < start:
        start, end = end, start
    # Distinct YYYY-MM strings the range spans (usually 1-2).
    months: list[str] = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        ym = cur.strftime("%Y-%m")
        if ym not in months:
            months.append(ym)
        # advance one month
        cur = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)

    priced: dict[date, list[dict]] = {}
    upcoming: dict[date, list[dict]] = {}
    filed: list[dict] = []
    withdrawn: list[dict] = []
    for ym in months:
        block = fetch_ipos_month(ym)
        for row in block.get("priced", []):
            d = row.get("date")
            if d and start <= d <= end:
                priced.setdefault(d, []).append(row)
        for row in block.get("upcoming", []):
            d = row.get("date")
            if d is None or start <= d <= end:
                # undated "upcoming" rows still belong in the window's outlook
                key = d or end
                upcoming.setdefault(key, []).append(row)
        filed.extend(block.get("filed", []))
        withdrawn.extend(block.get("withdrawn", []))

    return {
        "priced": dict(sorted(priced.items())),
        "upcoming": dict(sorted(upcoming.items())),
        "filed": filed,
        "withdrawn": withdrawn,
        "months": months,
    }


# ---------------------------------------------------------------------------
# Watchlist helper (for highlighting names the user actually tracks)
# ---------------------------------------------------------------------------

def watchlist_set() -> set[str]:
    try:
        return {s.upper().replace(".", "-") for s in db.get_watchlist()}
    except Exception:
        return set()


def week_start(offset: int = 0) -> date:
    """Monday's date for the requested week (0 = this week). Kept for callers
    that still navigate by week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday + timedelta(weeks=offset)
