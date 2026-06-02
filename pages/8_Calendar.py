# -*- coding: utf-8 -*-
"""Calendar — full-market earnings, economic events, and IPOs.

Consolidates the three views you'd otherwise check separately on Yahoo Finance
(earnings / economic / IPO calendars) into one date-range tool. Every company
reporting, every macro release, and every IPO in the selected range is shown on
its own date — sourced live from Nasdaq's public calendar API.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import ui
from lib import glossary as gloss
from lib import sidebar_chat
from lib import calendar_events as cal

st.set_page_config(page_title="Calendar", page_icon="📅", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()
sidebar_chat.render_chat("calendar")

ui.page_header(
    title="Calendar",
    subtitle="Full-market earnings, economic events, and IPOs for any date range. Everything on its respective date.",
    icon="📅",
    live=True,
)

if gloss.is_explain_mode():
    ui.explain_panel(
        "Pick a date range, then use the three tabs. <b>Earnings</b> = every company reporting "
        "(filter by size, search, or limit to your watchlist). <b>Economic</b> = macro releases "
        "like CPI, jobs, and Fed events. <b>IPOs</b> = newly priced and upcoming listings. "
        "Names on your watchlist are marked with a ★."
    )

# ---------------------------------------------------------------------------
# Date-range state + navigation
# ---------------------------------------------------------------------------

if "cal_start" not in st.session_state:
    st.session_state.cal_start = date.today()
    st.session_state.cal_end = date.today() + timedelta(days=6)

span_days = (st.session_state.cal_end - st.session_state.cal_start).days + 1

nav = st.columns([1, 1, 1, 3, 1])
if nav[0].button("◀ Back", use_container_width=True, key="cal_back"):
    st.session_state.cal_start -= timedelta(days=span_days)
    st.session_state.cal_end -= timedelta(days=span_days)
    st.rerun()
if nav[1].button("Today", use_container_width=True, key="cal_today"):
    st.session_state.cal_start = date.today()
    st.session_state.cal_end = date.today() + timedelta(days=6)
    st.rerun()
if nav[2].button("Forward ▶", use_container_width=True, key="cal_fwd"):
    st.session_state.cal_start += timedelta(days=span_days)
    st.session_state.cal_end += timedelta(days=span_days)
    st.rerun()
with nav[3]:
    picked = st.date_input(
        "Date range",
        value=(st.session_state.cal_start, st.session_state.cal_end),
        label_visibility="collapsed",
        key="cal_range_input",
    )
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        if (picked[0], picked[1]) != (st.session_state.cal_start, st.session_state.cal_end):
            st.session_state.cal_start, st.session_state.cal_end = picked[0], picked[1]
            st.rerun()
if nav[4].button("Reload", use_container_width=True, key="cal_reload",
                 help="Clear the calendar cache and refetch from Nasdaq"):
    cal.fetch_earnings_day.clear()
    cal.fetch_economic_day.clear()
    cal.fetch_ipos_month.clear()
    st.rerun()

start = st.session_state.cal_start
end = st.session_state.cal_end
if end < start:
    start, end = end, start
    st.session_state.cal_start, st.session_state.cal_end = start, end
if (end - start).days > cal.MAX_RANGE_DAYS:
    end = start + timedelta(days=cal.MAX_RANGE_DAYS)
    st.session_state.cal_end = end
    st.warning(f"Range capped at {cal.MAX_RANGE_DAYS + 1} days to keep things fast.")

st.markdown(
    f"### {start.strftime('%b')} {start.day}, {start.year} "
    f"&nbsp;→&nbsp; {end.strftime('%b')} {end.day}, {end.year}"
    f"<span style='font-size:12px;color:#6b6b6b;font-weight:400'> · {(end - start).days + 1} days · source: Nasdaq</span>",
    unsafe_allow_html=True,
)
st.caption(ui.freshness_note())

wl = cal.watchlist_set()


def _day_header(d: date, suffix: str) -> str:
    today = date.today()
    badge = " · 📍 today" if d == today else ""
    return f"#### {d.strftime('%A, %b')} {d.day}, {d.year}{badge} · {suffix}"


tab_earn, tab_econ, tab_ipo = st.tabs(["📊 Earnings", "🏛️ Economic", "🚀 IPOs"])

# ===========================================================================
# EARNINGS
# ===========================================================================
with tab_earn:
    fc = st.columns([1.2, 1, 2])
    cap_choice = fc[0].selectbox(
        "Min market cap", ["All sizes", "≥ $300M", "≥ $2B", "≥ $10B", "≥ $50B"], key="cal_cap",
    )
    wl_only = fc[1].checkbox("Watchlist only", key="cal_wl_only", disabled=not wl,
                             help=None if wl else "Your watchlist is empty.")
    search = fc[2].text_input("Search symbol or company", placeholder="e.g. NVDA or Costco",
                              key="cal_search").strip().lower()
    cap_min = {"All sizes": 0, "≥ $300M": 3e8, "≥ $2B": 2e9, "≥ $10B": 1e10, "≥ $50B": 5e10}[cap_choice]

    prog = st.progress(0.0, text="Loading earnings…")
    earnings = cal.get_earnings_range(
        start, end, lambda i, n, lbl: prog.progress(i / n, text=f"Loading earnings… {lbl}"))
    prog.empty()

    def _passes(r: dict) -> bool:
        if cap_min and (r["market_cap"] or 0) < cap_min:
            return False
        if wl_only and r["symbol"] not in wl:
            return False
        if search and search not in r["symbol"].lower() and search not in r["name"].lower():
            return False
        return True

    total_shown = 0
    rendered_any = False
    for d, rows in earnings.items():
        filtered = [r for r in rows if _passes(r)]
        if not filtered:
            continue
        rendered_any = True
        total_shown += len(filtered)
        filtered.sort(key=lambda r: (r["market_cap"] is not None, r["market_cap"] or 0), reverse=True)
        st.markdown(_day_header(d, f"{len(filtered)} reporting"), unsafe_allow_html=True)

        _cols = [
            {"key": "wl", "label": "★"},
            {"key": "when", "label": "When"},
            {"key": "sym", "label": "Symbol", "cls": "sym"},
            {"key": "company", "label": "Company"},
            {"key": "mktcap", "label": "Mkt Cap", "align": "num"},
            {"key": "fcst", "label": "EPS Fcst", "align": "num"},
            {"key": "actual", "label": "Reported", "align": "num"},
            {"key": "surprise", "label": "Surprise", "align": "num"},
            {"key": "ests", "label": "# Est", "align": "num"},
        ]
        _rows = []
        for r in filtered:
            is_wl = r["symbol"] in wl
            _rows.append({
                "_row_cls": "wl-row" if is_wl else "",
                "wl": "★" if is_wl else "",
                "when": r["time_label"],
                "sym": r["symbol"],
                "company": r["name"],
                "mktcap": cal.fmt_money_short(r["market_cap"]),
                "fcst": f"${r['eps_forecast']:.2f}" if r["eps_forecast"] is not None else "—",
                "actual": f"${r['eps_actual']:.2f}" if r["eps_actual"] is not None else "—",
                "surprise": f"{r['surprise_pct']:+.1f}%" if r["surprise_pct"] is not None else "—",
                "ests": r["num_ests"],
            })
        ui.glass_table(_cols, _rows)

    if not earnings:
        st.info("No earnings found in this range. Try widening the dates or clicking Reload.")
    elif not rendered_any:
        st.info("No earnings match your filters. Loosen the market-cap filter, clear the search, or turn off Watchlist only.")
    else:
        st.caption(f"Showing **{total_shown}** companies across {len(earnings)} day(s) with reports. ★ = watchlist.")

# ===========================================================================
# ECONOMIC EVENTS
# ===========================================================================
with tab_econ:
    prog = st.progress(0.0, text="Loading economic events…")
    econ = cal.get_economic_range(
        start, end, lambda i, n, lbl: prog.progress(i / n, text=f"Loading economic events… {lbl}"))
    prog.empty()

    if not econ:
        st.info("No economic events found in this range.")
    else:
        all_countries = sorted({r["country"] for rows in econ.values() for r in rows if r["country"] != "—"})
        default_countries = ["United States"] if "United States" in all_countries else all_countries
        picked_countries = st.multiselect(
            "Countries", all_countries, default=default_countries, key="cal_countries",
            help="Defaults to United States. Add others to compare global macro.",
        )
        show_desc = st.checkbox("Show event descriptions", value=False, key="cal_econ_desc")
        country_set = set(picked_countries)

        shown = 0
        for d, rows in econ.items():
            day_rows = [r for r in rows if r["country"] in country_set]
            if not day_rows:
                continue
            shown += len(day_rows)
            st.markdown(_day_header(d, f"{len(day_rows)} releases"), unsafe_allow_html=True)
            _econ_cols = [
                {"key": "time", "label": "Time"},
                {"key": "country", "label": "Country"},
                {"key": "event", "label": "Event"},
                {"key": "actual", "label": "Actual", "align": "num"},
                {"key": "consensus", "label": "Consensus", "align": "num"},
                {"key": "previous", "label": "Previous", "align": "num"},
            ]
            _econ_rows = [{"time": r["time"], "country": r["country"], "event": r["event"],
                           "actual": r["actual"], "consensus": r["consensus"], "previous": r["previous"]}
                          for r in day_rows]
            ui.glass_table(_econ_cols, _econ_rows)

            if show_desc:
                with st.expander("ℹ️ Event descriptions"):
                    seen = set()
                    for r in day_rows:
                        if r["description"] and r["event"] not in seen:
                            seen.add(r["event"])
                            st.markdown(f"**{r['event']}** — {r['description'][:400]}")

        if not shown:
            st.info("No events for the selected countries. Add more countries above.")
        else:
            st.caption(f"Showing **{shown}** releases. Times are GMT, as supplied by Nasdaq.")

# ===========================================================================
# IPOs
# ===========================================================================
with tab_ipo:
    with st.spinner("Loading IPO calendar…"):
        ipos = cal.get_ipos_range(start, end)

    _ipo_cols = [
        {"key": "date", "label": "Date"},
        {"key": "sym", "label": "Symbol", "cls": "sym"},
        {"key": "company", "label": "Company"},
        {"key": "exchange", "label": "Exchange"},
        {"key": "price", "label": "Price", "align": "num"},
        {"key": "shares", "label": "Shares", "align": "num"},
        {"key": "value", "label": "Offer Amt", "align": "num"},
    ]
    def _ipo_rows(rows):
        return [{
            "date": r["date_str"], "sym": r["symbol"], "company": r["company"],
            "exchange": r["exchange"],
            "price": f"${r['price']}" if r["price"] not in ("—", "") else "—",
            "shares": r["shares"], "value": r["value_str"],
        } for r in rows]

    priced = ipos["priced"]
    upcoming = ipos["upcoming"]

    st.markdown("#### 🟢 Priced in range")
    if priced:
        for d, rows in priced.items():
            st.markdown(_day_header(d, f"{len(rows)} priced"), unsafe_allow_html=True)
            ui.glass_table(_ipo_cols, _ipo_rows(rows))
    else:
        st.caption("No IPOs priced in this range.")

    st.markdown("#### 🔵 Upcoming / expected")
    if upcoming:
        for d, rows in upcoming.items():
            st.markdown(_day_header(d, f"{len(rows)} expected"), unsafe_allow_html=True)
            ui.glass_table(_ipo_cols, _ipo_rows(rows))
    else:
        st.caption("No upcoming IPOs dated within this range.")

    months_label = ", ".join(ipos.get("months", []))
    if ipos["filed"]:
        with st.expander(f"📄 Recently filed (S-1) — {months_label} ({len(ipos['filed'])})"):
            ui.glass_table(_ipo_cols, _ipo_rows(ipos["filed"]))
    if ipos["withdrawn"]:
        with st.expander(f"🚫 Withdrawn — {months_label} ({len(ipos['withdrawn'])})"):
            ui.glass_table(_ipo_cols, _ipo_rows(ipos["withdrawn"]))
