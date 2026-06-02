"""Macro Pro — major indices live, macro regime tiles, full macro reference.

Stripped of non-macro indicators (those live in Stock Pro). Added live indices
panel at top covering equities, rates, FX, commodities, crypto.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import data, indicators, indices
from lib import ui
from lib import glossary as gloss
from lib import sidebar_chat

st.set_page_config(page_title="Macro Pro", page_icon="📊", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()
sidebar_chat.render_chat("macro_pro")

ui.page_header(
    title="Macro Pro",
    subtitle="Live indices, macro regime, and a 20-indicator macro reference. The 30-second market read.",
    icon="📊",
    live=True,
)

# ---- Global chart range selector (applies to all sparklines on this page) ----
rc1, rc2 = st.columns([1, 5])
with rc1:
    if "chart_range" not in st.session_state:
        st.session_state.chart_range = "1Y"
    selected_range = st.radio(
        "Chart range",
        options=indices.RANGE_OPTIONS,
        index=indices.RANGE_OPTIONS.index(st.session_state.chart_range),
        horizontal=True,
        label_visibility="collapsed",
        key="chart_range_radio",
    )
    st.session_state.chart_range = selected_range
with rc2:
    st.caption(f"Charts and the **{selected_range}** performance on each card reflect the selected range. Day change, YTD, and vs-200DMA always use full data.")

st.write("")

# ---- Focused chart state ----
if "focused_chart" not in st.session_state:
    st.session_state.focused_chart = None  # tuple of (kind, identifier, display_name) or None

def _set_focus(kind, ident, name):
    """Toggle focus. Click same tile again = close."""
    if st.session_state.focused_chart and st.session_state.focused_chart[1] == ident:
        st.session_state.focused_chart = None
    else:
        st.session_state.focused_chart = (kind, ident, name)


def _render_focused_chart():
    """Render the focused full interactive chart above the indices grid."""
    if not st.session_state.focused_chart:
        return
    kind, ident, name = st.session_state.focused_chart

    # Scroll to chart on open — Streamlit reruns don't auto-scroll to new content
    st.markdown('<div id="focused-chart-anchor"></div>', unsafe_allow_html=True)
    st.components.v1.html(
        '<script>document.getElementById("focused-chart-anchor")'
        '?.scrollIntoView({behavior:"smooth",block:"start"});</script>',
        height=0,
    )

    with st.container(border=True):
        head_l, head_r = st.columns([5, 1])
        head_l.markdown(f"### 📈 {name} interactive chart")
        if head_r.button("✕ Close", key="close_focus", use_container_width=True):
            st.session_state.focused_chart = None
            st.rerun()
        if kind == "index":
            data_full = indices.get_full_history(ident, period="max")
            if data_full.get("error"):
                st.warning(f"Couldn't load history: {data_full['error']}")
                return
            overlays = []
            if any(v is not None for v in data_full["dma_50"]):
                overlays.append(("50 DMA", data_full["dma_50"], "#9a6500", "dot"))
            if any(v is not None for v in data_full["dma_200"]):
                overlays.append(("200 DMA", data_full["dma_200"], "#8a1818", "solid"))
            # Format hint: figure out from INDICES tuple
            fmt = next((h for sym, _, _, h in indices.INDICES if sym == ident), "index")
            is_curr = fmt in ("price",)
            fig = ui.interactive_chart(
                data_full["dates"], data_full["closes"],
                title=f"{name} ({ident})",
                color="#1e3a8a",
                dma_overlays=overlays if fmt in ("price", "index") else None,
                is_currency=is_curr,
                height=620,
            )
            st.plotly_chart(fig, use_container_width=True, config=ui.chart_config())
        elif kind == "fred":
            data_full = indices.get_fred_full_history(ident, years=50)
            if data_full.get("error"):
                st.warning(f"Couldn't load history: {data_full['error']}")
                return
            fig = ui.interactive_chart(
                data_full["dates"], data_full["values"],
                title=f"{name} (FRED: {ident})",
                color="#1e3a8a",
                is_currency=False,
                height=620,
            )
            st.plotly_chart(fig, use_container_width=True, config=ui.chart_config())


# Render focused chart at the top of the page (sticky-ish for visibility)
_render_focused_chart()

# ============================================================================
# SECTION 1 — Major indices live (top of page)
# ============================================================================
ui.section_head("Major indices today", "Equities, rates, FX, commodities, crypto. Cached 5 minutes.")
st.caption(ui.freshness_note())

if gloss.is_explain_mode():
    ui.explain_panel(
        "These are the markets to glance at every morning. <b>S&P 500</b> is the US market. "
        "<b>VIX</b> is fear. <b>10Y Treasury</b> drives mortgage rates and stock multiples. "
        "<b>DXY</b> is the dollar. <b>Gold</b> and <b>Oil</b> are inflation / cycle reads. "
        "<b>Bitcoin</b> is liquidity and risk-on/off."
    )

# Group by category
category_order = [("equity", "📈 Equity"), ("volatility", "💥 Volatility"),
                  ("rates", "📉 Rates"), ("fx", "💱 FX"),
                  ("commodity", "🛢️ Commodities"), ("crypto", "₿ Crypto")]

for cat_id, cat_label in category_order:
    snaps = indices.all_snapshots(categories=[cat_id])
    if not snaps:
        continue
    st.markdown(f"**{cat_label}**")
    cols = st.columns(min(len(snaps), 5))
    for i, snap in enumerate(snaps):
        col = cols[i % len(cols)]
        with col:
            if snap.get("error"):
                ui.kpi_tile(snap.get("name", "?"), "—", "data unavailable")
                continue
            level = indices.fmt_index_level(snap["symbol"], snap["level"], snap["fmt_hint"])
            day = snap.get("day_pct")
            day_str = ui.fmt_delta_pct(day)
            tone = ui.tone_from_pct(day)
            ytd = snap.get("ytd_pct")
            ytd_str = f"YTD {ui.fmt_delta_pct(ytd)}" if ytd is not None else ""
            vs200 = snap.get("vs_200")
            vs200_str = f" • vs 200DMA {ui.fmt_delta_pct(vs200)}" if vs200 is not None else ""
            spark = indices.get_sparkline_series(snap["symbol"], selected_range)
            # Performance over the selected chart range (first→last close of the
            # range series). Skipped for YTD since that's already shown below.
            range_str = ""
            if selected_range != "YTD" and spark and len(spark) >= 2 and spark[0]:
                range_ret = (spark[-1] / spark[0]) - 1
                range_str = f"{selected_range} {ui.fmt_delta_pct(range_ret)} • "
            sub = f"{day_str} today • {range_str}{ytd_str}{vs200_str}"
            spark_color = "#0a5f3c" if (spark and spark[-1] >= spark[0]) else "#8a1818"
            tile_html = ui.kpi_tile_with_spark(
                snap["name"], level, sub, tone, spark, spark_color
            )
            st.markdown(tile_html, unsafe_allow_html=True)
            if st.button("📈 Full chart", key=f"chart_{snap['symbol']}", use_container_width=True):
                _set_focus("index", snap["symbol"], snap["name"])
                st.rerun()
    st.write("")

st.divider()

# ============================================================================
# SECTION 2 — Macro regime quick read
# ============================================================================
ui.section_head("Macro regime read", "Risk-on vs risk-off, in one row. Live from FRED, updated hourly.")

if gloss.is_explain_mode():
    ui.explain_panel(
        "Each tile is a key macro condition graded green/yellow/red. "
        "When most are green: risk-on, lean into stocks. "
        "When most are red: risk-off, defensive positioning. "
        "Yellow yields are mixed signals to monitor."
    )


def classify(value, thresholds, good):
    def in_range(v, r):
        lo, hi = r
        if lo is not None and v < lo: return False
        if hi is not None and v > hi: return False
        return True
    if in_range(value, thresholds["green"]): return ("green", "🟢")
    if in_range(value, thresholds["amber"]): return ("amber", "🟡")
    if in_range(value, thresholds["red"]): return ("red", "🔴")
    return ("gray", "⚪")


regime_cols = st.columns(len(indicators.REGIME_TILES))
for col, tile in zip(regime_cols, indicators.REGIME_TILES):
    series = data.get_fred_series(tile["fred_id"])
    if not series or "error" in series:
        with col:
            ui.kpi_tile(tile["label"], "—", "FRED unavailable")
        continue
    value = series["value"]
    display_val = value
    # Pull enough history for the chart window AND for YoY calc if needed
    fetch_years = indices.RANGE_TO_FRED_FETCH_YEARS.get(selected_range, 2)
    if tile.get("yoy"):
        fetch_years = max(fetch_years, 2)  # need 12mo lookback
    hist = data.get_fred_history(tile["fred_id"], years=fetch_years)
    if tile.get("yoy"):
        if not hist.empty:
            now = hist.iloc[-1]
            yo_cutoff = now["date"] - pd.DateOffset(months=12)
            past = hist[hist["date"] <= yo_cutoff]
            if not past.empty:
                past_v = past.iloc[-1]["value"]
                if past_v:
                    display_val = (value / past_v - 1) * 100
    color, emoji = classify(display_val, tile["thresholds"], tile["good"])
    tone = "pos" if color == "green" else ("neg" if color == "red" else "warn")
    if tile.get("yoy"):
        val_str = f"{display_val:.2f}%"
    elif "OAS" in tile["label"]:
        val_str = f"{value:.0f} bps"
    elif tile["label"].startswith("VIX") or "Volatility" in tile["label"]:
        val_str = f"{value:.1f}"
    else:
        val_str = f"{value:.2f}"
    # Build sparkline using only the selected range
    spark_vals = []
    if not hist.empty:
        spark_hist = hist.sort_values("date")
        cutoff = indices.fred_cutoff_for_range(selected_range)
        if cutoff is not None:
            spark_hist = spark_hist[spark_hist["date"] >= cutoff]
        if spark_hist.empty:
            spark_hist = hist.sort_values("date").tail(8)
        vals = spark_hist["value"].tolist()
        sample_n = min(60, len(vals))
        step = max(1, len(vals) // sample_n)
        spark_vals = [float(v) for v in vals[::step] if v is not None]
    spark_color = "#0a5f3c" if (spark_vals and spark_vals[-1] >= spark_vals[0]) else "#8a1818"
    # Invert color for "good=low" indicators (rising = bad)
    if tile.get("good") == "low" and spark_vals:
        spark_color = "#8a1818" if spark_vals[-1] > spark_vals[0] else "#0a5f3c"
    with col:
        st.markdown(
            ui.kpi_tile_with_spark(
                f"{emoji} {tile['label']}", val_str, tile["explain"][:55],
                tone, spark_vals, spark_color
            ),
            unsafe_allow_html=True,
        )

st.divider()

# ============================================================================
# SECTION 3 — Macro indicator reference (macros only)
# ============================================================================
ui.section_head("Macro indicator reference", "20 macro indicators with target ranges and how to read them.")

if gloss.is_explain_mode():
    ui.explain_panel(
        "Each card explains one macro indicator: what it measures, how to read it, where to find it, "
        "and a pro tip. Use these to build your mental model of where the economy is in the cycle."
    )

# Filter to MACROS ONLY (per user request)
macro_indicators = [i for i in indicators.INDICATORS if i["c"] == "macro" or i["c"] == "sentiment" and "fred_id" in i]
# Also include VIX which is tagged 'sentiment' but is macro in spirit
# Actually filter strictly macro
macro_only = [i for i in indicators.INDICATORS if i["c"] == "macro"]

f_col1, f_col2 = st.columns([3, 1])
search_q = f_col1.text_input(
    "Search macro indicators",
    placeholder="Search (yield curve, CPI, ISM, oil...)",
    label_visibility="collapsed",
).strip().lower()

filtered = macro_only
if search_q:
    filtered = [i for i in macro_only if search_q in i["n"].lower() or search_q in i["m"].lower()
                or search_q in (i.get("r") or "").lower()]

st.caption(f"Showing {len(filtered)} of {len(macro_only)} macro indicators")


def score_indicator(ind):
    thresholds = ind.get("thresholds")
    fred_id = ind.get("fred_id")
    if not thresholds or not fred_id:
        return (None, "", None)
    series = data.get_fred_series(fred_id)
    if not series or "value" not in series:
        return (None, "", None)
    val = series["value"]
    display_val = val
    if ind.get("yoy"):
        hist = data.get_fred_history(fred_id, years=2)
        if not hist.empty:
            now = hist.iloc[-1]
            yo_cutoff = now["date"] - pd.DateOffset(months=12)
            past = hist[hist["date"] <= yo_cutoff]
            if not past.empty:
                past_v = past.iloc[-1]["value"]
                if past_v:
                    display_val = (val / past_v - 1) * 100
    def in_range(v, r):
        lo, hi = r
        if lo is not None and v < lo: return False
        if hi is not None and v > hi: return False
        return True
    if in_range(display_val, thresholds["green"]): return ("🟢", "PASS", display_val)
    if in_range(display_val, thresholds["amber"]): return ("🟡", "NEUTRAL", display_val)
    if in_range(display_val, thresholds["red"]): return ("🔴", "FAIL", display_val)
    return ("⚪", "—", display_val)


ROW_SIZE = 3
for row_start in range(0, len(filtered), ROW_SIZE):
    row = filtered[row_start : row_start + ROW_SIZE]
    cols = st.columns(ROW_SIZE)
    for ind, col in zip(row, cols):
        with col:
            with st.container(border=True):
                badge_emoji, badge_label, display_val = score_indicator(ind)
                tcol1, tcol2 = st.columns([3, 1])
                tcol1.markdown(f"**{ind['n']}**")
                if badge_emoji:
                    tcol2.markdown(
                        f"<div style='text-align:right;font-size:11px;color:#3d3d3d;line-height:1.4'>"
                        f"{badge_emoji} <b>{badge_label}</b></div>",
                        unsafe_allow_html=True,
                    )

                if ind.get("fred_id"):
                    series = data.get_fred_series(ind["fred_id"])
                    if series and "value" in series:
                        val = series["value"]
                        if ind.get("yoy") and display_val is not None:
                            st.caption(f"Current YoY: **{display_val:.2f}%** ({series['trend']}, {series['date']})")
                        else:
                            st.caption(f"Current: **{val:.2f}** ({series['trend']}, {series['date']})")

                    # Sparkline: user-selected range. Pull extra for YoY transform.
                    card_fetch_years = indices.RANGE_TO_FRED_FETCH_YEARS.get(selected_range, 2)
                    if ind.get("yoy"):
                        card_fetch_years = max(card_fetch_years, 2)
                    hist = data.get_fred_history(ind["fred_id"], years=card_fetch_years)
                    if not hist.empty:
                        card_cutoff = indices.fred_cutoff_for_range(selected_range)
                        if ind.get("yoy"):
                            spark_df = hist.copy().sort_values("date").reset_index(drop=True)
                            spark_df["yoy"] = spark_df["value"].pct_change(periods=12) * 100
                            spark_df = spark_df.dropna(subset=["yoy"])
                            if card_cutoff is not None:
                                spark_df = spark_df[spark_df["date"] >= card_cutoff]
                            raw = spark_df["yoy"].tolist()
                        else:
                            spark_df = hist.sort_values("date")
                            if card_cutoff is not None:
                                spark_df = spark_df[spark_df["date"] >= card_cutoff]
                            raw = spark_df["value"].tolist()
                        sample_n = min(60, len(raw))
                        step = max(1, len(raw) // sample_n)
                        spark_vals = [float(v) for v in raw[::step] if v is not None]
                        if spark_vals:
                            # Direction-aware color (account for good=low indicators)
                            rising = spark_vals[-1] >= spark_vals[0]
                            if ind.get("good") == "low":
                                color = "#8a1818" if rising else "#0a5f3c"
                            else:
                                color = "#0a5f3c" if rising else "#8a1818"
                            st.markdown(
                                ui.sparkline_svg(spark_vals, color=color,
                                                 width=320, height=44, fill=True),
                                unsafe_allow_html=True,
                            )

                st.caption(ind["m"])

                # Progressive disclosure: show target range + "how to read" on the card
                # face so you don't have to click 20 expanders to scan. Pro tip + source
                # stay in the expander (less essential).
                if ind.get("tgt"):
                    st.markdown(f"<span style='font-size:12px;color:var(--text-faint)'>Target: <b>{ind['tgt']}</b></span>",
                                unsafe_allow_html=True)
                if ind.get("r"):
                    st.caption(f"💡 {ind['r'][:120]}")

                if ind.get("fred_id"):
                    if st.button("📈 Full chart", key=f"ind_chart_{ind['fred_id']}_{ind['n'][:8]}", use_container_width=True):
                        _set_focus("fred", ind["fred_id"], ind["n"])
                        st.rerun()

                with st.expander("More"):
                    if gloss.is_explain_mode():
                        for term, entry in gloss.GLOSSARY.items():
                            if term.lower() in ind["n"].lower():
                                st.markdown(f"**In plain English:** {entry['plain']}")
                                break
                    st.markdown(f"**Where to find it**: {ind.get('src', '—')}")
                    st.markdown(f"**Pro tip**: {ind.get('tip', '—')}")
                    if ind.get("tgt"):
                        st.markdown(f"**Target ranges**: {ind['tgt']}")
                    if ind.get("link"):
                        st.markdown(f"[Open source ↗]({ind['link']})")

# ============================================================================
# Sidebar — combos / regime checklists
# ============================================================================
with st.sidebar:
    st.markdown("### Quick checklists")
    combos = [
        {"n": "Cycle bottom check", "items": [
            "HY OAS over 800 bps",
            "VIX over 35",
            "AAII bears over 50%",
            "% of S&P above 200 DMA under 20%",
        ]},
        {"n": "Pre-buy market check", "items": [
            "S&P above 200 DMA",
            "EPS revisions trending up",
            "Credit spreads tight",
            "VIX under 25",
        ]},
        {"n": "Late-cycle warnings", "items": [
            "Yield curve un-inverting (steepening)",
            "Margin debt at peak",
            "AAII bulls over 50%",
            "Real yields rising fast",
        ]},
        {"n": "Cyclical entry signal", "items": [
            "ISM Mfg trough under 45",
            "Copper turning up",
            "HY spreads peaking",
            "Industrials breaking out vs S&P",
        ]},
    ]
    for combo in combos:
        with st.expander(combo["n"]):
            for item in combo["items"]:
                st.markdown(f"• {item}")

    st.divider()
    st.markdown("### Refresh")
    if st.button("🔄 Clear cache", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
