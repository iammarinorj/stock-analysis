# -*- coding: utf-8 -*-
"""Insider Buys — market-wide SEC Form 4 open-market purchases.

Shows ALL recent insider purchases across the entire market (via Finviz),
with your watchlist tickers flagged ⭐. Also supports a focused SEC EDGAR
scan for specific tickers over a date range.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st

from lib import ui, edgar, db, finviz as fv_mod
from lib import glossary as gloss
from lib import sidebar_chat

st.set_page_config(page_title="Insider Buys", page_icon="🟢", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()
sidebar_chat.render_chat("insider_buys")

ui.page_header(
    title="Insider Buys",
    subtitle="Real insider purchases across the entire market. Insiders buy for one reason — conviction.",
    icon="🟢",
    live=True,
)

if gloss.is_explain_mode():
    ui.explain_panel(
        "Every officer, director, and 10%-owner must report trades to the SEC on a <b>Form 4</b>. "
        "This page shows <b>all recent insider purchases</b> across the market, not just your watchlist. "
        "Watchlist tickers are flagged with ⭐ so you can spot when YOUR names have insider activity. "
        "<b>Cluster buying</b> — multiple insiders buying the same stock in a short window — is one of "
        "the strongest signals available to retail investors. Use the 'Ticker lookup' tab for a deep "
        "EDGAR scan on specific names."
    )

wl = set(db.get_watchlist())

tab_market, tab_lookup = st.tabs(["🌐 Market-wide buys", "🔍 Ticker lookup (EDGAR)"])

# =====================================================================
# TAB 1: Market-wide insider buys
# =====================================================================
with tab_market:
    with st.spinner("Pulling latest insider buys across the market…"):
        all_buys = fv_mod.get_market_insider_buys()

    if not all_buys:
        ui.empty_state("No insider purchases found. Finviz may be temporarily unavailable — try again in a minute.")
        st.stop()

    # Flag watchlist tickers
    for b in all_buys:
        b["on_watchlist"] = b["symbol"] in wl

    wl_buys = [b for b in all_buys if b["on_watchlist"]]

    # ---- Summary tiles ----
    total_value = sum(b["value"] or 0 for b in all_buys)
    unique_tickers = sorted({b["symbol"] for b in all_buys})
    # Cluster = 2+ unique insiders buying same ticker
    clusters = [t for t in unique_tickers
                if len({b["owner"] for b in all_buys if b["symbol"] == t}) >= 2]

    s1, s2, s3, s4, s5 = st.columns(5)
    with s1:
        ui.kpi_tile("Purchases", str(len(all_buys)), "across market")
    with s2:
        ui.kpi_tile("Total bought", ui.fmt_money(total_value), "", "pos")
    with s3:
        ui.kpi_tile("Companies", str(len(unique_tickers)), "")
    with s4:
        ui.kpi_tile("Cluster buys", str(len(clusters)),
                    ", ".join(clusters[:4]) if clusters else "none", "pos" if clusters else "")
    with s5:
        ui.kpi_tile("⭐ On watchlist", str(len(wl_buys)),
                    f"{len({b['symbol'] for b in wl_buys})} tickers" if wl_buys else "none",
                    "pos" if wl_buys else "")

    if clusters:
        st.success(f"🔥 **Cluster buying** (2+ different insiders buying) detected in: **{', '.join(clusters)}**")

    if wl_buys:
        wl_names = sorted({b["symbol"] for b in wl_buys})
        st.info(f"⭐ Watchlist tickers with insider buys: **{', '.join(wl_names)}**")

    st.write("")

    # ---- Filter controls ----
    fc1, fc2 = st.columns([2, 1])
    filter_mode = fc1.radio(
        "Show", ["All buys", "⭐ Watchlist only", "Cluster buys only"],
        horizontal=True, key="mkt_filter",
    )
    min_value = fc2.number_input("Min value ($)", value=0, step=10000, key="mkt_minval",
                                  help="Filter out small insider buys below this dollar amount")

    # Apply filters
    display_buys = list(all_buys)
    if filter_mode == "⭐ Watchlist only":
        display_buys = [b for b in display_buys if b["on_watchlist"]]
    elif filter_mode == "Cluster buys only":
        display_buys = [b for b in display_buys if b["symbol"] in clusters]
    if min_value > 0:
        display_buys = [b for b in display_buys if (b["value"] or 0) >= min_value]

    # ---- Table ----
    display_buys.sort(key=lambda b: (b["value"] or 0), reverse=True)
    _cols = [
        {"key": "flag", "label": ""},
        {"key": "date", "label": "Date"},
        {"key": "sym", "label": "Symbol", "cls": "sym"},
        {"key": "insider", "label": "Insider"},
        {"key": "title", "label": "Title"},
        {"key": "shares", "label": "Shares", "align": "num"},
        {"key": "price", "label": "Price", "align": "num"},
        {"key": "value", "label": "Value", "align": "num"},
        {"key": "filed", "label": "Filed"},
    ]
    _rows = [{
        "flag": "⭐" if b["on_watchlist"] else ("🔥" if b["symbol"] in clusters else ""),
        "date": b["date"],
        "sym": b["symbol"],
        "insider": b["owner"],
        "title": b["title"],
        "shares": f"{int(b['shares']):,}" if b["shares"] else "—",
        "price": f"${b['cost']:.2f}" if b["cost"] else "—",
        "value": ui.fmt_money(b["value"]),
        "filed": b.get("filing_date", ""),
    } for b in display_buys]

    if _rows:
        ui.glass_table(_cols, _rows)
    else:
        ui.empty_state("No buys match your filters. Try broadening the criteria.")

    st.caption(
        "Recent open-market purchases across the entire US market. Sorted by dollar value. "
        "⭐ = on your watchlist. 🔥 = cluster buying (2+ insiders). "
        "Data: Finviz (sourced from SEC Form 4 filings), cached 30min."
    )


# =====================================================================
# TAB 2: Ticker lookup — focused SEC EDGAR scan
# =====================================================================
with tab_lookup:
    ui.section_head(
        "Deep EDGAR scan",
        "Enter specific tickers for a thorough SEC EDGAR Form 4 search over your chosen time window.",
    )

    c1, c2 = st.columns([2, 1])
    with c1:
        raw = st.text_input(
            "Tickers (comma-separated)",
            placeholder="e.g. HIMS, NVDA, F",
            key="edgar_tickers",
        ).strip()
    with c2:
        lookback_label = st.selectbox(
            "Look back", ["Today", "Last 7 days", "Last 30 days", "Last 90 days"], index=2,
            key="edgar_lookback",
        )
    days = {"Today": 1, "Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}[lookback_label]

    if raw:
        tickers = [t.strip().upper() for t in raw.replace(";", ",").split(",") if t.strip()]
    else:
        tickers = []

    if not tickers:
        ui.empty_state(
            "Enter one or more tickers above to scan SEC EDGAR directly for insider purchases."
        )
    else:
        st.caption(f"Scanning **{len(tickers)}** ticker(s) for insider purchases over **{lookback_label.lower()}** · source: SEC EDGAR Form 4")

        # ---- Fetch (parallel across tickers) ----
        prog = st.progress(0.0, text="Querying SEC EDGAR…")
        edgar_buys: list[dict] = []
        done = 0

        def _fetch(sym):
            return edgar.get_insider_transactions(sym, days=days, buys_only=True)

        with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as ex:
            futs = {ex.submit(_fetch, s): s for s in tickers}
            for fut in futs:
                try:
                    edgar_buys.extend(fut.result() or [])
                except Exception:
                    pass
                done += 1
                prog.progress(done / len(tickers), text=f"Querying SEC EDGAR… ({done}/{len(tickers)})")
        prog.empty()

        if not edgar_buys:
            st.info(
                f"No insider **purchases** filed for these tickers in the {lookback_label.lower()}. "
                "Try a longer window — purchases are rarer than sales, so 'Today' is often empty."
            )
        else:
            total_value = sum(b["value"] or 0 for b in edgar_buys)
            unique_tickers_e = sorted({b["symbol"] for b in edgar_buys})
            clusters_e = [t for t in unique_tickers_e
                          if len({b["owner"] for b in edgar_buys if b["symbol"] == t and b["is_buy"]}) >= 2]

            es1, es2, es3, es4 = st.columns(4)
            with es1:
                ui.kpi_tile("Purchases", str(len(edgar_buys)), "")
            with es2:
                ui.kpi_tile("Total bought", ui.fmt_money(total_value), "", "pos")
            with es3:
                ui.kpi_tile("Companies", str(len(unique_tickers_e)), "")
            with es4:
                ui.kpi_tile("Cluster buys", str(len(clusters_e)),
                            ", ".join(clusters_e[:4]) if clusters_e else "none", "pos" if clusters_e else "")

            if clusters_e:
                st.success(f"🔥 **Cluster buying** detected in: **{', '.join(clusters_e)}**")

            st.write("")

            edgar_buys.sort(key=lambda b: (b["value"] or 0), reverse=True)
            _cols_e = [
                {"key": "flag", "label": ""},
                {"key": "date", "label": "Date"},
                {"key": "sym", "label": "Symbol", "cls": "sym"},
                {"key": "insider", "label": "Insider"},
                {"key": "title", "label": "Title"},
                {"key": "shares", "label": "Shares", "align": "num"},
                {"key": "price", "label": "Price", "align": "num"},
                {"key": "value", "label": "Value", "align": "num"},
            ]
            _rows_e = [{
                "flag": "⭐" if b["symbol"] in wl else "",
                "date": b["date"],
                "sym": b["symbol"],
                "insider": b["owner"],
                "title": b["title"],
                "shares": f"{int(b['shares']):,}" if b["shares"] else "—",
                "price": f"${b['price']:.2f}" if b["price"] else "—",
                "value": ui.fmt_money(b["value"]),
            } for b in edgar_buys]
            ui.glass_table(_cols_e, _rows_e)

            st.caption(
                "Open-market purchases only (Form 4 transaction code P). Sorted by dollar value. "
                "⭐ = on your watchlist. Data: SEC EDGAR, cached 6h. Verify any single filing at sec.gov before acting."
            )
