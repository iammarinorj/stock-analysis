"""Discovery screeners via Finviz (finvizfinance package).

Each screen returns a DataFrame of tickers + metrics matching a style.
Cached aggressively (15-30 min) since results don't change intraday much.

Styles (mapped to Finviz filter dicts):
  - deep_value:        low P/E, low P/B, US, $300M+ cap
  - cigar_butt:        very low P/B, current ratio > 2, positive cash
  - quality_compounder: high ROE, low D/E, FCF positive, $2B+ cap
  - garp:              PEG < 1.5, EPS growth 5Y > 15%, ROE > 15%
  - growth:            EPS growth next 5Y > 25%, sales growth > 20%
  - high_yield:        dividend yield > 4%, payout < 70%, low debt
  - momentum:          50DMA > 200DMA, RSI 50-70, price near 52w high
  - insider_buys:      insider buying recent
  - fallen_angels:     near 52w low + still profitable + low debt
  - special_situations: small cap + insider buys + recent earnings beat
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


STYLE_FILTERS: dict[str, dict] = {
    "deep_value": {
        "P/E": "Under 15",
        "P/B": "Under 2",
        "Country": "USA",
        "Market Cap.": "+Small (over $300mln)",
        "Average Volume": "Over 100K",
        "Debt/Equity": "Under 1",
    },
    "cigar_butt": {
        "P/B": "Under 1",
        "Country": "USA",
        "Market Cap.": "+Micro (over $50mln)",
        "Current Ratio": "Over 2",
        "Average Volume": "Over 50K",
    },
    "quality_compounder": {
        "Return on Equity": "Over +20%",
        "Return on Investment": "Over +15%",
        "Gross Margin": "Over 40%",
        "Operating Margin": "Over 15%",
        "Debt/Equity": "Under 0.5",
        "Country": "USA",
        "Market Cap.": "+Mid (over $2bln)",
    },
    "garp": {
        "PEG": "Under 1",
        "EPS growthpast 5 years": "Over 15%",
        "EPS growthnext 5 years": "Over 15%",
        "Return on Equity": "Over +15%",
        "Country": "USA",
        "Market Cap.": "+Small (over $300mln)",
    },
    "growth": {
        "EPS growthnext 5 years": "Over 25%",
        "Sales growthpast 5 years": "Over 20%",
        "Gross Margin": "Over 40%",
        "Country": "USA",
        "Market Cap.": "+Small (over $300mln)",
    },
    "high_yield": {
        "Dividend Yield": "Over 4%",
        "Payout Ratio": "Under 70%",
        "Debt/Equity": "Under 1",
        "Country": "USA",
        "Market Cap.": "+Mid (over $2bln)",
    },
    "momentum": {
        "200-Day Simple Moving Average": "Price above SMA200",
        "50-Day Simple Moving Average": "SMA50 above SMA200",
        "RSI (14)": "Not Overbought (<60)",
        "Performance": "Quarter Up",
        "Country": "USA",
        "Average Volume": "Over 500K",
    },
    "insider_buys": {
        "InsiderTransactions": "Very Positive (>20%)",
        "Country": "USA",
        "Average Volume": "Over 100K",
    },
    "fallen_angels": {
        "52-Week High/Low": "30% or more below High",
        "Return on Equity": "Over +10%",
        "Debt/Equity": "Under 1",
        "Country": "USA",
        "Market Cap.": "+Mid (over $2bln)",
        "Average Volume": "Over 200K",
    },
    "special_situations": {
        "Market Cap.": "Small ($300mln to $2bln)",
        "InsiderTransactions": "Positive (>0%)",
        "EPS growthqtr over qtr": "Over 25%",
        "Country": "USA",
    },
    "inflection": {
        # PURE sales acceleration. NO profitability gate, NO forward-EPS gate.
        # This is what actually catches AAOI/AEVA/COHR/CEG — companies in deep inflection
        # where Finviz says "N/A" on forward EPS because the turn just started.
        # The Fit Score below ranks within these by other quality signals.
        "Sales growthqtr over qtr": "Over 20%",
        "Country": "USA",
        "Market Cap.": "+Small (over $300mln)",
        "Average Volume": "Over 200K",
    },
    "chokepoint": {
        # Established critical suppliers with pricing power. AVGO/ASML/CDNS/SNPS/MRVL territory.
        # Strong gross margin = chokepoint signal. ROE > industry avg = excess returns.
        "Gross Margin": "Over 50%",                  # pricing power
        "Return on Equity": "Over +15%",              # capital efficiency
        "Sales growthpast 5 years": "Over 10%",      # sustained demand
        "Market Cap.": "+Mid (over $2bln)",          # established business
        "Country": "USA",
        "Average Volume": "Over 500K",
        # Sector-agnostic — chokepoints exist everywhere
    },
    "datacenter_buildout": {
        # AI datacenter capex shovel-sellers: power, cooling, EMS, connectivity, optics.
        # Mostly Industrials + Tech mid-caps. VRT/ETN/MOD/POWL/GEV/JBL/CRDO/AAOI.
        "Sales growthqtr over qtr": "Over 15%",
        "EPS growthqtr over qtr": "Over 15%",
        "Return on Equity": "Over +15%",
        "Country": "USA",
        "Market Cap.": "+Small (over $300mln)",
        "Average Volume": "Over 300K",
    },
    "foreign_chokepoint": {
        # Foreign + micro-cap chokepoint hunters. Sivers, ASML, TSM, AIXTRON, Soitec etc.
        # Loosens Country, drops volume restriction, allows micro caps.
        # Finviz Foreign filter + we ALSO surface a curated allowlist below for OTC pinks
        # that don't appear in standard Finviz screens.
        "Country": "Foreign (ex-USA)",
        "Sales growthqtr over qtr": "Over 20%",
        "Average Volume": "Over 50K",
        "Market Cap.": "+Micro (over $50mln)",
    },
}

# Allowlist: foreign chokepoint tickers Finviz won't screen reliably.
# These are surfaced regardless of the Finviz screen results.
# (Add more as you find them — many are micro-caps on foreign exchanges or US OTC pinks.)
FOREIGN_CHOKEPOINT_ALLOWLIST = [
    # Photonics / InP / EML
    ("SIVE.ST", "Sivers Semiconductors AB",  "InP photonic ICs (Swedish — direct AI optics play)"),
    ("SIVEF",   "Sivers Semiconductors AB",  "US OTC pink sheet for Sivers (same company)"),
    # Lithography / semicap
    ("ASML",    "ASML Holding NV",           "EUV lithography monopoly (Netherlands ADR)"),
    ("ASMIY",   "ASM International NV",      "ALD deposition equipment (Netherlands)"),
    ("BESIY",   "BE Semiconductor Industries","Advanced packaging tools (Netherlands)"),
    # Foundries
    ("TSM",     "Taiwan Semiconductor",      "Leading-edge foundry monopoly"),
    ("UMC",     "United Microelectronics",   "Mature-node foundry (Taiwan)"),
    # MOCVD / GaAs / SiC
    ("AIXG",    "AIXTRON SE",                "MOCVD reactors for compound semis (Germany)"),
    ("AIXA.DE", "AIXTRON SE",                "AIXTRON primary German listing"),
    # SiC + power
    ("IFNNY",   "Infineon Technologies",     "Power semis + auto (Germany ADR)"),
    ("STM",     "STMicroelectronics",        "Power semis + SiC (France/Italy ADR)"),
    # Photonics specialty / SOI
    ("SOITF",   "Soitec SA",                 "SOI wafers (France OTC pink, photonics enabler)"),
    # Lasers / optics components
    ("IPGP",    "IPG Photonics",             "Fiber lasers (US but often overlooked)"),
    ("LASR",    "nLIGHT Inc",                "Industrial + defense lasers"),
    # Sensors
    ("AMS-CH",  "ams OSRAM",                 "Optical sensors (Austria/Swiss)"),
    # AI accelerators / connectivity (Korea/Japan)
    ("000660.KS", "SK Hynix",                "HBM memory monopoly w/ Samsung"),
    ("005930.KS", "Samsung Electronics",     "HBM + foundry + display"),
    ("ADYEN.AS",  "Adyen NV",                "Payments chokepoint (Netherlands)"),
]


STYLE_LABELS = {
    "deep_value": "Deep Value (Graham)",
    "cigar_butt": "Cigar Butts (Graham)",
    "quality_compounder": "Quality Compounders (Buffett/Munger)",
    "garp": "GARP (Lynch)",
    "growth": "Hyper-Growth (Fisher / O'Neil)",
    "high_yield": "Dividend Aristocrats",
    "momentum": "Momentum Leaders",
    "insider_buys": "Insider Cluster Buys",
    "fallen_angels": "Fallen Angels (quality at 30%+ off)",
    "special_situations": "Special Situations (small cap + insider + beat)",
    "inflection": "Inflection / Emerging Hypergrowth (AAOI-style — pure sales acceleration, no profit gate)",
    "chokepoint": "Chokepoint Suppliers (established critical-position monopolies)",
    "datacenter_buildout": "AI Datacenter Buildout (power/cooling/optics/EMS)",
    "foreign_chokepoint": "Foreign + Micro-cap Chokepoints (Sivers/ASML/TSM/AIXG-style)",
}

STYLE_DESCRIPTIONS = {
    "deep_value": "Classic Graham screen: cheap on P/E and P/B with manageable debt. Most pop out as banks, insurance, basic materials.",
    "cigar_butt": "Trading below book value with strong current ratio. One good puff left. High failure rate but lottery upside.",
    "quality_compounder": "High ROE + high ROIC + low debt + profitable. Buffett's '$1 of equity, $1+ of market value' test, applied broadly.",
    "garp": "Growth At Reasonable Price: PEG < 1, 5-year EPS growth >15%, ROE >15%. Lynch's PEG world.",
    "growth": "Earnings growth >25% next 5yr + gross margin >40%. Most likely to be SaaS/biotech/semis.",
    "high_yield": "Yield >4%, payout <70%, manageable debt. Income with safety.",
    "momentum": "Stage-2 trends with healthy RSI. O'Neil/Minervini territory.",
    "insider_buys": "Insider net buying >20% over 6mo. Strongest single signal in the toolbox.",
    "fallen_angels": "30%+ below 52w high but still profitable with manageable debt. Mean-reversion candidates.",
    "special_situations": "Small cap with insider buying and big EPS beat last quarter. Hunting ground for outsized returns.",
    "inflection": "Companies in deep inflection where sales are accelerating >20% Q/Q but forward EPS may still be N/A (Finviz can't model profits yet). Pure sales-acceleration funnel with no profitability gate — designed to catch AAOI / AEVA / COHR / CEG / ALAB / ANET / AVGO before they show up in any other screen. The Fit Score ranks within results by gross margin, balance sheet, and sector quality.",
    "chokepoint": "Established critical-position suppliers with pricing power: high gross margin (>50% = moat), high ROE, sustained 5y growth. AVGO/CDNS/SNPS/MRVL/ANET territory. The 'shovel sellers' you want to own forever in any secular wave.",
    "datacenter_buildout": "Companies winning the AI datacenter capex wave: power (CEG/VST/GEV/ETN), cooling (VRT/MOD), optics (AAOI/CRDO/COHR), EMS (JBL/FLEX), connectivity (ANET/ALAB). Sector-agnostic — catches the full picks-and-shovels stack.",
    "foreign_chokepoint": "Foreign + micro-cap chokepoints that USA/$300M+ screens miss. Sivers Semiconductors (InP photonics), ASML (EUV monopoly), TSM (foundry), AIXTRON (MOCVD), Soitec (SOI), Infineon (SiC power). Loosens Country, volume, and cap filters. Also surfaces an editable allowlist of known foreign critical suppliers — useful for catching the NEXT ASML at micro-cap stage.",
}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_industry_peers(symbol: str, limit: int = 8) -> list[str]:
    """Largest same-industry peers via the Finviz screener.

    Uses the subject's own Finviz industry string (so the filter value always
    matches), screens that industry ordered by market cap descending, and drops
    the subject itself. Tries a $300M+ cap floor first for meaningful comparables,
    then falls back to no floor if the industry is too small to fill the list.

    Returns [] on any failure — callers (peer table, sector medians) then behave
    exactly as they did before peer auto-discovery existed.
    """
    from lib import finviz as _fv
    from lib import http as _http

    fund = _fv.get_finviz_fundament(symbol)
    industry = (fund or {}).get("industry")
    if not industry:
        return []

    def _screen(extra_filters: dict) -> list[str]:
        def _run():
            from finvizfinance.screener.overview import Overview
            ov = Overview()
            ov.set_filter(filters_dict={"Industry": industry, **extra_filters})
            return ov.screener_view(order="Market Cap.", limit=limit + 6,
                                    ascend=False, verbose=0)
        df = _http.with_retry(_run, attempts=2, backoff=0.5)
        if df is None or getattr(df, "empty", True) or "Ticker" not in df.columns:
            return []
        sym_u = symbol.upper()
        return [t for t in df["Ticker"].tolist() if t and t.upper() != sym_u]

    peers = _screen({"Market Cap.": "+Small (over $300mln)", "Country": "USA"})
    if len(peers) < 3:
        # Industry may be mostly micro-cap or non-US — widen to fill the list.
        peers = _screen({}) or peers
    return peers[:limit]


# Per-style "best-fit" sort order to escape Finviz's alphabetical default. The
# screen is pulled by THIS metric (and by market cap) and unioned, so results
# span the whole alphabet instead of just A-names. Field strings must be valid
# finvizfinance order options; anything invalid falls back to market cap.
STYLE_ORDER: dict[str, tuple[str, bool]] = {
    "deep_value":          ("P/E", True),                      # cheapest first
    "cigar_butt":          ("P/B", True),
    "quality_compounder":  ("Return on Equity", False),
    "garp":                ("PEG", True),
    "growth":              ("Sales growth past 5 years", False),
    "high_yield":          ("Dividend Yield", False),
    "momentum":            ("Performance (Year)", False),
    "insider_buys":        ("Market Cap.", False),
    "fallen_angels":       ("Performance (Year)", True),        # worst performers (near lows)
    "special_situations":  ("Market Cap.", False),
    "inflection":          ("Sales growth past 5 years", False),
    "chokepoint":          ("Return on Equity", False),
    "datacenter_buildout": ("Market Cap.", False),
    "foreign_chokepoint":  ("Market Cap.", False),
}


@st.cache_data(ttl=1800, show_spinner=False)
def run_screen(style: str, view: str = "valuation", limit: int = 30,
               order: str = "Market Cap.", ascend: bool = False) -> pd.DataFrame:
    """Run a named style screen.

    view: 'overview' | 'valuation' | 'financial' | 'ownership' | 'performance' | 'technical'
    """
    if style not in STYLE_FILTERS:
        return pd.DataFrame()
    filters = STYLE_FILTERS[style]
    try:
        if view == "valuation":
            from finvizfinance.screener.valuation import Valuation
            s = Valuation()
        elif view == "financial":
            from finvizfinance.screener.financial import Financial
            s = Financial()
        elif view == "ownership":
            from finvizfinance.screener.ownership import Ownership
            s = Ownership()
        elif view == "performance":
            from finvizfinance.screener.performance import Performance
            s = Performance()
        elif view == "technical":
            from finvizfinance.screener.technical import Technical
            s = Technical()
        else:
            from finvizfinance.screener.overview import Overview
            s = Overview()
        s.set_filter(filters_dict=filters)
        try:
            df = s.screener_view(order=order, limit=limit, ascend=ascend, verbose=0)
        except Exception:
            # Invalid order string for this Finviz build — fall back to default order.
            df = s.screener_view(limit=limit, verbose=0)
        return df if df is not None else pd.DataFrame()
    except Exception:
        # Filter dictionary may have changed format on Finviz side; return empty
        return pd.DataFrame()


def _pull_view_multi(style: str, view: str, limit: int, orders: list[tuple[str, bool]]) -> pd.DataFrame:
    """Pull one Finviz view across multiple sort orders and union by Ticker.
    De-biases Finviz's alphabetical default so results span the whole alphabet."""
    frames = []
    for field, asc in orders:
        d = run_screen(style, view, limit=limit, order=field, ascend=asc)
        if d is not None and not d.empty:
            frames.append(d)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if "Ticker" in out.columns:
        out = out.drop_duplicates(subset="Ticker", keep="first").reset_index(drop=True)
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def run_combined_screen(style: str, limit: int = 75) -> pd.DataFrame:
    """Pull overview + valuation + financial and merge into one wide table.

    Each view is pulled across TWO sort orders — the style's best-fit metric and
    market cap (descending) — then unioned. This breaks Finviz's alphabetical
    bias: instead of 'the first N A-names', you get the strongest matches AND the
    biggest names across the entire alphabet. `limit` is per-order, so the unioned
    result is typically 1.5-2x larger.
    """
    # Pull across the style's own metric PLUS a spread of orthogonal axes (size,
    # quality, momentum, growth). Each axis surfaces different names, so the union
    # is broad and alphabet-agnostic. More orders = more complete = slower.
    _base_orders = [
        ("Market Cap.", False),
        ("Return on Equity", False),
        ("Performance (Year)", False),
        ("Sales growth past 5 years", False),
    ]
    primary = STYLE_ORDER.get(style, ("Market Cap.", False))
    orders: list[tuple[str, bool]] = [primary]
    for o in _base_orders:
        if o not in orders:
            orders.append(o)

    ov = _pull_view_multi(style, "overview", limit, orders)
    val = _pull_view_multi(style, "valuation", limit, orders)
    fin = _pull_view_multi(style, "financial", limit, orders)
    if val.empty and ov.empty:
        return fin
    if val.empty:
        base = ov
    else:
        base = val
        if not ov.empty:
            ov_cols = ["Ticker"] + [c for c in ["Company", "Sector", "Industry", "Country"] if c in ov.columns]
            base = base.merge(ov[ov_cols], on="Ticker", how="left")
    if not fin.empty:
        merge_cols = ["ROA", "ROE", "ROIC", "Gross M", "Oper M", "Profit M", "Debt/Eq"]
        cols_to_take = ["Ticker"] + [c for c in merge_cols if c in fin.columns]
        base = base.merge(fin[cols_to_take], on="Ticker", how="left")
    return base


def available_styles() -> list[str]:
    return list(STYLE_FILTERS.keys())


# ---------------------------------------------------------------------------
# Per-style fit scoring: ranks rows within a screen by philosophy strength.
# Uses only the columns we get back from Finviz (no extra network calls).
# ---------------------------------------------------------------------------

def _safe_num(v):
    try:
        if v is None: return None
        if isinstance(v, float) and v != v: return None  # NaN
        return float(v)
    except (TypeError, ValueError):
        return None


def _gt(v, thresh): return v is not None and v > thresh
def _lt(v, thresh): return v is not None and v < thresh
def _between(v, lo, hi): return v is not None and lo <= v <= hi


def _score_quality_compounder(row) -> tuple[int, int, list]:
    """Buffett-style. Higher ROE/ROIC, low debt, fat margins, fair PEG."""
    checks = [
        ("ROE > 25% (elite)",        _gt(_safe_num(row.get("ROE")),  0.25), 2),
        ("ROE > 15%",                _gt(_safe_num(row.get("ROE")),  0.15), 1),
        ("ROIC > 20% (elite)",       _gt(_safe_num(row.get("ROIC")), 0.20), 2),
        ("ROIC > 15%",               _gt(_safe_num(row.get("ROIC")), 0.15), 1),
        ("Gross margin > 50%",       _gt(_safe_num(row.get("Gross M")), 0.50), 2),
        ("Gross margin > 40%",       _gt(_safe_num(row.get("Gross M")), 0.40), 1),
        ("Op margin > 25%",          _gt(_safe_num(row.get("Oper M")), 0.25), 1),
        ("Op margin > 15%",          _gt(_safe_num(row.get("Oper M")), 0.15), 1),
        ("Debt/Eq < 0.3 (clean)",    _lt(_safe_num(row.get("Debt/Eq")), 0.30), 2),
        ("Debt/Eq < 0.5",            _lt(_safe_num(row.get("Debt/Eq")), 0.50), 1),
        ("PEG < 1 (fair growth)",    _between(_safe_num(row.get("PEG")), 0, 1.0), 1),
        ("Forward P/E < 25",         _between(_safe_num(row.get("Forward P/E")), 0, 25), 1),
    ]
    return _aggregate(checks)


def _score_deep_value(row) -> tuple[int, int, list]:
    """Graham. Cheap on P/E, P/B, P/FCF, low debt, profitable."""
    checks = [
        ("P/E < 8 (cheap)",          _between(_safe_num(row.get("P/E")), 0, 8), 2),
        ("P/E < 15",                 _between(_safe_num(row.get("P/E")), 0, 15), 1),
        ("P/B < 1 (net-net zone)",   _between(_safe_num(row.get("P/B")), 0, 1.0), 2),
        ("P/B < 2",                  _between(_safe_num(row.get("P/B")), 0, 2.0), 1),
        ("P/FCF < 10",               _between(_safe_num(row.get("P/FCF")), 0, 10), 2),
        ("Debt/Eq < 0.5",            _lt(_safe_num(row.get("Debt/Eq")), 0.50), 2),
        ("Debt/Eq < 1",              _lt(_safe_num(row.get("Debt/Eq")), 1.0), 1),
        ("ROE > 10% (profitable)",   _gt(_safe_num(row.get("ROE")), 0.10), 1),
    ]
    return _aggregate(checks)


def _score_cigar_butt(row) -> tuple[int, int, list]:
    """Graham extreme. Trading below book, current ratio cushion, any profitability."""
    checks = [
        ("P/B < 0.67 (Graham net-net)", _between(_safe_num(row.get("P/B")), 0, 0.67), 3),
        ("P/B < 1",                  _between(_safe_num(row.get("P/B")), 0, 1.0), 2),
        ("P/E < 10",                 _between(_safe_num(row.get("P/E")), 0, 10), 1),
        ("Positive ROE",             _gt(_safe_num(row.get("ROE")), 0), 1),
        ("Debt/Eq < 1",              _lt(_safe_num(row.get("Debt/Eq")), 1.0), 1),
    ]
    return _aggregate(checks)


def _score_garp(row) -> tuple[int, int, list]:
    """Lynch. Low PEG, double-digit growth, ROE."""
    checks = [
        ("PEG < 0.5 (deep GARP)",    _between(_safe_num(row.get("PEG")), 0, 0.5), 2),
        ("PEG < 1",                  _between(_safe_num(row.get("PEG")), 0, 1.0), 2),
        ("EPS next 5Y > 25%",        _gt(_safe_num(row.get("EPS Next 5Y")), 0.25), 2),
        ("EPS next 5Y > 15%",        _gt(_safe_num(row.get("EPS Next 5Y")), 0.15), 1),
        ("EPS past 5Y > 15%",        _gt(_safe_num(row.get("EPS Past 5Y")), 0.15), 1),
        ("ROE > 15%",                _gt(_safe_num(row.get("ROE")), 0.15), 1),
        ("Debt/Eq < 1",              _lt(_safe_num(row.get("Debt/Eq")), 1.0), 1),
    ]
    return _aggregate(checks)


def _score_growth(row) -> tuple[int, int, list]:
    """Fisher/O'Neil hypergrowth. Big growth, fat margins."""
    checks = [
        ("EPS next 5Y > 35%",        _gt(_safe_num(row.get("EPS Next 5Y")), 0.35), 2),
        ("EPS next 5Y > 25%",        _gt(_safe_num(row.get("EPS Next 5Y")), 0.25), 1),
        ("Sales past 5Y > 30%",      _gt(_safe_num(row.get("Sales Past 5Y")), 0.30), 2),
        ("Sales past 5Y > 20%",      _gt(_safe_num(row.get("Sales Past 5Y")), 0.20), 1),
        ("Gross margin > 50%",       _gt(_safe_num(row.get("Gross M")), 0.50), 2),
        ("Gross margin > 40%",       _gt(_safe_num(row.get("Gross M")), 0.40), 1),
        ("ROIC > 15%",               _gt(_safe_num(row.get("ROIC")), 0.15), 1),
    ]
    return _aggregate(checks)


def _score_high_yield(row) -> tuple[int, int, list]:
    """Generic dividend strength fit. Finviz overview has Dividend Yield."""
    dy = _safe_num(row.get("Dividend"))
    checks = [
        ("Dividend Yield > 5%",      _gt(dy, 0.05), 2),
        ("Dividend Yield > 3%",      _gt(dy, 0.03), 1),
        ("Debt/Eq < 1",              _lt(_safe_num(row.get("Debt/Eq")), 1.0), 1),
        ("ROE > 10%",                _gt(_safe_num(row.get("ROE")), 0.10), 1),
        ("Op margin > 10%",          _gt(_safe_num(row.get("Oper M")), 0.10), 1),
    ]
    return _aggregate(checks)


def _score_generic(row) -> tuple[int, int, list]:
    """Fallback: just check basic financial health."""
    checks = [
        ("ROE > 15%",                _gt(_safe_num(row.get("ROE")), 0.15), 1),
        ("Debt/Eq < 1",              _lt(_safe_num(row.get("Debt/Eq")), 1.0), 1),
        ("Op margin > 10%",          _gt(_safe_num(row.get("Oper M")), 0.10), 1),
        ("P/E < 25",                 _between(_safe_num(row.get("P/E")), 0, 25), 1),
    ]
    return _aggregate(checks)


def _aggregate(checks: list) -> tuple[int, int, list]:
    """Return (score, max_score, passed_labels)."""
    score = sum(w for _, passed, w in checks if passed)
    max_score = sum(w for _, _, w in checks)
    passed = [label for label, passed, _ in checks if passed]
    return score, max_score, passed


def _score_chokepoint(row) -> tuple[int, int, list]:
    """Established critical suppliers. Pricing power + capital efficiency + scale."""
    gm = _safe_num(row.get("Gross M"))
    roe = _safe_num(row.get("ROE"))
    roic = _safe_num(row.get("ROIC"))
    om = _safe_num(row.get("Oper M"))
    checks = [
        ("Gross margin > 60% (elite moat)", _gt(gm, 0.60), 3),
        ("Gross margin > 50%",              _gt(gm, 0.50), 2),
        ("ROIC > 20%",                       _gt(roic, 0.20), 2),
        ("ROIC > 15%",                       _gt(roic, 0.15), 1),
        ("ROE > 25%",                        _gt(roe, 0.25), 2),
        ("ROE > 15%",                        _gt(roe, 0.15), 1),
        ("Op margin > 30%",                  _gt(om, 0.30), 2),
        ("Op margin > 20%",                  _gt(om, 0.20), 1),
        ("Sales past 5Y > 10%",              _gt(_safe_num(row.get("Sales Past 5Y")), 0.10), 1),
        ("EPS next 5Y > 15%",                _gt(_safe_num(row.get("EPS Next 5Y")), 0.15), 1),
        ("Debt/Eq < 1",                      _lt(_safe_num(row.get("Debt/Eq")), 1.0), 1),
    ]
    return _aggregate(checks)


def _score_datacenter(row) -> tuple[int, int, list]:
    """Catches the AI datacenter capex wave winners. Mix of pricing power + growth."""
    eps_qoq = _safe_num(row.get("EPS This Y"))
    eps_5y = _safe_num(row.get("EPS Next 5Y"))
    sales_qoq = None  # not in basic Finviz views; using past growth proxy
    checks = [
        ("EPS next 5Y > 25%",                _gt(eps_5y, 0.25), 2),
        ("EPS next 5Y > 15%",                _gt(eps_5y, 0.15), 1),
        ("EPS this Y > 20%",                 _gt(eps_qoq, 0.20), 1),
        ("Gross margin > 30%",               _gt(_safe_num(row.get("Gross M")), 0.30), 1),
        ("ROE > 15%",                        _gt(_safe_num(row.get("ROE")), 0.15), 1),
        ("ROIC > 10%",                       _gt(_safe_num(row.get("ROIC")), 0.10), 1),
        ("Sales past 5Y > 15%",              _gt(_safe_num(row.get("Sales Past 5Y")), 0.15), 1),
        ("Debt/Eq < 1.5",                    _lt(_safe_num(row.get("Debt/Eq")), 1.5), 1),
    ]
    return _aggregate(checks)


def _score_inflection(row) -> tuple[int, int, list]:
    """Inflection / emerging hypergrowth. Pure sales-driven scoring.
    Rewards growth + gross margin + balance sheet. Does NOT require positive earnings.
    Bonus points when forward EPS / PEG exist (analyst conviction)."""
    sales_5y = _safe_num(row.get("Sales Past 5Y"))
    eps_5y = _safe_num(row.get("EPS Next 5Y"))
    gm = _safe_num(row.get("Gross M"))
    sector = str(row.get("Sector", ""))
    checks = [
        ("Sales past 5Y > 25%",          _gt(sales_5y, 0.25), 2),
        ("Sales past 5Y > 15%",          _gt(sales_5y, 0.15), 1),
        ("EPS next 5Y > 25% (analyst conviction)", _gt(eps_5y, 0.25), 1),
        ("Gross margin > 40% (pricing power)", _gt(gm, 0.40), 2),
        ("Gross margin > 25%",           _gt(gm, 0.25), 1),
        ("Debt/Eq < 1.5",                _lt(_safe_num(row.get("Debt/Eq")), 1.5), 1),
        ("Innovation sector (Tech/Comm/HC)",
         any(s in sector for s in ("Technology", "Communication", "Healthcare")), 1),
        ("PEG < 2 (when measurable)",    _between(_safe_num(row.get("PEG")), 0, 2.0), 1),
    ]
    return _aggregate(checks)


STYLE_SCORERS = {
    "quality_compounder": _score_quality_compounder,
    "deep_value": _score_deep_value,
    "cigar_butt": _score_cigar_butt,
    "garp": _score_garp,
    "growth": _score_growth,
    "high_yield": _score_high_yield,
    "momentum": _score_generic,
    "insider_buys": _score_quality_compounder,  # rank insider buy results by quality
    "fallen_angels": _score_quality_compounder,
    "special_situations": _score_garp,
    "inflection": _score_inflection,
    "chokepoint": _score_chokepoint,
    "datacenter_buildout": _score_datacenter,
    "foreign_chokepoint": _score_chokepoint,  # same quality bar applies
}


@st.cache_data(ttl=3600, show_spinner=False)
def get_allowlist_quotes() -> pd.DataFrame:
    """Pull live quotes for the curated foreign chokepoint allowlist via yfinance.
    Returns a DataFrame with columns aligned to the Finviz screen output so it can
    be merged or displayed alongside.
    """
    import yfinance as yf
    rows = []
    for ticker, name, note in FOREIGN_CHOKEPOINT_ALLOWLIST:
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            hist = t.history(period="2d", auto_adjust=False)
            price = float(hist["Close"].iloc[-1]) if not hist.empty else info.get("regularMarketPrice")
            rows.append({
                "Ticker": ticker,
                "Company": name,
                "Sector": info.get("sector", ""),
                "Country": info.get("country", ""),
                "Market Cap": info.get("marketCap"),
                "P/E": info.get("trailingPE"),
                "Forward P/E": info.get("forwardPE"),
                "PEG": info.get("trailingPegRatio") or info.get("pegRatio"),
                "P/B": info.get("priceToBook"),
                "ROE": info.get("returnOnEquity"),
                "ROIC": None,
                "Gross M": info.get("grossMargins"),
                "Oper M": info.get("operatingMargins"),
                "Debt/Eq": info.get("debtToEquity"),
                "Price": price,
                "Change": (info.get("regularMarketChangePercent") or 0) / 100 if info.get("regularMarketChangePercent") else 0,
                "Note": note,
            })
        except Exception as e:
            rows.append({"Ticker": ticker, "Company": name, "Note": f"fetch failed: {e}"})
    return pd.DataFrame(rows)


def add_fit_score(df: pd.DataFrame, style: str) -> pd.DataFrame:
    """Add Fit Score column (0-100) ranking each row by philosophy strength.

    Also adds Fit Label (Strong/Solid/OK/Weak) and Strengths column listing
    which checks passed.
    """
    if df is None or df.empty:
        return df
    scorer = STYLE_SCORERS.get(style, _score_generic)

    fits = []
    labels = []
    strengths = []
    for _, row in df.iterrows():
        score, max_score, passed = scorer(row)
        pct = (score / max_score) if max_score else 0
        fits.append(round(pct * 100))
        if pct >= 0.75:
            labels.append("🟢 Strong")
        elif pct >= 0.55:
            labels.append("🟢 Solid")
        elif pct >= 0.35:
            labels.append("🟡 OK")
        else:
            labels.append("🔴 Weak")
        strengths.append(" • ".join(passed[:3]) if passed else "—")

    df = df.copy()
    df.insert(1, "Fit", fits)
    df.insert(2, "Rating", labels)
    df["Strengths"] = strengths
    df = df.sort_values("Fit", ascending=False).reset_index(drop=True)
    return df
