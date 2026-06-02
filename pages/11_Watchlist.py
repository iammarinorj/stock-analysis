# -*- coding: utf-8 -*-
"""Watchlist — your tracked tickers with live P&L since added.

Not auto-populated from diagnoses. You explicitly add tickers via the
"+ Watchlist" button on Stock Pro. This page shows every watched name
with the price when added, current price, and total gain/loss.
"""
from __future__ import annotations

import streamlit as st

from lib import ui, db, data
from lib import paper as paper_mod
from lib import glossary as gloss
from lib import sidebar_chat

st.set_page_config(page_title="Watchlist", page_icon="⭐", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()
sidebar_chat.render_chat("watchlist")

ui.page_header(
    title="Watchlist",
    subtitle="Your tracked tickers. Add from Stock Pro — track price changes since you started watching.",
    icon="⭐",
    live=True,
)

if gloss.is_explain_mode():
    ui.explain_panel(
        "Your watchlist is tickers you <b>explicitly chose to track</b> — not every ticker you've "
        "looked up. Add a stock on the Stock Pro page with the '+ Watchlist' button. This page "
        "shows the price at the time you added it, the current live price, and the % gain or loss "
        "since you started watching. Use it to see if your instincts about a name were right before "
        "committing capital."
    )

# ---- Add ticker form ----
with st.expander("➕ Add a ticker to your watchlist"):
    ac1, ac2 = st.columns([3, 1])
    add_raw = ac1.text_input("Ticker or company name", placeholder="e.g. AAPL, Hims, Tesla",
                              key="wl_add_input").strip()
    if ac2.button("Add", type="primary", use_container_width=True, key="wl_add_btn"):
        if add_raw:
            with st.spinner(f"Looking up '{add_raw}'…"):
                resolved = data.resolve_ticker(add_raw)
            if resolved.get("error"):
                st.error(resolved["error"])
            else:
                sym = resolved["symbol"]
                price = data.get_last_price(sym)
                db.add_to_watchlist(sym, price)
                st.success(f"Added **{sym}** ({resolved.get('name', '')}) at ${price:.2f}" if price
                           else f"Added **{sym}** (price unavailable)")
                st.rerun()
        else:
            st.warning("Enter a ticker or company name.")

st.write("")

# ---- Load watchlist ----
wl_detail = db.get_watchlist_detailed()
if not wl_detail:
    ui.empty_state(
        "Your watchlist is empty. Add tickers from <b>Stock Pro</b> (the '+ Watchlist' button) "
        "or use the form above."
    )
    st.stop()

# ---- Pull live prices ----
symbols = tuple(r["symbol"] for r in wl_detail)
with st.spinner(f"Pulling live prices for {len(symbols)} tickers…"):
    prices = paper_mod.get_prices_batch(symbols)

# ---- Build rows ----
rows = []
total_winners = 0
total_losers = 0
for row in wl_detail:
    sym = row["symbol"]
    added_price = row.get("added_price")
    added_at = (row.get("added_at") or "")[:10]  # date only
    current_price = prices.get(sym.upper())

    # Compute gain/loss
    if added_price and current_price and added_price > 0:
        change_pct = (current_price / added_price - 1)
        change_abs = current_price - added_price
        if change_pct >= 0:
            total_winners += 1
        else:
            total_losers += 1
    else:
        change_pct = None
        change_abs = None

    rows.append({
        "symbol": sym,
        "added_at": added_at,
        "added_price": added_price,
        "current_price": current_price,
        "change_abs": change_abs,
        "change_pct": change_pct,
    })

# ---- Summary KPIs ----
k1, k2, k3, k4 = st.columns(4)
with k1:
    ui.kpi_tile("Watching", str(len(rows)), "tickers")
with k2:
    avg_ret = None
    valid = [r["change_pct"] for r in rows if r["change_pct"] is not None]
    if valid:
        avg_ret = sum(valid) / len(valid)
    ui.kpi_tile("Avg return", f"{avg_ret*100:+.1f}%" if avg_ret is not None else "—",
                "since added", "pos" if avg_ret and avg_ret > 0 else ("neg" if avg_ret and avg_ret < 0 else ""))
with k3:
    ui.kpi_tile("Winners", str(total_winners), f"of {total_winners+total_losers}",
                "pos" if total_winners > total_losers else "")
with k4:
    best = max(rows, key=lambda r: r["change_pct"] if r["change_pct"] is not None else -999)
    ui.kpi_tile("Best pick",
                f"{best['symbol']} {best['change_pct']*100:+.1f}%" if best.get("change_pct") is not None else "—",
                "", "pos")

st.write("")

# ---- Sort control ----
sort_by = st.radio("Sort by", ["Date added (newest)", "Gain/loss %", "Ticker"], horizontal=True,
                    key="wl_sort")
if sort_by == "Gain/loss %":
    rows.sort(key=lambda r: r["change_pct"] if r["change_pct"] is not None else -999, reverse=True)
elif sort_by == "Ticker":
    rows.sort(key=lambda r: r["symbol"])
# else: already in date-added order (newest first from DB)

# ---- Glass table ----
_cols = [
    {"key": "sym", "label": "Ticker", "cls": "sym"},
    {"key": "added", "label": "Added", "align": "num"},
    {"key": "added_px", "label": "Price when added", "align": "num"},
    {"key": "current", "label": "Current price", "align": "num"},
    {"key": "chg", "label": "Change ($)", "align": "num"},
    {"key": "ret", "label": "Gain/Loss %", "align": "num"},
    {"key": "action", "label": ""},
]

_rows = []
for r in rows:
    pct_str = f"{r['change_pct']*100:+.2f}%" if r["change_pct"] is not None else "—"
    chg_str = f"${r['change_abs']:+.2f}" if r["change_abs"] is not None else "—"
    _rows.append({
        "sym": r["symbol"],
        "added": r["added_at"],
        "added_px": f"${r['added_price']:.2f}" if r["added_price"] else "—",
        "current": f"${r['current_price']:.2f}" if r["current_price"] else "—",
        "chg": chg_str,
        "ret": pct_str,
        "action": "",
    })

ui.glass_table(_cols, _rows)

# ---- Remove section ----
st.divider()
ui.section_head("Manage watchlist", "Remove tickers you're no longer tracking.")
rm_cols = st.columns([3, 1, 4])
rm_sym = rm_cols[0].selectbox("Ticker to remove", options=[r["symbol"] for r in rows], key="wl_rm_sym")
if rm_cols[1].button("Remove", type="primary", use_container_width=True, key="wl_rm_btn"):
    db.remove_from_watchlist(rm_sym)
    st.success(f"Removed {rm_sym} from watchlist.")
    st.rerun()

st.caption("Add tickers from Stock Pro (the '+ Watchlist' button) or the form at the top of this page.")
