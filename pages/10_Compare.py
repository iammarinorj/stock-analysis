# -*- coding: utf-8 -*-
"""Head-to-head — diagnose two tickers side by side.

You're almost never deciding whether to own a stock in isolation; you're choosing
between A and B. This page runs both through the full diagnosis in parallel and
lines up the key metrics + the 9 profile scores so the better business is obvious.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st

from lib import ui, data, diagnose as diagnose_mod
from lib import glossary as gloss
from lib import sidebar_chat

st.set_page_config(page_title="Compare", page_icon="⚖️", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()
sidebar_chat.render_chat("compare")

ui.page_header(
    title="Head-to-Head",
    subtitle="Two tickers, side by side — key metrics and all nine investor lenses at once.",
    icon="⚖️",
    live=True,
)

wl = []
try:
    from lib import db
    wl = db.get_watchlist()
except Exception:
    wl = []

c1, c2, c3 = st.columns([2, 2, 1])
with c1:
    a_in = st.text_input("Ticker A", value=(wl[0] if wl else "AAPL")).strip()
with c2:
    b_in = st.text_input("Ticker B", value=(wl[1] if len(wl or []) > 1 else "MSFT")).strip()
with c3:
    go = st.button("Compare", type="primary", use_container_width=True)

# Only diagnose on an explicit click (each Compare is two full diagnoses — don't
# auto-run on page load). Persist the chosen pair so reruns keep showing results.
if go and a_in and b_in:
    st.session_state.cmp_pair = (a_in, b_in)
pair = st.session_state.get("cmp_pair")
if not pair:
    ui.empty_state("Enter two tickers and click <b>Compare</b>.")
    st.stop()
a_in, b_in = pair

# Resolve + diagnose both in parallel
def _resolve(x):
    r = data.resolve_ticker(x)
    return r.get("symbol") if not r.get("error") else None

sym_a, sym_b = _resolve(a_in), _resolve(b_in)
if not sym_a or not sym_b:
    st.error("Couldn't resolve one of the tickers. Check the symbols.")
    st.stop()

with st.spinner(f"Diagnosing {sym_a} and {sym_b}…"):
    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(diagnose_mod.diagnose, sym_a)
        fb = ex.submit(diagnose_mod.diagnose, sym_b)
        da, db_ = fa.result(), fb.result()

if da.get("error") or db_.get("error"):
    st.error(f"Diagnosis failed: {da.get('error') or db_.get('error')}")
    st.stop()

qa, qb = da["quote"], db_["quote"]
sa, sb = da["scores"], db_["scores"]

# ---- Header row ----
h = st.columns(2)
for col, q, sym in [(h[0], qa, sym_a), (h[1], qb, sym_b)]:
    with col:
        st.markdown(f"#### {q.get('name') or sym} ({sym})")
        st.caption(f"{q.get('sector','—')} · {q.get('industry','—')}")
        mc = st.columns(3)
        mc[0].metric("Price", f"${q['price']:.2f}" if q.get("price") else "—")
        mc[1].metric("Mkt cap", ui.fmt_money(q.get("market_cap")))
        _sc = sa if q is qa else sb
        bp = max(_sc, key=lambda k: _sc[k]["pct"])
        mc[2].metric("Best fit", _sc[bp]["profile_name"].split(" — ")[0],
                     f"{_sc[bp]['pct']*100:.0f}%")

st.divider()

# ---- Key metrics, side by side, with a winner mark ----
ui.section_head("Key metrics", "✓ marks the more favorable side per row.")

def _pct(v):  # decimal -> %
    return f"{v*100:.1f}%" if isinstance(v, (int, float)) else "—"
def _x(v):
    return f"{v:.1f}x" if isinstance(v, (int, float)) else "—"
def _money(v):
    return ui.fmt_money(v) if isinstance(v, (int, float)) else "—"

# (label, key, formatter, higher_is_better)
METRICS = [
    ("Revenue", "revenue", _money, True),
    ("Net income", "net_income", _money, True),
    ("Fwd P/E", "pe_forward", _x, False),
    ("P/B", "pb", _x, False),
    ("EV/EBITDA", "ev_ebitda", _x, False),
    ("PEG", "peg", lambda v: f"{v:.2f}" if isinstance(v,(int,float)) else "—", False),
    ("Dividend yield", "div_yield", _pct, True),
    ("ROE", "roe", _pct, True),
    ("Operating margin", "operating_margin", _pct, True),
    ("Gross margin", "gross_margin", _pct, True),
    ("Revenue growth", "rev_growth", _pct, True),
    ("FCF margin", None, None, True),  # computed
]

rows = []
for label, key, fmt, hib in METRICS:
    if key is None:  # FCF margin = fcf / revenue
        va = (qa.get("fcf") / qa["revenue"]) if (qa.get("fcf") and qa.get("revenue")) else None
        vb = (qb.get("fcf") / qb["revenue"]) if (qb.get("fcf") and qb.get("revenue")) else None
        fmt = _pct
    else:
        va, vb = qa.get(key), qb.get(key)
    a_win = b_win = ""
    if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va != vb:
        if (va > vb) == hib:
            a_win = " ✓"
        else:
            b_win = " ✓"
    rows.append({"metric": label, "a": fmt(va) + a_win, "b": fmt(vb) + b_win})

ui.glass_table(
    [{"key": "metric", "label": "Metric"},
     {"key": "a", "label": sym_a, "align": "num"},
     {"key": "b", "label": sym_b, "align": "num"}],
    rows,
)

# ---- Profile scores side by side ----
st.divider()
ui.section_head("Investor lenses", "Score out of each profile's max, for both names.")
prof_rows = []
for pid in sa:
    pa, pb = sa[pid], sb[pid]
    name = pa["profile_name"].split(" — ")[0]
    a_mark = " ✓" if pa["pct"] > pb["pct"] else ""
    b_mark = " ✓" if pb["pct"] > pa["pct"] else ""
    prof_rows.append({
        "profile": name,
        "a": f"{pa['total']}/{pa['max']} ({pa['pct']*100:.0f}%)" + a_mark,
        "b": f"{pb['total']}/{pb['max']} ({pb['pct']*100:.0f}%)" + b_mark,
    })
ui.glass_table(
    [{"key": "profile", "label": "Profile"},
     {"key": "a", "label": sym_a, "align": "num"},
     {"key": "b", "label": sym_b, "align": "num"}],
    prof_rows,
)

st.caption("Full diagnosis for each name lives in Stock Pro. This view is for the A-vs-B call.")
