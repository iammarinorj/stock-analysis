"""Stock Analysis landing page."""
import streamlit as st

from lib import ui
from lib import glossary as gloss
from lib import sidebar_chat
from lib import alerts as alerts_mod

st.set_page_config(
    page_title="Stock Analysis",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.inject_global_css()
gloss.explain_toggle_sidebar()
sidebar_chat.render_chat("home")

ui.page_header(
    title="Stock Analysis",
    subtitle="Find ideas. Diagnose with four investor lenses. Write the thesis. Track outcomes.",
    icon="",
    live=False,
)

if gloss.is_explain_mode():
    ui.explain_panel(
        "Welcome. Discover, Diagnose, Decide, Track. Toggle Explain Mode off in the sidebar for a denser layout."
    )

# Active-alert strip — a clean, clickable banner (reads existing unseen alerts).
_n_alerts = alerts_mod.unseen_count()
if _n_alerts:
    st.markdown(
        f'<a href="/Thesis" target="_self" style="display:flex;align-items:center;gap:10px;'
        f'background:var(--amber-bg);border:1px solid var(--amber);border-left:4px solid var(--amber);'
        f'border-radius:12px;padding:12px 16px;margin-bottom:18px;text-decoration:none">'
        f'<span style="font-size:18px">🔔</span>'
        f'<span style="color:var(--text);font-size:13.5px"><b>{_n_alerts} active alert(s)</b> — '
        f'stops, targets, key-metric breaks, or watchlist events triggered.</span>'
        f'<span style="margin-left:auto;color:var(--amber);font-weight:700;font-size:12.5px">Review →</span>'
        f'</a>',
        unsafe_allow_html=True,
    )

ui.group_label("Research & analysis")
ui.nav_grid([
    {"href": "/Discover", "icon": "🔭", "title": "Discover",
     "desc": "Hunt for ideas across 10 investing styles."},
    {"href": "/Stock_Pro", "icon": "📈", "title": "Stock Pro",
     "desc": "Full diagnosis — overview, 9 investor lenses, sector-relative scoring, DCF, trends."},
    {"href": "/Compare", "icon": "⚖️", "title": "Compare",
     "desc": "Two tickers head-to-head across every metric and lens."},
    {"href": "/Indicators_Pro", "icon": "📊", "title": "Macro Pro",
     "desc": "Live indices, macro regime, and 20 macro indicators."},
    {"href": "/Calendar", "icon": "📅", "title": "Calendar", "new": True,
     "desc": "Full-market earnings, economic events, and IPOs by date range."},
    {"href": "/Insider_Buys", "icon": "🟢", "title": "Insider Buys", "new": True,
     "desc": "Real SEC Form 4 open-market purchases. Cluster buying = strongest retail signal."},
    {"href": "/Options_Lab", "icon": "\U0001f9ea", "title": "Options Lab", "new": True,
     "desc": "Interactive P&L simulator — what-if scenarios for any options contract."},
])

ui.group_label("Decide & track")
ui.nav_grid([
    {"href": "/Watchlist", "icon": "⭐", "title": "Watchlist",
     "desc": "Your tracked tickers with live price and gain/loss since you started watching."},
    {"href": "/Thesis", "icon": "📝", "title": "Thesis Journal",
     "desc": "Bull case, bear case, and breaks-if triggers for every open position."},
    {"href": "/Thesis", "icon": "🔔", "title": "Alerts",
     "desc": "Stops, targets, and watchlist events — inside the Thesis page."},
    {"href": "/Paper_Trading", "icon": "💼", "title": "Paper Trading",
     "desc": "Track simulated portfolios with live P&L."},
    {"href": "/Backtest", "icon": "🎯", "title": "Backtest",
     "desc": "Does your scoring actually predict returns? Plus your judgment scorecard."},
])

ui.group_label("Reference")
ui.nav_grid([
    {"href": "/Glossary", "icon": "📖", "title": "Glossary",
     "desc": "Every term in plain English."},
])

st.divider()
st.caption("Data sources: yfinance · Finviz · SEC EDGAR · Nasdaq · FRED · SQLite — all free, no API keys required.")
