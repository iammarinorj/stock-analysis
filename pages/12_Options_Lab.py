# -*- coding: utf-8 -*-
"""Options Lab — Interactive P&L simulator for any options contract.

Uses Black-Scholes pricing to project profit/loss across stock prices and
dates.  Pulls real chain data (strikes, premiums, IV) from yfinance and the
risk-free rate from FRED.

Use case: "I want to buy a SPY put LEAP — what happens to my money if SPY
drops to $X by date Y?"
"""
from __future__ import annotations

import math

import plotly.graph_objects as go
import streamlit as st

from lib import options as opts_mod
from lib import data, ui
from lib import glossary as gloss
from lib import sidebar_chat

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Options Lab", page_icon="\U0001f9ea", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()
sidebar_chat.render_chat("options_lab")

ui.page_header(
    title="Options Lab",
    subtitle="Interactive options P&L simulator. Pick a real contract, see your profit at any price and date.",
    icon="\U0001f9ea",
    live=False,
)

if gloss.is_explain_mode():
    ui.explain_panel(
        "This page prices options using the <b>Black-Scholes model</b> and shows you a profit/loss "
        "heatmap across stock prices and days remaining. Green = profit, red = loss. Use it to "
        "visualize any contract before you trade. Pick a ticker, choose an expiry (LEAPs are at "
        "the bottom of the list), select your strike, and the page does the rest."
    )


# ===================================================================
# STEP 1 — Ticker + Load
# ===================================================================

ui.section_head("1. Pick a contract", "Load the real options chain, then choose your contract.")

col_tick, col_btn = st.columns([3, 1])
with col_tick:
    ticker_input = st.text_input("Ticker", value="SPY", key="olab_ticker",
                                  placeholder="SPY, AAPL, QQQ, TSLA…").strip().upper()
with col_btn:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    load = st.button("Load chain", type="primary", key="olab_load", use_container_width=True)

if load and ticker_input:
    st.session_state["olab_sym"] = ticker_input
    st.session_state["olab_loaded"] = True
    # Reset downstream state so new ticker gets fresh defaults
    for k in list(st.session_state.keys()):
        if k.startswith("olab_") and k not in ("olab_sym", "olab_loaded", "olab_ticker"):
            del st.session_state[k]
    st.rerun()

if not st.session_state.get("olab_loaded"):
    ui.empty_state("Enter a ticker and click <b>Load chain</b> to get started.")
    st.stop()

sym = st.session_state["olab_sym"]

# Fetch spot + expirations
spot = data.get_last_price(sym)
expirations = opts_mod.get_expirations(sym)

if not spot:
    st.error(f"Could not fetch a price for **{sym}**. Check the ticker and try again.")
    st.stop()
if not expirations:
    st.error(f"No options chain available for **{sym}**.")
    st.stop()


# ===================================================================
# STEP 2 — Expiry (with DTE labels so you can find LEAPs)
# ===================================================================

# Format expirations with DTE so the user can scan easily
exp_labels = []
for e in expirations:
    d = opts_mod._dte(e)
    if d > 365:
        tag = f"{e}  ({d} days — LEAP)"
    elif d > 90:
        tag = f"{e}  ({d} days)"
    elif d > 30:
        tag = f"{e}  ({d}d)"
    else:
        tag = f"{e}  ({d}d ⚡)"
    exp_labels.append(tag)

# Default to ~30 DTE
default_exp = opts_mod.pick_default_expiry(expirations, min_dte=25)
default_idx = expirations.index(default_exp) if default_exp in expirations else 0

selected_label = st.selectbox(
    "Expiration — scroll down for LEAPs",
    exp_labels, index=default_idx, key="olab_expiry_sel",
)
# Extract the actual date from the label
expiry = selected_label.split("  ")[0].strip()
dte = opts_mod._dte(expiry)


# ===================================================================
# STEP 3 — Type, Strike, Side (all from the real chain)
# ===================================================================

# Pull FULL chain for this expiry (not just near-the-money)
chain = opts_mod._raw_chain(sym, expiry)

c1, c2, c3 = st.columns([1, 2, 1])
with c1:
    opt_type_label = st.radio("Type", ["Put", "Call"], horizontal=True, key="olab_type")
    opt_type = opt_type_label.lower()

with c2:
    chain_rows = chain["calls"] if opt_type == "call" else chain["puts"]
    all_strikes = sorted({r["strike"] for r in chain_rows if r.get("strike")})
    if not all_strikes:
        st.warning("No strikes available for this expiry/type.")
        st.stop()

    # Build strike labels with premium + OI for context
    strike_info = {}
    for r in chain_rows:
        s = r.get("strike")
        if s:
            mid = r.get("bid", 0) or 0
            ask = r.get("ask", 0) or 0
            last = r.get("lastPrice", 0) or 0
            price = ((mid + ask) / 2) if (mid and ask) else last
            oi = int(r.get("openInterest") or 0) if r.get("openInterest") and r["openInterest"] == r["openInterest"] else 0
            iv = r.get("impliedVolatility") or 0
            itm = r.get("inTheMoney", False)
            strike_info[s] = {"price": price, "oi": oi, "iv": iv, "itm": itm}

    strike_labels = []
    for s in all_strikes:
        info = strike_info.get(s, {})
        p = info.get("price", 0)
        oi = info.get("oi", 0)
        itm = info.get("itm", False)
        marker = " ITM" if itm else ""
        strike_labels.append(f"${s:.0f}  (${p:.2f}, OI {oi:,}{marker})")

    # Default to ATM
    atm_idx = min(range(len(all_strikes)), key=lambda i: abs(all_strikes[i] - spot))
    sel_strike_label = st.selectbox("Strike — price, open interest", strike_labels,
                                     index=atm_idx, key="olab_strike_sel")
    strike = all_strikes[strike_labels.index(sel_strike_label)]

with c3:
    side_label = st.radio("Side", ["Buy (long)", "Sell (short)"], horizontal=True, key="olab_side")
    is_long = "Buy" in side_label
    direction = 1 if is_long else -1


# ===================================================================
# STEP 4 — Premium, IV, Contracts (auto-filled from chain)
# ===================================================================

# Look up the selected contract's live data
sel_info = strike_info.get(strike, {})
chain_premium = sel_info.get("price", 0.0)
chain_iv = sel_info.get("iv", 0.30)
if chain_iv == 0:
    chain_iv = 0.30  # fallback

c4, c5, c6, c7 = st.columns(4)
with c4:
    contracts = st.number_input("Contracts", min_value=1, max_value=1000, value=1, key="olab_contracts")
with c5:
    entry_premium = st.number_input(
        "Entry premium (per share)",
        min_value=0.0,
        value=round(float(chain_premium), 2),
        step=0.05, format="%.2f", key="olab_premium",
    )
with c6:
    iv_pct = st.slider("IV (%)", min_value=1.0, max_value=200.0,
                         value=min(round(float(chain_iv) * 100, 1), 200.0),
                         step=0.5, key="olab_iv")
    sigma = iv_pct / 100.0
with c7:
    rfr_default = opts_mod.get_risk_free_rate()
    rfr = st.number_input("Risk-free rate (%)", min_value=0.0, max_value=20.0,
                           value=round(rfr_default * 100, 2),
                           step=0.05, format="%.2f", key="olab_rfr")
    r = rfr / 100.0

if entry_premium <= 0:
    st.warning("Enter a premium > 0 to see projections. Check that the contract has liquidity.")
    st.stop()

# Derived values
T_total = max(dte, 1) / 365.0
multiplier = contracts * 100
total_cost = entry_premium * multiplier

# Breakeven
if opt_type == "call":
    be_at_expiry = strike + entry_premium
else:
    be_at_expiry = strike - entry_premium

# Max profit / loss
if is_long:
    max_loss_display = f"${total_cost:,.0f}"
    if opt_type == "call":
        max_profit_display = "Unlimited"
    else:
        max_profit_display = f"${max(0, (strike - entry_premium)) * multiplier:,.0f}"
else:
    max_profit_display = f"${total_cost:,.0f}"
    if opt_type == "call":
        max_loss_display = "Unlimited"
    else:
        max_loss_display = f"${max(0, (strike - entry_premium)) * multiplier:,.0f}"


# ===================================================================
# POSITION SUMMARY
# ===================================================================

st.divider()
side_word = "Long" if is_long else "Short"
ui.section_head(
    f"{side_word} {sym} ${strike:.0f} {opt_type_label}",
    f"Expiry {expiry} ({dte} DTE)  ·  {contracts} contract{'s' if contracts > 1 else ''}  ·  IV {iv_pct:.1f}%",
)

greeks = opts_mod.bs_greeks(spot, strike, T_total, r, sigma, opt_type)

k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    cost_label = "Total cost" if is_long else "Credit received"
    ui.kpi_tile(cost_label, f"${total_cost:,.0f}", f"{contracts} × ${entry_premium:.2f} × 100")
with k2:
    be_dir = "above" if opt_type == "call" else "below"
    pct_from_spot = (be_at_expiry / spot - 1) * 100
    ui.kpi_tile("Breakeven", f"${be_at_expiry:,.2f}", f"{pct_from_spot:+.1f}% from spot")
with k3:
    ui.kpi_tile("Max profit", max_profit_display, f"Max loss: {max_loss_display}")
with k4:
    adj_delta = greeks["delta"] * direction
    adj_theta = greeks["theta"] * direction * multiplier
    ui.kpi_tile("Delta", f"{adj_delta:+.3f}", f"Theta: ${adj_theta:+,.2f}/day",
                tone="neg" if adj_theta < 0 else "pos")
with k5:
    adj_vega = greeks["vega"] * direction * multiplier
    ui.kpi_tile("Vega", f"${adj_vega:+,.2f}", f"Gamma: {greeks['gamma']:.5f}")


# ===================================================================
# P&L HEATMAP
# ===================================================================

st.divider()
price_range = st.slider("Price range (% from spot)", min_value=10, max_value=80, value=40, step=5, key="olab_range")
ui.section_head("P&L Projection", "Green = profit, red = loss. Hover for details.")

grid = opts_mod.simulate_pnl_grid(
    S_now=spot, K=strike, T_total=T_total, r=r, sigma=sigma,
    opt_type=opt_type, entry_premium=entry_premium, contracts=contracts,
    price_steps=60, time_steps=25,
    price_lo=spot * (1 - price_range / 100),
    price_hi=spot * (1 + price_range / 100),
)

# Flip P&L for short positions
pnl_data = [[-v for v in row] for row in grid["pnl"]] if not is_long else grid["pnl"]
prices = grid["prices"]
days_rem = grid["days_remaining"]

# Hover text
hover_text = []
for t_idx, d in enumerate(days_rem):
    row_text = []
    for p_idx, p in enumerate(prices):
        pl = pnl_data[t_idx][p_idx]
        pct_ret = (pl / total_cost * 100) if total_cost else 0
        row_text.append(
            f"Stock: ${p:,.2f}<br>"
            f"Days left: {d}<br>"
            f"P&L: ${pl:+,.0f} ({pct_ret:+.1f}%)"
        )
    hover_text.append(row_text)

# Heatmap — use numeric x-axis so vlines work
max_abs = max(abs(v) for row in pnl_data for v in row) if pnl_data else 1
fig_heat = go.Figure(data=go.Heatmap(
    z=pnl_data,
    x=prices,
    y=days_rem,
    text=hover_text,
    hoverinfo="text",
    colorscale=[
        [0.0, "#c0392b"],
        [0.3, "#f1948a"],
        [0.5, "#ffffff"],
        [0.7, "#82e0aa"],
        [1.0, "#0a8f5b"],
    ],
    zmid=0,
    colorbar=dict(title=dict(text="P&L ($)", font=dict(size=11)),
                  tickprefix="$", tickformat=",.0f"),
))
fig_heat.update_layout(
    xaxis_title="Stock Price",
    yaxis_title="Days Remaining",
    height=520,
    margin=dict(l=10, r=10, t=30, b=10),
    xaxis=dict(tickprefix="$", tickformat=",.0f", nticks=12),
)
# Spot + strike markers
fig_heat.add_vline(x=spot, line_dash="dash", line_color="rgba(0,0,0,0.5)", line_width=1.5,
                    annotation_text=f"Spot ${spot:,.0f}", annotation_position="top")
fig_heat.add_vline(x=strike, line_dash="dot", line_color="#e67e22", line_width=1,
                    annotation_text=f"Strike ${strike:,.0f}", annotation_position="bottom")
ui.style_fig(fig_heat, height=520)
st.plotly_chart(fig_heat, use_container_width=True, config=ui.chart_config())


# ===================================================================
# PAYOFF AT EXPIRY
# ===================================================================

ui.section_head("Payoff at Expiry", "Classic P&L diagram at expiration")

# Find expiry row
expiry_idx = next((i for i, d in enumerate(days_rem) if d == 0), len(days_rem) - 1)
expiry_pnl = pnl_data[expiry_idx]

fig_payoff = go.Figure()

# Profit fill
fig_payoff.add_trace(go.Scatter(
    x=prices, y=[max(v, 0) for v in expiry_pnl],
    fill="tozeroy", fillcolor="rgba(10,143,91,0.15)",
    line=dict(color="rgba(10,143,91,0.5)", width=1),
    name="Profit", hoverinfo="skip",
))
# Loss fill
fig_payoff.add_trace(go.Scatter(
    x=prices, y=[min(v, 0) for v in expiry_pnl],
    fill="tozeroy", fillcolor="rgba(192,57,43,0.15)",
    line=dict(color="rgba(192,57,43,0.5)", width=1),
    name="Loss", hoverinfo="skip",
))
# Main line
fig_payoff.add_trace(go.Scatter(
    x=prices, y=expiry_pnl,
    mode="lines", line=dict(color="#1a1a2e", width=2.5),
    name="P&L at Expiry",
    hovertemplate="Stock: $%{x:,.2f}<br>P&L: $%{y:+,.0f}<extra></extra>",
))
fig_payoff.add_hline(y=0, line_dash="dot", line_color="rgba(0,0,0,0.3)")
fig_payoff.add_vline(x=be_at_expiry, line_dash="dash", line_color="#e67e22", line_width=1.5,
                      annotation_text=f"BE ${be_at_expiry:,.2f}", annotation_position="top left",
                      annotation_font_color="#e67e22")
fig_payoff.add_vline(x=spot, line_dash="dot", line_color="#6d3bf5", line_width=1.5,
                      annotation_text=f"Spot ${spot:,.2f}", annotation_position="bottom right",
                      annotation_font_color="#6d3bf5")
fig_payoff.update_layout(
    xaxis_title="Stock Price at Expiry",
    yaxis_title="Profit / Loss ($)",
    height=380, margin=dict(l=10, r=10, t=20, b=10),
    showlegend=False,
    yaxis=dict(tickprefix="$", tickformat=",.0f"),
    xaxis=dict(tickprefix="$", tickformat=",.0f"),
)
ui.style_fig(fig_payoff, height=380)
st.plotly_chart(fig_payoff, use_container_width=True, config=ui.chart_config())


# ===================================================================
# SCENARIO TABLE
# ===================================================================

st.divider()
ui.section_head("Scenario Analysis", "What if the stock is at $X on date Y?")

# Smart defaults based on put vs call
if opt_type == "put":
    default_targets = [
        round(spot * 1.05, 2),
        round(spot, 2),
        round(spot * 0.95, 2),
        round(spot * 0.90, 2),
        round(spot * 0.80, 2),
    ]
else:
    default_targets = [
        round(spot * 0.95, 2),
        round(spot, 2),
        round(spot * 1.05, 2),
        round(spot * 1.10, 2),
        round(spot * 1.20, 2),
    ]

tc = st.columns(5)
targets = []
for i, (col, default) in enumerate(zip(tc, default_targets)):
    with col:
        val = st.number_input(f"Target {i+1}", min_value=0.01,
                               value=default, step=1.0, format="%.2f",
                               key=f"olab_target_{i}")
        targets.append(val)

# Time horizons — adapt to DTE
horizons = [("Today", T_total)]
for label, days_out in [("30d", 30), ("60d", 60), ("90d", 90), ("6mo", 180), ("1yr", 365)]:
    t_rem = T_total - days_out / 365.0
    if t_rem > 0.001:  # only show if before expiry
        horizons.append((label, t_rem))
horizons.append(("Expiry", 0))

columns = [{"key": "target", "label": "Target Price", "align": "num"},
           {"key": "move", "label": "Move", "align": "num"}]
for label, _ in horizons:
    columns.append({"key": label, "label": label, "align": "num"})

rows = []
for t_price in sorted(targets, reverse=(opt_type == "put")):
    move_pct = (t_price / spot - 1) * 100
    row = {"target": f"${t_price:,.2f}", "move": f"{move_pct:+.1f}%"}
    for label, t_rem in horizons:
        theo = opts_mod.bs_price(t_price, strike, t_rem, r, sigma, opt_type)
        position_value = theo * multiplier
        pl = (position_value - total_cost) * direction
        pct = (pl / total_cost * 100) if total_cost else 0
        if pl >= 0:
            row[label] = f"<span style='color:#0a8f5b;font-weight:600'>${pl:+,.0f} ({pct:+.0f}%)</span>"
        else:
            row[label] = f"<span style='color:#c0392b'>${pl:+,.0f} ({pct:+.0f}%)</span>"
    rows.append(row)

ui.glass_table(columns, rows)

st.caption(
    "Black-Scholes assumes constant IV, no dividends, European exercise. "
    "Real P&L will differ due to IV changes (vega risk), bid-ask spread, "
    "and early exercise. Use as directional guidance, not exact prediction."
)
