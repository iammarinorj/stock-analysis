"""Thesis Journal — open positions, closed positions, triggered alerts.

The discipline layer. Every position needs a written bull case, bear case,
and breaks-if triggers. When you close, you write what you learned.
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from lib import db, data, alerts as alerts_mod
from lib import profiles as profiles_mod
from lib import ui
from lib import glossary as gloss
from lib import sidebar_chat

st.set_page_config(page_title="Thesis Journal", page_icon="📝", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()


def _thesis_context() -> str:
    open_theses = db.get_theses(status="open")
    parts = [f"User is viewing the Thesis Journal. They have {len(open_theses)} open positions."]
    if open_theses:
        parts.append("\nOpen positions:")
        for t in open_theses[:10]:
            parts.append(f"- {t['symbol']} ({t.get('side','long')}, opened {t['opened_at'][:10]}, profile {t.get('profile','?')})")
    return "\n".join(parts)


sidebar_chat.render_chat("thesis", _thesis_context)

ui.page_header(
    title="Thesis Journal",
    subtitle="Every open position has a written thesis with breaks-if triggers. This is the discipline layer.",
    icon="📝",
)

if gloss.is_explain_mode():
    ui.explain_panel(
        "Most retail investors lose because they don't have a written thesis. They buy on a hunch and "
        "sell on emotion. <b>Open theses</b> are your live positions with clear stops and targets. "
        "<b>Closed theses</b> are your learning library. Reviewing your closed positions monthly is "
        "how you compound investing skill, not just capital."
    )

tab_open, tab_closed, tab_alerts = st.tabs(["📂 Open theses", "✅ Closed positions", "🔔 Alerts"])

# -------------------- OPEN --------------------
with tab_open:
    open_theses = db.get_theses(status="open")
    if not open_theses:
        ui.empty_state("No open theses. Diagnose a stock in Stock Pro, then save its bull/bear thesis.")
    else:
        ui.section_head(f"{len(open_theses)} open positions", "Click to expand. Stops fire automatically.")
        for th in open_theses:
            quote = data.get_quote(th["symbol"])
            current = quote.get("price") if quote and "error" not in quote else None
            entry = th.get("entry_price")
            target = th.get("target_price")
            stop = th.get("stop_price")

            unrealized_pct = None
            if current and entry:
                unrealized_pct = (current / entry - 1) * 100
                if th.get("side") == "short":
                    unrealized_pct = -unrealized_pct

            tone = "pos" if (unrealized_pct or 0) > 0 else ("neg" if (unrealized_pct or 0) < 0 else "")

            label_parts = [f"**{th['symbol']}**", f"({th.get('side', '?')})",
                           f"· {th.get('profile', '—')}",
                           f"· opened {th['opened_at'][:10]}"]
            if unrealized_pct is not None:
                label_parts.append(f"· P&L {unrealized_pct:+.1f}%")

            with st.expander(" ".join(label_parts), expanded=False):
                cols = st.columns([1, 1, 1, 1, 1])
                cols[0].metric("Entry", f"${entry:.2f}" if entry else "—")
                cols[1].metric("Current", f"${current:.2f}" if current else "—",
                               f"{unrealized_pct:+.1f}%" if unrealized_pct is not None else None)
                cols[2].metric("Target", f"${target:.2f}" if target else "—",
                               f"{((target/current)-1)*100:+.1f}% upside" if target and current else None)
                cols[3].metric("Stop", f"${stop:.2f}" if stop else "—",
                               f"{((stop/current)-1)*100:+.1f}%" if stop and current else None)
                cols[4].metric("Size", f"{th.get('position_size_pct', 0)}%")

                if th.get("key_metric"):
                    st.caption(f"**Key metric to track:** {th['key_metric']} "
                               f"(target {th.get('key_metric_target', '—')})")

                bc, br = st.columns(2)
                bc.markdown("**🟢 Bull case**")
                bc.markdown(th.get("bull_case") or "_no bull case recorded_")
                br.markdown("**🔴 Bear case**")
                br.markdown(th.get("bear_case") or "_no bear case recorded_")

                st.markdown("**⚠️ Breaks if**")
                st.markdown(th.get("breaks_if") or "_no triggers recorded_")

                triggers_hit = []
                if current and stop:
                    if th.get("side") == "long" and current < stop:
                        triggers_hit.append(f"Price ${current:.2f} hit stop ${stop:.2f}")
                    elif th.get("side") == "short" and current > stop:
                        triggers_hit.append(f"Price ${current:.2f} hit stop ${stop:.2f}")
                if triggers_hit:
                    st.error("🚨 Trigger hit: " + " · ".join(triggers_hit))

                st.divider()
                ac1, ac2, ac3 = st.columns([2, 2, 1])
                with ac1:
                    close_price = st.number_input("Close at price", value=current or 0.0,
                                                  step=0.01, key=f"cp_{th['id']}")
                with ac2:
                    close_notes = st.text_input("Close notes (what did you learn?)",
                                                key=f"cn_{th['id']}")
                with ac3:
                    if st.button("Close", key=f"close_{th['id']}", type="primary"):
                        db.close_thesis(th["id"], close_price, close_notes)
                        st.success("Thesis closed.")
                        st.rerun()
                    if st.button("Delete", key=f"del_{th['id']}"):
                        db.delete_thesis(th["id"])
                        st.rerun()

# -------------------- CLOSED --------------------
with tab_closed:
    closed = db.get_theses(status="closed")
    if not closed:
        ui.empty_state("No closed positions yet. Close a thesis from the Open tab to start your record.")
    else:
        ui.section_head(f"{len(closed)} closed positions", "Your track record. Review monthly.")

        wins = 0; losses = 0; total_pct = 0
        for th in closed:
            if th.get("entry_price") and th.get("close_price"):
                ret = (th["close_price"] / th["entry_price"] - 1)
                if th.get("side") == "short":
                    ret = -ret
                total_pct += ret * 100
                if ret > 0:
                    wins += 1
                else:
                    losses += 1
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Wins", wins)
        col2.metric("Losses", losses)
        wr = (wins / (wins + losses) * 100) if (wins + losses) else 0
        col3.metric("Win rate", f"{wr:.0f}%")
        avg = total_pct / len(closed) if closed else 0
        col4.metric("Avg return", f"{avg:+.1f}%")

        st.write("")
        rows = []
        for th in closed:
            ret = None
            if th.get("entry_price") and th.get("close_price"):
                ret = (th["close_price"] / th["entry_price"] - 1) * 100
                if th.get("side") == "short":
                    ret = -ret
            rows.append({
                "Symbol": th["symbol"],
                "Side": th.get("side"),
                "Profile": th.get("profile"),
                "Opened": th["opened_at"][:10],
                "Closed": (th.get("closed_at") or "")[:10],
                "Entry": f"${th.get('entry_price', 0):.2f}" if th.get("entry_price") else "—",
                "Exit": f"${th.get('close_price', 0):.2f}" if th.get("close_price") else "—",
                "Return": f"{ret:+.1f}%" if ret is not None else "—",
                "Learning": (th.get("close_notes") or "")[:80],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# -------------------- ALERTS --------------------
with tab_alerts:
    # Run the monitor on load so alerts reflect live data, then read them back.
    with st.spinner("Scanning theses + watchlist against live data…"):
        newly = alerts_mod.check_all()
    if newly:
        st.toast(f"{newly} new alert(s)")

    top = st.columns([4, 1])
    top[1].button("🔄 Re-scan", use_container_width=True, key="alerts_rescan")  # triggers rerun
    alerts = db.get_alerts(seen=False)
    if not alerts:
        ui.empty_state("No active alerts. Stops, targets, key-metric breaks, 200DMA crosses, and earnings within 5 days will show here.")
    else:
        ui.section_head(f"{len(alerts)} unseen alerts", "Live triggers from your open theses and watchlist.")
        for a in alerts:
            val = a.get("value_at_trigger")
            val_str = f" (was {val:.2f})" if isinstance(val, (int, float)) else ""
            st.warning(f"**{a['symbol']}** — {a['condition']}{val_str} · fired {a['fired_at'][:10]}")
        if st.button("Mark all as seen"):
            db.mark_alerts_seen()
            st.rerun()

    st.divider()
    st.caption(
        "The monitor scans on every visit: open-thesis stops/targets/key-metric breaks, "
        "plus watchlist 200DMA crosses, 52-week extremes, and earnings within 5 days. "
        "Cached quotes keep the scan fast; duplicate conditions are suppressed until you mark them seen."
    )
