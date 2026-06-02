"""Discover — find stocks before you analyze them.

Style-specific Finviz screens. One click sends a hit to Stock Pro.
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from lib import screener, db
from lib import ui
from lib import glossary as gloss
from lib import sidebar_chat

st.set_page_config(page_title="Discover", page_icon="🔭", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()


def _discover_context() -> str:
    sel = st.session_state.get("chart_range_radio") or ""
    selected_style = st.session_state.get("discover_style", "")
    parts = ["User is on the Discover page browsing stock screens."]
    if selected_style:
        parts.append(f"Current screen: **{selected_style}** ({screener.STYLE_LABELS.get(selected_style, selected_style)}).")
    return "\n".join(parts)


sidebar_chat.render_chat("discover", _discover_context)

ui.page_header(
    title="Discover",
    subtitle="Hunt for ideas across ten investment styles. Then send the best to Stock Pro for diagnosis.",
    icon="🔭",
    live=True,
)

if gloss.is_explain_mode():
    ui.explain_panel(
        "The hard part of investing isn't analyzing a stock you already know about. "
        "It's <b>finding</b> the right stocks to analyze. This page runs live Finviz screens for ten different "
        "investment styles. Pick the style that matches your approach, find a few interesting names, "
        "then send the best one to Stock Pro for the full diagnosis."
    )

# ============================================================================
# SECTION 1 — Pick a style
# ============================================================================
ui.section_head("Pick a style", "Each style is a different way to find stocks.")

sc1, sc2 = st.columns([3, 1])
selected = sc1.selectbox(
    "Investment style",
    options=screener.available_styles(),
    format_func=lambda k: screener.STYLE_LABELS.get(k, k),
    label_visibility="collapsed",
)
limit = sc2.number_input(
    "Depth", min_value=25, max_value=300, value=100, step=25,
    help="How deep to pull per sort order. Results are unioned across 5 sort orders "
         "(the style metric + market cap, ROE, 1-yr performance, sales growth), so the "
         "final list spans the whole alphabet and is much larger than this number. "
         "Higher = more complete but slower (cached 30 min after the first run).",
)

st.caption(screener.STYLE_DESCRIPTIONS.get(selected, ""))

with st.expander("Show Finviz filters used for this screen"):
    filt = screener.STYLE_FILTERS[selected]
    for k, v in filt.items():
        st.markdown(f"• **{k}**: `{v}`")

# Run screen (pulls across multiple sort orders to avoid alphabetical bias — slower but deep)
with st.spinner(f"Running {screener.STYLE_LABELS[selected]} screen across multiple sort orders…"):
    df = screener.run_combined_screen(selected, limit=limit)

# For foreign_chokepoint style, ALSO pull the curated allowlist of known
# foreign chokepoints that Finviz doesn't reliably surface (OTC pinks, micro caps)
if selected == "foreign_chokepoint":
    with st.spinner("Pulling curated allowlist of foreign chokepoints (Sivers/ASML/AIXG/Soitec…)..."):
        allowlist_df = screener.get_allowlist_quotes()
    if not allowlist_df.empty:
        ui.section_head(
            f"Curated foreign chokepoint allowlist ({len(allowlist_df)} names)",
            "Hand-picked critical foreign suppliers Finviz's USA filter would miss.",
        )
        if gloss.is_explain_mode():
            ui.explain_panel(
                "These tickers are known photonics/semicap/foundry chokepoints not always reachable "
                "via Finviz screens (OTC pinks, foreign primary listings, micro caps). "
                "Sivers Semiconductors (SIVE.ST) is the headliner — Swedish InP photonic IC company "
                "in the heart of the AI optics bottleneck. Edit FOREIGN_CHOKEPOINT_ALLOWLIST in "
                "lib/screener.py to add more names as you find them."
            )
        # Format the allowlist columns
        adisp = allowlist_df.copy()
        if "Market Cap" in adisp.columns:
            adisp["Market Cap"] = adisp["Market Cap"].apply(
                lambda v: ui.fmt_money(v) if isinstance(v, (int, float)) and v == v else "—"
            )
        if "Price" in adisp.columns:
            adisp["Price"] = adisp["Price"].apply(
                lambda v: f"${v:.2f}" if isinstance(v, (int, float)) and v == v else "—"
            )
        for pct_col in ("ROE", "Gross M", "Oper M"):
            if pct_col in adisp.columns:
                adisp[pct_col] = adisp[pct_col].apply(
                    lambda v: f"{v*100:+.1f}%" if isinstance(v, (int, float)) and v == v and abs(v) < 5 else (f"{v:.2f}" if isinstance(v, (int, float)) and v == v else "—")
                )
        show_cols = [c for c in ["Ticker","Company","Country","Sector","Market Cap","P/E","Forward P/E","PEG","ROE","Gross M","Price","Note"] if c in adisp.columns]
        st.dataframe(adisp[show_cols], use_container_width=True, hide_index=True, height=520)
        st.divider()

if df is None or df.empty:
    # Contextual empty state — distinguish why there are no results.
    style_label = screener.STYLE_LABELS.get(selected, selected)
    filt = screener.STYLE_FILTERS.get(selected, {})
    tightest = list(filt.keys())[:3]
    ui.empty_state(
        f"<b>0 matches</b> for the <b>{style_label}</b> screen right now.<br><br>"
        f"This can happen if (a) Finviz didn't respond (click Reload), "
        f"(b) the filters are too strict for the current market — try a different style, or "
        f"(c) no stocks genuinely pass today (normal for niche screens like Cigar Butt or Insider Buys)."
        f"<br><br>Strictest filters: <code>{', '.join(tightest)}</code>"
    )
else:
    # Add Fit score ranked by style philosophy strength
    df = screener.add_fit_score(df, selected)

    # "New this week" — flag tickers that weren't in the previous run of this screen.
    prev_set, prev_run = db.get_prev_screen_tickers(selected)
    cur_tickers = df["Ticker"].tolist() if "Ticker" in df.columns else []
    new_set = (set(cur_tickers) - prev_set) if prev_set else set()
    if "Ticker" in df.columns:
        df.insert(0, "New", df["Ticker"].apply(lambda t: "🆕" if t in new_set else ""))
        db.save_screen_tickers(selected, cur_tickers)

    new_note = ""
    if prev_set:
        when = (prev_run or "")[:10]
        new_note = (f" · **{len(new_set)} new** since last run ({when})" if new_set
                    else f" · no new entrants since {when}")
    ui.section_head(
        f"{len(df)} matches, ranked by fit strength",
        f"Top of the list = strongest fit for {screener.STYLE_LABELS[selected]}. "
        f"🆕 = newly in this screen vs your last visit.{new_note} Hover any column header for a plain-English explanation.",
    )

    display_cols = [c for c in [
        "New", "Ticker", "Fit", "Rating", "Company", "Sector", "Market Cap",
        "P/E", "Forward P/E", "PEG", "P/B", "P/FCF",
        "ROE", "ROIC", "Oper M", "Gross M", "Debt/Eq",
        "EPS This Y", "EPS Next 5Y", "Price", "Change", "Strengths",
    ] if c in df.columns]
    disp = df[display_cols].copy()

    # Format Market Cap with TH/M/B/T (always 2 decimals)
    if "Market Cap" in disp.columns:
        disp["Market Cap"] = disp["Market Cap"].apply(
            lambda v: ui.fmt_money(v) if isinstance(v, (int, float)) and v == v else "—"
        )
    if "Price" in disp.columns:
        disp["Price"] = disp["Price"].apply(
            lambda v: f"${v:.2f}" if isinstance(v, (int, float)) and v == v else "—"
        )
    if "Change" in disp.columns:
        disp["Change"] = disp["Change"].apply(
            lambda v: f"{v*100:+.2f}%" if isinstance(v, (int, float)) and v == v else "—"
        )
    for pct_col in ("ROE", "ROIC", "Oper M", "Gross M", "EPS This Y", "EPS Next 5Y"):
        if pct_col in disp.columns:
            disp[pct_col] = disp[pct_col].apply(
                lambda v: f"{v*100:+.2f}%" if isinstance(v, (int, float)) and v == v and abs(v) < 5
                else (f"{v:+.2f}%" if isinstance(v, (int, float)) and v == v else "—")
            )

    # Glass table columns + rows (replaces st.dataframe for the aurora-glass look).
    _fmt_safe = lambda v: str(v) if v is not None and not (isinstance(v, float) and v != v) else "—"
    _gt_cols = []
    for c in display_cols:
        align = "num" if c in ("Fit", "P/E", "Forward P/E", "PEG", "P/B", "P/FCF",
                                "Market Cap", "Debt/Eq", "Price", "Change",
                                "ROE", "ROIC", "Oper M", "Gross M",
                                "EPS This Y", "EPS Next 5Y") else ""
        cls = "sym" if c == "Ticker" else ""
        _gt_cols.append({"key": c, "label": c, "align": align, "cls": cls})

    _gt_rows = []
    for _, row in disp.iterrows():
        rd = {}
        for c in display_cols:
            v = row.get(c)
            if c == "New" and v == "🆕":
                rd[c] = '<span class="new-badge">new</span>'
            elif c == "Rating":
                r = str(v).strip() if v else ""
                pcls = "p-s" if r == "Strong" else ("p-o" if r == "Solid" else "p-w")
                rd[c] = f'<span class="pill {pcls}">{r}</span>' if r and r != "—" else "—"
            else:
                rd[c] = _fmt_safe(v)
        _gt_rows.append(rd)

    ui.glass_table(_gt_cols, _gt_rows, max_height=620)

    ui.section_head("Send to Stock Pro", "Picks land in your watchlist and become the active ticker.")
    if "Ticker" in df.columns:
        # Build (ticker, label) pairs — label includes company name when available
        pairs = []
        for _, row in df.head(6).iterrows():
            t = row["Ticker"]
            co = row.get("Company") if "Company" in df.columns else None
            label = f"{t} — {co[:22]}" if (co and isinstance(co, str)) else t
            pairs.append((t, label))
        send_cols = st.columns(min(6, len(pairs)))
        for i, (t, label) in enumerate(pairs):
            if send_cols[i].button(label, use_container_width=True, key=f"send_{t}"):
                st.session_state.active_ticker = t
                db.add_to_watchlist(t)
                st.success(f"Added {t} to watchlist.")
                st.page_link("pages/2_Stock_Pro.py", label=f"→ Open Stock Pro with {t}", icon="📈")

st.divider()

# ============================================================================
# SECTION 2 — Find overlap between two styles
# ============================================================================
ui.section_head("Find overlap between two styles",
                "Stocks that show up in two screens are double-confirmed.")

if gloss.is_explain_mode():
    ui.explain_panel(
        "Each screen has its own bias. A quality-compounder screen finds great businesses but "
        "doesn't care about price. A deep-value screen finds cheap stocks but doesn't care about quality. "
        "Stocks that appear in <b>both</b> a quality screen AND a value screen are the goldilocks zone: "
        "good business at a good price. That's the alpha."
    )

cmp1, cmp2 = st.columns(2)
sty_a = cmp1.selectbox("Style A", options=screener.available_styles(),
                       format_func=lambda k: screener.STYLE_LABELS.get(k, k),
                       index=screener.available_styles().index("quality_compounder"),
                       key="cmp_a")
sty_b = cmp2.selectbox("Style B", options=screener.available_styles(),
                       format_func=lambda k: screener.STYLE_LABELS.get(k, k),
                       index=screener.available_styles().index("insider_buys"),
                       key="cmp_b")

if st.button("Find overlap", type="primary"):
    with st.spinner(f"Running {sty_a} + {sty_b}..."):
        df_a = screener.run_screen(sty_a, "overview", limit=100)
        df_b = screener.run_screen(sty_b, "overview", limit=100)

    if df_a.empty or df_b.empty:
        st.warning("One of the screens returned no results.")
    else:
        set_a = set(df_a["Ticker"].tolist()) if "Ticker" in df_a.columns else set()
        set_b = set(df_b["Ticker"].tolist()) if "Ticker" in df_b.columns else set()
        overlap = set_a & set_b
        if overlap:
            # Build ticker → company map from either df
            ticker_to_company = {}
            for _df in (df_a, df_b):
                if "Company" in _df.columns:
                    for _, row in _df.iterrows():
                        if row["Ticker"] in overlap and row["Ticker"] not in ticker_to_company:
                            ticker_to_company[row["Ticker"]] = row.get("Company", "")
            st.success(f"**{len(overlap)} stocks** appear in both screens. Double-confirmed candidates:")
            # Show as table with company names
            import pandas as pd
            overlap_rows = [{"Ticker": t, "Company": ticker_to_company.get(t, "")} for t in sorted(overlap)]
            st.dataframe(pd.DataFrame(overlap_rows), use_container_width=True, hide_index=True)
            # Send buttons
            ov_cols = st.columns(min(6, len(overlap)))
            for i, t in enumerate(sorted(overlap)[:6]):
                co = ticker_to_company.get(t, "")
                label = f"{t} — {co[:18]}" if co else t
                if ov_cols[i].button(label, key=f"ov_{t}", use_container_width=True):
                    st.session_state.active_ticker = t
                    db.add_to_watchlist(t)
                    st.success(f"Added {t} to watchlist. Open Stock Pro to diagnose.")
        else:
            st.info("No overlap right now. These styles don't share candidates today.")

st.divider()
ui.section_head("External screeners", "Backup hunting grounds when Finviz is limited.")
ec = st.columns(4)
ec[0].markdown("[**Finviz screener**](https://finviz.com/screener.ashx)")
ec[1].markdown("[**Dataroma super investors**](https://www.dataroma.com/m/home.php)")
ec[2].markdown("[**OpenInsider top buys**](http://openinsider.com/insider-purchases-25k)")
ec[3].markdown("[**Magic Formula**](https://www.magicformulainvesting.com/Screening/StockScreening)")
