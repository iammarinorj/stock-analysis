"""Backtest — does the scorecard actually predict returns?

Two modes:
  1. Historical (point-in-time across last ~5 years of yfinance data)
  2. Forward tracking (snapshots accumulated from your live diagnoses)
"""
from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from lib import backtest as bt
from lib import profiles as profiles_mod
from lib import db
from lib import ui
from lib import glossary as gloss
from lib import sidebar_chat

st.set_page_config(page_title="Backtest", page_icon="📊", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()
sidebar_chat.render_chat("backtest")

ui.page_header(
    title="Backtest",
    subtitle="Does the scorecard actually predict returns? Two tests, one truth.",
    icon="📊",
)

if gloss.is_explain_mode():
    ui.explain_panel(
        "A scorecard that <i>feels</i> smart isn't the same as one that <b>actually predicts returns</b>. "
        "This page tests both. <b>Historical backtest</b> runs the scorecard against the last ~5 years "
        "of point-in-time data (limited to fundamental signals since old market prices for PE/PB aren't "
        "in yfinance). <b>Forward tracking</b> uses real snapshots from your own diagnoses to measure "
        "out-of-sample accuracy. Forward tracking takes weeks to fill but is the honest answer."
    )

tab_hist, tab_forward = st.tabs(["📜 Historical backtest", "🎯 Forward tracking (live snapshots)"])

# ============================================================================
# TAB 1 — Historical backtest
# ============================================================================
with tab_hist:
    ui.section_head("Pick universe + profile", "")

    c1, c2, c3 = st.columns([2, 2, 1])

    AUTO_LABEL = "🎯 Auto: let the profile pick (unbound by exchange)"
    universe_choice = c1.selectbox(
        "Universe",
        options=[AUTO_LABEL] + list(bt.DEFAULT_UNIVERSES.keys()) + ["My watchlist", "Custom list"],
        index=0,
    )
    profile_choice = c2.selectbox(
        "Profile",
        options=list(profiles_mod.PROFILES.keys()),
        format_func=lambda k: profiles_mod.PROFILES[k]["name"],
        index=0,
    )
    forward_days = c3.number_input("Forward days", min_value=30, max_value=730,
                                   value=365, step=30)

    # Auto-universe options
    auto_settings = {}
    if universe_choice == AUTO_LABEL:
        ac1, ac2, ac3 = st.columns([1, 1, 1])
        auto_settings["include_foreign"] = ac1.toggle(
            "🌐 Include foreign listings",
            value=False,
            help="Drop Country=USA filter. Adds ADRs like ASML, TSM, NVO. More survivorship bias since we still only see tickers that PASS the screen today.",
        )
        auto_settings["min_mkt_cap"] = ac2.selectbox(
            "Min market cap",
            options=["+Micro (over $50mln)", "+Small (over $300mln)", "+Mid (over $2bln)", "+Large (over $10bln)"],
            index=1,
        )
        auto_settings["limit"] = ac3.number_input("Max tickers", min_value=10, max_value=100, value=30, step=5)

        if gloss.is_explain_mode():
            ui.explain_panel(
                "<b>Auto mode</b>: instead of a hand-picked universe, run the profile's matching Finviz "
                "screen TODAY, take the top N tickers, then backtest those. Useful for 'what does this "
                "profile want to own right now, and would those names have worked historically?'. "
                "<b>Caveat (survivorship bias)</b>: we only see stocks that pass the screen TODAY, "
                "not stocks that passed in 2021. The backtest results will look better than a true "
                "point-in-time test. Treat as directional, not absolute."
            )

    custom_input = ""
    if universe_choice == "Custom list":
        custom_input = st.text_input(
            "Tickers (comma-separated)",
            placeholder="AAPL, MSFT, GOOGL, BRK-B, F, COST, ...",
        )

    if st.button("Run historical backtest", type="primary"):
        # Build universe
        if universe_choice == AUTO_LABEL:
            with st.spinner(f"Letting {profile_choice} profile pick its own universe..."):
                universe = bt.get_auto_universe(
                    profile_choice,
                    include_foreign=auto_settings.get("include_foreign", False),
                    min_mkt_cap=auto_settings.get("min_mkt_cap", "+Small (over $300mln)"),
                    limit=auto_settings.get("limit", 30),
                )
            if universe:
                st.info(
                    f"**{profile_choice} profile auto-selected {len(universe)} tickers**: "
                    + ", ".join(universe[:15])
                    + (f", ... +{len(universe)-15} more" if len(universe) > 15 else "")
                )
            else:
                st.error(
                    f"Auto-selection returned 0 tickers — the screen filters for "
                    f"{profile_choice} may be too strict. Try a different profile or "
                    f"set a lower min market cap."
                )
                st.stop()
        elif universe_choice == "My watchlist":
            universe = tuple(db.get_watchlist())
        elif universe_choice == "Custom list":
            universe = tuple([t.strip().upper() for t in custom_input.split(",") if t.strip()])
        else:
            universe = bt.DEFAULT_UNIVERSES[universe_choice]

        if not universe:
            st.warning("Universe is empty.")
        else:
            with st.spinner(f"Backtesting {len(universe)} tickers concurrently..."):
                result = bt.backtest_universe(universe, profile_choice, forward_days)

            if result.get("error"):
                st.error(result["error"])
            else:
                summ = result["summary"]
                rows = result["rows"]

                ui.section_head(
                    f"Results: {profiles_mod.PROFILES[profile_choice]['name']}",
                    f"{summ['n_observations']} observations across {summ['n_tickers']} tickers · ran in {result['elapsed_s']:.1f}s",
                )

                # Headline metrics
                m_cols = st.columns(4)
                m_cols[0].metric("Observations", summ["n_observations"])
                m_cols[1].metric(
                    f"Avg {forward_days}d return",
                    f"{summ['avg_return_overall']*100:+.1f}%",
                    f"hit rate {summ['hit_rate_overall']*100:.0f}%",
                )
                m_cols[2].metric(
                    "Median return",
                    f"{summ['median_return_overall']*100:+.1f}%",
                )
                corr_val = summ.get("correlation")
                m_cols[3].metric(
                    "Score-vs-return correlation",
                    f"{corr_val:+.3f}" if corr_val is not None else "—",
                    "positive = scoring works" if (corr_val or 0) > 0 else "negative or zero = no signal",
                )

                # Quartile breakdown
                ui.section_head("Returns by score quartile",
                                "If scoring works, Q4 (top scores) should outperform Q1 (bottom).")
                if gloss.is_explain_mode():
                    ui.explain_panel(
                        "We rank all observations from worst score (Q1) to best (Q4) and look at the "
                        "average forward return per bucket. A working scorecard shows <b>Q4 return > Q1 return</b>. "
                        "If they're flat or inverted, the scorecard isn't picking winners."
                    )

                by_q = summ["by_quartile"]
                hit_q = summ["hit_rate_by_quartile"]
                if by_q:
                    q_df = pd.DataFrame([
                        {
                            "Quartile": f"Q{q}",
                            f"Avg {forward_days}d return": f"{by_q.get(q, 0)*100:+.1f}%",
                            "Hit rate": f"{hit_q.get(q, 0)*100:.0f}%",
                            "Signal": ("🟢 Best" if q == 4 else ("🔴 Worst" if q == 1 else "—")),
                        }
                        for q in sorted(by_q.keys())
                    ])
                    st.dataframe(q_df, use_container_width=True, hide_index=True)

                    # Bar chart
                    qs = sorted(by_q.keys())
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        x=[f"Q{q}" for q in qs],
                        y=[by_q[q] * 100 for q in qs],
                        marker_color=["#a82626", "#9a6500", "#1e4dd8", "#0f7a4d"][:len(qs)],
                        text=[f"{by_q[q]*100:+.1f}%" for q in qs],
                        textposition="outside",
                    ))
                    fig.update_layout(
                        title="Average forward return by score quartile",
                        height=320,
                        plot_bgcolor="#fff", paper_bgcolor="#fff",
                        yaxis_title="Return (%)",
                        margin=dict(l=10, r=10, t=40, b=10),
                        font=dict(family="-apple-system, sans-serif"),
                    )
                    fig.update_xaxes(showgrid=False)
                    fig.update_yaxes(showgrid=True, gridcolor="#f0f0eb", zeroline=True, zerolinecolor="#888")
                    st.plotly_chart(fig, use_container_width=True)

                # Scatter
                ui.section_head("Score vs return scatter", "Each dot = one ticker-year observation.")
                df = pd.DataFrame(rows)
                if not df.empty:
                    fig2 = go.Figure()
                    fig2.add_trace(go.Scatter(
                        x=df["pct"] * 100,
                        y=df["forward_return"] * 100,
                        mode="markers",
                        marker=dict(size=8, color="#1e4dd8", opacity=0.7,
                                    line=dict(width=1, color="#1e3a8a")),
                        text=[f"{r['symbol']} {r['year_end']}" for r in rows],
                        hovertemplate="<b>%{text}</b><br>Score: %{x:.0f}%<br>Return: %{y:+.1f}%<extra></extra>",
                    ))
                    fig2.update_layout(
                        height=380,
                        plot_bgcolor="#fff", paper_bgcolor="#fff",
                        xaxis_title="Score (%)",
                        yaxis_title=f"Forward {forward_days}d return (%)",
                        margin=dict(l=10, r=10, t=20, b=10),
                        font=dict(family="-apple-system, sans-serif"),
                    )
                    fig2.update_xaxes(showgrid=True, gridcolor="#f0f0eb")
                    fig2.update_yaxes(showgrid=True, gridcolor="#f0f0eb", zeroline=True, zerolinecolor="#888")
                    st.plotly_chart(fig2, use_container_width=True)

                # Best & worst observations
                with st.expander(f"Show all {len(rows)} observations"):
                    show_df = df.copy()
                    show_df["pct"] = (show_df["pct"] * 100).round(1).astype(str) + "%"
                    show_df["forward_return"] = (show_df["forward_return"] * 100).round(1).astype(str) + "%"
                    show_df["price_at"] = show_df["price_at"].round(2)
                    show_df["price_fwd"] = show_df["price_fwd"].round(2)
                    st.dataframe(show_df, use_container_width=True, hide_index=True)

# ============================================================================
# TAB 2 — Forward tracking
# ============================================================================
with tab_forward:
    ui.section_head("🏅 Your judgment scorecard",
                    "Out-of-sample proof: do the stocks YOU score highly actually go up?")
    if gloss.is_explain_mode():
        ui.explain_panel(
            "Every time you diagnose a stock, the app silently saves the scorecard + price. "
            "Once a snapshot is at least 30 days old, we compare what you scored vs what actually happened. "
            "<b>This is honest out-of-sample evidence</b> — no backfitting, no hindsight bias. It answers the "
            "only question that matters: <b>is your process working?</b> Takes weeks to fill, then compounds."
        )

    age_threshold = st.slider("Minimum age of snapshot (days)", min_value=7, max_value=365, value=30)

    if st.button("Run forward-tracking report", type="primary"):
        with st.spinner("Pulling current prices for snapshots..."):
            report = bt.forward_tracking_report(min_age_days=age_threshold)

        if report.get("message"):
            ui.empty_state(report["message"])
        else:
            summ = report["summary"]
            rows = report["rows"]

            st.markdown(f"**{summ['n_observations']} snapshots evaluated** "
                        f"(at least {age_threshold} days old)")

            m_cols = st.columns(4)
            m_cols[0].metric("Snapshots", summ["n_observations"])
            m_cols[1].metric("Avg actual return", f"{summ['avg_actual_return']*100:+.1f}%")
            m_cols[2].metric("Hit rate (positive)", f"{summ['hit_rate']*100:.0f}%")

            # Plain-English verdict: which profile's scoring best predicted returns?
            prof_corrs = {p: v.get("correlation") for p, v in summ.items()
                          if isinstance(v, dict) and v.get("correlation") is not None}
            if prof_corrs:
                best_p = max(prof_corrs, key=lambda k: prof_corrs[k])
                best_c = prof_corrs[best_p]
                best_name = profiles_mod.PROFILES.get(best_p, {}).get("name", best_p).split(" — ")[0]
                if best_c > 0.2:
                    verdict = (f"✅ Your scoring shows a **positive predictive signal** — higher-scored picks "
                               f"tended to return more. Strongest lens for you: **{best_name}** (corr {best_c:+.2f}).")
                    color = "darkgreen"
                elif best_c > 0:
                    verdict = (f"🟡 **Weak/mixed signal** so far. Best lens: {best_name} (corr {best_c:+.2f}). "
                               f"Keep diagnosing — the sample is still small.")
                    color = "amber"
                else:
                    verdict = ("🔴 **No predictive signal yet** — high scores haven't translated to returns in this "
                               "sample. Either it's early, or worth reflecting on which lenses fit your picks.")
                    color = "red"
                ui.verdict_box("What this says about your process", "", verdict, color)

            ui.section_head("Correlation by profile",
                            "Did each profile's score predict the actual return?")
            corr_rows = []
            for profile, vals in summ.items():
                if profile in ("n_observations", "avg_actual_return", "hit_rate"):
                    continue
                if not isinstance(vals, dict):
                    continue
                corr = vals.get("correlation")
                corr_rows.append({
                    "Profile": profiles_mod.PROFILES.get(profile, {}).get("name", profile),
                    "Correlation": f"{corr:+.3f}" if corr is not None else "—",
                    "Signal": ("🟢 Positive" if (corr or 0) > 0.1 else
                               ("🔴 Negative" if (corr or 0) < -0.1 else "⚪ Noise")),
                })
            if corr_rows:
                st.dataframe(pd.DataFrame(corr_rows), use_container_width=True, hide_index=True)

            with st.expander(f"Show all {len(rows)} snapshots"):
                df = pd.DataFrame(rows)
                if not df.empty:
                    df["actual_return"] = (df["actual_return"] * 100).round(1).astype(str) + "%"
                    for col in ["buffett_pct", "graham_pct", "lynch_pct", "fisher_pct", "best_pct"]:
                        if col in df.columns:
                            df[col] = (df[col] * 100).round(0).astype(int).astype(str) + "%"
                    df["old_price"] = df["old_price"].round(2)
                    df["current_price"] = df["current_price"].round(2)
                    st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        # Show count of existing snapshots
        snaps = db.get_all_snapshots()
        st.caption(f"You have {len(snaps)} snapshots saved across {len(set(s['symbol'] for s in snaps))} tickers.")
        if snaps:
            oldest = min(s["snapped_at"] for s in snaps)[:10]
            st.caption(f"Oldest snapshot: {oldest}")
