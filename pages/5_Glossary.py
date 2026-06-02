"""Glossary — every term in plain English, with examples and rules of thumb.

Beginner's reference. Searchable, category-filterable. The "for dummies"
companion to every other page.
"""
from __future__ import annotations

import streamlit as st

from lib import ui
from lib import glossary as gloss
from lib import sidebar_chat

st.set_page_config(page_title="Glossary", page_icon="📚", layout="wide")
ui.inject_global_css()
gloss.explain_toggle_sidebar()
sidebar_chat.render_chat("glossary")

ui.page_header(
    title="Glossary",
    subtitle="Every term in plain English. Searchable, sortable, with rules of thumb you can use today.",
    icon="📚",
)

ui.explain_panel(
    "Every metric, ratio, framework, technical signal, and options term used in the app is defined here "
    "in plain English with a <b>why it matters</b> and a <b>rule of thumb</b>. Includes the investor "
    "philosophies behind each lens — Buffett, Graham, Lynch, Fisher's Scuttlebutt, Greenblatt's Magic "
    "Formula, O'Neil's CAN SLIM, and more. Bookmark this page — investing has more jargon than law school."
)

# Category legend / key — a quick map of what's in the dictionary.
_cat_counts: dict[str, int] = {}
for _g in gloss.GLOSSARY.values():
    _cat_counts[_g["category"]] = _cat_counts.get(_g["category"], 0) + 1
_legend = "".join(
    ui.pill(f"{gloss.CATEGORY_LABELS.get(c, c)} · {n}", "navy")
    for c, n in sorted(_cat_counts.items(), key=lambda kv: -kv[1])
)
st.markdown(
    f"<div style='display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 14px'>{_legend}</div>",
    unsafe_allow_html=True,
)

# ============================================================================
# Search + filter
# ============================================================================
sc1, sc2 = st.columns([3, 1])
search = sc1.text_input(
    "Search glossary",
    placeholder="Search (ROIC, P/E, Piotroski, reverse DCF...)",
    label_visibility="collapsed",
).strip()

all_cats = sorted(set(g["category"] for g in gloss.GLOSSARY.values()))
sel_cat = sc2.selectbox(
    "Category",
    options=["all"] + all_cats,
    format_func=lambda c: "All categories" if c == "all" else gloss.CATEGORY_LABELS.get(c, c).title(),
    label_visibility="collapsed",
)

# Filter
items = list(gloss.GLOSSARY.values())
if sel_cat != "all":
    items = [g for g in items if g["category"] == sel_cat]
if search:
    items = gloss.search_glossary(search)
    if sel_cat != "all":
        items = [g for g in items if g["category"] == sel_cat]

st.caption(f"Showing {len(items)} of {len(gloss.GLOSSARY)} terms")

# ============================================================================
# Cards
# ============================================================================
items_sorted = sorted(items, key=lambda g: g["term"])

ROW_SIZE = 2
for i in range(0, len(items_sorted), ROW_SIZE):
    row = items_sorted[i : i + ROW_SIZE]
    cols = st.columns(ROW_SIZE)
    for entry, col in zip(row, cols):
        with col:
            with st.container(border=True):
                cat_label = gloss.CATEGORY_LABELS.get(entry["category"], entry["category"])
                hc1, hc2 = st.columns([3, 1])
                hc1.markdown(f"### {entry['term']}")
                hc2.markdown(
                    f"<div style='text-align:right'>{ui.pill(cat_label, 'navy')}</div>",
                    unsafe_allow_html=True,
                )

                st.markdown(f"**In plain English:** {entry['plain']}")

                if entry.get("why"):
                    st.markdown(f"**Why it matters:** {entry['why']}")

                if entry.get("rule"):
                    st.markdown(f"**Rule of thumb:** _{entry['rule']}_")

                if entry.get("example"):
                    st.caption(f"📌 Example: {entry['example']}")
