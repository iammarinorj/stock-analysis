"""Paper Trading — track simulated portfolios with live P&L.

- Auto-seeds the $100K analyst recommendation book on first visit
- Multi-account support (create your own portfolios)
- Live P&L via cached yfinance pulls
- Buy / sell trades adjust cash + create transaction records
- Performance dashboard with SPY benchmark
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from datetime import date, timedelta

from lib import db, ui
from lib import paper
from lib import options as options_mod
from lib import data as data_mod
from lib import profiles as profiles_mod
from lib import glossary as gloss
from lib import sidebar_chat


st.set_page_config(page_title="Paper Trading", page_icon="📒", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()
sidebar_chat.render_chat("paper_trading")

ui.page_header(
    title="Paper Trading",
    subtitle="Track simulated portfolios with live P&L. Validate your thesis without real money on the line.",
    icon="📒",
    live=True,
)

if gloss.is_explain_mode():
    ui.explain_panel(
        "Paper trading lets you test ideas without risking real money. Open an account with starting cash, "
        "buy and sell positions at live market prices, and track P&L over time. Compare to SPY (the S&P 500) "
        "to see if you'd actually beat the index. This is the discipline layer for testing your thesis BEFORE "
        "committing capital. The $100K Analyst Book auto-loads on first visit so you can see how the "
        "recommended portfolio plays out in real time."
    )

# ----- Auto-seed the analyst book on first visit -----
accounts = db.get_paper_accounts()
if not accounts:
    with st.spinner("Loading the $100K Analyst Book at live market prices..."):
        seed_id = paper.seed_analyst_book()
    st.success(f"Seeded the $100K Analyst Recommendation Book with 15 positions at today's prices.")
    accounts = db.get_paper_accounts()

# ----- Account selector -----
col1, col2, col3 = st.columns([3, 1, 1])
account_names = [a["name"] for a in accounts]
selected_name = col1.selectbox("Account", options=account_names, key="paper_acct")
selected_acct = next((a for a in accounts if a["name"] == selected_name), None)
account_id = selected_acct["id"]

if col2.button("➕ New account", use_container_width=True):
    st.session_state["show_new_account"] = True
if col3.button("🔄 Refresh prices", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

# New account form
if st.session_state.get("show_new_account"):
    with st.form("new_account"):
        st.markdown("##### Create a new paper trading account")
        new_name = st.text_input("Account name", value="My Portfolio")
        new_cash = st.number_input("Starting cash ($)", value=100000.0, step=1000.0)
        new_notes = st.text_input("Notes (optional)")
        c1, c2 = st.columns(2)
        if c1.form_submit_button("Create", type="primary"):
            try:
                db.create_paper_account(new_name, new_cash, new_notes)
                st.success(f"Created '{new_name}' with ${new_cash:,.0f}")
                st.session_state["show_new_account"] = False
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
        if c2.form_submit_button("Cancel"):
            st.session_state["show_new_account"] = False
            st.rerun()

st.divider()

# ----- Pull summary -----
with st.spinner("Pulling live prices..."):
    summary = paper.portfolio_summary(account_id)

# ----- Headline KPIs -----
ui.section_head(selected_name, f"Opened {selected_acct['opened_at'][:10]}")

k_cols = st.columns(6)
k_cols[0].metric("Total value",     ui.fmt_money(summary["total_value"]),
                 f"{summary['total_return_pct']*100:+.2f}% vs start")
k_cols[1].metric("Open positions",  summary["n_open"],
                 f"market value {ui.fmt_money(summary['open_market_value'])}")
k_cols[2].metric("Open P&L (live)", ui.fmt_money(summary["open_pnl_abs"]),
                 f"{summary['open_pnl_pct']*100:+.2f}% on cost")
k_cols[3].metric("Options",         summary["n_options"],
                 f"P&L {ui.fmt_money(summary['options_pnl'])}" if summary["n_options"] else "none open")
k_cols[4].metric("Realized P&L",    ui.fmt_money(summary["realized_pnl"]),
                 f"{summary['n_closed']} closed positions")
k_cols[5].metric("Cash",            ui.fmt_money(summary["cash"]),
                 f"{(1-summary['deployed_pct'])*100:.1f}% of book")

# Benchmark comparison
bench_ret = paper.benchmark_return_since(selected_acct["opened_at"], "SPY")
if bench_ret is not None:
    alpha = summary["total_return_pct"] - bench_ret
    bcols = st.columns(3)
    bcols[0].metric("Portfolio return", f"{summary['total_return_pct']*100:+.2f}%")
    bcols[1].metric("SPY return same period", f"{bench_ret*100:+.2f}%")
    bcols[2].metric("Alpha vs SPY", f"{alpha*100:+.2f}%",
                    "Beating market" if alpha > 0 else "Trailing market")

st.write("")

# ----- Tabs -----
tab_open, tab_add, tab_opts, tab_auto, tab_closed, tab_tx = st.tabs([
    f"📂 Open ({summary['n_open']})", "➕ Add Trade",
    f"📈 Options ({summary['n_options']})",
    "🤖 Auto-build from profile",
    f"✅ Closed ({summary['n_closed']})", "📜 Transactions"
])

# === Open positions ===
with tab_open:
    if summary["n_open"] == 0:
        ui.empty_state("No open positions. Use the 'Add Trade' tab to open one.")
    else:
        rows = []
        for p in summary["open_book"]:
            curr = p.get("current_price")
            tgt = p.get("target_price"); stop = p.get("stop_price")
            tgt_pct = ((tgt / curr - 1) * 100) if (curr and tgt) else None
            stop_pct = ((stop / curr - 1) * 100) if (curr and stop) else None
            trigger = ""
            if curr and stop and curr <= stop:
                trigger = "🚨 stop hit"
            elif curr and tgt and curr >= tgt:
                trigger = "🎯 target hit"
            rows.append({
                "Ticker": p["symbol"],
                "Qty": round(p["qty"], 2),
                "Entry": f"${p['entry_price']:.2f}",
                "Current": f"${curr:.2f}" if curr else "—",
                "Market Value": ui.fmt_money(p["market_value"]),
                "Cost": ui.fmt_money(p["cost_basis"]),
                "P&L $": ui.fmt_money(p["pnl_abs"]),
                "P&L %": f"{p['pnl_pct']*100:+.2f}%",
                "Target": f"${tgt:.2f}" + (f" ({tgt_pct:+.0f}%)" if tgt_pct is not None else "") if tgt else "—",
                "Stop": f"${stop:.2f}" + (f" ({stop_pct:+.0f}%)" if stop_pct is not None else "") if stop else "—",
                "Flag": trigger,
                "Thesis": (p.get("thesis") or "")[:60],
            })
        rows.sort(key=lambda r: -float(r["P&L %"].replace("%", "").replace("+", "")))

        _pos_cols = [
            {"key": "Ticker", "label": "Ticker", "cls": "sym"},
            {"key": "Qty", "label": "Qty", "align": "num"},
            {"key": "Entry", "label": "Entry", "align": "num"},
            {"key": "Current", "label": "Current", "align": "num"},
            {"key": "Market Value", "label": "Mkt Value", "align": "num"},
            {"key": "Cost", "label": "Cost", "align": "num"},
            {"key": "P&L $", "label": "P&L $", "align": "num"},
            {"key": "P&L %", "label": "P&L %", "align": "num"},
            {"key": "Target", "label": "Target", "align": "num"},
            {"key": "Stop", "label": "Stop", "align": "num"},
            {"key": "Flag", "label": ""},
        ]
        ui.glass_table(_pos_cols, rows)

        st.divider()
        ui.section_head("Close a position", "Sell at current market price or specify exit.")
        close_cols = st.columns([2, 2, 2, 2, 1])
        symbols_in_book = [p["symbol"] for p in summary["open_book"]]
        close_sym = close_cols[0].selectbox("Symbol", options=symbols_in_book, key="close_sym")
        target_pos = next(p for p in summary["open_book"] if p["symbol"] == close_sym)
        suggested_exit = target_pos.get("current_price") or target_pos["entry_price"]
        close_price = close_cols[1].number_input("Exit price", value=float(suggested_exit), step=0.01)
        close_notes = close_cols[2].text_input("Notes (what did you learn?)")
        close_cols[3].markdown(
            f"**P&L preview**: ${(target_pos['qty'] * close_price - target_pos['cost_basis']):+,.2f} "
            f"({(close_price / target_pos['entry_price'] - 1) * 100:+.2f}%)"
        )
        if close_cols[4].button("Close", type="primary", use_container_width=True):
            try:
                db.close_paper_position(target_pos["id"], close_price, close_notes)
                st.success(f"Closed {close_sym} at ${close_price:.2f}")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

# === Add trade ===
with tab_add:
    ui.section_head("Open a new position", "Buy at current price or specify entry.")
    with st.form("new_trade"):
        c1, c2, c3 = st.columns(3)
        new_sym = c1.text_input("Ticker", placeholder="AAPL").strip().upper()
        live_price = None
        if new_sym:
            live_price = paper.get_current_price(new_sym)
            c1.caption(f"Live price: ${live_price:.2f}" if live_price else "Couldn't fetch price")

        size_mode = c2.radio("Size by", ["Dollar amount", "Share quantity"], horizontal=True)
        if size_mode == "Dollar amount":
            dollar_amt = c2.number_input("$ to invest", value=5000.0, step=100.0)
            qty_input = None
        else:
            qty_input = c2.number_input("Shares", value=10.0, step=1.0)
            dollar_amt = None

        entry_price = c3.number_input(
            "Entry price",
            value=float(live_price) if live_price else 0.0,
            step=0.01,
        )

        c4, c5, c6 = st.columns(3)
        target = c4.number_input("Target price", value=float(entry_price * 1.25) if entry_price else 0.0, step=0.01)
        stop = c5.number_input("Stop price", value=float(entry_price * 0.85) if entry_price else 0.0, step=0.01)
        thesis = c6.text_input("Thesis (1 line)")

        submitted = st.form_submit_button("Open position", type="primary")
        if submitted:
            try:
                if not new_sym:
                    st.error("Enter a ticker")
                elif entry_price <= 0:
                    st.error("Entry price must be positive")
                else:
                    if dollar_amt:
                        qty = round(dollar_amt / entry_price, 4)
                    else:
                        qty = qty_input
                    db.open_paper_position(
                        account_id=account_id,
                        symbol=new_sym,
                        qty=qty,
                        entry_price=entry_price,
                        target_price=target if target > 0 else None,
                        stop_price=stop if stop > 0 else None,
                        thesis=thesis,
                    )
                    st.success(f"Opened {new_sym}: {qty} shares at ${entry_price:.2f} = ${qty*entry_price:,.2f}")
                    st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

# === Options ===
with tab_opts:
    opts_book = summary.get("options_book", [])

    # --- Open options table ---
    if not opts_book:
        ui.empty_state("No open options positions. Use the form below to open one.")
    else:
        ui.section_head("Open Options", f"{len(opts_book)} contracts")
        opt_rows = []
        for o in opts_book:
            dte = 0
            try:
                dte = (date.fromisoformat(o["expiry"]) - date.today()).days
            except Exception:
                pass
            curr = o.get("current_premium")
            opt_rows.append({
                "Symbol": o["symbol"],
                "Type": "C" if o["opt_type"] == "call" else "P",
                "Strike": f"${o['strike']:.2f}",
                "Expiry": o["expiry"],
                "DTE": dte,
                "Side": o["side"].capitalize(),
                "Qty": o["qty"],
                "Entry": f"${o['entry_premium']:.2f}",
                "Current": f"${curr:.2f}" if curr is not None else "—",
                "P&L $": ui.fmt_money(o["pnl_abs"]),
                "P&L %": f"{o['pnl_pct']*100:+.2f}%" if o.get("pnl_pct") is not None else "—",
                "Status": o["status"],
            })
        _opt_cols = [
            {"key": "Symbol", "label": "Symbol", "cls": "sym"},
            {"key": "Type", "label": "Type"},
            {"key": "Strike", "label": "Strike", "align": "num"},
            {"key": "Expiry", "label": "Expiry"},
            {"key": "DTE", "label": "DTE", "align": "num"},
            {"key": "Side", "label": "Side"},
            {"key": "Qty", "label": "Qty", "align": "num"},
            {"key": "Entry", "label": "Entry", "align": "num"},
            {"key": "Current", "label": "Current", "align": "num"},
            {"key": "P&L $", "label": "P&L $", "align": "num"},
            {"key": "P&L %", "label": "P&L %", "align": "num"},
            {"key": "Status", "label": "Status"},
        ]
        ui.glass_table(_opt_cols, opt_rows)

        # --- Close option section ---
        st.divider()
        ui.section_head("Close an option", "Close at current premium or specify exit.")
        oc_cols = st.columns([2, 2, 2, 1])
        opt_labels = [
            f"{o['symbol']} {o['opt_type'][0].upper()} ${o['strike']:.0f} {o['expiry']} (id={o['id']})"
            for o in opts_book
        ]
        selected_opt_label = oc_cols[0].selectbox("Option position", options=opt_labels, key="close_opt_sel")
        selected_opt_idx = opt_labels.index(selected_opt_label) if selected_opt_label else 0
        target_opt = opts_book[selected_opt_idx]
        suggested_exit_prem = target_opt.get("current_premium") or target_opt["entry_premium"]
        close_opt_price = oc_cols[1].number_input(
            "Exit premium (per share)", value=float(suggested_exit_prem), step=0.01, key="close_opt_price"
        )
        close_opt_notes = oc_cols[2].text_input("Notes", key="close_opt_notes")
        if oc_cols[3].button("Close", type="primary", use_container_width=True, key="close_opt_btn"):
            try:
                db.close_paper_option(target_opt["id"], close_opt_price, close_opt_notes)
                st.success(
                    f"Closed {target_opt['symbol']} {target_opt['opt_type']} "
                    f"${target_opt['strike']:.0f} at ${close_opt_price:.2f}"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

        # --- Expire option section ---
        st.divider()
        ui.section_head("Expire an option", "Mark as expired worthless (exit_premium = 0).")
        ex_cols = st.columns([3, 2, 1])
        expire_opt_label = ex_cols[0].selectbox("Option to expire", options=opt_labels, key="expire_opt_sel")
        expire_opt_idx = opt_labels.index(expire_opt_label) if expire_opt_label else 0
        expire_target = opts_book[expire_opt_idx]
        expire_notes = ex_cols[1].text_input("Notes", key="expire_opt_notes")
        if ex_cols[2].button("Expire", use_container_width=True, key="expire_opt_btn"):
            try:
                db.expire_paper_option(expire_target["id"], expire_notes)
                st.success(f"Expired {expire_target['symbol']} {expire_target['opt_type']} ${expire_target['strike']:.0f}")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    # --- Open new option form ---
    st.divider()
    ui.section_head("Open a new options position", "Buy or write an option contract.")
    with st.form("new_option"):
        oc1, oc2, oc3, oc4 = st.columns(4)
        opt_ticker = oc1.text_input("Ticker", placeholder="AAPL", key="opt_ticker").strip().upper()
        opt_type_choice = oc2.radio("Option type", ["Call", "Put"], horizontal=True, key="opt_type_radio")
        opt_strike = oc3.number_input("Strike price", value=0.0, step=1.0, key="opt_strike")
        opt_expiry = oc4.date_input(
            "Expiry", value=date.today() + timedelta(days=30), key="opt_expiry"
        )

        oc5, oc6, oc7, oc8 = st.columns(4)
        opt_side_choice = oc5.radio("Side", ["Long", "Short"], horizontal=True, key="opt_side_radio")
        opt_qty = oc6.number_input("Contracts", value=1, min_value=1, step=1, key="opt_qty")
        opt_premium = oc7.number_input("Premium per share ($)", value=0.0, step=0.05, key="opt_premium")
        opt_thesis = oc8.text_input("Thesis", key="opt_thesis")

        # Show cost/proceeds preview
        total_cost = opt_qty * 100 * opt_premium
        side_str = opt_side_choice.lower() if opt_side_choice else "long"
        if side_str == "long":
            st.caption(f"Total cost: {opt_qty} x 100 x ${opt_premium:.2f} = **${total_cost:,.2f}** (deducted from cash)")
        else:
            st.caption(f"Premium received: {opt_qty} x 100 x ${opt_premium:.2f} = **${total_cost:,.2f}** (added to cash)")

        submitted_opt = st.form_submit_button("Open option position", type="primary")
        if submitted_opt:
            try:
                if not opt_ticker:
                    st.error("Enter a ticker")
                elif opt_strike <= 0:
                    st.error("Strike must be positive")
                elif opt_premium <= 0:
                    st.error("Premium must be positive")
                else:
                    db.open_paper_option(
                        account_id=account_id,
                        symbol=opt_ticker,
                        opt_type=opt_type_choice.lower(),
                        strike=opt_strike,
                        expiry=str(opt_expiry),
                        side=side_str,
                        qty=int(opt_qty),
                        entry_premium=opt_premium,
                        thesis=opt_thesis,
                    )
                    action = "Bought" if side_str == "long" else "Wrote"
                    st.success(
                        f"{action} {opt_qty} {opt_ticker} {opt_type_choice} ${opt_strike:.0f} "
                        f"exp {opt_expiry} @ ${opt_premium:.2f}/sh = ${total_cost:,.2f}"
                    )
                    st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    # Live premium lookup (outside form for interactivity)
    st.divider()
    ui.section_head("Live premium lookup", "Check current option pricing before trading.")
    lk1, lk2, lk3, lk4, lk5 = st.columns(5)
    lk_sym = lk1.text_input("Ticker", key="lk_sym", placeholder="AAPL").strip().upper()
    lk_type = lk2.radio("Type", ["Call", "Put"], horizontal=True, key="lk_type")
    lk_strike = lk3.number_input("Strike", value=0.0, step=1.0, key="lk_strike")
    lk_expiry = lk4.date_input("Expiry", value=date.today() + timedelta(days=30), key="lk_expiry")
    if lk5.button("Lookup", use_container_width=True, key="lk_btn"):
        if lk_sym and lk_strike > 0:
            price_info = options_mod.get_contract_price(lk_sym, str(lk_expiry), lk_type.lower(), lk_strike)
            if price_info:
                st.json(price_info)
            else:
                st.warning("Contract not found. Check ticker, strike, and expiry (must match available chain).")
        else:
            st.warning("Enter a ticker and strike to look up.")


# === Auto-build from profile ===
with tab_auto:
    ui.section_head(
        "Build a portfolio automatically from a profile",
        "Pick an investor style. The app screens the market, ranks by Fit Score, sizes positions, and opens them all in a new tracked paper account."
    )

    if gloss.is_explain_mode():
        ui.explain_panel(
            "Pick a profile (Buffett, Graham, Lynch, Magic Formula, Dividend, etc). The app runs that "
            "profile's screen across the market today, takes the highest-Fit names, sizes them, and creates "
            "a brand new paper account with all positions opened. You can then watch how Buffett-style picks "
            "do over time vs Graham-style picks vs Magic Formula picks — all in real out-of-sample. "
            "<b>Caveat</b>: stocks selected today won't be the same stocks that would have passed in 2021. "
            "This is forward-tracking only, not historical backtesting."
        )

    ac1, ac2 = st.columns(2)
    auto_profile = ac1.selectbox(
        "Investment philosophy",
        options=list(profiles_mod.PROFILES.keys()),
        format_func=lambda k: profiles_mod.PROFILES[k]["name"],
        index=0,
        key="auto_profile",
    )
    ac1.caption(profiles_mod.PROFILES[auto_profile].get("tagline", ""))
    account_name_default = (
        f"{profiles_mod.PROFILES[auto_profile]['name'].split(' — ')[0]} Auto Book "
        f"({pd.Timestamp.now().strftime('%b %Y')})"
    )
    new_acct_name = ac2.text_input("New account name", value=account_name_default, key="auto_acct_name")

    bc1, bc2, bc3, bc4 = st.columns(4)
    auto_capital = bc1.number_input("Total capital ($)", value=100000.0, step=5000.0, key="auto_cap")
    auto_n_pos = bc2.number_input("Number of positions", min_value=5, max_value=30, value=15, step=1, key="auto_n")
    auto_min_cap = bc3.selectbox(
        "Min market cap",
        options=["+Micro (over $50mln)", "+Small (over $300mln)", "+Mid (over $2bln)", "+Large (over $10bln)"],
        index=1, key="auto_mincap",
    )
    auto_sizing = bc4.selectbox(
        "Position sizing",
        options=["equal", "fit-weighted"],
        format_func=lambda s: "Equal weight" if s == "equal" else "Fit-weighted (higher fit = larger size)",
        key="auto_sizing",
    )
    auto_foreign = st.toggle(
        "🌐 Include foreign listings (ADRs like ASML, TSM, NVO)",
        value=False, key="auto_foreign",
        help="Drops the Country=USA filter. Adds foreign ADRs to the candidate pool.",
    )

    # Universe-size knob — bigger pool = less alphabetical bias = longer wait
    pool_size = st.select_slider(
        "Candidate pool size (bigger = less alphabetical bias, longer wait)",
        options=[200, 500, 1000, 1500, 2500],
        value=1000,
        key="auto_pool_size",
        help="Pulls top N from each of 6 sort dimensions (market cap, ROE, momentum, growth, sales, margins) "
             "and unions them. Larger = more thorough scan. 1000 takes ~1-2min; 2500 takes ~3-5min.",
    )

    # Preview step
    if st.button("Preview portfolio", key="auto_preview_btn"):
        progress_bar = st.progress(0.0, text="Starting…")
        def _progress(label, pct):
            try: progress_bar.progress(min(0.99, max(0.0, pct)), text=label)
            except Exception: pass
        try:
            st.session_state["auto_preview"] = paper.preview_profile_portfolio(
                profile_id=auto_profile,
                n_positions=int(auto_n_pos),
                total_capital=float(auto_capital),
                include_foreign=auto_foreign,
                min_mkt_cap=auto_min_cap,
                sizing=auto_sizing,
                universe_limit=int(pool_size),
                progress_cb=_progress,
            )
            progress_bar.progress(1.0, text="Done.")
        finally:
            # Clear the progress bar after a moment
            import time
            time.sleep(0.5)
            try: progress_bar.empty()
            except Exception: pass

    preview = st.session_state.get("auto_preview")
    if preview and not preview.get("error"):
        # Headline metrics
        st.write("")
        pm = st.columns(4)
        pm[0].metric("Profile", preview["profile_name"].split(" — ")[0])
        pm[1].metric("Positions", preview["n_positions"])
        pm[2].metric("Allocated", ui.fmt_money(preview["total_allocated"]),
                     f"{(preview['total_allocated']/preview['total_capital'])*100:.1f}% of capital")
        pm[3].metric("Cash remaining", ui.fmt_money(preview["cash_remaining"]))

        # Position table
        ui.section_head("Proposed positions", "Sorted by Fit Score descending.")
        rows = []
        for p in preview["positions"]:
            rows.append({
                "Ticker": p["symbol"],
                "Company": p["company"] or "—",
                "Sector": p["sector"] or "—",
                "Fit": p["fit"],
                "Price": f"${p['price']:.2f}",
                "Qty": round(p["qty"], 2),
                "$ Allocated": ui.fmt_money(p["actual_cost"]),
                "% of Book": f"{p['actual_cost']/preview['total_capital']*100:.1f}%",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=480)

        # Lock-in button
        st.warning(
            "⚠️ Locking in will create a NEW paper account with all these positions opened at the prices shown. "
            "You can close any position later, but entry prices are fixed once locked."
        )
        lc1, lc2 = st.columns([1, 4])
        if lc1.button("🔒 Lock in & create account", type="primary", key="auto_lock_btn"):
            try:
                new_acct_id = paper.lock_in_profile_portfolio(preview, new_acct_name)
                st.cache_data.clear()
                st.success(
                    f"✅ Created account '{new_acct_name}' (id={new_acct_id}) with "
                    f"{preview['n_positions']} positions. Refresh / switch to it in the account selector above."
                )
                st.session_state.pop("auto_preview", None)
                st.rerun()
            except Exception as e:
                st.error(f"Error locking in: {e}")
    elif preview and preview.get("error"):
        st.error(preview["error"])


# === Closed positions ===
with tab_closed:
    if summary["n_closed"] == 0:
        ui.empty_state("No closed positions yet. Close one from the Open tab.")
    else:
        rows = []
        wins = 0; losses = 0; total_ret_pct = 0
        for p in summary["closed_positions"]:
            ret = (p["exit_price"] / p["entry_price"] - 1) if p.get("exit_price") and p["entry_price"] else 0
            pnl = p["qty"] * ((p.get("exit_price") or 0) - p["entry_price"])
            if ret > 0: wins += 1
            elif ret < 0: losses += 1
            total_ret_pct += ret
            rows.append({
                "Ticker": p["symbol"],
                "Qty": round(p["qty"], 2),
                "Entry": f"${p['entry_price']:.2f}",
                "Exit": f"${p.get('exit_price', 0):.2f}",
                "P&L $": ui.fmt_money(pnl),
                "Return": f"{ret*100:+.2f}%",
                "Opened": p["entry_date"][:10],
                "Closed": (p.get("exit_date") or "")[:10],
                "Notes (learnings)": (p.get("notes") or "")[:80],
            })
        rows.sort(key=lambda r: -float(r["Return"].replace("%", "").replace("+", "")))

        m_cols = st.columns(4)
        m_cols[0].metric("Wins", wins)
        m_cols[1].metric("Losses", losses)
        win_rate = wins / (wins + losses) * 100 if (wins + losses) else 0
        m_cols[2].metric("Win rate", f"{win_rate:.0f}%")
        avg = total_ret_pct / len(rows) * 100 if rows else 0
        m_cols[3].metric("Avg return", f"{avg:+.2f}%")
        st.write("")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# === Transaction log ===
with tab_tx:
    txs = db.get_paper_transactions(account_id)
    if not txs:
        ui.empty_state("No transactions yet.")
    else:
        rows = []
        for t in txs:
            action_color = "🟢" if t["action"] == "BUY" else "🔴"
            rows.append({
                " ": action_color,
                "Date": t["executed_at"][:16].replace("T", " "),
                "Action": t["action"],
                "Symbol": t["symbol"],
                "Qty": round(t["qty"], 2),
                "Price": f"${t['price']:.2f}",
                "Total": ui.fmt_money(t["total"]),
                "Notes": (t.get("notes") or "")[:80],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=500)

# ----- Sidebar account management -----
with st.sidebar:
    st.divider()
    st.markdown("### Paper Trading")
    if selected_acct["name"] == paper.ANALYST_BOOK_NAME:
        st.caption("This is the auto-seeded $100K analyst book.")
        if st.button("🔁 Reset to current prices", use_container_width=True,
                      help="Delete and re-create the book at today's prices"):
            paper.seed_analyst_book(force=True)
            st.cache_data.clear()
            st.success("Re-seeded.")
            st.rerun()
    else:
        with st.expander("⚠️ Delete this account"):
            st.warning("This will permanently delete the account and all its positions/transactions.")
            if st.button("Confirm delete", type="primary", use_container_width=True, key="confirm_del"):
                db.delete_paper_account(account_id)
                st.cache_data.clear()
                st.success("Deleted.")
                st.rerun()
