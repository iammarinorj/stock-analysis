"""SEC EDGAR insider-transaction (Form 4) reader — authoritative, no API key.

Replaces the fragile Finviz insider scrape for the detailed insider views with
data straight from the SEC:

  ticker -> CIK         via https://www.sec.gov/files/company_tickers.json
  recent Form 4 list    via https://data.sec.gov/submissions/CIK##########.json
  per-filing detail     via the Form 4 XML in the filing's Archives folder

We parse non-derivative transactions and key on transaction code:
  P = open-market / private PURCHASE (what we care about — real conviction)
  S = sale

SEC asks for a descriptive User-Agent and ~10 req/s max. We send a UA, route
through the shared retrying/caching session, fetch filing XML concurrently with a
small worker pool, and cache aggressively (filings are immutable once filed).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any

import streamlit as st

from lib import http as _http

# SEC requires a descriptive UA with contact info. Generic personal-research UA.
SEC_HEADERS = {"User-Agent": "StockAnalysisApp personal-research contact@example.com"}


# ---------------------------------------------------------------------------
# Ticker -> CIK
# ---------------------------------------------------------------------------

@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def _cik_map() -> dict[str, str]:
    """{TICKER: zero-padded-CIK}. Cached a week (rarely changes)."""
    try:
        r = _http.get_session().get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS, timeout=15,
        )
        m = r.json()
        return {str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10) for v in m.values()}
    except Exception:
        return {}


def ticker_to_cik(symbol: str) -> str | None:
    if not symbol:
        return None
    return _cik_map().get(symbol.upper())


# ---------------------------------------------------------------------------
# Recent Form 4 filings for a CIK
# ---------------------------------------------------------------------------

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _recent_form4(cik: str) -> list[dict]:
    """[{acc, date, doc}] of recent Form 4 filings, most recent first."""
    try:
        sub = _http.get_session().get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=SEC_HEADERS, timeout=15,
        ).json()
        rec = sub.get("filings", {}).get("recent", {})
        forms = rec.get("form", [])
        out = []
        for i in range(len(forms)):
            if forms[i] == "4":
                out.append({
                    "acc": rec["accessionNumber"][i],
                    "date": rec["filingDate"][i],
                    "doc": rec["primaryDocument"][i],
                })
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Parse one Form 4 XML
# ---------------------------------------------------------------------------

def _relationship_title(root: ET.Element) -> str:
    rel = root.find(".//reportingOwner/reportingOwnerRelationship")
    if rel is None:
        return "—"
    parts = []
    if rel.findtext("isDirector") in ("1", "true"):
        parts.append("Director")
    if rel.findtext("isOfficer") in ("1", "true"):
        parts.append(rel.findtext("officerTitle") or "Officer")
    if rel.findtext("isTenPercentOwner") in ("1", "true"):
        parts.append("10% owner")
    if rel.findtext("isOther") in ("1", "true"):
        parts.append(rel.findtext("otherText") or "Other")
    return ", ".join(parts) if parts else "—"


@st.cache_data(ttl=30 * 24 * 3600, show_spinner=False)
def _parse_form4(cik_nozero: str, acc: str, doc: str) -> list[dict]:
    """Parse a single Form 4 filing's non-derivative transactions.

    Returns list of {owner, title, code, is_buy, is_sell, shares, price, value, date}.
    Cached 30 days — filed documents never change.
    """
    acc_nodash = acc.replace("-", "")
    raw_doc = doc.split("/")[-1]  # strip the xslF345X06/ styled-view prefix
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_nozero}/{acc_nodash}/{raw_doc}"
    try:
        txt = _http.get_session().get(url, headers=SEC_HEADERS, timeout=15).text
        root = ET.fromstring(txt)
    except Exception:
        return []

    owner = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName") or "—"
    title = _relationship_title(root)
    out = []
    for t in root.findall(".//nonDerivativeTransaction"):
        code = (t.findtext(".//transactionCoding/transactionCode") or "").upper()
        if code not in ("P", "S"):
            continue
        try:
            shares = float(t.findtext(".//transactionAmounts/transactionShares/value") or 0)
        except (TypeError, ValueError):
            shares = 0.0
        try:
            price = float(t.findtext(".//transactionAmounts/transactionPricePerShare/value") or 0)
        except (TypeError, ValueError):
            price = 0.0
        tdate = t.findtext(".//transactionDate/value") or ""
        out.append({
            "owner": owner.title() if owner.isupper() else owner,
            "title": title,
            "code": code,
            "is_buy": code == "P",
            "is_sell": code == "S",
            "shares": shares,
            "price": price,
            "value": shares * price if (shares and price) else None,
            "date": tdate,
        })
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_insider_transactions(symbol: str, days: int = 90, buys_only: bool = True,
                             max_filings: int = 60) -> list[dict]:
    """Insider transactions for `symbol` over the last `days`.

    Filters Form 4s by filing date *before* fetching XML (cheap), then parses the
    survivors concurrently. Each row also carries the symbol. Sorted newest first.
    """
    cik = ticker_to_cik(symbol)
    if not cik:
        return []
    cik_nozero = str(int(cik))  # Archives path uses the un-padded CIK

    cutoff = date.today() - timedelta(days=days)
    filings = []
    for f in _recent_form4(cik):
        try:
            fdate = datetime.strptime(f["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if fdate >= cutoff:
            filings.append(f)
    filings = filings[:max_filings]
    if not filings:
        return []

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = ex.map(lambda f: _parse_form4(cik_nozero, f["acc"], f["doc"]), filings)
        for txns in results:
            rows.extend(txns)

    if buys_only:
        rows = [r for r in rows if r["is_buy"]]
    # Keep only transactions whose TRADE date is within the window (filing can lag).
    cstr = cutoff.strftime("%Y-%m-%d")
    rows = [r for r in rows if r["date"] >= cstr]
    for r in rows:
        r["symbol"] = symbol.upper()
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_insider_summary(symbol: str, months: int = 6) -> dict[str, Any]:
    """Buy/sell summary over the last `months`, shape-compatible with the old
    Finviz summary used by scoring/profiles.

    {has_cluster_buy, buy_count, sell_count, net_value, last_buy_date}
    """
    days = int(months * 30.4)
    txns = get_insider_transactions(symbol, days=days, buys_only=False)
    buys = [t for t in txns if t["is_buy"]]
    sells = [t for t in txns if t["is_sell"]]
    unique_buyers = {t["owner"] for t in buys}
    net = sum(t["value"] or 0 for t in buys) - sum(t["value"] or 0 for t in sells)
    last_buy = buys[0]["date"] if buys else None
    return {
        "has_cluster_buy": len(unique_buyers) >= 2,
        "buy_count": len(buys),
        "sell_count": len(sells),
        "net_value": net,
        "last_buy_date": last_buy,
    }
