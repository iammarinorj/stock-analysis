"""Stock Pro v2 — Multi-style diagnosis with polished UI + Explain Mode.

Tabs: Multi-Style scorecards, 5yr Trends, Quality Flags, Reverse DCF,
Bull/Bear Thesis, Deep-dive, Earnings, Sources.
"""
from __future__ import annotations

import math
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from lib import data, db
from lib import indices as indices_mod
from lib import trends as trends_mod
from lib import profiles as profiles_mod
from lib import quality_flags as quality_mod
from lib import valuation as val_mod
from lib import narrative as narr_mod
from lib import diagnose as diagnose_mod
from lib import extra_metrics
from lib import financials as fin_mod
from lib import technicals as tech_mod
from lib import options as options_mod
from lib import scoring as scoring_mod
from lib import sector_medians as sector_mod
from lib import ui
from lib import glossary as gloss
from lib import sidebar_chat

st.set_page_config(page_title="Stock Pro", page_icon="📈", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()


def _stock_pro_context() -> str:
    """Bundle current ticker diagnosis into context for the AI."""
    t = st.session_state.get("active_ticker", "")
    if not t:
        return "User is on Stock Pro page but hasn't diagnosed any ticker yet."
    parts = [f"User is currently diagnosing **{t}** in Stock Pro."]
    # Pull saved scorecards if available
    try:
        saved = db.get_profile_scorecards(t)
        if saved:
            parts.append("\nLatest multi-style scorecard:")
            for pid, sc in saved.items():
                parts.append(f"- {pid}: {sc.get('total', 0)}/{sc.get('max', 0)} ({sc.get('pct', 0)*100:.0f}%) — {sc.get('verdict', {}).get('head', '')}")
    except Exception:
        pass
    return "\n".join(parts)


sidebar_chat.render_chat("stock_pro", _stock_pro_context)

ui.page_header(
    title="Stock Pro",
    subtitle="One ticker, four investor lenses. Live trends, quality flags, reverse DCF, bull/bear thesis.",
    icon="📈",
    live=True,
)


def _safe(v):
    if v is None:
        return False
    try:
        if isinstance(v, float) and v != v:
            return False
    except Exception:
        pass
    return True


# ----- Session state -----
if "active_ticker" not in st.session_state:
    st.session_state.active_ticker = ""

# ----- Input row (accepts ticker OR company name) -----
col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
with col1:
    raw_input = st.text_input(
        "Ticker or company name",
        value=st.session_state.active_ticker,
        placeholder="e.g. AAPL, Apple, Hims & Hers, Berkshire, Ford",
        label_visibility="collapsed",
        key="sp_ticker_input",
    ).strip()
with col2:
    score_clicked = st.button("Diagnose", type="primary", use_container_width=True)
with col3:
    add_clicked = st.button("+ Watchlist", use_container_width=True)
with col4:
    refresh_clicked = st.button("Refresh", use_container_width=True, help="Clear cached data")

if refresh_clicked:
    st.cache_data.clear()
    st.rerun()

# Resolve user input (ticker or company name) on button click
if score_clicked and not raw_input:
    st.warning("Enter a ticker or company name first.")
elif (score_clicked or add_clicked) and raw_input:
    with st.spinner(f"Looking up '{raw_input}'..."):
        resolved = data.resolve_ticker(raw_input)
    if resolved.get("error"):
        st.error(resolved["error"])
        st.stop()
    resolved_symbol = resolved["symbol"]
    # Show "interpreted as" notice unless input was already a clean ticker
    if resolved.get("confidence") != "exact_ticker":
        notice = f"Interpreted **'{raw_input}'** as **{resolved_symbol}** ({resolved['name']})"
        if resolved.get("alternatives"):
            alts = ", ".join(
                f"`{a['symbol']}` ({a['name'][:24]})"
                for a in resolved["alternatives"][:3]
            )
            notice += f". Other matches: {alts}"
        st.info(notice)
    if score_clicked:
        st.session_state.active_ticker = resolved_symbol
        st.rerun()  # re-render immediately with the resolved ticker
    if add_clicked:
        # Capture the price at add-time so we can show return-since-added later.
        _q = data.get_quote(resolved_symbol)
        db.add_to_watchlist(resolved_symbol, (_q or {}).get("price"))
        st.success(f"Added {resolved_symbol} to watchlist.")

# ----- Watchlist chips -----
wl = db.get_watchlist()
if wl:
    wl_cols = st.columns([0.1] + [1] * min(len(wl), 8) + [0.5])
    wl_cols[0].caption("Watchlist:")
    for i, sym in enumerate(wl[:8]):
        if wl_cols[i + 1].button(sym, key=f"wl_{sym}", use_container_width=True):
            st.session_state.active_ticker = sym
            st.rerun()

ticker = st.session_state.active_ticker
if not ticker:
    ui.empty_state(
        "Type a ticker above and click <b>Diagnose</b>. "
        "Try <b>AAPL</b> (compounder), <b>F</b> (value), <b>CMG</b> (growth), or <b>BRK-B</b> (Buffett)."
    )
    if gloss.is_explain_mode():
        ui.explain_panel(
            "This page diagnoses one stock at a time. You'll get four investor-style scorecards "
            "(Buffett, Graham, Lynch, Fisher), five years of fundamental trends, three earnings-quality "
            "flags, a reverse DCF that tells you what growth today's price assumes, and an auto-generated "
            "bull/bear thesis you can save to your journal."
        )
    st.stop()

# ----- Fetch live data (concurrent orchestrator: ~3-4s vs ~12s serial) -----
with st.spinner(f"Diagnosing {ticker} (parallel fetches)..."):
    diag = diagnose_mod.diagnose(ticker)

if diag.get("error"):
    st.error(f"Couldn't diagnose {ticker}. {diag['error']}")
    st.stop()

quote = diag["quote"]
# If this ticker is on the watchlist but predates price-tracking, set its baseline now.
db.backfill_watchlist_price(ticker, quote.get("price"))
tr = diag["trends"]
all_scores = diag["scores"]
qflags = diag["quality_flags"]
rdcf = diag["rdcf"]
thesis = diag["thesis"]
best_pid = thesis["best_profile"]

# Persist all four profile scorecards
for pid, sc in all_scores.items():
    db.save_profile_scorecard(ticker, pid, sc)

# ----- Header card -----
sector = quote.get('sector', '—')
industry = quote.get('industry', '—')
hcol = st.columns([3, 1, 1, 1, 1])
with hcol[0]:
    st.markdown(
        f"""<div style="padding:6px 0">
<div style="font-size:20px;font-weight:600;letter-spacing:-.01em">{quote.get('name') or ticker} <span style="color:var(--text-faint);font-weight:400;font-size:14px">({ticker})</span></div>
<div style="font-size:12.5px;color:var(--text-faint)">{sector} · {industry}</div>
</div>""",
        unsafe_allow_html=True,
    )
day_tone = "pos" if quote.get('change_pct', 0) >= 0 else "neg"
with hcol[1]:
    ui.kpi_tile("Price", f"${quote['price']:.2f}",
                f"{quote['change']:+.2f} ({quote['change_pct']:+.2f}%)", day_tone)
with hcol[2]:
    ui.kpi_tile("Market Cap", ui.fmt_money(quote.get("market_cap")), "")
with hcol[3]:
    best_name = all_scores[best_pid]["profile_name"].split(" — ")[0]
    ui.kpi_tile("Best Fit", best_name, f"{all_scores[best_pid]['pct']*100:.0f}% match")
with hcol[4]:
    stance = thesis["stance"]
    stance_tone = {"darkgreen": "pos", "green": "pos", "amber": "warn", "red": "neg"}.get(stance["color"], "")
    sub = f"RDCF {rdcf['implied_growth']*100:+.1f}%/yr" if rdcf else "—"
    ui.kpi_tile("Stance", stance["label"], sub, stance_tone)

# Freshness stamp (#8)
st.caption(ui.freshness_note("Diagnosed"))

# "What changed" since last snapshot (#6) — shows deltas vs the previous diagnosis.
_prev_snaps = db.get_snapshots(symbol=ticker)
if len(_prev_snaps) >= 2:
    _prev = _prev_snaps[1]  # [0] is the one we just saved; [1] is the prior visit
    _prev_px = _prev.get("price")
    _prev_date = (_prev.get("snapped_at") or "")[:10]
    if _prev_px and quote.get("price"):
        _px_chg = (quote["price"] / _prev_px - 1) * 100
        _parts = [f"Price **{_px_chg:+.1f}%** (${_prev_px:.2f} → ${quote['price']:.2f})"]
        for _pid in ("buffett", "graham", "lynch", "fisher"):
            _old_pct = _prev.get(f"{_pid}_pct")
            _new_pct = all_scores.get(_pid, {}).get("pct")
            if _old_pct is not None and _new_pct is not None:
                _d = (_new_pct - _old_pct) * 100
                if abs(_d) >= 1:
                    _parts.append(f"{_pid.title()} {_d:+.0f}pp")
        if len(_parts) > 1:
            st.info(f"📊 **Since last diagnosis** ({_prev_date}): {' · '.join(_parts)}")

st.write("")

# Surface a data-source outage instead of silently rendering blanks. When Finviz
# is unreachable, RSI / insider / performance / some balance-sheet ratios go
# missing — tell the user rather than letting them read "—" as real zeros.
if quote.get("_finviz_error"):
    st.warning(
        "⚠️ **Finviz is unavailable right now**, so a few fields may be blank — "
        "RSI, insider activity, performance windows, and some balance-sheet ratios "
        "(current ratio, debt/equity). Price, fundamentals, financials, and the "
        "scorecards are unaffected. Click **Refresh** in a minute to retry."
    )

# Liquidity warning for low-volume / micro-cap names
_avg_vol = quote.get("avg_volume") or quote.get("volume")
_mkt_cap = quote.get("market_cap")
if _avg_vol and _avg_vol < 100_000:
    st.warning(
        f"⚠️ **Low liquidity** — average daily volume is {_avg_vol:,.0f} shares. "
        "Bid-ask spreads may be wide and entries/exits could incur significant slippage. "
        "Size positions accordingly."
    )
elif _mkt_cap and _mkt_cap < 300_000_000:
    st.info(
        f"ℹ️ **Micro-cap** (${_mkt_cap/1e6:.0f}M market cap). "
        "Lower institutional coverage, wider spreads, and higher volatility than large-caps. "
        "Do extra due diligence on management and financials."
    )

# ----- Tab labels (smart based on Explain Mode) -----
labels = {
    "overview": gloss.smart_label("📋 Overview", "📋 Overview"),
    "profiles": gloss.smart_label("🎯 Multi-Style", "🎯 Investor Lenses"),
    "sector": gloss.smart_label("🏛️ Sector-Relative", "🏛️ Fair by Sector"),
    "trends": gloss.smart_label("📈 Trends (5yr)", "📈 5-Year History"),
    "quality": gloss.smart_label("🛡️ Quality Flags", "🛡️ Safety Checks"),
    "val": gloss.smart_label("💰 Valuation", "💰 What's it Worth?"),
    "thesis": gloss.smart_label("📝 Bull/Bear", "📝 Why Buy or Sell?"),
    "deep": gloss.smart_label("🔬 Deep-dive", "🔬 Full Details"),
    "earn": gloss.smart_label("📅 Earnings", "📅 Earnings History"),
    "src": gloss.smart_label("🔗 Sources", "🔗 Where to Verify"),
}

(tab_overview, tab_profiles, tab_sector, tab_trends, tab_quality, tab_val,
 tab_thesis, tab_deep, tab_earn, tab_sources) = st.tabs(list(labels.values()))

# ============================================================================
# TAB 0 — Overview (the readable research note: summary + key metrics + consensus + news)
# ============================================================================
with tab_overview:
    # Lazy-loaded Overview extras — only fetched when this tab is visible, not on every
    # Stock Pro render. Reuse the 1y price history from diagnose for technicals (avoids a
    # redundant 5y fetch), and pull valuation percentile + options concurrently.
    _ph = diag.get("price_history")
    _tech_ov = tech_mod.compute(ticker, _ph, quote)
    _opt_ov = options_mod.get_summary(ticker, spot=quote.get("price"))
    _hist5y_ov = data.get_price_history(ticker, period="5y")
    _vpct_ov = val_mod.valuation_percentile(_hist5y_ov, diag.get("financials") or {},
                                            quote.get("pe_trailing") or quote.get("pe_forward"))
    summary_paras = narr_mod.executive_summary(quote, tr, thesis, _vpct_ov, qflags,
                                               _tech_ov, _opt_ov, rdcf)
    ui.section_head("The read", "A research-note synthesis from live fundamentals, technicals, options, and consensus.")
    with st.container(border=True):
        for para in summary_paras:
            st.markdown(para)

    # Key metrics grid
    ui.section_head("Key metrics", "What an investor should know before going deeper.")

    def _km(v, kind="num", d=2):
        if v is None or (isinstance(v, float) and v != v):
            return "—"
        if kind == "pct":
            return f"{v*100:.1f}%"
        if kind == "money":
            return ui.fmt_money(v)
        if kind == "x":
            return f"{v:.1f}x"
        return f"{v:.{d}f}"

    row1 = st.columns(4)
    with row1[0]:
        ui.kpi_tile("Market cap", ui.fmt_money(quote.get("market_cap")), "")
    with row1[1]:
        ui.kpi_tile("Fwd P/E", _km(quote.get("pe_forward"), "x"),
                    f"Trailing {_km(quote.get('pe_trailing'),'x')}")
    with row1[2]:
        ui.kpi_tile("PEG", _km(quote.get("peg"), "num"), "growth-adjusted")
    with row1[3]:
        ui.kpi_tile("EV/EBITDA", _km(quote.get("ev_ebitda"), "x"), "")

    # Quarterly + Annual Revenue / Net Income (size numbers)
    _snap = fin_mod.get_period_snapshot(diag.get("financials") or {}, quote=quote)
    row_size = st.columns(4)
    with row_size[0]:
        ui.kpi_tile("Revenue (Q)", ui.fmt_money(_snap["q_rev"]),
                    _snap["q_rev_period"] or "latest quarter")
    with row_size[1]:
        _ni_tone = "pos" if (_snap["q_ni"] or 0) > 0 else ("neg" if _snap["q_ni"] is not None and _snap["q_ni"] < 0 else "")
        ui.kpi_tile("Net income (Q)", ui.fmt_money(_snap["q_ni"]),
                    _snap["q_ni_period"] or "latest quarter", _ni_tone)
    with row_size[2]:
        ui.kpi_tile("Revenue (FY)", ui.fmt_money(_snap["fy_rev"]),
                    _snap["fy_rev_period"] or "latest fiscal year")
    with row_size[3]:
        _fy_ni_tone = "pos" if (_snap["fy_ni"] or 0) > 0 else ("neg" if _snap["fy_ni"] is not None and _snap["fy_ni"] < 0 else "")
        ui.kpi_tile("Net income (FY)", ui.fmt_money(_snap["fy_ni"]),
                    _snap["fy_ni_period"] or "latest fiscal year", _fy_ni_tone)

    row2 = st.columns(4)
    with row2[0]:
        ui.kpi_tile("ROE", _km(quote.get("roe"), "pct"), "return on equity",
                    "pos" if (quote.get("roe") or 0) > 0.15 else "")
    with row2[1]:
        ui.kpi_tile("Operating margin", _km(quote.get("operating_margin"), "pct"), "")
    with row2[2]:
        rgv = quote.get("rev_growth")
        ui.kpi_tile("Revenue growth", _km(rgv, "pct"), "YoY",
                    "pos" if (rgv or 0) > 0 else "neg" if rgv is not None else "")
    with row2[3]:
        dy = quote.get("div_yield")
        ui.kpi_tile("Dividend yield", _km(dy, "pct") if dy else "—", "")
    row3 = st.columns(4)
    with row3[0]:
        ui.kpi_tile("Free cash flow", ui.fmt_money(quote.get("fcf")), "TTM")
    with row3[1]:
        ui.kpi_tile("Gross margin", _km(quote.get("gross_margin"), "pct"), "")
    with row3[2]:
        ui.kpi_tile("Beta", _km(quote.get("beta"), "num"), "volatility vs market")
    with row3[3]:
        rsi = quote.get("rsi_14")
        rsi_tone = "neg" if (rsi or 50) > 70 else "pos" if (rsi or 50) < 30 else ""
        ui.kpi_tile("RSI (14)", _km(rsi, "num", 0) if rsi else "—",
                    "overbought" if (rsi or 0) > 70 else "oversold" if (0 < (rsi or 0) < 30) else "neutral",
                    rsi_tone)

    # Forward estimates row
    _eps_fwd = quote.get("eps_forward")
    _eps_trail = quote.get("eps_trailing")
    _tgt_med = quote.get("target_median")
    _tgt_lo = quote.get("target_low")
    _tgt_hi = quote.get("target_high")
    _n_ana = quote.get("n_analysts")
    if _eps_fwd is not None or _tgt_med is not None or _n_ana:
        row_fwd = st.columns(4)
        with row_fwd[0]:
            _eps_sub = f"Trailing ${_eps_trail:.2f}" if _eps_trail is not None else ""
            ui.kpi_tile("Forward EPS",
                        f"${_eps_fwd:.2f}" if _eps_fwd is not None else "—",
                        _eps_sub)
        with row_fwd[1]:
            _tgt_range = f"${_tgt_lo:.0f} – ${_tgt_hi:.0f}" if (_tgt_lo and _tgt_hi) else ""
            _tgt_upside = ""
            if _tgt_med and quote.get("price"):
                _tgt_upside = f"{((_tgt_med / quote['price']) - 1) * 100:+.1f}% upside"
            ui.kpi_tile("Analyst target (median)",
                        f"${_tgt_med:.2f}" if _tgt_med else "—",
                        f"{_tgt_range}  {_tgt_upside}".strip())
        with row_fwd[2]:
            ui.kpi_tile("# Analysts", str(_n_ana) if _n_ana else "—", "covering this stock")
        with row_fwd[3]:
            _rev_est = quote.get("revenue_estimate")
            ui.kpi_tile("Revenue estimate",
                        ui.fmt_money(_rev_est) if _rev_est else "—",
                        "consensus next period" if _rev_est else "")

    # Consensus + 52-week range
    cc1, cc2 = st.columns([1, 1])
    with cc1:
        ui.section_head("Analyst consensus", "")
        a_cols = st.columns(3)
        a_cols[0].metric("Rating", (quote.get("recommend") or "—").replace("_", " ").upper())
        med = quote.get("target_median")
        a_cols[1].metric("Median target", f"${med:.2f}" if med else "—",
                         f"{((med/quote['price'])-1)*100:+.0f}%" if (med and quote.get('price')) else None)
        a_cols[2].metric("# Analysts", quote.get("n_analysts") or "—")
    with cc2:
        ui.section_head("52-week range", "")
        yl, yh, px = quote.get("year_low"), quote.get("year_high"), quote.get("price")
        if yl and yh and px:
            pos = max(0, min(100, (px - yl) / (yh - yl) * 100))
            st.markdown(
                f'<div style="margin-top:6px">'
                f'<div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-faint)">'
                f'<span>${yl:.2f}</span><span>${yh:.2f}</span></div>'
                f'<div style="position:relative;height:8px;background:var(--surface-alt);border-radius:999px;margin:4px 0">'
                f'<div style="position:absolute;left:{pos}%;top:-3px;width:14px;height:14px;border-radius:50%;'
                f'background:var(--accent);transform:translateX(-50%);border:2px solid var(--surface)"></div></div>'
                f'<div style="text-align:center;font-size:13px;color:var(--text);font-weight:600">'
                f'${px:.2f} · {pos:.0f}% of range</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("Range data unavailable.")

    # Technicals
    if _tech_ov:
        ui.section_head("Technicals", _tech_ov.get("summary", ""))
        tcols = st.columns(4)
        tcols[0].metric("Trend", _tech_ov.get("trend_stage", "—"))
        tcols[1].metric("RSI (14)", f"{_tech_ov['rsi']:.0f}" if _tech_ov.get("rsi") is not None else "—")
        tcols[2].metric("MACD", "Bullish" if _tech_ov.get("macd", {}).get("bullish") else "Bearish")
        tcols[3].metric("vs 200 DMA", "Above" if _tech_ov.get("above_200dma") else "Below")
        m2 = st.columns(4)
        m2[0].metric("50 DMA", f"${_tech_ov['sma50']:.2f}" if _tech_ov.get("sma50") else "—")
        m2[1].metric("200 DMA", f"${_tech_ov['sma200']:.2f}" if _tech_ov.get("sma200") else "—")
        m2[2].metric("Support (3m)", f"${_tech_ov['support']:.2f}" if _tech_ov.get("support") else "—")
        m2[3].metric("Resistance (3m)", f"${_tech_ov['resistance']:.2f}" if _tech_ov.get("resistance") else "—")
        rets = _tech_ov.get("returns", {})
        if rets:
            st.caption("Trailing returns: " + " · ".join(f"**{k}** {v*100:+.1f}%" for k, v in rets.items()))

    # Options snapshot
    if _opt_ov and not _opt_ov.get("err") and _opt_ov.get("expiry"):
        ui.section_head("Options snapshot",
                        f"Nearest meaningful expiry: {_opt_ov['expiry']} ({_opt_ov.get('dte')} days out).")
        ocols = st.columns(4)
        em = _opt_ov.get("expected_move_pct")
        ocols[0].metric("Expected move", f"±{em*100:.1f}%" if em else "—",
                        f"±${_opt_ov.get('expected_move_abs', 0):.2f}" if em else None)
        ocols[1].metric("ATM IV", f"{_opt_ov['atm_iv']*100:.0f}%" if _opt_ov.get("atm_iv") else "—")
        pc = _opt_ov.get("pc_oi_ratio")
        ocols[2].metric("Put/Call OI", f"{pc:.2f}" if pc is not None else "—",
                        ("bearish" if (pc or 0) > 1.2 else "bullish" if (pc is not None and pc < 0.7) else "balanced"))
        ocols[3].metric("Max pain", f"${_opt_ov['max_pain']:.0f}" if _opt_ov.get("max_pain") else "—")
        with st.expander("Near-the-money chain"):
            _chain_cols = [
                {"key": "type", "label": "Type"},
                {"key": "strike", "label": "Strike", "align": "num"},
                {"key": "last", "label": "Last", "align": "num"},
                {"key": "bid", "label": "Bid", "align": "num"},
                {"key": "ask", "label": "Ask", "align": "num"},
                {"key": "iv", "label": "IV", "align": "num"},
                {"key": "oi", "label": "OI", "align": "num"},
                {"key": "vol", "label": "Vol", "align": "num"},
            ]
            _chain_rows = []
            from lib import fmt as _fmt
            _si = lambda v: int(v) if not _fmt.is_nan(v) and v is not None else 0
            _sf = lambda v, d=0.0: v if not _fmt.is_nan(v) and v is not None else d
            for kind, src in [("Call", _opt_ov.get("calls_near", [])), ("Put", _opt_ov.get("puts_near", []))]:
                for r in src:
                    _chain_rows.append({
                        "type": kind, "strike": f"${r['strike']:.0f}",
                        "last": f"${_sf(r.get('lastPrice')):.2f}", "bid": f"${_sf(r.get('bid')):.2f}",
                        "ask": f"${_sf(r.get('ask')):.2f}",
                        "iv": f"{_sf(r.get('impliedVolatility'))*100:.0f}%",
                        "oi": f"{_si(r.get('openInterest')):,}",
                        "vol": f"{_si(r.get('volume')):,}",
                    })
            if _chain_rows:
                ui.glass_table(_chain_cols, _chain_rows)
        st.caption("Options via yfinance. Expected move = at-the-money straddle price. "
                   "Paper-trade options on the **Paper Trading** page.")

    # Recent news
    ui.section_head("Recent news", "Latest headlines. Click through to read.")
    news = data.get_news(ticker, limit=8)
    if news:
        for n in news:
            title = n.get("title") or "—"
            link = n.get("link")
            src = n.get("source") or ""
            dt = n.get("date") or ""
            meta = " · ".join([x for x in (src, dt) if x])
            if link:
                st.markdown(f"- [{title}]({link})  \n  <span style='color:var(--text-faint);font-size:11.5px'>{meta}</span>",
                            unsafe_allow_html=True)
            else:
                st.markdown(f"- {title}  \n  <span style='color:var(--text-faint);font-size:11.5px'>{meta}</span>",
                            unsafe_allow_html=True)
    else:
        st.caption("No recent headlines available right now.")

    st.caption("Want the philosophy-by-philosophy verdicts? See the **Investor Lenses** tab. "
               "Full financials and charts are in **Deep-dive**.")

# ============================================================================
# TAB 1 — Multi-Style Scorecards
# ============================================================================
with tab_profiles:
    ui.section_head("One stock, four philosophies",
                    "Same data scored against four different investor styles.")
    if gloss.is_explain_mode():
        ui.explain_panel(
            "Every great investor has a different test. A cigar butt that fails Buffett's quality test "
            "can score 9/10 for Graham. A 50x P/E tech stock that fails Graham's price test can be Fisher's "
            "wheelhouse. The same stock looks different through different lenses. The <b>★ Best Fit</b> "
            "highlights which style this stock fits most naturally."
        )

    # Dynamic column count so the card grid scales with number of profiles.
    # 3-wide for 5+ profiles gives a clean 3x3 grid for the 9 styles instead of
    # a lopsided 5+4 wrap. Re-create the column row at the start of each row so
    # cards align top-to-bottom rather than stacking inside one column.
    n_profiles = len(all_scores)
    cols_per_row = 3 if n_profiles > 4 else n_profiles
    pcols = st.columns(cols_per_row)
    for i, (pid, sc) in enumerate(all_scores.items()):
        if i > 0 and i % cols_per_row == 0:
            pcols = st.columns(cols_per_row)
        col = pcols[i % cols_per_row]
        with col:
            tag = "★ BEST FIT" if pid == best_pid else ""
            short_name = sc["profile_name"].split(" — ")[0]
            sub_name = sc["profile_name"].split(" — ")[1] if " — " in sc["profile_name"] else ""
            sub = f"{sc['pct']*100:.0f}% · {sc['verdict']['head'][:38]}"
            st.markdown(
                ui.score_card(
                    label=f"{short_name}<br><span style='font-size:11px;font-weight:400;color:#666'>{sub_name}</span>",
                    value=f"{sc['total']}/{sc['max']}",
                    sub=sub,
                    color=sc["verdict"]["color"],
                    tag=tag,
                    height=180,
                ),
                unsafe_allow_html=True,
            )

    st.write("")
    # Detailed checklists
    for pid, sc in all_scores.items():
        is_best = pid == best_pid
        prefix = "★ " if is_best else ""
        with st.expander(
            f"{prefix}{sc['profile_name']}  ·  {sc['total']}/{sc['max']} ({sc['pct']*100:.0f}%)  ·  {sc['verdict']['head']}",
            expanded=is_best,
        ):
            _gkey = gloss.PROFILE_GLOSSARY.get(pid)
            _gentry = gloss.GLOSSARY.get(_gkey) if _gkey else None
            if _gentry:
                st.markdown(f"📖 **The idea:** {_gentry['plain']} _{_gentry.get('why', '')}_")
            st.caption(profiles_mod.PROFILES[pid]["description"])
            st.markdown(f"_{sc['verdict']['explain']}_")
            st.write("")
            for item in sc["items"]:
                icon = "✅" if item["pass"] else "❌"
                wtag = ui.pill(f"W{item['weight']}", "accent") if item["weight"] > 1 else ""
                col_a, col_b = st.columns([3, 2])
                col_a.markdown(f"{icon} **{item['label']}** {wtag}", unsafe_allow_html=True)
                col_a.caption(item["note"])
                col_b.markdown(ui.actual_value(item["actual"]), unsafe_allow_html=True)

    # ----- Score history: how this stock's scores evolved across your diagnoses -----
    st.write("")
    snaps = db.get_snapshots(symbol=ticker)
    if len(snaps) >= 2:
        ui.section_head("📈 Score history", "How your scores for this stock evolved over past diagnoses.")
        snaps_chrono = sorted(snaps, key=lambda s: s["snapped_at"])
        xs = [s["snapped_at"][:10] for s in snaps_chrono]
        fig = go.Figure()
        for pid, color in [("buffett", "#1e3a8a"), ("graham", "#0a5f3c"),
                           ("lynch", "#9a6500"), ("fisher", "#8a1818")]:
            ys = [round((s.get(f"{pid}_pct") or 0) * 100) for s in snaps_chrono]
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=pid.title(),
                                     line=dict(color=color, width=2)))
        # Price on a secondary axis for context
        prices = [s.get("price") for s in snaps_chrono]
        if any(p for p in prices):
            fig.add_trace(go.Scatter(x=xs, y=prices, mode="lines", name="Price",
                                     line=dict(color="#888", width=1, dash="dot"), yaxis="y2"))
        fig.update_layout(
            height=300, margin=dict(l=10, r=10, t=10, b=10),
            yaxis=dict(title="Score %", range=[0, 100]),
            yaxis2=dict(title="Price", overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", y=1.12),
        )
        ui.style_fig(fig)
        st.plotly_chart(fig, use_container_width=True, config=ui.chart_config())
        st.caption(f"{len(snaps)} snapshots saved (one per diagnose, max one per 12h). "
                   "Was it always this cheap/strong, or did the setup just change?")

# ============================================================================
# TAB 2 — Sector-Relative scorecard
# ============================================================================
with tab_sector:
    ui.section_head(
        "Same metrics, fair by sector",
        "Compares each metric to this stock's sector peers' median, not absolute thresholds. Fixes the 'COST fails 15% op margin' problem.",
    )
    if gloss.is_explain_mode():
        ui.explain_panel(
            "The 4 profile scorecards (Buffett / Graham / Lynch / Fisher) use the philosophy each investor actually used — "
            "absolute thresholds like 'ROE &gt; 15%' or 'P/E &lt; 15'. That's right for picking investments in those styles. "
            "But it's <b>unfair when comparing across sectors</b>: a retailer's 4% op margin is elite, but it'd fail Buffett's "
            "15% test. This tab grades the stock against <b>its sector peers' median</b>, so a great retailer doesn't get "
            "punished for being a retailer. Use this tab when you want sector-aware ranking; use the profile tab when you "
            "want to know if a name fits a specific philosophy."
        )

    sym = quote.get("symbol", "")
    with st.spinner(f"Pulling {sym}'s peer medians (cached 7 days)..."):
        sec_data = sector_mod.compute_sector_medians(sym)

    if sec_data.get("err") or sec_data.get("n", 0) < 3:
        st.warning(
            f"Sector-relative not available for **{sym}**: {sec_data.get('err', 'insufficient peers')}. "
            "We fall back to the absolute scorecard below. Add peers to `lib/data.get_peers()`'s "
            "hardcoded map to expand coverage."
        )
        sec_for_scoring = None
    else:
        sec_for_scoring = sec_data
        peers_list = ", ".join(sec_data.get("peers_used", []))
        st.caption(f"📊 Compared to **{sec_data.get('n', 0)}** sector peers: {peers_list}")

    sec_result = scoring_mod.score(quote, sector_medians=sec_for_scoring)

    # Verdict box
    v = sec_result["verdict"]
    mode_tag = (
        f"sector-relative vs <b>{sec_result.get('sector') or 'sector'}</b> ({sec_result.get('n_peers')} peers)"
        if sec_result["mode"] == "sector"
        else "absolute thresholds (no sector peers found)"
    )
    ui.verdict_box(
        label="SECTOR-RELATIVE VERDICT",
        headline=f"{sec_result['total']} / {sec_result['max']} ({sec_result['pct']*100:.0f}%) — {v['head']}",
        body=f"{v['explain']}<br><span style='font-size:11.5px;color:#3d3d3d'>Mode: {mode_tag}</span>",
        color=v["color"],
    )

    # Category tiles
    cat_cols = st.columns(4)
    cat_meta = {"val": "Valuation", "qual": "Quality", "cat": "Catalyst", "tech": "Technical"}
    for i, (cid, cname) in enumerate(cat_meta.items()):
        sc = sec_result["by_cat"].get(cid, {"s": 0, "m": 0, "pct": 0})
        pct = sc["pct"]
        color = "darkgreen" if pct >= 0.85 else "green" if pct >= 0.6 else "yellow" if pct >= 0.4 else "amber" if pct >= 0.25 else "red"
        with cat_cols[i]:
            st.markdown(
                ui.score_card(
                    label=cname,
                    value=f"{sc['s']}/{sc['m']}",
                    sub=f"{pct*100:.0f}%",
                    color=color,
                    height=110,
                ),
                unsafe_allow_html=True,
            )

    st.write("")

    # Detailed checklist by category
    cat_order = ["val", "qual", "cat", "tech"]
    cat_labels = {"val": "💰 Valuation", "qual": "🛡️ Quality", "cat": "🚀 Catalyst", "tech": "📊 Technical"}
    for cid in cat_order:
        cat_items = [(item_def, sec_result["items"][item_def["id"]]) for item_def in scoring_mod.SCORECARD_ITEMS if item_def["cat"] == cid]
        sc = sec_result["by_cat"].get(cid, {"s": 0, "m": 0})
        with st.expander(f"{cat_labels[cid]} — {sc['s']}/{sc['m']}", expanded=(cid in ("val", "qual"))):
            for item_def, ev in cat_items:
                icon = "✅" if ev["pass"] else "❌"
                wtag = ui.pill(f"W{ev['weight']}", "accent") if ev["weight"] > 1 else ""
                col_a, col_b = st.columns([3, 2])
                col_a.markdown(f"{icon} **{ev['label']}** {wtag}", unsafe_allow_html=True)
                col_a.caption(ev["note"])
                col_b.markdown(ui.actual_value(ev["actual"]), unsafe_allow_html=True)

# ============================================================================
# TAB 3 — Trends (5yr)
# ============================================================================
with tab_trends:
    if tr.get("error"):
        st.warning(f"Couldn't pull annual financials: {tr['error']}")
    else:
        ui.section_head(
            f"{tr['n_years']}-year trajectories",
            "Direction matters more than level. Rising metrics = compounding.",
        )
        if gloss.is_explain_mode():
            ui.explain_panel(
                "This is where alpha hides. A company with 15% ROE today tells you almost nothing. "
                "15% ROE every year for 5 years = quality compounder. 15% ROE down from 28% = falling business. "
                "Direction matters more than level."
            )

        # ------ FY financials summary table with YoY % change ------
        _fy_metrics = [
            ("revenue", "Revenue", True, False),
            ("net_income", "Net Income", True, False),
            ("fcf", "Free Cash Flow", True, False),
            ("gross_margin", "Gross Margin", False, True),
            ("operating_margin", "Operating Margin", False, True),
        ]
        _fy_years = tr.get("years", [])  # most recent first
        _fy_data = tr.get("metrics", {})
        if _fy_years and len(_fy_years) >= 2:
            ui.section_head("Fiscal year financials", "Key metrics by year with YoY change.")
            # Build rows: each metric across FY columns, with YoY %
            _fy_header_cols = [{"key": "metric", "label": "Metric"}]
            for y in reversed(_fy_years):
                _fy_header_cols.append({"key": str(y), "label": str(y), "align": "num"})
            _fy_table_rows = []
            for mid, label, is_money, is_pct in _fy_metrics:
                vals = _fy_data.get(mid, [])
                if not vals or all(v is None for v in vals):
                    continue
                row = {"metric": label}
                # vals are most-recent-first, years are most-recent-first
                val_by_year = dict(zip(_fy_years, vals))
                years_asc = list(reversed(_fy_years))
                for i, y in enumerate(years_asc):
                    v = val_by_year.get(y)
                    if v is None:
                        row[str(y)] = "—"
                        continue
                    # Format the value
                    if is_pct:
                        formatted = f"{v*100:.1f}%"
                    elif is_money:
                        formatted = ui.fmt_money(v)
                    else:
                        formatted = f"{v:,.0f}"
                    # Compute YoY change vs previous year
                    if i > 0:
                        prev_y = years_asc[i - 1]
                        pv = val_by_year.get(prev_y)
                        if pv is not None and pv != 0:
                            if is_pct:
                                # For margins, show absolute pp change
                                delta_pp = (v - pv) * 100
                                formatted += f"  ({delta_pp:+.1f}pp)"
                            else:
                                yoy = (v / pv - 1) * 100
                                formatted += f"  ({yoy:+.0f}%)"
                    row[str(y)] = formatted
                _fy_table_rows.append(row)
            if _fy_table_rows:
                ui.glass_table(_fy_header_cols, _fy_table_rows)
            st.write("")

        # ------ Trend direction summary ------
        trend_rows = []
        priority = ["revenue", "gross_margin", "operating_margin", "roic", "roe",
                    "fcf", "fcf_margin", "fcf_conv", "nd_ebitda", "shares_diluted",
                    "eps", "interest_coverage"]
        for m in priority:
            t = tr["trends"].get(m, {})
            if t.get("direction") == "insufficient_data":
                continue
            direction = t.get("direction", "?")
            _arrow_map = {
                "rising strongly": "⬆", "rising": "↗", "rising slightly": "↗",
                "falling sharply": "⬇", "falling": "↘", "falling slightly": "↘",
                "flat": "→", "erratic": "⤨",
            }
            arrow = _arrow_map.get(direction, "?")
            # For nd_ebitda and shares_diluted, "rising" is bad
            inverse_metrics = ("nd_ebitda", "shares_diluted")
            _is_rising = direction.startswith("rising")
            _is_falling = direction.startswith("falling")
            if m in inverse_metrics and _is_rising:
                color_emoji = "🔴"
            elif m in inverse_metrics and _is_falling:
                color_emoji = "🟢"
            elif _is_rising:
                color_emoji = "🟢"
            elif _is_falling:
                color_emoji = "🔴"
            elif direction == "flat":
                color_emoji = "⚪"
            else:
                color_emoji = "🟡"
            trend_rows.append({
                "": color_emoji,
                "Metric": m.replace("_", " ").title(),
                "Direction": f"{arrow} {direction}",
                "Detail": t.get("label", "—"),
            })
        if trend_rows:
            st.dataframe(pd.DataFrame(trend_rows), use_container_width=True, hide_index=True)

        st.write("")
        ui.section_head("Charts", "Key metrics, charted over time.")

        def trend_chart(metric_id, title, is_pct=False, is_money=False):
            vals = tr["metrics"].get(metric_id, [])
            years = tr["years"]
            pairs = [(y, v) for y, v in zip(years[::-1], vals[::-1]) if v is not None]
            if len(pairs) < 2:
                return None
            xs, ys = zip(*pairs)
            ys_display = [v * 100 for v in ys] if is_pct else list(ys)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=list(xs), y=ys_display, mode="lines+markers",
                                     line=dict(color="#1e3a8a", width=2.5),
                                     marker=dict(size=8, color="#1e4dd8"),
                                     fill="tozeroy", fillcolor="rgba(30,77,216,0.08)"))
            fig.update_layout(
                title=dict(text=title, font=dict(size=13)),
                height=220,
                margin=dict(l=10, r=10, t=34, b=10),
                xaxis_title=None,
                yaxis_title=("%" if is_pct else ("$" if is_money else None)),
                showlegend=False,
            )
            ui.style_fig(fig)
            fig.update_xaxes(showgrid=False)
            if is_money:
                fig.update_yaxes(tickformat="$,.0f")
            return fig

        ch_cols = st.columns(2)
        charts = [
            ("revenue", "Revenue", False, True),
            ("operating_margin", "Operating Margin (%)", True, False),
            ("roic", "ROIC (%)", True, False),
            ("fcf", "Free Cash Flow", False, True),
            ("gross_margin", "Gross Margin (%)", True, False),
            ("shares_diluted", "Shares Outstanding", False, False),
        ]
        for i, (mid, title, is_pct, is_money) in enumerate(charts):
            fig = trend_chart(mid, title, is_pct, is_money)
            if fig:
                ch_cols[i % 2].plotly_chart(fig, use_container_width=True)

# ============================================================================
# TAB 3 — Quality Flags
# ============================================================================
with tab_quality:
    ui.section_head("Quality + bankruptcy + manipulation flags",
                    "Three academic factors. Use as red-flag detectors.")
    if gloss.is_explain_mode():
        ui.explain_panel(
            "These three models answer different questions: <b>Piotroski</b> asks 'is the balance sheet "
            "getting stronger or weaker year-over-year?' (9 yes/no checks). <b>Altman Z</b> asks 'how far "
            "is this company from bankruptcy?' (5 weighted ratios). <b>Beneish M</b> asks 'are the "
            "reported numbers suspiciously good?' (8 earnings-manipulation flags). A red flag here doesn't "
            "mean sell — it means <b>dig deeper before you buy</b>."
        )

    qc1, qc2, qc3 = st.columns(3)

    p = qflags["piotroski"]
    with qc1:
        if p.get("error"):
            st.warning(f"Piotroski: {p['error']}")
        else:
            st.markdown(
                ui.score_card("Piotroski F-Score", f"{p['score']}/9", p["grade"], p["color"], height=120),
                unsafe_allow_html=True,
            )
            st.caption(p["interpretation"])
            with st.expander("9-point breakdown"):
                for cid, label in p["labels"].items():
                    ok = p["checks"].get(cid, False)
                    st.markdown(f"{'✅' if ok else '❌'} {label}")

    a = qflags["altman"]
    with qc2:
        if a.get("error"):
            st.warning(f"Altman Z: {a['error']}")
        else:
            st.markdown(
                ui.score_card("Altman Z-Score", f"{a['score']}", a["grade"], a["color"], height=120),
                unsafe_allow_html=True,
            )
            st.caption(a["interpretation"])
            with st.expander("Component breakdown"):
                for k, v in a.get("components", {}).items():
                    st.markdown(f"- **{k}**: {v:.3f}")

    b = qflags["beneish"]
    with qc3:
        if b.get("error"):
            st.warning(f"Beneish M: {b['error']}")
        else:
            st.markdown(
                ui.score_card("Beneish M-Score", f"{b['score']}", b["grade"], b["color"], height=120),
                unsafe_allow_html=True,
            )
            st.caption(b["interpretation"])

# ============================================================================
# TAB 4 — Valuation
# ============================================================================
with tab_val:
    ui.section_head("Reverse DCF — what growth does today's price imply?",
                    "Twiddle assumptions in the sidebar to find your fair value.")
    if gloss.is_explain_mode():
        ui.explain_panel(
            "Most valuation models guess at future growth, then compute a price. <b>Reverse DCF</b> flips that. "
            "It takes today's price and works backward: 'what annual growth rate does the market need to "
            "see for the stock to be worth this much?' If the answer is 25% and the company grows 10%, "
            "the stock is priced for perfection. If the answer is 4% and the company grows 8%, you have margin "
            "of safety on growth alone."
        )

    # ----- Valuation percentile vs own history (mean-reversion read) -----
    _cur_pe = quote.get("pe_trailing") or quote.get("pe_forward")
    _hist5y = data.get_price_history(ticker, period="5y")
    vpct = val_mod.valuation_percentile(_hist5y, diag.get("financials") or {}, _cur_pe)
    if vpct:
        p = vpct["percentile"]
        tone = "neg" if p >= 80 else ("warn" if p >= 60 else ("pos" if p <= 35 else ""))
        read = ("expensive vs its own history" if p >= 80 else
                "above its own norm" if p >= 60 else
                "cheap vs its own history" if p <= 35 else
                "around its own historical norm")
        vp_cols = st.columns([2, 1, 1, 1])
        with vp_cols[0]:
            ui.kpi_tile(f"{vpct['metric']} percentile (5y)", f"{p:.0f}th",
                        f"Today's {vpct['metric']} {vpct['current']:.1f}x is {read}", tone)
        vp_cols[1].metric("5y low", f"{vpct['low']:.1f}x")
        vp_cols[2].metric("5y median", f"{vpct['median']:.1f}x")
        vp_cols[3].metric("5y high", f"{vpct['high']:.1f}x")
        st.caption(f"Based on {vpct['n_obs']:,} daily observations of price ÷ trailing annual EPS. "
                   "A high percentile means the market is paying more for this stock than it usually does.")
        st.write("")

    if rdcf is None:
        fcf_now = quote.get("fcf")
        if fcf_now is not None and fcf_now < 0:
            ui.empty_state(
                f"Reverse DCF unavailable because current FCF is negative (${fcf_now/1e6:.0f}M). "
                f"That's common for inflection plays building capacity. "
                f"<b>Scroll down to the Pre-profit Projection DCF</b> — it values the company based on "
                f"future revenue × target FCF margin, which is how analysts actually price AAOI-style names."
            )
        else:
            ui.empty_state("Reverse DCF unavailable (need positive FCF, shares outstanding, and price).")
    else:
        rcols = st.columns([2, 1, 1])
        with rcols[0]:
            color = rdcf["color"]
            ui.verdict_box(
                "Implied annual growth (10 years)",
                f"{rdcf['implied_growth']*100:.2f}% / year",
                rdcf["verdict"],
                color,
            )
        with rcols[1]:
            st.markdown("**Default assumptions**")
            asm = rdcf["assumptions"]
            st.caption(f"• Price: ${asm['price']:.2f}")
            st.caption(f"• Base FCF: ${asm['fcf_base']/1e9:.2f}B")
            st.caption(f"• High-growth years: {asm['high_years']}")
            st.caption(f"• Discount rate: {asm['discount']*100:.1f}%")
            st.caption(f"• Terminal growth: {asm['terminal_growth']*100:.1f}%")

        with rcols[2]:
            st.markdown("**Your assumptions**")
            user_yrs = st.slider("High-growth years", 5, 15, 10, 1, key="rdcf_yrs")
            user_disc = st.slider("Discount rate (%)", 5.0, 15.0, 9.0, 0.5, key="rdcf_disc") / 100
            user_term = st.slider("Terminal growth (%)", 1.0, 4.0, 2.5, 0.25, key="rdcf_term") / 100

        net_cash = (quote.get("total_cash") or 0) - (quote.get("total_debt") or 0)
        user_rdcf = val_mod.reverse_dcf(
            price=quote["price"], fcf_base=quote["fcf"], shares=quote["shares_out"],
            high_years=user_yrs, growth_terminal=user_term, discount=user_disc, net_cash=net_cash,
        )
        if user_rdcf.get("implied_growth") is not None:
            st.info(
                f"**With your assumptions:** Implied growth = "
                f"**{user_rdcf['implied_growth']*100:.2f}%/yr**. {user_rdcf['verdict']}"
            )

    # Forward DCF
    st.write("")
    ui.section_head("Forward 2-stage DCF (sanity check)",
                    "Pick your assumptions and see implied fair value.")

    if gloss.is_explain_mode():
        ui.explain_panel(
            "Project the company's free cash flow growing at your <b>high-stage growth</b> rate for some years, "
            "then settling to a <b>terminal growth</b> rate forever. Discount it all back to today using a "
            "<b>discount rate</b> (your required return). The result is your fair value per share."
        )

    fdc1, fdc2 = st.columns(2)
    with fdc1:
        g_high = st.slider("High-stage growth (%)", 0.0, 30.0, 12.0, 1.0, key="fdc_g") / 100
        years_high = st.slider("High-stage years", 5, 15, 10, 1, key="fdc_yrs")
        g_term = st.slider("Terminal growth (%)", 1.0, 4.0, 2.5, 0.25, key="fdc_term") / 100
        disc = st.slider("Discount rate (%)", 5.0, 15.0, 9.0, 0.5, key="fdc_disc") / 100
    if quote.get("fcf") and quote.get("shares_out") and quote["fcf"] > 0:
        net_cash = (quote.get("total_cash") or 0) - (quote.get("total_debt") or 0)
        fwd = val_mod.forward_dcf(quote["fcf"], g_high, years_high, g_term, disc,
                                  quote["shares_out"], net_cash)
        with fdc2:
            if "error" in fwd:
                st.warning(fwd["error"])
            else:
                fv = fwd["fair_value_per_share"]
                price = quote["price"]
                mos = (fv - price) / fv if fv else 0
                color = "green" if mos > 0.25 else ("amber" if mos > 0 else "red")
                ui.verdict_box(
                    "Fair value (per share)",
                    f"${fv:.2f}",
                    f"Current: ${price:.2f} · Margin of safety: <b>{mos*100:+.1f}%</b>. "
                    f"Terminal = {fwd['terminal_pct_of_value']*100:.0f}% of value"
                    f"{' (too much — lower g_high)' if fwd['terminal_pct_of_value'] > 0.70 else ''}.",
                    color,
                )
                bands = val_mod.mos_bands(fv)
                st.markdown("**Margin-of-safety price bands**")
                st.caption(f"• 25% MoS: ${bands['25_pct_mos']:.2f} (Buffett comfortable)")
                st.caption(f"• 33% MoS: ${bands['33_pct_mos']:.2f} (Buffett traditional)")
                st.caption(f"• 50% MoS: ${bands['50_pct_mos']:.2f} (Klarman / cigar butt)")

    # ============================================================================
    # PROJECTION DCF — for pre-profit / inflection companies
    # ============================================================================
    st.write("")
    ui.section_head(
        "Pre-profit Projection DCF (inflection / hypergrowth mode)",
        "Value the company on FUTURE revenue × target FCF margin. Use when FCF is negative or tiny today.",
    )

    if gloss.is_explain_mode():
        ui.explain_panel(
            "Standard DCFs need positive cash flow to start from. Inflection plays "
            "(AAOI, CRDO, ALAB) don't have that yet. Instead, project: "
            "<b>(1)</b> revenue grows at X% per year for Y years, "
            "<b>(2)</b> FCF margin ramps from ~0% today to a target margin (e.g. 15%) over Z years, "
            "<b>(3)</b> then everything settles into a low-growth steady state forever. "
            "Discount it all back. This is how Wall Street actually values pre-profit growth companies."
        )

    rev_now = quote.get("revenue") or 0
    shares_now = quote.get("shares_out") or 0
    sector_now = (quote.get("sector") or "").lower()

    # Sensible defaults — adapt to inflection nature of the stock
    default_growth = 25 if (quote.get("rev_growth") or 0) > 0.30 else 15
    default_margin = 20 if "technolog" in sector_now else 12
    default_discount = 11 if (quote.get("rev_growth") or 0) > 0.30 else 9

    if rev_now > 0 and shares_now > 0:
        pdc1, pdc2 = st.columns(2)
        with pdc1:
            st.markdown(f"**Starting from today**")
            st.caption(f"• Current revenue: ${rev_now/1e9:.2f}B")
            st.caption(f"• Current FCF: ${(quote.get('fcf') or 0)/1e6:+.0f}M")
            st.caption(f"• Current shares out: {shares_now/1e6:.0f}M")
            st.write("")
            pg = st.slider("Revenue growth /yr (%)", 5.0, 60.0, float(default_growth), 1.0, key="pdc_g") / 100
            py = st.slider("High-growth years", 3, 12, 7, 1, key="pdc_yrs")
            pmargin = st.slider("Target FCF margin (%)", 5.0, 40.0, float(default_margin), 1.0, key="pdc_m") / 100
            pramp = st.slider("Years to reach target margin", 1, 10, 5, 1, key="pdc_ramp")
            pdisc = st.slider("Discount rate (%)", 6.0, 18.0, float(default_discount), 0.5, key="pdc_disc") / 100
            pterm = st.slider("Terminal growth (%)", 1.0, 4.0, 2.5, 0.25, key="pdc_term") / 100

        net_cash = (quote.get("total_cash") or 0) - (quote.get("total_debt") or 0)
        proj = val_mod.projection_dcf(
            price=quote["price"],
            revenue_today=rev_now,
            rev_growth_high=pg,
            high_years=py,
            target_fcf_margin=pmargin,
            margin_ramp_years=pramp,
            discount=pdisc,
            growth_terminal=pterm,
            shares=shares_now,
            net_cash=net_cash,
        )

        with pdc2:
            if "error" in proj:
                st.warning(proj["error"])
            else:
                fv = proj["fair_value_per_share"]
                price = quote["price"]
                mos = proj.get("margin_of_safety", 0)
                color = "darkgreen" if mos > 0.40 else ("green" if mos > 0.20 else ("amber" if mos > 0 else "red"))
                ui.verdict_box(
                    "Projection fair value (per share)",
                    f"${fv:.2f}",
                    f"Current ${price:.2f} · Margin of safety: <b>{mos*100:+.1f}%</b>. "
                    f"In Year {py}, this model implies revenue of ${proj['last_year_revenue']/1e9:.1f}B "
                    f"and FCF of ${proj['last_year_fcf']/1e9:.2f}B. "
                    f"Terminal = {proj['terminal_pct_of_value']*100:.0f}% of value.",
                    color,
                )
                bands = val_mod.mos_bands(fv)
                st.markdown("**Margin-of-safety price bands**")
                st.caption(f"• 25% MoS: ${bands['25_pct_mos']:.2f} (cushion for execution risk)")
                st.caption(f"• 33% MoS: ${bands['33_pct_mos']:.2f} (Buffett buy zone)")
                st.caption(f"• 50% MoS: ${bands['50_pct_mos']:.2f} (deep margin, accepts the bet)")

                st.divider()
                st.markdown("**Sanity check the model**")
                impl_rev_cagr = pg * 100
                yr5_rev = rev_now * (1 + pg) ** 5 / 1e9
                yr10_rev = rev_now * (1 + pg) ** py / 1e9
                st.caption(
                    f"If this company grows {impl_rev_cagr:.0f}%/yr, it'll do ~${yr5_rev:.1f}B "
                    f"in revenue in 5 years and ~${yr10_rev:.1f}B in {py} years. Is that realistic given its TAM?"
                )
                st.caption(
                    f"At a {pmargin*100:.0f}% FCF margin, Year {py} FCF would be "
                    f"${proj['last_year_fcf']/1e9:.2f}B. Compare to peer mature FCF margins."
                )
    else:
        ui.empty_state("Need positive revenue and shares outstanding for projection DCF.")

# ============================================================================
# TAB 5 — Bull/Bear thesis
# ============================================================================
with tab_thesis:
    ui.section_head("Auto-synthesized thesis",
                    "Heuristic starting point. Edit before sizing.")

    if gloss.is_explain_mode():
        ui.explain_panel(
            "Every position you take should have three things written down: <b>why you're buying</b> (bull case), "
            "<b>what could go wrong</b> (bear case), and <b>what would prove you wrong</b> (breaks-if triggers). "
            "Below is an auto-synthesized version from all the data we pulled. Edit it, then save to your "
            "Thesis Journal so future-you can audit past-you's reasoning."
        )

    stance = thesis["stance"]
    ui.verdict_box(
        f"Overall stance for {ticker}",
        stance["label"],
        stance["rationale"],
        stance["color"],
    )

    bb_cols = st.columns(2)
    with bb_cols[0]:
        st.markdown("##### 🟢 Bull case")
        for b in thesis["bull"]:
            st.markdown(f"• {b}")
    with bb_cols[1]:
        st.markdown("##### 🔴 Bear case")
        for b in thesis["bear"]:
            st.markdown(f"• {b}")

    st.markdown("##### ⚠️ Thesis breaks if")
    for b in thesis["breaks_if"]:
        st.markdown(f"• {b}")

    st.divider()
    ui.section_head("Save to thesis journal",
                    "Make it real. Set entry, target, stop. Track over time.")
    with st.form("thesis_form"):
        side = st.selectbox("Side", ["long", "short"], index=0)
        prof = st.selectbox(
            "Profile",
            list(profiles_mod.PROFILES.keys()),
            format_func=lambda k: profiles_mod.PROFILES[k]["name"],
            index=list(profiles_mod.PROFILES.keys()).index(best_pid),
        )
        ep_col, tp_col, sp_col, sz_col = st.columns(4)
        entry = ep_col.number_input("Entry price", value=float(quote["price"]), step=0.01)
        target = tp_col.number_input("Target price", value=float(quote["price"]) * 1.25, step=0.01)
        stop = sp_col.number_input("Stop", value=float(quote["price"]) * 0.85, step=0.01)
        size = sz_col.number_input("Position size (%)", value=3.0, step=0.5)
        bull_txt = st.text_area("Bull case", value="\n".join(f"- {b}" for b in thesis["bull"]), height=140)
        bear_txt = st.text_area("Bear case", value="\n".join(f"- {b}" for b in thesis["bear"]), height=120)
        breaks_txt = st.text_area("Breaks if", value="\n".join(f"- {b}" for b in thesis["breaks_if"]), height=100)
        km_col, kmt_col = st.columns(2)
        key_metric = km_col.text_input("Key metric to track", value="ROIC")
        key_target = kmt_col.number_input("Key metric target", value=15.0, step=0.5)
        save_thesis_btn = st.form_submit_button("💾 Save thesis", type="primary")
    if save_thesis_btn:
        tid = db.save_thesis({
            "symbol": ticker, "side": side, "profile": prof,
            "entry_price": entry, "target_price": target, "stop_price": stop,
            "position_size_pct": size,
            "bull_case": bull_txt, "bear_case": bear_txt, "breaks_if": breaks_txt,
            "key_metric": key_metric, "key_metric_target": key_target,
            "status": "open",
        })
        st.success(f"Thesis #{tid} saved. View in the Thesis Journal page.")

# ============================================================================
# TAB 6 — Deep-dive
# ============================================================================
with tab_deep:
    ui.section_head("Snapshot", "Today's read at a glance.")
    snap_cols = st.columns(6)
    snap_cols[0].metric("Price", f"${quote['price']:.2f}")
    snap_cols[1].metric("52w high", f"${quote['year_high']:.2f}" if quote.get("year_high") else "—")
    snap_cols[2].metric("52w low", f"${quote['year_low']:.2f}" if quote.get("year_low") else "—")
    snap_cols[3].metric("200 DMA", f"${quote['dma_200']:.2f}" if quote.get("dma_200") else "—")
    snap_cols[4].metric("Beta", f"{quote['beta']:.2f}" if quote.get("beta") else "—")
    snap_cols[5].metric("RSI 14", f"{quote['rsi_14']:.1f}" if quote.get("rsi_14") else "—")

    # ====== NEW: 12 strong-but-simple metrics in 3 panels ======
    extra = extra_metrics.compute_all(quote, tr, diag.get("price_history"))

    ui.section_head("Capital Return + Quality", "Where the cash goes. What the moat looks like.")
    if gloss.is_explain_mode():
        ui.explain_panel(
            "Six metrics that separate compounders from value traps: <b>Total Shareholder Yield</b> "
            "(divs + buybacks combined), <b>Buyback Yield</b> (per-share value growth), and <b>FCF Margin</b>. Compounders consistently return cash AND grow per-share value."
        )

    crq_cols = st.columns(3)
    for i, mid in enumerate(["tsy", "bb_yield", "capex_intensity", "roic_delta", "gm_delta", "net_cash"]):
        m = extra.get(mid, {"label": mid, "value": "—", "tone": "", "sub": ""})
        with crq_cols[i % 3]:
            ui.kpi_tile(m["label"], m["value"], m.get("sub", ""), m.get("tone", ""))

    ui.section_head("Momentum + Trend", "Where the price is, where it's going, and is it leading?")
    mom_cols = st.columns(3)
    for i, mid in enumerate(["from_52w_high", "returns", "rs_vs_spy"]):
        m = extra.get(mid, {"label": mid, "value": "—", "tone": "", "sub": ""})
        with mom_cols[i % 3]:
            ui.kpi_tile(m["label"], m["value"], m.get("sub", ""), m.get("tone", ""))

    ui.section_head("Earnings Quality + Safety", "How real are the earnings. Can the balance sheet survive a shock.")
    eq_cols = st.columns(3)
    runway_key = "runway" if "runway" in extra else "op_leverage"
    for i, mid in enumerate(["eps_streak", "forward_eps_growth", "interest_coverage", runway_key]):
        if mid not in extra:
            continue
        m = extra[mid]
        with eq_cols[i % 3]:
            ui.kpi_tile(m["label"], m["value"], m.get("sub", ""), m.get("tone", ""))

    st.divider()

    ui.section_head("Business", "What does this company do?")
    biz_l, biz_r = st.columns([2, 1])
    biz_l.markdown(quote.get("description") or "_No description available._")
    emp = quote.get("employees")
    biz_r.markdown(f"""
- **Sector**: {quote.get('sector', '—')}
- **Industry**: {quote.get('industry', '—')}
- **Country**: {quote.get('country', '—')}
- **CEO**: {quote.get('ceo', '—')}
- **Employees**: {f'{emp:,}' if emp else '—'}
- **Website**: {quote.get('website') or '—'}
""")

    insider_df = diag.get("insider_df")
    if insider_df is not None and not insider_df.empty:
        ui.section_head("Insider transactions", "Buys and sells in the last few months.")
        i_cols = st.columns(4)
        i_cols[0].metric("Buys (6mo)", quote.get("insider_buys_6mo", 0))
        i_cols[1].metric("Sells (6mo)", quote.get("insider_sells_6mo", 0))
        i_cols[2].metric("Net $", ui.fmt_money(quote.get("insider_net_value", 0)),
                         "Cluster ✅" if quote.get("insider_cluster_buy") else None)
        i_cols[3].metric("Last buy", quote.get("insider_last_buy") or "—")
        st.dataframe(insider_df, use_container_width=True, hide_index=True, height=200)

    ui.section_head("Analyst consensus", "What the sell side says.")
    a_cols = st.columns(4)
    a_cols[0].metric("Consensus", (quote.get("recommend") or "—").upper())
    a_cols[1].metric(
        "Median PT",
        f"${quote['target_median']:.2f}" if quote.get("target_median") else "—",
        f"{((quote['target_median'] / quote['price']) - 1) * 100:+.1f}%" if quote.get("target_median") else None,
    )
    a_cols[2].metric("High PT", f"${quote['target_high']:.2f}" if quote.get("target_high") else "—")
    a_cols[3].metric("# Analysts", quote.get("n_analysts", "—"))

    ui.section_head("Price chart", "Full history with moving averages.")
    full = indices_mod.get_full_history(ticker, period="max")
    if not full.get("error"):
        overlays = [
            ("50 DMA", full["dma_50"], "#9a6500", "dot"),
            ("200 DMA", full["dma_200"], "#8a1818", "solid"),
        ]
        fig = ui.interactive_chart(
            full["dates"], full["closes"],
            title=f"{ticker} price history",
            color="#1e3a8a",
            dma_overlays=overlays,
            is_currency=True,
            height=520,
        )
        st.plotly_chart(fig, use_container_width=True, config=ui.chart_config())
    else:
        hist = diag.get("price_history")
        if hist is not None and not hist.empty:
            dates = list(hist.index)
            closes = [float(v) for v in hist["Close"].tolist()]
            ma50 = [float(v) if v == v else None for v in hist["Close"].rolling(50).mean().tolist()]
            ma200 = [float(v) if v == v else None for v in hist["Close"].rolling(200).mean().tolist()]
            fig = ui.interactive_chart(
                dates, closes,
                title=f"{ticker} price",
                color="#1e3a8a",
                dma_overlays=[("50 DMA", ma50, "#9a6500", "dot"),
                              ("200 DMA", ma200, "#8a1818", "solid")],
                is_currency=True,
                height=480,
            )
            st.plotly_chart(fig, use_container_width=True, config=ui.chart_config())

# ============================================================================
# TAB — Earnings
# ============================================================================
with tab_earn:
    next_e = quote.get("next_earnings")
    ui.section_head(f"Next earnings: {next_e or 'unknown'}", "Recent earnings history below.")

    hist_e = data.get_earnings_history(ticker, quarters=8)
    if not hist_e.empty:
        import math
        cols_to_show = [c for c in ["date", "eps_est", "eps_act", "eps_surp_pct"] if c in hist_e.columns]
        disp_e = hist_e[cols_to_show].copy()
        if "date" in disp_e.columns:
            disp_e["date"] = disp_e["date"].dt.strftime("%Y-%m-%d")
        if "eps_surp_pct" in disp_e.columns:
            disp_e["eps_surp_pct"] = disp_e["eps_surp_pct"].apply(
                lambda x: f"{x:+.1f}%" if (x is not None and not (isinstance(x, float) and math.isnan(x))) else "—"
            )
        st.dataframe(disp_e, use_container_width=True, hide_index=True)

    ui.section_head("External earnings calendars", "Cross-reference dates and consensus.")
    e_cols = st.columns(4)
    e_cols[0].markdown(f"[Yahoo](https://finance.yahoo.com/quote/{ticker}/calendar)")
    e_cols[1].markdown(f"[Earnings Whispers](https://www.earningswhispers.com/stocks/{ticker})")
    e_cols[2].markdown(f"[Estimize](https://www.estimize.com/{ticker.lower()})")
    e_cols[3].markdown(f"[Zacks](https://www.zacks.com/stock/research/{ticker}/earnings-announcements)")

# ============================================================================
# TAB — Sources
# ============================================================================
with tab_sources:
    ui.section_head("Verify externally", "Don't trust one source. Especially for high-stakes decisions.")

    t = ticker; tl = ticker.lower()
    src_groups = [
        ("Price / quote", [
            ("Yahoo Finance", f"https://finance.yahoo.com/quote/{t}"),
            ("TradingView", f"https://www.tradingview.com/symbols/{t}/"),
            ("Finviz", f"https://finviz.com/quote.ashx?t={t}"),
        ]),
        ("Fundamentals", [
            ("Stock Analysis", f"https://stockanalysis.com/stocks/{tl}/"),
            ("Macrotrends", f"https://www.macrotrends.net/stocks/charts/{t}/{tl}/"),
            ("TIKR", f"https://app.tikr.com/search?s={t}"),
        ]),
        ("Filings + insiders", [
            ("SEC EDGAR", f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={t}"),
            ("OpenInsider", f"http://openinsider.com/screener?s={t}"),
        ]),
        ("News", [
            ("Yahoo news", f"https://finance.yahoo.com/quote/{t}/news"),
            ("Seeking Alpha", f"https://seekingalpha.com/symbol/{t}/news"),
        ]),
        ("Charts + TA", [
            ("TradingView chart", f"https://www.tradingview.com/chart/?symbol={t}"),
            ("StockCharts", f"https://stockcharts.com/h-sc/ui?s={t}"),
        ]),
    ]
    s_cols = st.columns(2)
    for i, (group, items) in enumerate(src_groups):
        with s_cols[i % 2]:
            st.markdown(f"**{group}**")
            for label, url in items:
                st.markdown(f"• [{label}]({url})")
            st.write("")

# ----- Perf timing footer (subtle) -----
timings = diag.get("timings", {})
if timings:
    st.caption(diagnose_mod.format_timings(timings))

# ----- Sidebar -----
with st.sidebar:
    st.markdown("### Watchlist")
    wl_detail = db.get_watchlist_detailed()
    if wl_detail:
        for row in wl_detail:
            sym = row["symbol"]
            added_px = row.get("added_price")
            since_str = ""
            if added_px:
                cur = data.get_last_price(sym)
                if cur:
                    chg = (cur / added_px) - 1
                    color = "#0a5f3c" if chg >= 0 else "#8a1818"
                    since_str = (f"<span style='color:{color};font-size:11px'>"
                                 f"{chg*100:+.1f}% since added (${added_px:.2f}→${cur:.2f})</span>")
            wl_row = st.columns([3, 1])
            if wl_row[0].button(sym, key=f"sb_{sym}", use_container_width=True):
                st.session_state.active_ticker = sym
                st.rerun()
            if wl_row[1].button("✕", key=f"sb_rm_{sym}"):
                db.remove_from_watchlist(sym)
                st.rerun()
            if since_str:
                st.markdown(since_str, unsafe_allow_html=True)
    else:
        st.caption("Empty.")
    st.divider()
    st.markdown("### Recent diagnoses")
    saved = db.list_profile_scorecards_summary()
    seen_syms = set()
    for s in saved[:50]:
        if s["symbol"] in seen_syms:
            continue
        seen_syms.add(s["symbol"])
        if len(seen_syms) > 10:
            break
        if st.button(s["symbol"], key=f"sv_{s['symbol']}", use_container_width=True):
            st.session_state.active_ticker = s["symbol"]
            st.rerun()
