"""Design system for Stock Analysis app — light theme, high contrast.

Single source of truth for typography, colors, spacing, and reusable components.
Call inject_global_css() early in each page (after st.set_page_config).

Designed for LIGHT mode only. Streamlit config (.streamlit/config.toml) locks
the theme to light so this CSS doesn't fight with auto dark detection.
"""
from __future__ import annotations

import streamlit as st

from lib import fmt as _fmt


# ---------------------------------------------------------------------------
# Color tokens — deeper saturation than v1 so cards actually pop on light bg
# ---------------------------------------------------------------------------

COLORS = {
    "bg": "#fafaf7",
    "surface": "#ffffff",
    "surface_alt": "#f3f1ec",
    "border": "rgba(0,0,0,.12)",
    "border_strong": "rgba(0,0,0,.22)",
    "text": "#0d0d0d",
    "text_muted": "#3d3d3d",
    "text_faint": "#6b6b6b",
    "navy": "#1e3a8a",
    "accent": "#1e4dd8",
    "accent_bg": "#e8efff",
    "green": "#0a5f3c",
    "green_bg": "#e3f3ea",
    "green_strong": "#063b25",
    "green_strong_bg": "#cdeadb",
    "amber": "#7a4f00",
    "amber_bg": "#fcefd0",
    "yellow": "#8a6f00",
    "yellow_bg": "#fff6da",
    "red": "#8a1818",
    "red_bg": "#fce0e0",
    "purple": "#5a2e8f",
    "teal": "#06544f",
}

# Components reference CSS variables (not raw hex) so they adapt to dark mode.
COLOR_PAIRS = {
    "darkgreen": ("var(--green-strong-bg)", "var(--green-strong)"),
    "green":     ("var(--green-bg)", "var(--green)"),
    "yellow":    ("var(--yellow-bg)", "var(--yellow)"),
    "amber":     ("var(--amber-bg)", "var(--amber)"),
    "red":       ("var(--red-bg)", "var(--red)"),
    "navy":      ("var(--accent-bg)", "var(--navy)"),
    "accent":    ("var(--accent-bg)", "var(--accent)"),
    "gray":      ("var(--surface-alt)", "var(--text-muted)"),
}


def is_dark() -> bool:
    """True when the user has toggled dark mode on (opt-in; default light)."""
    return bool(st.session_state.get("sap_dark", False))


# ---------------------------------------------------------------------------
# Global CSS — hard-overrides Streamlit's theme
# ---------------------------------------------------------------------------

_FONTS = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');"
)

_LIGHT_VARS = """
:root {
  color-scheme: light;
  /* Aurora gradient — softened so semantic green/red stays the loudest signal on data pages */
  --app-bg: radial-gradient(900px 620px at 6% 2%, rgba(196,181,253,.45) 0%, transparent 55%),
            radial-gradient(840px 560px at 96% 6%, rgba(167,243,208,.35) 0%, transparent 52%),
            radial-gradient(900px 760px at 50% 108%, rgba(251,207,232,.30) 0%, transparent 55%),
            linear-gradient(180deg,#f5f4ff,#f0f2ff);
  --bg:#f1f0fb; --surface:rgba(255,255,255,.72); --surface-alt:rgba(255,255,255,.5); --surface-2:rgba(255,255,255,.62);
  --glass:rgba(255,255,255,.55); --blur: saturate(150%) blur(16px);
  --border:rgba(255,255,255,.7); --border-strong:rgba(16,19,46,.18); --input-border:rgba(16,19,46,.18);
  --text:#10132e; --text-muted:#454a72; --text-faint:#6a6f96;
  --navy:#5a2fd0; --accent:#6d3bf5; --accent-bg:rgba(109,59,245,.14);
  --green:#0a8f5b; --green-bg:rgba(10,143,91,.14); --green-strong:#076b44; --green-strong-bg:rgba(10,143,91,.2);
  --amber:#a96a00; --amber-bg:rgba(169,106,0,.15); --yellow:#9a7d00; --yellow-bg:rgba(154,125,0,.15);
  --red:#d23b5b; --red-bg:rgba(210,59,91,.13);
  --explain-bg:rgba(255,255,255,.5); --explain-border:rgba(109,59,245,.3); --explain-accent:#6d3bf5; --explain-text:#3a2b66;
  --tag-bg:#0a8f5b;
  --radius:14px; --radius-sm:10px; --radius-lg:18px;
  --shadow:0 8px 26px rgba(60,40,120,.12);
  --shadow-hover:0 16px 40px rgba(80,50,160,.20);
  --font:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  --font-mono:'IBM Plex Mono',ui-monospace,'SF Mono',Menlo,monospace;
}
"""

_DARK_VARS = """
:root {
  color-scheme: dark;
  --app-bg: radial-gradient(900px 600px at 6% 2%, rgba(124,77,255,.28) 0%, transparent 55%),
            radial-gradient(820px 540px at 96% 8%, rgba(16,185,129,.16) 0%, transparent 52%),
            radial-gradient(900px 760px at 50% 110%, rgba(236,72,153,.16) 0%, transparent 55%),
            linear-gradient(180deg,#0b0d18,#0a0c14);
  --bg:#0b0d16; --surface:rgba(30,32,48,.6); --surface-alt:rgba(42,44,66,.55); --surface-2:rgba(24,26,40,.6);
  --glass:rgba(30,32,48,.55); --blur: saturate(150%) blur(16px);
  --border:rgba(255,255,255,.10); --border-strong:rgba(255,255,255,.22); --input-border:rgba(255,255,255,.18);
  --text:#eceaf7; --text-muted:#b3b1c9; --text-faint:#8a87a6;
  --navy:#b9a3ff; --accent:#a78bfa; --accent-bg:rgba(124,77,255,.24);
  --green:#4ade9a; --green-bg:rgba(16,185,129,.18); --green-strong:#86efc0; --green-strong-bg:rgba(16,185,129,.30);
  --amber:#e3b35a; --amber-bg:rgba(180,120,20,.22); --yellow:#e6cf6c; --yellow-bg:rgba(180,150,20,.2);
  --red:#ff7a93; --red-bg:rgba(210,59,91,.24);
  --explain-bg:rgba(124,77,255,.12); --explain-border:rgba(167,139,250,.4); --explain-accent:#a78bfa; --explain-text:#d9cffb;
  --tag-bg:#0a8f5b;
  --shadow:0 8px 26px rgba(0,0,0,.5);
  --shadow-hover:0 16px 44px rgba(0,0,0,.6);
}
"""

_BODY_CSS = """
html, body, .stApp {
  background: var(--app-bg) !important;
  background-attachment: fixed !important;
  background-color: var(--bg) !important;
  color: var(--text) !important;
}
[data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stHeader"], [data-testid="stToolbar"],
.main, .block-container {
  background: transparent !important;
  color: var(--text) !important;
}
html, body, [class*="css"] {
  font-family: var(--font) !important;
  font-feature-settings: "tnum" 1, "cv01" 1;
}
.block-container { padding-top: 1.2rem !important; padding-bottom: 4rem !important; max-width: 1320px !important; }
h1,h2,h3,h4,h5,h6 { color: var(--text) !important; }
h1 { font-weight:600 !important; letter-spacing:-.02em !important; font-size:28px !important; }
h2 { font-weight:600 !important; letter-spacing:-.01em !important; font-size:22px !important; }
h3 { font-weight:600 !important; letter-spacing:-.01em !important; font-size:18px !important; }
h4,h5 { font-weight:600 !important; font-size:14.5px !important; }
p, li, div, span, label { color: var(--text); font-size:14.5px; line-height:1.55; }
[data-testid="stCaptionContainer"], .caption, small { color: var(--text-muted) !important; font-size:12.5px !important; }

/* Tabular monospace for numbers */
[data-testid="stMetricValue"], .sap-kpi-value, .sap-kpi-sub, code, pre,
.stDataFrame, .stTable { font-variant-numeric: tabular-nums; }
[data-testid="stMetricValue"], .sap-kpi-value, .sap-kpi-sub { font-family: var(--font-mono) !important; }

/* Buttons */
.stButton > button {
  border-radius:8px !important; border:1px solid var(--input-border) !important;
  background: var(--surface) !important; color: var(--text) !important;
  font-weight:500 !important; font-size:13.5px !important; padding:8px 14px !important;
  box-shadow: var(--shadow) !important; transition: all .14s ease;
}
.stButton > button:hover {
  border-color: var(--accent) !important; background: var(--accent-bg) !important;
  color: var(--navy) !important; transform: translateY(-1px);
  box-shadow: var(--shadow-hover) !important;
}
.stButton > button[kind="primary"] { background: var(--navy) !important; color:#fff !important; border:1px solid var(--navy) !important; }
.stButton > button[kind="primary"]:hover { background: var(--accent) !important; border-color: var(--accent) !important; color:#fff !important; }
/* Higher-specificity surface fill for non-primary buttons — Streamlit 1.5x sets a
   white bg at equal specificity that otherwise wins (invisible in light, white-on-dark in dark). */
.stButton > button[kind="secondary"], .stButton > button:not([kind="primary"]),
[data-testid="stSidebar"] .stButton > button:not([kind="primary"]) {
  background: var(--surface) !important; color: var(--text) !important;
}
.stButton > button:not([kind="primary"]):hover {
  background: var(--accent-bg) !important; color: var(--navy) !important;
}
/* Streamlit 1.5x paints the secondary button via an emotion class; beat it with a
   higher-specificity longhand so dark mode fills correctly (no-op in light). */
.stApp .stButton button:not([kind="primary"]),
.stApp button[data-testid="stBaseButton-secondary"],
.stApp [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
  background-color: var(--surface) !important; color: var(--text) !important;
}

/* Metric tiles */
[data-testid="stMetric"] {
  background: var(--surface) !important; border:1px solid var(--border) !important;
  border-radius: var(--radius) !important; padding:14px 16px !important;
  box-shadow: var(--shadow) !important;
}
[data-testid="stMetricValue"] { font-size:24px !important; font-weight:600 !important; letter-spacing:-.01em !important; color: var(--text) !important; }
[data-testid="stMetricLabel"] { font-size:11px !important; text-transform:uppercase !important; letter-spacing:.05em !important; color: var(--text-faint) !important; font-weight:600 !important; }
[data-testid="stMetricDelta"] { font-size:12px !important; }

/* Inputs */
.stTextInput input, .stNumberInput input {
  background: var(--surface) !important; color: var(--text) !important;
  border:1px solid var(--input-border) !important; border-radius: var(--radius-sm) !important;
}
.stTextInput input:focus, .stNumberInput input:focus { border-color: var(--accent) !important; box-shadow:0 0 0 2px var(--accent-bg) !important; }
.stSelectbox > div > div { background: var(--surface) !important; color: var(--text) !important; border-radius: var(--radius-sm) !important; }

/* Tabs */
[data-baseweb="tab-list"] { background:transparent !important; gap:2px !important; border-bottom:1px solid var(--border) !important; margin-bottom:18px !important; }
[data-baseweb="tab"] { background:transparent !important; color: var(--text-muted) !important; font-size:14px !important; font-weight:500 !important; padding:10px 14px !important; border-radius:0 !important; }
[data-baseweb="tab"]:hover { color: var(--text) !important; background: var(--surface-alt) !important; }
[data-baseweb="tab"][aria-selected="true"] { color: var(--navy) !important; border-bottom:2px solid var(--navy) !important; font-weight:600 !important; }
[data-baseweb="tab-panel"] { background:transparent !important; }
[data-baseweb="tab-highlight"] { background: var(--navy) !important; }

/* Code */
.stCode, code, pre, [data-testid="stCode"], [data-testid="stCodeBlock"] { background: var(--surface-alt) !important; color: var(--text) !important; }
.stCode pre, .stCode code, code, [data-testid="stCode"] pre {
  background: var(--surface-alt) !important; color: var(--text) !important;
  border:1px solid var(--border) !important; border-radius:4px !important; padding:6px 10px !important;
  font-family: var(--font-mono) !important; font-size:12.5px !important; font-weight:500 !important;
}
.stCode > div, .stCode * { background: var(--surface-alt) !important; color: var(--text) !important; }

/* Dataframes — panel feel */
.stDataFrame, [data-testid="stDataFrame"] {
  background: var(--surface) !important; border:1px solid var(--border) !important;
  border-radius: var(--radius-sm) !important; box-shadow: var(--shadow) !important;
}
.stDataFrame th { background: var(--surface-alt) !important; color: var(--text-faint) !important; font-weight:600 !important; text-transform:uppercase; letter-spacing:.03em; font-size:11px !important; }
.stDataFrame td { color: var(--text) !important; font-size:13px !important; }

/* Expanders */
[data-testid="stExpander"] { border:1px solid var(--border) !important; border-radius: var(--radius-sm) !important; background: var(--surface) !important; box-shadow: var(--shadow) !important; }
[data-testid="stExpander"] summary { font-size:14px !important; font-weight:500 !important; color: var(--text) !important; }
[data-testid="stExpander"] summary:hover { background: var(--surface-alt) !important; }

/* Sidebar */
[data-testid="stSidebar"] { background-color: var(--surface-alt) !important; border-right:1px solid var(--border) !important; -webkit-backdrop-filter: var(--blur) !important; backdrop-filter: var(--blur) !important; }
/* Force all sidebar nav pages visible — no "View X more" collapse */
[data-testid="stSidebarNav"] ul { max-height: none !important; overflow: visible !important; }
[data-testid="stSidebarNav"] li { display: list-item !important; }
[data-testid="stSidebarNav"] button[kind="header"] { display: none !important; }
[data-testid="stSidebarNav"] details { display: contents !important; }
[data-testid="stSidebarNav"] details > summary { display: none !important; }
[data-testid="stSidebarNav"] details[open] > ul { display: block !important; }
[data-testid="stSidebarNav"] details > ul { display: block !important; }
/* Active page highlight in Streamlit's nav */
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {
  background: var(--accent-bg) !important; color: var(--accent) !important; font-weight:600 !important;
  border-radius: var(--radius-sm) !important;
}
[data-testid="stSidebar"] * { color: var(--text) !important; }
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,[data-testid="stSidebar"] h4 {
  font-size:12px !important; text-transform:uppercase !important; letter-spacing:.05em !important; color: var(--text-muted) !important; font-weight:700 !important; margin-top:12px !important;
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: var(--text-faint) !important; }
[data-testid="stSidebar"] .stButton > button { background: var(--surface) !important; color: var(--text) !important; border:1px solid var(--border-strong) !important; }

/* Custom components */
.sap-card { background: var(--surface); border:1px solid var(--border); border-radius: var(--radius); padding:16px 18px; margin-bottom:12px; box-shadow: var(--shadow); }
.sap-kpi { background: var(--surface); border:1px solid var(--border); border-left:4px solid var(--text-faint); border-radius: var(--radius-sm); padding:12px 14px; box-shadow: var(--shadow); transition: box-shadow .14s ease, transform .14s ease; }
.sap-kpi:hover { box-shadow: var(--shadow-hover); transform: translateY(-1px); }
.sap-kpi.pos { border-left-color: var(--green); }
.sap-kpi.neg { border-left-color: var(--red); }
.sap-kpi.warn { border-left-color: var(--amber); }
.sap-kpi-label { font-size:10.5px; text-transform:uppercase; letter-spacing:.05em; color: var(--text-faint); font-weight:700; margin-bottom:4px; }
.sap-kpi-value { font-size:22px; font-weight:600; letter-spacing:-.01em; color: var(--text); }
.sap-kpi-sub { font-size:12px; color: var(--text-muted); margin-top:2px; }
.sap-pos { color: var(--green); font-weight:600; }
.sap-neg { color: var(--red); font-weight:600; }
.sap-warn { color: var(--amber); font-weight:600; }
.sap-pill { display:inline-block; font-size:10.5px; font-weight:700; padding:2px 8px; border-radius:999px; letter-spacing:.04em; text-transform:uppercase; vertical-align:2px; }
.sap-section-head { display:flex; align-items:baseline; gap:12px; margin:24px 0 12px; padding-bottom:8px; border-bottom:1px solid var(--border); }
.sap-section-title { font-size:16px; font-weight:600; color: var(--text); letter-spacing:-.01em; }
.sap-section-sub { font-size:13px; color: var(--text-faint); }
.sap-explain { background: var(--explain-bg); border:1px solid var(--explain-border); border-left:4px solid var(--explain-accent); border-radius: var(--radius-sm); padding:12px 16px; font-size:13.5px; color: var(--explain-text); margin-bottom:12px; }
.sap-explain b { color: var(--explain-text); font-weight:700; }
.sap-empty { text-align:center; padding:40px 20px; color: var(--text-faint); font-size:13.5px; border:1px dashed var(--border-strong); border-radius: var(--radius); background: var(--surface); }
.sap-brand { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
.sap-brand-mark { width:30px; height:30px; background: linear-gradient(135deg, var(--navy) 0%, var(--accent) 100%); border-radius:7px; display:inline-flex; align-items:center; justify-content:center; color:#fff; font-weight:700; font-size:14px; letter-spacing:-.04em; }
.sap-brand-name { font-size:19px; font-weight:600; letter-spacing:-.02em; color: var(--text); }
.sap-tag { display:inline-block; font-size:9.5px; background: var(--tag-bg); color:#fff; padding:2px 8px; border-radius:3px; font-weight:700; letter-spacing:.05em; vertical-align:4px; margin-left:8px; }
.sap-hero-rule { height:3px; width:54px; background: linear-gradient(90deg, var(--navy), var(--accent)); border-radius:2px; margin:2px 0 14px; }

/* Hide Streamlit chrome */
#MainMenu { visibility:hidden; }
footer { visibility:hidden; }
header [data-testid="stHeaderActionElements"] { display:none; }

a { color: var(--accent) !important; }
a:hover { color: var(--navy) !important; text-decoration:underline; }
label, .stRadio label, .stCheckbox label { color: var(--text) !important; }
hr { border-color: var(--border) !important; }

[data-testid="stVerticalBlockBorderWrapper"] {
  border:1px solid var(--border) !important; border-radius: var(--radius) !important;
  padding:16px 20px !important; background: var(--surface) !important; box-shadow: var(--shadow) !important;
}

/* === Modern clickable nav cards (home page) === */
.sap-navgrid { display:grid; grid-template-columns: repeat(3, 1fr); gap:14px; margin-bottom:8px; }
@media (max-width: 900px) { .sap-navgrid { grid-template-columns: repeat(2, 1fr); } }
.sap-navcard {
  display:flex; flex-direction:column; gap:5px;
  background: var(--surface); border:1px solid var(--border);
  border-radius: var(--radius-lg); padding:18px 18px 16px; min-height:148px;
  box-shadow: var(--shadow); text-decoration:none !important;
  transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
.sap-navcard:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); border-color: var(--accent); text-decoration:none !important; }
.sap-navcard-icon {
  width:38px; height:38px; display:flex; align-items:center; justify-content:center;
  background: var(--accent-bg); border-radius:10px; font-size:19px; margin-bottom:6px;
}
.sap-navcard-title { font-size:15.5px; font-weight:650; color: var(--text) !important; letter-spacing:-.01em; display:flex; align-items:center; gap:7px; }
.sap-navcard-new { font-size:8.5px; font-weight:700; letter-spacing:.06em; background: var(--green); color:#fff; padding:1px 6px; border-radius:999px; text-transform:uppercase; }
.sap-navcard-desc { font-size:12.5px; color: var(--text-faint) !important; line-height:1.45; flex:1; }
.sap-navcard-go { font-size:12.5px; font-weight:600; color: var(--accent) !important; margin-top:8px; }
.sap-navcard:hover .sap-navcard-go { text-decoration:none; }
.sap-group-label { font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color: var(--text-faint); margin:22px 0 10px; }

/* === Aurora glass — frost every translucent surface ===
   Backgrounds are already translucent via the theme vars; this adds the blur so
   the gradient shows through as frosted glass. (st.dataframe cells are canvas-
   rendered and stay opaque — the frame frosts, the grid doesn't.) */
.sap-card, .sap-kpi, .sap-empty, .sap-navcard, .sap-explain,
[data-testid="stMetric"], [data-testid="stExpander"],
[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stDataFrame"], .stDataFrame,
[data-testid="stSidebar"], .stButton > button,
.stTextInput input, .stNumberInput input, .stSelectbox > div > div {
  -webkit-backdrop-filter: var(--blur) !important;
  backdrop-filter: var(--blur) !important;
}

/* === Glass table — custom HTML table that actually frosts through the gradient === */
.gtbl-wrap {
  border-radius: var(--radius); overflow:hidden;
  background: var(--surface); border:1px solid var(--border);
  box-shadow: var(--shadow);
  -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
  margin-bottom:14px; max-height:620px; overflow-y:auto;
}
.gtbl { width:100%; border-collapse:collapse; font-size:13px; font-family: var(--font); }
.gtbl th {
  position:sticky; top:0; z-index:1;
  background: var(--surface-alt);
  -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
  text-align:left; padding:10px 13px; font-size:10px; letter-spacing:.06em;
  text-transform:uppercase; color: var(--text-faint); font-weight:700;
  border-bottom:1px solid var(--border);
}
.gtbl th.num { text-align:right; }
.gtbl td { padding:9px 13px; border-bottom:1px solid var(--border); color: var(--text); }
.gtbl td.num { text-align:right; font-family: var(--font-mono); font-variant-numeric:tabular-nums; }
.gtbl td.sym { font-weight:700; font-family: var(--font-mono); color: var(--accent); }
.gtbl tr:hover td { background: var(--accent-bg); }
.gtbl td.up { color: var(--green); font-weight:600; }
.gtbl td.dn { color: var(--red); font-weight:600; }
.gtbl .pill { display:inline-block; font-size:9px; font-weight:700; padding:2px 7px;
  border-radius:99px; letter-spacing:.04em; text-transform:uppercase; }
.gtbl .p-s { background: var(--green-bg); color: var(--green); }
.gtbl .p-o { background: var(--accent-bg); color: var(--accent); }
.gtbl .p-w { background: var(--amber-bg); color: var(--amber); }
.gtbl .new-badge { font-size:7.5px; font-weight:800; background: var(--green); color:#fff;
  padding:1px 5px; border-radius:99px; text-transform:uppercase; letter-spacing:.04em; }
.gtbl .wl-row td { background: var(--accent-bg); }
"""


def inject_global_css():
    # Dark-mode toggle lives at the very top of the sidebar on every page. Opt-in;
    # default is light, so the existing light experience is never altered unless asked.
    st.sidebar.toggle("🌗 Dark mode", key="sap_dark",
                      help="Easier on the eyes for long sessions. Default is light.")
    dark = bool(st.session_state.get("sap_dark", False))
    css = "<style>" + _FONTS + _LIGHT_VARS + (_DARK_VARS if dark else "") + _BODY_CSS + "</style>"
    st.markdown(css, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def page_header(title: str, subtitle: str = "", icon: str = "", live: bool = False):
    live_tag = '<span class="sap-tag">LIVE</span>' if live else ""
    icon_html = f'<span style="margin-right:8px">{icon}</span>' if icon else ""
    st.markdown(
        f"""<div class="sap-brand">
<div class="sap-brand-mark">SA</div>
<div class="sap-brand-name">Stock Analysis{live_tag}</div>
</div>
<h1 style="margin:6px 0 4px;color:var(--text)">{icon_html}{title}</h1>
<div class="sap-hero-rule"></div>
<p style="color:var(--text-muted);font-size:14px;margin:0 0 14px">{subtitle}</p>""",
        unsafe_allow_html=True,
    )


def section_head(title: str, subtitle: str = "", anchor: str = ""):
    anchor_attr = f' id="{anchor}"' if anchor else ""
    st.markdown(
        f"""<div class="sap-section-head"{anchor_attr}>
<span class="sap-section-title">{title}</span>
<span class="sap-section-sub">{subtitle}</span>
</div>""",
        unsafe_allow_html=True,
    )


def kpi_tile(label: str, value: str, sub: str = "", tone: str = ""):
    tone_cls = f" {tone}" if tone else ""
    sub_html = f'<div class="sap-kpi-sub">{sub}</div>' if sub else ""
    st.markdown(
        f"""<div class="sap-kpi{tone_cls}">
<div class="sap-kpi-label">{label}</div>
<div class="sap-kpi-value">{value}</div>
{sub_html}
</div>""",
        unsafe_allow_html=True,
    )


def pill(text: str, color: str = "gray") -> str:
    bg, fg = COLOR_PAIRS.get(color, COLOR_PAIRS["gray"])
    return f'<span class="sap-pill" style="background:{bg};color:{fg}">{text}</span>'


def score_card(label: str, value: str, sub: str, color: str = "gray",
               tag: str = "", height: int = 165) -> str:
    """Polished score card HTML. Vivid colors that pop on light bg."""
    bg, fg = COLOR_PAIRS.get(color, COLOR_PAIRS["gray"])
    tag_html = f'<div style="font-size:10.5px;color:var(--text);text-transform:uppercase;letter-spacing:.05em;font-weight:700;margin-bottom:4px">{tag}</div>' if tag else ""
    return (
        f'<div style="background:{bg};border:1px solid {fg};border-left:5px solid {fg};'
        f'padding:14px 16px;border-radius:8px;height:{height}px;display:flex;flex-direction:column;justify-content:space-between;color:var(--text);box-shadow:var(--shadow)">'
        f'{tag_html}'
        f'<div>'
        f'<div style="font-size:13.5px;font-weight:700;color:{fg};margin-bottom:3px;letter-spacing:-.01em">{label}</div>'
        f'<div style="font-size:26px;font-weight:700;color:{fg};line-height:1.05;font-family:var(--font-mono);font-variant-numeric:tabular-nums;margin:4px 0">{value}</div>'
        f'</div>'
        f'<div style="font-size:12px;color:var(--text);line-height:1.4;font-weight:500">{sub}</div>'
        f'</div>'
    )


def verdict_box(label: str, headline: str, body: str, color: str = "gray"):
    bg, fg = COLOR_PAIRS.get(color, COLOR_PAIRS["gray"])
    st.markdown(
        f"""<div style="background:{bg};border:1px solid {fg};border-left:6px solid {fg};
padding:16px 20px;border-radius:8px;margin-bottom:16px;color:var(--text);box-shadow:var(--shadow)">
<div style="font-size:11px;color:var(--text);text-transform:uppercase;letter-spacing:.05em;font-weight:700;opacity:.7">{label}</div>
<div style="font-size:24px;font-weight:700;color:{fg};margin:6px 0 6px;letter-spacing:-.01em">{headline}</div>
<div style="font-size:13.5px;line-height:1.6;color:var(--text)">{body}</div>
</div>""",
        unsafe_allow_html=True,
    )


def explain_panel(plain: str):
    st.markdown(f'<div class="sap-explain"><b>What you\'re looking at:</b> {plain}</div>',
                unsafe_allow_html=True)


def empty_state(message: str):
    st.markdown(f'<div class="sap-empty">{message}</div>', unsafe_allow_html=True)


def nav_card(href: str, icon: str, title: str, desc: str, new: bool = False) -> str:
    """A modern, fully-clickable navigation card (whole card is the link)."""
    badge = '<span class="sap-navcard-new">new</span>' if new else ""
    return (
        f'<a class="sap-navcard" href="{href}" target="_self">'
        f'<div class="sap-navcard-icon">{icon}</div>'
        f'<div class="sap-navcard-title">{title}{badge}</div>'
        f'<div class="sap-navcard-desc">{desc}</div>'
        f'<div class="sap-navcard-go">Open →</div>'
        f'</a>'
    )


def nav_grid(cards: list[dict]):
    """Render a responsive 3-up grid of clickable nav cards.
    Each card dict: {href, icon, title, desc, new?}."""
    html = '<div class="sap-navgrid">' + "".join(
        nav_card(c["href"], c.get("icon", ""), c["title"], c["desc"], c.get("new", False))
        for c in cards
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def group_label(text: str):
    st.markdown(f'<div class="sap-group-label">{text}</div>', unsafe_allow_html=True)


def glass_table(columns: list[dict], rows: list[dict], max_height: int = 560):
    """Render a frosted-glass HTML table that shows the gradient through it.

    columns: list of {key, label, align?:'num', cls?:'sym'|'up'|'dn'}
    rows: list of dicts keyed by column key. Special keys:
      _row_cls: extra class on <tr> (e.g. 'wl-row' for watchlist highlight)
    """
    import html as _html

    hdr = "".join(
        f'<th class="{c.get("align","")}">{_html.escape(c["label"])}</th>'
        for c in columns
    )
    body = []
    for r in rows:
        rcls = f' class="{r["_row_cls"]}"' if r.get("_row_cls") else ""
        cells = []
        for c in columns:
            val = r.get(c["key"], "")
            raw = _html.escape(str(val)) if not str(val).startswith("<") else str(val)
            align = c.get("align", "")
            cls = c.get("cls", "")
            # Auto-color: detect +/- for up/dn
            extra = ""
            sv = str(val)
            if align == "num" and sv.startswith("+") and not cls:
                extra = " up"
            elif align == "num" and sv.startswith("-") and sv not in ("—",):
                extra = " dn"
            cell_cls = " ".join(filter(None, [align, cls, extra])).strip()
            cells.append(f'<td class="{cell_cls}">{raw}</td>')
        body.append(f'<tr{rcls}>{"".join(cells)}</tr>')

    st.markdown(
        f'<div class="gtbl-wrap" style="max-height:{max_height}px">'
        f'<table class="gtbl"><thead><tr>{hdr}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def freshness_note(prefix: str = "Data loaded") -> str:
    """A 'loaded at HH:MM' string for data-freshness captions. Call at render time
    (not inside a cached function) so it reflects the actual page load."""
    from datetime import datetime
    # %I (zero-padded 12-hour) is Windows-safe; %-I is not.
    return f"🕒 {prefix} {datetime.now().strftime('%b %d, %I:%M %p')}"


def sparkline_svg(values: list, color: str = "#1e3a8a",
                  width: int = 160, height: int = 36, fill: bool = True,
                  show_endpoints: bool = True) -> str:
    """Inline SVG sparkline. No plotly, no dependencies, instant render.

    Returns an <svg> string ready to drop into st.markdown(..., unsafe_allow_html=True).
    Args:
      values: list of floats (None values are skipped)
      color: stroke color hex
      width / height: pixels
      fill: if True, render translucent area under the line
      show_endpoints: dot at first and last point
    """
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return f'<svg width="{width}" height="{height}"></svg>'

    vmin = min(clean)
    vmax = max(clean)
    rng = (vmax - vmin) or 1
    pad = 3
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    pts = []
    for i, v in enumerate(clean):
        x = pad + (i / (len(clean) - 1)) * inner_w
        y = pad + (1 - (v - vmin) / rng) * inner_h
        pts.append((x, y))

    line_path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    fill_path = ""
    if fill:
        fill_pts = pts + [(pts[-1][0], height - pad), (pts[0][0], height - pad)]
        fill_path = (f'<path d="M ' + " L ".join(f"{x:.1f} {y:.1f}" for x, y in fill_pts) +
                     f' Z" fill="{color}" fill-opacity="0.10" stroke="none"/>')

    # Choose endpoint dot color: green if last > first, red if last < first
    end_color = color
    if clean[-1] > clean[0]:
        end_color = "#0a5f3c"
    elif clean[-1] < clean[0]:
        end_color = "#8a1818"

    endpoints = ""
    if show_endpoints:
        first_x, first_y = pts[0]
        last_x, last_y = pts[-1]
        endpoints = (
            f'<circle cx="{first_x:.1f}" cy="{first_y:.1f}" r="2" fill="#6b6b6b"/>'
            f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.5" fill="{end_color}"/>'
        )

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block">'
        f'{fill_path}'
        f'<path d="{line_path}" stroke="{end_color}" stroke-width="1.5" fill="none" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'{endpoints}'
        f'</svg>'
    )


def kpi_tile_with_spark(label: str, value: str, sub: str, tone: str,
                        spark_values: list, spark_color: str = "#1e3a8a") -> str:
    """Return KPI tile HTML with a sparkline at the bottom. Renders into a column."""
    tone_cls = f" {tone}" if tone else ""
    spark = sparkline_svg(spark_values, color=spark_color, width=180, height=32, fill=True)
    return (
        f'<div class="sap-kpi{tone_cls}">'
        f'<div class="sap-kpi-label">{label}</div>'
        f'<div class="sap-kpi-value">{value}</div>'
        f'<div class="sap-kpi-sub">{sub}</div>'
        f'<div style="margin-top:6px">{spark}</div>'
        f'</div>'
    )


def chart_theme() -> dict:
    """Theme-aware Plotly colors (dark-mode-aware). One source of truth so every
    chart in the app matches and flips with the dark toggle."""
    dark = is_dark()
    return {
        # Slightly warm-tinted so charts don't sit as stark white islands on the Aurora gradient.
        "paper": "#181b22" if dark else "#f8f7fd",
        "plot": "#181b22" if dark else "#f8f7fd",
        "text": "#e7e9ee" if dark else "#0d0d0d",
        "grid": "rgba(255,255,255,.08)" if dark else "rgba(0,0,0,.06)",
        "axis": "rgba(255,255,255,.20)" if dark else "rgba(0,0,0,.12)",
        "ctrl_bg": "#20242d" if dark else "#f0eee8",
        "line": "#7aa2ff" if dark else "#1e3a8a",
        "font_family": "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    }


def style_fig(fig, height: int | None = None):
    """Apply the shared chart theme to any Plotly figure (used by the simpler
    charts that don't go through interactive_chart)."""
    t = chart_theme()
    fig.update_layout(
        paper_bgcolor=t["paper"], plot_bgcolor=t["plot"],
        font=dict(family=t["font_family"], size=12, color=t["text"]),
        **({"height": height} if height else {}),
    )
    fig.update_xaxes(gridcolor=t["grid"], zerolinecolor=t["grid"], linecolor=t["axis"])
    fig.update_yaxes(gridcolor=t["grid"], zerolinecolor=t["grid"], linecolor=t["axis"])
    return fig


def interactive_chart(dates, values, title: str = "", color: str = "#1e3a8a",
                      range_selector: bool = True, range_slider: bool = True,
                      height: int = 520, dma_overlays: list = None,
                      y_title: str = None, is_currency: bool = True):
    """Return a stock-app-style Plotly Figure with full interactivity.

    Features:
      - Hover crosshair with date + value tooltip (x-unified)
      - Range selector pills above (5D/1M/3M/6M/YTD/1Y/2Y/5Y/MAX)
      - Range slider below (drag to zoom into any period)
      - Optional moving-average overlays
      - Plotly modebar with built-in fullscreen, zoom, pan, autoscale, download

    Args:
      dates: list of date-like values (pd.Timestamp or datetime)
      values: list of floats (close prices typically)
      dma_overlays: optional list of tuples (name, values, color, dash_style)
        e.g. [("50 DMA", ma50, "#9a6500", "dot"), ("200 DMA", ma200, "#8a1818", "solid")]
    """
    import plotly.graph_objects as go

    _t = chart_theme()
    if color == "#1e3a8a":          # default navy → lighten for dark mode
        color = _t["line"]
    fig = go.Figure()
    # Convert hex color to rgba for fill (plotly fillcolor doesn't accept 8-char hex)
    def _hex_to_rgba(hex_color: str, alpha: float = 0.12) -> str:
        h = hex_color.lstrip("#")
        if len(h) == 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"rgba({r},{g},{b},{alpha})"
        return f"rgba(30,58,138,{alpha})"  # navy fallback

    fill_color = _hex_to_rgba(color, 0.12)
    fig.add_trace(go.Scatter(
        x=dates, y=values, mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy", fillcolor=fill_color,
        hovertemplate="<b>%{x|%b %d, %Y}</b><br>" +
                      ("$%{y:,.2f}" if is_currency else "%{y:.2f}") +
                      "<extra></extra>",
        name="Close",
    ))

    # Optional DMA overlays
    if dma_overlays:
        for name, dma_vals, dma_color, dash in dma_overlays:
            fig.add_trace(go.Scatter(
                x=dates, y=dma_vals, mode="lines",
                line=dict(color=dma_color, width=1.4, dash=dash),
                name=name,
                hovertemplate=f"{name}: " +
                              ("$%{y:,.2f}" if is_currency else "%{y:.2f}") +
                              "<extra></extra>",
            ))

    # Layout
    layout = dict(
        title=dict(text=title, font=dict(size=15, color=_t["text"])) if title else None,
        height=height,
        hovermode="x unified",
        margin=dict(l=10, r=10, t=60 if title else 30, b=10),
        plot_bgcolor=_t["plot"],
        paper_bgcolor=_t["paper"],
        font=dict(family=_t["font_family"], size=12, color=_t["text"]),
        showlegend=bool(dma_overlays),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    bgcolor=_t["paper"], bordercolor=_t["axis"], borderwidth=1),
    )

    xaxis = dict(showgrid=False, zeroline=False, showline=True,
                 linecolor=_t["axis"])
    if range_selector:
        xaxis["rangeselector"] = dict(
            buttons=[
                dict(count=5, label="5D", step="day", stepmode="backward"),
                dict(count=1, label="1M", step="month", stepmode="backward"),
                dict(count=3, label="3M", step="month", stepmode="backward"),
                dict(count=6, label="6M", step="month", stepmode="backward"),
                dict(count=1, label="YTD", step="year", stepmode="todate"),
                dict(count=1, label="1Y", step="year", stepmode="backward"),
                dict(count=2, label="2Y", step="year", stepmode="backward"),
                dict(count=5, label="5Y", step="year", stepmode="backward"),
                dict(step="all", label="MAX"),
            ],
            bgcolor=_t["ctrl_bg"],
            activecolor=_t["line"],
            font=dict(size=11, color=_t["text"]),
            x=0, y=1.08, xanchor="left",
            bordercolor=_t["axis"], borderwidth=1,
        )
    if range_slider:
        xaxis["rangeslider"] = dict(visible=True, thickness=0.06,
                                    bgcolor=_t["ctrl_bg"], bordercolor=_t["axis"])
    layout["xaxis"] = xaxis

    layout["yaxis"] = dict(
        title=dict(text=y_title) if y_title else None,
        showgrid=True, gridcolor=_t["grid"],
        zeroline=False,
        tickformat="$,.2f" if is_currency else ",.2f",
        side="right",
    )

    fig.update_layout(**layout)
    return fig


def chart_config() -> dict:
    """Plotly config for st.plotly_chart: modebar always visible with useful buttons."""
    return {
        "displayModeBar": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
        "toImageButtonOptions": {"format": "png", "scale": 2},
        "responsive": True,
    }


def actual_value(text: str) -> str:
    """Return an inline-styled value chip — replaces st.code() which renders dark."""
    return (f'<div style="display:inline-block;background:var(--surface-alt);border:1px solid var(--border);'
            f'border-radius:4px;padding:5px 10px;font-family:var(--font-mono);'
            f'font-size:12.5px;font-weight:500;color:var(--text);font-variant-numeric:tabular-nums">{text}</div>')


# Money/percent formatting now lives in lib/fmt.py (single source of truth).
# Re-exported here so existing `ui.fmt_money(...)` call sites keep working.
fmt_money = _fmt.fmt_money
fmt_pct = _fmt.fmt_pct
fmt_delta_pct = _fmt.fmt_delta_pct


def tone_from_pct(v: float | None, threshold_pos: float = 0, threshold_neg: float = 0) -> str:
    if v is None: return ""
    if v > threshold_pos: return "pos"
    if v < threshold_neg: return "neg"
    return ""


def thesis_card(thesis: dict, grade_bar: dict, bottom_line: str, simple_mode: bool = False):
    """Render the structured investment thesis card with grade bar and bottom-line summary."""
    stance = thesis.get("stance", {})
    color_map = {"darkgreen": "#0a5f3c", "green": "#16a34a", "amber": "#d97706", "red": "#dc2626"}
    accent = color_map.get(stance.get("color", ""), "#6b7280")

    # Stance + grade bar + bottom line
    st.markdown(f'''
    <div style="border-left:4px solid {accent}; padding:16px 20px; background:var(--surface); border-radius:0 12px 12px 0; margin-bottom:16px; box-shadow:var(--shadow)">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
            <span style="font-size:24px;font-weight:700;color:{accent}">{stance.get("label", "WATCH")}</span>
            <span style="font-size:13px;color:var(--text-muted)">&mdash; {stance.get("rationale", "")}</span>
        </div>
        <div style="display:flex;gap:24px;margin-bottom:16px;font-size:13px">
            <span>{grade_bar["valuation"]["emoji"]} Valuation: <b>{grade_bar["valuation"]["grade"]}</b></span>
            <span>{grade_bar["quality"]["emoji"]} Quality: <b>{grade_bar["quality"]["grade"]}</b></span>
            <span>{grade_bar["momentum"]["emoji"]} Momentum: <b>{grade_bar["momentum"]["grade"]}</b></span>
        </div>
        <div style="font-size:14px;line-height:1.6;color:var(--text);margin-bottom:16px">{bottom_line}</div>
    </div>
    ''', unsafe_allow_html=True)

    # Bull/Bear columns
    if not simple_mode:
        bc, brc = st.columns(2)
        with bc:
            st.markdown("**✅ Bull case**")
            for b in thesis.get("bull", []):
                st.markdown(f"- {b}")
        with brc:
            st.markdown("**❌ Bear case**")
            for b in thesis.get("bear", []):
                st.markdown(f"- {b}")
        if thesis.get("breaks_if"):
            st.markdown("**⚡ Thesis breaks if:**")
            for b in thesis["breaks_if"]:
                st.markdown(f"- {b}")
    else:
        # Simple mode: show abbreviated bull/bear
        bc, brc = st.columns(2)
        with bc:
            st.markdown("**✅ Reasons to buy**")
            for b in thesis.get("bull", [])[:3]:
                st.markdown(f"- {b}")
        with brc:
            st.markdown("**❌ Reasons to wait**")
            for b in thesis.get("bear", [])[:3]:
                st.markdown(f"- {b}")
