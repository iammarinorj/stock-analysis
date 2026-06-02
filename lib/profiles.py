"""Multi-style scoring engine: Buffett, Graham, Lynch, Fisher.

Each profile is a *different test* for whether a stock fits *that* investor's
philosophy. Same stock can be a 9/10 Graham cigar butt and a 2/10 Buffett
compounder — that's the truth and old single-rubric scorecards hide it.

Each profile defines:
  - id, name, description, tagline
  - items: list of criteria. Each item has:
      id, label, weight, note, evaluate(quote, trends) -> (passed, actual_str, optional_note)
  - verdict(by_cat_or_total) -> {head, explain, color}

A single quote dict (from data.get_enriched_quote) + a trends dict
(from trends.get_annual_trends) feed all four profiles.
"""
from __future__ import annotations

from typing import Any, Callable

from lib import trends as _trends


# ---------------------------------------------------------------------------
# Helper: pull a value, return None on missing/nan
# ---------------------------------------------------------------------------

def _v(d: dict, *keys):
    for k in keys:
        if k in d and d[k] is not None:
            try:
                if isinstance(d[k], float) and d[k] != d[k]:  # NaN
                    continue
            except Exception:
                pass
            return d[k]
    return None


def _consistency(values: list, threshold: float, n: int = 3, op: str = ">") -> dict:
    """How many of the last n years cleared the threshold?"""
    vals = [v for v in values[:n] if v is not None]
    if not vals:
        return {"hits": 0, "total": 0, "all_pass": False, "label": "—"}
    if op == ">":
        hits = sum(1 for v in vals if v > threshold)
    elif op == "<":
        hits = sum(1 for v in vals if v < threshold)
    else:
        hits = sum(1 for v in vals if v >= threshold)
    return {"hits": hits, "total": len(vals), "all_pass": hits == len(vals),
            "label": f"{hits}/{len(vals)} years"}


def _mk_item(id_, label, w, note, evaluate):
    return {"id": id_, "label": label, "w": w, "note": note, "evaluate": evaluate}


# ===========================================================================
# Profile 1 — BUFFETT (Quality Compounder)
# "Wonderful companies at fair prices, held forever"
# ===========================================================================

def _buffett_items():
    items = []

    def roic_check(q, t):
        cons = _consistency(t["metrics"].get("roic", []), 0.15, n=5)
        last = t["metrics"]["roic"][0] if t["metrics"].get("roic") else None
        passed = cons["hits"] >= 3 and last is not None and last > 0.12
        actual = f"ROIC last 5y: {cons['label']} above 15%"
        if last is not None:
            actual += f" (latest {last*100:.1f}%)"
        return passed, actual
    items.append(_mk_item("roic_consistent", "ROIC > 15% in 3+ of last 5yrs", 3,
                          "Buffett's #1 quality test. Single-year ROIC means nothing.", roic_check))

    def roe_stable(q, t):
        vals = [v for v in t["metrics"].get("roe", []) if v is not None]
        if len(vals) < 3:
            return False, "Insufficient ROE history"
        last = vals[0]
        avg = sum(vals[:5]) / min(5, len(vals))
        improving_or_stable = t["trends"].get("roe", {}).get("direction") in ("rising", "flat")
        passed = avg > 0.15 and improving_or_stable
        return passed, f"5yr avg ROE {avg*100:.1f}%, trend: {t['trends'].get('roe', {}).get('direction', '?')}"
    items.append(_mk_item("roe_stable", "ROE stable/rising and 5yr avg > 15%", 2,
                          "Stable high ROE = durable advantage.", roe_stable))

    def gross_margin_stable(q, t):
        vals = [v for v in t["metrics"].get("gross_margin", []) if v is not None]
        if not vals:
            return False, "No gross margin data"
        last = vals[0]
        direction = t["trends"].get("gross_margin", {}).get("direction", "?")
        passed = last > 0.35 and direction != "falling"
        return passed, f"Latest gross margin {last*100:.1f}%, trend: {direction}"
    items.append(_mk_item("gm_durable", "Gross margin > 35% and not falling", 2,
                          "Munger: persistent gross margin = pricing power / moat.", gross_margin_stable))

    def leverage_check(q, t):
        nde_vals = [v for v in t["metrics"].get("nd_ebitda", []) if v is not None]
        last_nde = nde_vals[0] if nde_vals else None
        if last_nde is None:
            return False, "Net Debt/EBITDA unavailable"
        passed = last_nde < 2.0
        return passed, f"Net Debt/EBITDA: {last_nde:.2f}x"
    items.append(_mk_item("low_leverage", "Net Debt/EBITDA < 2x", 2,
                          "Buffett pays cash, hates levered businesses.", leverage_check))

    def fcf_consistent(q, t):
        fcf_vals = t["metrics"].get("fcf", [])
        positive = [v for v in fcf_vals[:5] if v is not None and v > 0]
        n_pos = len(positive)
        n_total = len([v for v in fcf_vals[:5] if v is not None])
        passed = n_total >= 3 and n_pos == n_total
        return passed, f"Positive FCF: {n_pos}/{n_total} years"
    items.append(_mk_item("fcf_consistent", "Positive FCF every year (last 5)", 2,
                          "Cash machines compound.", fcf_consistent))

    def buyback_check(q, t):
        sh_change = t["metrics"].get("shares_change", [])
        # Most recent yoy share count change. Negative = buyback.
        recent = [v for v in sh_change[:3] if v is not None]
        if not recent:
            return False, "Share count data missing"
        avg_change = sum(recent) / len(recent)
        passed = avg_change < 0  # shrinking
        return passed, f"3yr avg share change: {avg_change*100:+.2f}%/yr {'(buybacks)' if avg_change < 0 else '(dilution)'}"
    items.append(_mk_item("buybacks", "Share count shrinking (buybacks > issuance)", 1,
                          "Buffett wants per-share value compounding.", buyback_check))

    def reasonable_price(q, t):
        fcf = _v(q, "fcf"); mc = _v(q, "market_cap")
        if not (fcf and mc and fcf > 0):
            return False, "FCF yield uncomputable"
        fy = fcf / mc
        passed = fy > 0.04
        return passed, f"FCF yield: {fy*100:.2f}% (need > 4%)"
    items.append(_mk_item("fcf_yield_ok", "FCF yield > 4% (fair price)", 2,
                          "Buffett: fair price for wonderful biz.", reasonable_price))

    def moat_proxy(q, t):
        # Operating margin durability + ROIC > WACC proxy (10%)
        om_vals = [v for v in t["metrics"].get("operating_margin", []) if v is not None]
        roic_vals = [v for v in t["metrics"].get("roic", []) if v is not None]
        if not om_vals or not roic_vals:
            return False, "Margin/ROIC history missing"
        om_avg = sum(om_vals[:5]) / min(5, len(om_vals))
        roic_avg = sum(roic_vals[:5]) / min(5, len(roic_vals))
        passed = om_avg > 0.15 and roic_avg > 0.10
        return passed, f"5yr avg op margin {om_avg*100:.1f}%, ROIC {roic_avg*100:.1f}%"
    items.append(_mk_item("moat", "Op margin > 15% AND ROIC > WACC (~10%)", 2,
                          "Margin + ROIC = moat proxy.", moat_proxy))

    return items


# ===========================================================================
# Profile 2 — GRAHAM (Deep Value / Cigar Butt)
# "Buy dollars for fifty cents. Quality optional."
# ===========================================================================

def _graham_items():
    items = []

    def pb_test(q, t):
        pb = _v(q, "pb")
        if pb is None:
            return False, "P/B unavailable"
        passed = pb < 1.0
        return passed, f"P/B: {pb:.2f}x (need < 1.0)"
    items.append(_mk_item("pb_under_1", "P/B < 1.0", 3,
                          "Graham's most famous test: trade below tangible book.", pb_test))

    def pe_low(q, t):
        pe = _v(q, "pe_trailing")
        if pe is None or pe <= 0:
            return False, "P/E missing or negative"
        passed = pe < 10
        return passed, f"P/E: {pe:.1f}x (need < 10)"
    items.append(_mk_item("pe_under_10", "P/E < 10", 2,
                          "Statistical cheapness.", pe_low))

    def current_ratio(q, t):
        # yfinance doesn't expose current ratio directly; compute from balance sheet via finviz
        cr = _v(q, "current_ratio")
        if cr is None:
            return False, "Current ratio unavailable"
        passed = cr > 2.0
        return passed, f"Current ratio: {cr:.2f}x (need > 2)"
    items.append(_mk_item("current_ratio_2", "Current ratio > 2", 2,
                          "Graham: liquidity buffer in case of distress.", current_ratio))

    def low_debt(q, t):
        de = _v(q, "debt_eq")
        if de is None:
            return False, "Debt/Equity unavailable"
        passed = de < 0.5
        return passed, f"Debt/Equity: {de:.2f} (need < 0.5)"
    items.append(_mk_item("low_debt_graham", "Long-term debt < equity", 2,
                          "Don't catch a falling knife with a leveraged balance sheet.", low_debt))

    def dividend_paying(q, t):
        dy = _v(q, "div_yield", "dividend_yield")
        if dy is None or dy == 0:
            return False, "No dividend"
        passed = dy > 0
        return passed, f"Yield: {dy*100:.2f}%"
    items.append(_mk_item("pays_dividend", "Pays a dividend", 1,
                          "Graham: any dividend = real cash return.", dividend_paying))

    def historical_profitability(q, t):
        # 5+ years of positive earnings
        ni_vals = [v for v in t["metrics"].get("net_income", []) if v is not None]
        n_pos = sum(1 for v in ni_vals[:5] if v > 0)
        n_total = len(ni_vals[:5])
        passed = n_total >= 3 and n_pos == n_total
        return passed, f"{n_pos}/{n_total} years profitable"
    items.append(_mk_item("profit_history", "Profitable every year (last 5)", 2,
                          "Graham: at least no losses in recent history.", historical_profitability))

    def earnings_growth_modest(q, t):
        eps_vals = [v for v in t["metrics"].get("eps", []) if v is not None and v > 0]
        if len(eps_vals) < 3:
            return False, "Insufficient EPS history"
        # Compare oldest available to latest
        first = eps_vals[-1]; last = eps_vals[0]
        n = len(eps_vals) - 1
        try:
            cagr = (last / first) ** (1 / n) - 1
        except Exception:
            return False, "EPS calc failed"
        passed = cagr > 0.025
        return passed, f"EPS CAGR (~{n}yr): {cagr*100:+.1f}% (need > 2.5%)"
    items.append(_mk_item("modest_growth", "EPS CAGR > 2.5% (real growth)", 1,
                          "Graham: prefer at least inflation-rate EPS growth.", earnings_growth_modest))

    def mos_vs_book(q, t):
        # NCAV ≈ current assets - total liabilities; price < 2/3 NCAV = Graham's net-net
        # yfinance doesn't expose NCAV cleanly; use P/B as proxy
        pb = _v(q, "pb")
        if pb is None:
            return False, "P/B unavailable"
        passed = pb < 0.67
        return passed, f"P/B: {pb:.2f}x (net-net zone < 0.67)"
    items.append(_mk_item("net_net_proxy", "Net-net proxy: P/B < 0.67", 1,
                          "Graham's Holy Grail: price < 2/3 book.", mos_vs_book))

    return items


# ===========================================================================
# Profile 3 — LYNCH (Growth at Reasonable Price)
# "PEG < 1, story you can explain in one breath"
# ===========================================================================

def _lynch_items():
    items = []

    def peg_under_1(q, t):
        peg = _v(q, "peg")
        if peg is None or peg <= 0:
            return False, "PEG unavailable or non-positive"
        passed = peg < 1.0
        return passed, f"PEG: {peg:.2f}"
    items.append(_mk_item("peg_under_1", "PEG < 1.0", 3,
                          "Lynch's core ratio. PEG > 2 is rarely worth it.", peg_under_1))

    def earnings_growing(q, t):
        eps_growth = [v for v in t["metrics"].get("eps_growth", []) if v is not None]
        if not eps_growth:
            # Fall back to TTM
            eg = _v(q, "earnings_growth")
            if eg is None:
                return False, "EPS growth unavailable"
            return eg > 0.15, f"TTM EPS growth: {eg*100:+.1f}%"
        avg = sum(eps_growth[:3]) / min(3, len(eps_growth))
        passed = avg > 0.15
        return passed, f"3yr avg EPS growth: {avg*100:+.1f}% (need > 15%)"
    items.append(_mk_item("eps_growing", "EPS growing > 15%/yr", 2,
                          "Lynch's growth threshold.", earnings_growing))

    def revenue_growing(q, t):
        rg = [v for v in t["metrics"].get("revenue_growth", []) if v is not None]
        if not rg:
            r = _v(q, "rev_growth")
            return (r is not None and r > 0.10), f"TTM rev growth: {r*100:+.1f}%" if r else "Rev growth unavailable"
        avg = sum(rg[:3]) / min(3, len(rg))
        passed = avg > 0.10
        return passed, f"3yr avg rev growth: {avg*100:+.1f}%"
    items.append(_mk_item("rev_growing", "Revenue growing > 10%/yr", 2,
                          "Top-line confirmation.", revenue_growing))

    def insider_buying(q, t):
        # Use enriched quote insider signals
        cluster = _v(q, "insider_cluster_buy")
        net = _v(q, "insider_net_value")
        if cluster or (net is not None and net > 0):
            return True, f"Cluster buy: {cluster}, Net ${net or 0:,.0f}"
        return False, "No recent insider cluster buying"
    items.append(_mk_item("insider_active", "Recent insider cluster buying", 2,
                          "Lynch loved insider buying.", insider_buying))

    def manageable_debt(q, t):
        de = _v(q, "debt_eq")
        if de is None:
            return False, "Debt/Eq unavailable"
        passed = de < 1.0
        return passed, f"Debt/Eq: {de:.2f}"
    items.append(_mk_item("debt_manageable", "Debt/Equity < 1", 1,
                          "Lynch: avoid companies leveraged to the gills.", manageable_debt))

    def small_or_mid_cap_pref(q, t):
        mc = _v(q, "market_cap")
        if mc is None:
            return False, "Mkt cap unavailable"
        # Lynch loved the under-followed range
        passed = mc < 50_000_000_000  # under $50B
        return passed, f"Mkt cap: ${mc/1e9:.1f}B {'(Lynch sweet spot)' if mc < 10e9 else '(too big for outsized returns)'}"
    items.append(_mk_item("size_sweet_spot", "Mkt cap < $50B (room to compound)", 1,
                          "Lynch: big edge in under-covered small/mid caps.", small_or_mid_cap_pref))

    def margin_expansion(q, t):
        direction = t["trends"].get("operating_margin", {}).get("direction", "?")
        passed = direction == "rising"
        return passed, f"Operating margin trend: {direction}"
    items.append(_mk_item("margins_expanding", "Operating margins expanding", 2,
                          "Lynch: best stories show op leverage.", margin_expansion))

    return items


# ===========================================================================
# Profile 4 — FISHER (Scuttlebutt / Quality Growth)
# "15 points: management, R&D, sales depth — own for decades"
# ===========================================================================

def _fisher_items():
    items = []

    def superior_growth(q, t):
        rg = [v for v in t["metrics"].get("revenue_growth", []) if v is not None]
        if not rg or len(rg) < 3:
            return False, "Insufficient revenue history"
        avg = sum(rg[:3]) / 3
        passed = avg > 0.15
        return passed, f"3yr avg rev growth: {avg*100:+.1f}% (need > 15%)"
    items.append(_mk_item("growth_above_15", "Revenue CAGR > 15% (3yr)", 2,
                          "Fisher's first test: above-average growth.", superior_growth))

    def margins_above_peers_proxy(q, t):
        om = _v(q, "operating_margin")
        gm = _v(q, "gross_margin")
        if om is None or gm is None:
            return False, "Margins unavailable"
        passed = gm > 0.40 and om > 0.15
        return passed, f"Gross {gm*100:.0f}%, Op {om*100:.0f}%"
    items.append(_mk_item("superior_margins", "Gross > 40% AND Op > 15%", 2,
                          "Fisher: superior cost-of-doing-business.", margins_above_peers_proxy))

    def rd_investment(q, t):
        # yfinance doesn't expose R&D cleanly; use sector heuristic
        sector = (_v(q, "sector") or "").lower()
        is_innovation_sector = any(s in sector for s in ["technology", "health", "communication"])
        gm = _v(q, "gross_margin") or 0
        # High gross margin + tech/health sector implies R&D investment
        passed = is_innovation_sector and gm > 0.50
        return passed, f"Sector: {sector or '—'}, Gross margin: {gm*100:.0f}%"
    items.append(_mk_item("rd_proxy", "Innovation sector + high gross margin", 1,
                          "Fisher loved companies that re-invest in R&D.", rd_investment))

    def long_runway(q, t):
        # Multi-year revenue trajectory rising + ROIC stable
        rev_dir = t["trends"].get("revenue", {}).get("direction", "?")
        roic_dir = t["trends"].get("roic", {}).get("direction", "?")
        passed = rev_dir == "rising" and roic_dir in ("rising", "flat")
        return passed, f"Revenue {rev_dir}, ROIC {roic_dir}"
    items.append(_mk_item("long_runway", "Revenue rising + ROIC not deteriorating", 2,
                          "Fisher: long runways for compounding.", long_runway))

    def quality_balance_sheet(q, t):
        nde_vals = [v for v in t["metrics"].get("nd_ebitda", []) if v is not None]
        last = nde_vals[0] if nde_vals else None
        if last is None:
            return False, "Net Debt/EBITDA unavailable"
        passed = last < 1.5
        return passed, f"Net Debt/EBITDA: {last:.2f}x (need < 1.5)"
    items.append(_mk_item("clean_balance_sheet", "Net Debt/EBITDA < 1.5x", 2,
                          "Fisher: clean BS funds R&D + buybacks through cycles.", quality_balance_sheet))

    def shares_disciplined(q, t):
        sh_change = t["metrics"].get("shares_change", [])
        recent = [v for v in sh_change[:3] if v is not None]
        if not recent:
            return False, "Share data unavailable"
        avg = sum(recent) / len(recent)
        # Fisher tolerated some dilution for growth, but heavy dilution is a red flag
        passed = avg < 0.03  # < 3%/yr dilution acceptable
        return passed, f"3yr avg share change: {avg*100:+.2f}%/yr"
    items.append(_mk_item("discipline", "Share count change < +3%/yr", 1,
                          "Fisher: hyper-dilution destroys returns.", shares_disciplined))

    def own_for_decades(q, t):
        # Proxy: 5yr revenue CAGR > 10% AND 5yr ROIC avg > 15%
        rev_vals = [v for v in t["metrics"].get("revenue", []) if v is not None]
        roic_vals = [v for v in t["metrics"].get("roic", []) if v is not None]
        if len(rev_vals) < 4 or not roic_vals:
            return False, "Insufficient history for decadal test"
        # 5yr revenue CAGR
        first = rev_vals[-1]; last = rev_vals[0]; n = len(rev_vals) - 1
        try:
            cagr = (last / first) ** (1 / n) - 1
        except Exception:
            return False, "CAGR calc failed"
        avg_roic = sum(roic_vals[:5]) / min(5, len(roic_vals))
        passed = cagr > 0.10 and avg_roic > 0.15
        return passed, f"{n}yr rev CAGR {cagr*100:.1f}%, 5yr avg ROIC {avg_roic*100:.1f}%"
    items.append(_mk_item("decadal", "Rev CAGR > 10% AND 5yr ROIC avg > 15%", 2,
                          "Fisher: own for decades, not quarters.", own_for_decades))

    return items


# ===========================================================================
# Profile 5 — INFLECTION (Secular Tailwind / Hypergrowth Turning Profitable)
# "AAOI-style. Find them BEFORE the earnings catch up to the story."
# ===========================================================================

def _inflection_items():
    items = []

    def rev_accelerating(q, t):
        """Latest YoY growth + recent multi-year trend both strong."""
        rg_vals = [v for v in t["metrics"].get("revenue_growth", []) if v is not None]
        latest_yoy = _v(q, "rev_growth") or (rg_vals[0] if rg_vals else None)
        if latest_yoy is None:
            return False, "Revenue growth unavailable"
        passed = latest_yoy > 0.30
        return passed, f"Latest YoY revenue growth: {latest_yoy*100:+.1f}% (need > 30%)"
    items.append(_mk_item("rev_accel_30", "Latest YoY revenue growth > 30%", 3,
                          "Big acceleration is the entry signal. 30%+ separates inflections from steady growers.",
                          rev_accelerating))

    def rev_3yr_cagr(q, t):
        rev_vals = [v for v in t["metrics"].get("revenue", []) if v is not None]
        if len(rev_vals) < 3:
            return False, "Insufficient revenue history"
        first = rev_vals[-1]; last = rev_vals[0]
        n = len(rev_vals) - 1
        if first <= 0:
            return False, "Cannot compute CAGR"
        cagr = (last / first) ** (1 / n) - 1
        passed = cagr > 0.20
        return passed, f"{n}yr revenue CAGR: {cagr*100:+.1f}%"
    items.append(_mk_item("rev_cagr_20", "Multi-year revenue CAGR > 20%", 2,
                          "Sustained growth, not a one-quarter pop.", rev_3yr_cagr))

    def gross_margin_expanding(q, t):
        direction = t["trends"].get("gross_margin", {}).get("direction", "?")
        gm_vals = [v for v in t["metrics"].get("gross_margin", []) if v is not None]
        if not gm_vals:
            return False, "Gross margin history unavailable"
        first = gm_vals[-1] if len(gm_vals) > 1 else gm_vals[0]
        last = gm_vals[0]
        improvement = last - first
        passed = direction == "rising" and improvement > 0.03
        return passed, f"Gross margin: {first*100:.0f}% → {last*100:.0f}% (Δ{improvement*100:+.1f}pp, {direction})"
    items.append(_mk_item("gm_expanding", "Gross margin expanding (Δ > +3pp)", 2,
                          "Pricing power + mix shift + scale. The earnings inflection driver.",
                          gross_margin_expanding))

    def gm_above_25(q, t):
        gm = _v(q, "gross_margin")
        if gm is None:
            return False, "Gross margin unavailable"
        passed = gm > 0.25
        return passed, f"Current gross margin: {gm*100:.1f}%"
    items.append(_mk_item("gm_above_25", "Gross margin > 25% (reasonable level)", 1,
                          "Even hypergrowth needs a baseline economic profile.", gm_above_25))

    def op_margin_inflecting(q, t):
        """Op margin doesn't need to be positive, just rising fast or already flipping."""
        om_vals = [v for v in t["metrics"].get("operating_margin", []) if v is not None]
        if len(om_vals) < 2:
            return False, "Insufficient op margin history"
        first = om_vals[-1]; last = om_vals[0]
        improvement = last - first
        direction = t["trends"].get("operating_margin", {}).get("direction", "?")
        passed = direction == "rising" or improvement > 0.05
        return passed, f"Op margin: {first*100:+.1f}% → {last*100:+.1f}% (Δ{improvement*100:+.1f}pp, {direction})"
    items.append(_mk_item("op_inflecting", "Operating margin trending up (loss narrowing OK)", 2,
                          "Look for the slope, not the level. Negative is OK if going hard the right way.",
                          op_margin_inflecting))

    def forward_pe_exists(q, t):
        """If analysts can model a forward P/E, they believe profitability is coming."""
        fpe = _v(q, "pe_forward")
        if fpe is None or fpe <= 0:
            return False, "No forward P/E — analysts can't model profitability yet"
        passed = 0 < fpe < 60
        return passed, f"Forward P/E: {fpe:.1f}x"
    items.append(_mk_item("fwd_pe_exists", "Forward P/E exists and < 60x", 1,
                          "Forward P/E means analysts can model real profits next year. That's the inflection.",
                          forward_pe_exists))

    def peg_reasonable(q, t):
        peg = _v(q, "peg")
        if peg is None or peg <= 0:
            return False, "PEG unavailable"
        passed = peg < 1.5
        return passed, f"PEG: {peg:.2f}"
    items.append(_mk_item("peg_reasonable", "PEG < 1.5 (growth priced fairly)", 1,
                          "Even with hypergrowth priced in, PEG should clear 1.5x.", peg_reasonable))

    def insider_aligned(q, t):
        own = _v(q, "held_insiders", "insider_own")
        cluster = _v(q, "insider_cluster_buy")
        if cluster:
            return True, f"Cluster buying detected (insider ownership: {(own or 0)*100:.1f}%)"
        if own is None:
            return False, "Insider ownership unavailable"
        passed = own > 0.05
        return passed, f"Insider ownership: {own*100:.1f}% (need > 5%)"
    items.append(_mk_item("insider_skin", "Insider ownership > 5% OR cluster buying", 2,
                          "Founder/exec alignment matters most in hypergrowth where execution risk is high.",
                          insider_aligned))

    def innovation_sector(q, t):
        sector = (_v(q, "sector") or "").lower()
        industry = (_v(q, "industry") or "").lower()
        passed = any(s in sector for s in ["technology", "healthcare", "communication"]) or \
                 any(i in industry for i in ["semi", "biotech", "software", "photonic", "optical", "communication equipment"])
        return passed, f"Sector: {sector or '—'}, Industry: {industry or '—'}"
    items.append(_mk_item("sector_innovation", "Innovation sector (Tech/Healthcare/Comm)", 1,
                          "Inflection plays live where TAMs are expanding. Mature industries rarely have them.",
                          innovation_sector))

    def stage_2_trend(q, t):
        px = _v(q, "price"); dma200 = _v(q, "dma_200")
        if px is None or dma200 is None:
            return False, "Price/DMA data unavailable"
        passed = px > dma200
        delta_pct = (px / dma200 - 1) * 100
        return passed, f"Price ${px:.2f} vs 200DMA ${dma200:.2f} ({delta_pct:+.1f}%)"
    items.append(_mk_item("stage_2", "Price above 200 DMA (Stage 2 trend)", 1,
                          "Inflection thesis already in motion. Don't bottom-pick before the trend confirms.",
                          stage_2_trend))

    def balance_sheet_not_distressed(q, t):
        """Allow capex-heavy negative FCF but balance sheet shouldn't be exploding."""
        de = _v(q, "debt_eq")
        nde_vals = [v for v in t["metrics"].get("nd_ebitda", []) if v is not None]
        if de is not None:
            passed = de < 1.5
            return passed, f"Debt/Equity: {de:.2f}"
        # Fallback: check net debt absolute vs market cap
        td = _v(q, "total_debt") or 0
        tc = _v(q, "total_cash") or 0
        mc = _v(q, "market_cap")
        if mc and mc > 0:
            net_debt_pct = (td - tc) / mc
            passed = net_debt_pct < 0.30
            return passed, f"Net debt {net_debt_pct*100:+.1f}% of mkt cap"
        return False, "Debt/Equity data unavailable"
    items.append(_mk_item("not_levered", "Balance sheet not distressed (Debt/Eq < 1.5)", 1,
                          "Inflection plays often have negative FCF from capex. That's fine. Over-levered is not.",
                          balance_sheet_not_distressed))

    def reasonable_size(q, t):
        mc = _v(q, "market_cap")
        if mc is None:
            return False, "Market cap unavailable"
        # Want $100M to $50B sweet spot — too small = junk risk, too big = no more multiple expansion room
        passed = 100e6 < mc < 50e9
        return passed, f"Mkt cap ${mc/1e9:.2f}B (sweet spot $100M-$50B)"
    items.append(_mk_item("size_runway", "Mkt cap $100M-$50B (room to compound)", 1,
                          "Sub-$100M = too risky; over $50B = already discovered.", reasonable_size))

    return items


# ===========================================================================
# Profile 6 — O'NEIL CAN SLIM (Growth + Leadership Momentum)
# "Current EPS, Annual EPS, New product, Supply, Leader, Institutional, Market"
# ===========================================================================

def _canslim_items():
    items = []

    def current_eps_growth(q, t):
        """C: Current quarterly EPS growth > 25%"""
        eg = _v(q, "earnings_growth")
        if eg is None:
            eps_growth_vals = [v for v in t["metrics"].get("eps_growth", []) if v is not None]
            if not eps_growth_vals:
                return False, "EPS growth unavailable"
            eg = eps_growth_vals[0]
        passed = eg > 0.25
        return passed, f"Latest EPS growth: {eg*100:+.1f}% (need > 25%)"
    items.append(_mk_item("c_current_eps", "C: Current EPS growth > 25%", 2,
                          "O'Neil's first letter: explosive current EPS acceleration.", current_eps_growth))

    def annual_eps_growth(q, t):
        """A: Annual EPS growing for last 3 years"""
        eps_vals = [v for v in t["metrics"].get("eps", []) if v is not None and v > 0]
        if len(eps_vals) < 3:
            return False, "Insufficient EPS history"
        # Most recent to oldest: each should be > the next
        last_3 = eps_vals[:3]
        all_rising = all(last_3[i] > last_3[i+1] for i in range(len(last_3)-1))
        return all_rising, f"EPS last 3y: {[f'${v:.2f}' for v in last_3]}"
    items.append(_mk_item("a_annual_eps", "A: Annual EPS rising 3 years straight", 2,
                          "Sustained earnings power, not a one-quarter pop.", annual_eps_growth))

    def revenue_acceleration(q, t):
        """N: New product/service (proxy: revenue acceleration)"""
        rg = [v for v in t["metrics"].get("revenue_growth", []) if v is not None]
        if len(rg) < 2:
            r = _v(q, "rev_growth")
            return (r is not None and r > 0.20), f"TTM rev growth: {(r or 0)*100:+.1f}%"
        recent = rg[0]; prior = rg[1] if len(rg) > 1 else 0
        accel = recent > prior and recent > 0.15
        return accel, f"Rev growth: {prior*100:+.1f}% → {recent*100:+.1f}%"
    items.append(_mk_item("n_new_high", "N: Revenue accelerating (new catalyst)", 1,
                          "Proxy for 'New product/service/management/highs'.", revenue_acceleration))

    def s_supply(q, t):
        """S: Supply / demand — float shrinking via buybacks"""
        sh_change = t["metrics"].get("shares_change", [])
        recent = [v for v in sh_change[:3] if v is not None]
        if not recent:
            return False, "Share count data missing"
        avg = sum(recent) / len(recent)
        passed = avg < 0
        return passed, f"3y avg share change: {avg*100:+.2f}%/yr"
    items.append(_mk_item("s_supply", "S: Buybacks shrinking share count", 1,
                          "Tightening float = supply/demand favorable.", s_supply))

    def l_leader(q, t):
        """L: Leader, not laggard — relative price strength (>70 percentile proxy)"""
        px = _v(q, "price"); d50 = _v(q, "dma_50"); d200 = _v(q, "dma_200")
        if not all([px, d50, d200]):
            return False, "DMA data missing"
        # Stage 2 trend: price > 50DMA > 200DMA, all rising
        passed = px > d50 > d200
        return passed, f"Price ${px:.2f} > 50DMA ${d50:.2f} > 200DMA ${d200:.2f}: {passed}"
    items.append(_mk_item("l_leader", "L: Stage-2 trend (Px > 50DMA > 200DMA)", 2,
                          "O'Neil's leadership confirmation — buy leaders, not laggards.", l_leader))

    def i_institutional(q, t):
        """I: Institutional sponsorship"""
        inst = _v(q, "held_institutions") or _v(q, "inst_own") or 0
        passed = inst > 0.30  # 30%+ institutional = real sponsorship
        return passed, f"Institutional ownership: {inst*100:.1f}%"
    items.append(_mk_item("i_institutional", "I: Institutional ownership > 30%", 1,
                          "Big money is the gas under the price.", i_institutional))

    def m_market(q, t):
        """M: Market direction — stock above 200DMA (proxy)"""
        px = _v(q, "price"); d200 = _v(q, "dma_200")
        if not (px and d200):
            return False, "DMA missing"
        passed = px > d200 * 1.05  # 5% buffer for genuine uptrend
        return passed, f"Price {((px/d200)-1)*100:+.1f}% vs 200DMA"
    items.append(_mk_item("m_market", "M: Above 200DMA by 5%+ (market regime)", 1,
                          "Don't fight the tape. Be long only in uptrends.", m_market))

    def reasonable_valuation(q, t):
        """Bonus: PEG < 2 (CAN SLIM allows premiums but not absurd)"""
        peg = _v(q, "peg")
        if peg is None or peg <= 0:
            return False, "PEG unavailable"
        passed = peg < 2.0
        return passed, f"PEG: {peg:.2f}"
    items.append(_mk_item("reasonable_peg", "Bonus: PEG < 2 (not absurd)", 1,
                          "O'Neil tolerated growth premiums but PEG > 2 = chase.", reasonable_valuation))

    return items


# ===========================================================================
# Profile 7 — GREENBLATT MAGIC FORMULA (Mechanical Quant Value)
# "Buy good companies (high ROIC) at cheap prices (high earnings yield)"
# ===========================================================================

def _magicformula_items():
    items = []

    def high_earnings_yield(q, t):
        """Earnings yield (EBIT/EV) > 12% = top quintile cheap"""
        pe = _v(q, "pe_trailing") or _v(q, "pe_forward")
        if not pe or pe <= 0:
            return False, "P/E unavailable"
        ey = 1 / pe
        passed = ey > 0.10  # 10% earnings yield = P/E < 10
        return passed, f"Earnings yield {ey*100:.1f}% (P/E {pe:.1f}x)"
    items.append(_mk_item("mf_earnings_yield", "Earnings yield > 10% (P/E < 10)", 3,
                          "Greenblatt's first lever: cheap on owner earnings.",
                          high_earnings_yield))

    def high_roic(q, t):
        """ROIC > 20% = top quintile quality"""
        roic_vals = [v for v in t["metrics"].get("roic", []) if v is not None]
        latest = roic_vals[0] if roic_vals else _v(q, "roe")  # fallback to ROE
        if latest is None:
            return False, "ROIC unavailable"
        passed = latest > 0.20
        return passed, f"ROIC: {latest*100:.1f}%"
    items.append(_mk_item("mf_roic", "ROIC > 20%", 3,
                          "Greenblatt's second lever: high quality business.", high_roic))

    def consistent_profitability(q, t):
        """Profitable in 4 of last 5 years"""
        ni_vals = [v for v in t["metrics"].get("net_income", []) if v is not None]
        if len(ni_vals) < 4:
            return False, "Insufficient earnings history"
        last_5 = ni_vals[:5]
        pos = sum(1 for v in last_5 if v > 0)
        passed = pos >= 4
        return passed, f"{pos}/{len(last_5)} years profitable"
    items.append(_mk_item("mf_consistent", "Profitable 4 of last 5 yrs", 2,
                          "Mechanical screen needs durable earnings.", consistent_profitability))

    def reasonable_size(q, t):
        """Greenblatt avoids micro-caps — mkt cap > $100M for liquidity"""
        mc = _v(q, "market_cap")
        if not mc:
            return False, "Mkt cap unavailable"
        passed = mc > 100e6
        return passed, f"Mkt cap ${mc/1e9:.2f}B"
    items.append(_mk_item("mf_size", "Mkt cap > $100M (avoid micros)", 1,
                          "Magic Formula explicitly excludes financials + micro-caps.", reasonable_size))

    def not_financial(q, t):
        """Magic Formula explicitly excludes financials and utilities"""
        sector = (_v(q, "sector") or "").lower()
        passed = "financial" not in sector and "utilities" not in sector
        return passed, f"Sector: {sector or '—'}"
    items.append(_mk_item("mf_not_fin", "Not Financials/Utilities", 1,
                          "Greenblatt: ROIC math distorted for banks/insurers/utes.", not_financial))

    return items


# ===========================================================================
# Profile 8 — DIVIDEND ARISTOCRAT / QUALITY INCOME
# "Buy compounders that pay you while they compound"
# ===========================================================================

def _dividend_items():
    items = []

    def yield_floor(q, t):
        dy = _v(q, "div_yield", "dividend_yield")
        if dy is None or dy <= 0:
            return False, "No dividend"
        passed = dy > 0.025  # 2.5%+ yield
        return passed, f"Dividend yield: {dy*100:.2f}%"
    items.append(_mk_item("div_yield_25", "Dividend yield > 2.5%", 2,
                          "Real income, not a yield trap.", yield_floor))

    def yield_high(q, t):
        dy = _v(q, "div_yield", "dividend_yield")
        if dy is None: return False, "—"
        passed = dy > 0.04
        return passed, f"Yield: {(dy or 0)*100:.2f}%"
    items.append(_mk_item("div_yield_40", "Dividend yield > 4% (high)", 1,
                          "Premium income territory.", yield_high))

    def manageable_payout(q, t):
        """Payout ratio < 70% — sustainable, room to grow"""
        # Approximate from div_yield / earnings yield
        dy = _v(q, "div_yield") or 0
        pe = _v(q, "pe_trailing") or 0
        if not (dy > 0 and pe > 0):
            return False, "Payout calc unavailable"
        payout = dy * pe  # dy/ey = dy*pe
        passed = 0 < payout < 0.70
        return passed, f"Payout ratio ≈ {payout*100:.0f}% (need < 70%)"
    items.append(_mk_item("div_payout", "Payout ratio < 70% (sustainable)", 2,
                          "Room to keep raising without earnings squeeze.", manageable_payout))

    def dividend_growth(q, t):
        """Earnings growing (so dividend has room to grow)"""
        eps_growth = [v for v in t["metrics"].get("eps_growth", []) if v is not None]
        if not eps_growth:
            eg = _v(q, "earnings_growth")
            return (eg is not None and eg > 0.05), f"TTM EPS growth: {(eg or 0)*100:+.1f}%"
        avg = sum(eps_growth[:3]) / min(3, len(eps_growth))
        passed = avg > 0.05
        return passed, f"3y avg EPS growth: {avg*100:+.1f}%"
    items.append(_mk_item("div_growth", "EPS growing > 5%/yr (room to raise)", 2,
                          "A static dividend gets eaten by inflation.", dividend_growth))

    def low_debt(q, t):
        nde_vals = [v for v in t["metrics"].get("nd_ebitda", []) if v is not None]
        last = nde_vals[0] if nde_vals else None
        if last is None:
            de = _v(q, "debt_eq")
            return (de is not None and de < 1.0), f"Debt/Eq: {de:.2f}" if de else "—"
        passed = last < 3.0
        return passed, f"Net Debt/EBITDA: {last:.2f}x"
    items.append(_mk_item("div_low_debt", "Net Debt/EBITDA < 3x", 2,
                          "Dividends die when leverage forces cuts.", low_debt))

    def fcf_covers_div(q, t):
        """Free cash flow covers dividend"""
        fcf = _v(q, "fcf")
        mc = _v(q, "market_cap")
        dy = _v(q, "div_yield") or 0
        if not (fcf and fcf > 0 and mc and dy > 0):
            return False, "FCF or yield data missing"
        annual_div = mc * dy
        coverage = fcf / annual_div if annual_div else 0
        passed = coverage > 1.5
        return passed, f"FCF covers div {coverage:.1f}x"
    items.append(_mk_item("div_fcf_cover", "FCF covers dividend > 1.5x", 2,
                          "Real safety. Reported earnings can be massaged; cash can't.", fcf_covers_div))

    def stable_business(q, t):
        """ROIC stable (not collapsing)"""
        roic_vals = [v for v in t["metrics"].get("roic", []) if v is not None]
        if len(roic_vals) < 3:
            return False, "Need ROIC history"
        latest = roic_vals[0]; avg = sum(roic_vals[:5]) / min(5, len(roic_vals))
        passed = latest > 0.08 and latest >= avg * 0.8
        return passed, f"ROIC {latest*100:.1f}% (5y avg {avg*100:.1f}%)"
    items.append(_mk_item("div_stable", "ROIC stable and > 8%", 1,
                          "No yield trap from a deteriorating business.", stable_business))

    return items


# ===========================================================================
# Profile 9 — MINERVINI TREND TEMPLATE (Pure Momentum)
# "Buy Stage 2 trends with chart confirmation"
# ===========================================================================

def _minervini_items():
    items = []

    def stage_2_template(q, t):
        """Px > 50DMA > 150DMA > 200DMA (using available)"""
        px = _v(q, "price"); d50 = _v(q, "dma_50"); d200 = _v(q, "dma_200")
        if not all([px, d50, d200]):
            return False, "DMA data missing"
        passed = px > d50 > d200
        return passed, f"Px ${px:.2f} > 50DMA ${d50:.2f} > 200DMA ${d200:.2f}: {passed}"
    items.append(_mk_item("min_stage2", "Stage 2: Px > 50DMA > 200DMA", 3,
                          "Minervini's #1 rule. No exceptions.", stage_2_template))

    def dma_200_rising(q, t):
        """200DMA trending up (proxy: price 5%+ above 200DMA)"""
        px = _v(q, "price"); d200 = _v(q, "dma_200")
        if not (px and d200):
            return False, "—"
        passed = px > d200 * 1.05
        return passed, f"Px {((px/d200)-1)*100:+.1f}% vs 200DMA"
    items.append(_mk_item("min_200dma", "Price 5%+ above 200DMA", 2,
                          "200DMA rising = uptrend confirmed.", dma_200_rising))

    def price_above_52wk_low_30pct(q, t):
        """Price >= 30% above 52w low — not bottom fishing"""
        px = _v(q, "price"); low = _v(q, "year_low")
        if not (px and low):
            return False, "—"
        from_low = (px / low) - 1
        passed = from_low > 0.30
        return passed, f"+{from_low*100:.0f}% above 52w low ${low:.2f}"
    items.append(_mk_item("min_off_low", "30%+ off 52w low", 2,
                          "Not catching falling knives. Confirmed turn.", price_above_52wk_low_30pct))

    def price_near_52wk_high(q, t):
        """Within 25% of 52w high — momentum / leadership"""
        px = _v(q, "price"); hi = _v(q, "year_high")
        if not (px and hi):
            return False, "—"
        from_high = (px / hi) - 1
        passed = from_high > -0.25
        return passed, f"{from_high*100:+.1f}% from 52w high ${hi:.2f}"
    items.append(_mk_item("min_near_high", "Within 25% of 52w high", 2,
                          "Strong stocks stay strong. Leadership signal.", price_near_52wk_high))

    def relative_strength(q, t):
        """RSI in healthy uptrend range — not stupid extended, not weak"""
        rsi = _v(q, "rsi_14")
        if rsi is None:
            # Fall back to vs 200DMA strength
            px = _v(q, "price"); d200 = _v(q, "dma_200")
            if px and d200:
                strong = px > d200 * 1.10
                return strong, f"No RSI; using vs 200DMA: {((px/d200)-1)*100:+.1f}%"
            return False, "Momentum data missing"
        passed = 50 <= rsi <= 75  # strong but not blown out
        return passed, f"RSI {rsi:.1f}"
    items.append(_mk_item("min_rs", "RSI in 50-75 (strong, not extended)", 1,
                          "Minervini buys strength, sells extreme strength.", relative_strength))

    def earnings_growing(q, t):
        """Underlying fundamentals matter — earnings growing"""
        eg = _v(q, "earnings_growth")
        if eg is None:
            eps_g = [v for v in t["metrics"].get("eps_growth", []) if v is not None]
            return (eps_g and eps_g[0] > 0.20), f"Latest EPS growth: {(eps_g[0] if eps_g else 0)*100:+.1f}%"
        passed = eg > 0.20
        return passed, f"TTM earnings growth: {eg*100:+.1f}%"
    items.append(_mk_item("min_earnings", "Earnings growing > 20%", 2,
                          "Minervini: fundamentals AND chart, not chart alone.", earnings_growing))

    return items


# ===========================================================================
# Profile registry
# ===========================================================================

PROFILES = {
    "buffett": {
        "id": "buffett",
        "name": "Buffett — Quality Compounder",
        "tagline": "Wonderful companies at fair prices, held forever",
        "description": "Tests: ROIC consistency, durable margins, low leverage, persistent FCF, buybacks, moat proxies.",
        "items": _buffett_items(),
    },
    "graham": {
        "id": "graham",
        "name": "Graham — Deep Value / Cigar Butt",
        "tagline": "Buy dollars for fifty cents. Quality optional.",
        "description": "Tests: P/B < 1, P/E < 10, current ratio > 2, dividend paying, NCAV proxy, historical profitability.",
        "items": _graham_items(),
    },
    "lynch": {
        "id": "lynch",
        "name": "Lynch — GARP (Growth at Reasonable Price)",
        "tagline": "PEG < 1, story you can explain in one breath",
        "description": "Tests: PEG < 1, EPS/rev growth > 15%/10%, insider buying, manageable debt, small/mid cap sweet spot.",
        "items": _lynch_items(),
    },
    "fisher": {
        "id": "fisher",
        "name": "Fisher — Scuttlebutt / Quality Growth",
        "tagline": "Own for decades. 15-point qualitative test.",
        "description": "Tests: rev CAGR > 15%, superior margins, R&D proxy, long runway, clean balance sheet, decadal compounding test.",
        "items": _fisher_items(),
    },
    "inflection": {
        "id": "inflection",
        "name": "Inflection — Secular Tailwind / Hypergrowth Turning Profitable",
        "tagline": "Find them BEFORE earnings catch up to the story (AAOI-style)",
        "description": "Tests: revenue accelerating, gross margin EXPANDING (direction not level), op margin inflecting, forward P/E exists, PEG fair, insider aligned, innovation sector, Stage 2 trend. Negative FCF from capacity capex is OK.",
        "items": _inflection_items(),
    },
    "canslim": {
        "id": "canslim",
        "name": "O'Neil CAN SLIM — Growth + Leadership Momentum",
        "tagline": "Buy fast-growing leaders during bull markets",
        "description": "C: Current EPS growth >25%. A: Annual EPS rising 3y. N: Revenue accelerating. S: Buybacks shrinking supply. L: Leader (Stage 2 trend). I: Institutional ownership >30%. M: Market regime bullish. Plus reasonable PEG.",
        "items": _canslim_items(),
    },
    "magic_formula": {
        "id": "magic_formula",
        "name": "Greenblatt Magic Formula — Mechanical Quant Value",
        "tagline": "High ROIC + High Earnings Yield, ranked together",
        "description": "Earnings yield > 10% (P/E < 10), ROIC > 20%, profitable 4 of last 5y, mkt cap > $100M, NOT financials/utilities. Greenblatt's quant rule — Joel said the dumbest strategy that beats markets if you can stomach the volatility.",
        "items": _magicformula_items(),
    },
    "dividend": {
        "id": "dividend",
        "name": "Dividend Aristocrat — Quality Income",
        "tagline": "Buy compounders that pay you to wait",
        "description": "Yield >2.5%, payout <70%, EPS growing >5%, Net Debt/EBITDA <3x, FCF covers dividend >1.5x, ROIC stable >8%. Real income streams from real businesses — not yield traps.",
        "items": _dividend_items(),
    },
    "minervini": {
        "id": "minervini",
        "name": "Minervini Trend Template — Pure Momentum",
        "tagline": "Stage 2 trends with earnings confirmation",
        "description": "Price > 50DMA > 200DMA, 5%+ above 200DMA, 30%+ off 52w low, within 25% of 52w high, RSI 50-75 (strong not extended), earnings growing >20%. Pure trend-follower discipline.",
        "items": _minervini_items(),
    },
}


# ===========================================================================
# Scoring engine
# ===========================================================================

def score_profile(profile_id: str, quote: dict, trends: dict | None = None) -> dict:
    """Score a stock against one profile. Returns full result."""
    profile = PROFILES.get(profile_id)
    if not profile:
        return {"error": f"Unknown profile: {profile_id}"}

    if trends is None:
        symbol = quote.get("symbol", "")
        trends = _trends.get_annual_trends(symbol) if symbol else {"metrics": {}, "trends": {}}

    items_out = []
    total = 0
    max_score = 0
    for item in profile["items"]:
        try:
            passed, actual = item["evaluate"](quote, trends)
        except Exception as e:
            passed, actual = False, f"calc error: {e}"
        max_score += item["w"]
        if passed:
            total += item["w"]
        items_out.append({
            "id": item["id"],
            "label": item["label"],
            "weight": item["w"],
            "note": item["note"],
            "pass": bool(passed),
            "actual": actual,
        })

    pct = total / max_score if max_score else 0
    verdict = _profile_verdict(profile_id, total, max_score, pct, items_out)

    return {
        "profile": profile_id,
        "profile_name": profile["name"],
        "items": items_out,
        "total": total,
        "max": max_score,
        "pct": pct,
        "verdict": verdict,
    }


def score_all_profiles(quote: dict, trends: dict | None = None) -> dict:
    """Score against all four profiles. Returns dict keyed by profile_id."""
    if trends is None:
        symbol = quote.get("symbol", "")
        trends = _trends.get_annual_trends(symbol) if symbol else {"metrics": {}, "trends": {}}
    return {pid: score_profile(pid, quote, trends) for pid in PROFILES}


def _profile_verdict(profile_id: str, total: int, max_score: int, pct: float, items: list) -> dict:
    """Verdict text per profile."""
    passed_ids = [it["id"] for it in items if it["pass"]]
    failed_ids = [it["id"] for it in items if not it["pass"]]

    if profile_id == "buffett":
        if pct >= 0.80:
            return {"head": "Textbook Buffett compounder",
                    "explain": f"Hits {total}/{max_score} on the Buffett checklist. Cheap-ish AND durable AND well-managed. Pay attention.",
                    "color": "darkgreen"}
        if pct >= 0.60:
            gaps = ", ".join(it["label"].split(" (")[0] for it in items if not it["pass"])[:120]
            return {"head": "Solid quality, some gaps",
                    "explain": f"{total}/{max_score}. Missing: {gaps}. May still be worth owning if gaps are small.",
                    "color": "green"}
        if pct >= 0.40:
            return {"head": "Quality lite — not a Buffett name",
                    "explain": f"{total}/{max_score}. Some quality signals but too many gaps. Try other profiles.",
                    "color": "amber"}
        return {"head": "Not a Buffett stock",
                "explain": f"{total}/{max_score}. Fails the durability / quality test. Pass.",
                "color": "red"}

    if profile_id == "graham":
        if pct >= 0.75:
            return {"head": "Textbook Graham cigar butt",
                    "explain": f"{total}/{max_score}. Statistically cheap with safety buffer. Size small (these often turn out for a reason).",
                    "color": "darkgreen"}
        if pct >= 0.50:
            return {"head": "Decent value setup",
                    "explain": f"{total}/{max_score}. Cheap on some metrics. Investigate why it's cheap before buying.",
                    "color": "green"}
        if pct >= 0.30:
            return {"head": "Not cheap enough for Graham",
                    "explain": f"{total}/{max_score}. Doesn't meet Graham's cigar-butt thresholds.",
                    "color": "amber"}
        return {"head": "Full price — not a Graham name",
                "explain": f"{total}/{max_score}. Pass.",
                "color": "red"}

    if profile_id == "lynch":
        if pct >= 0.75:
            return {"head": "Lynch's wheelhouse",
                    "explain": f"{total}/{max_score}. Growth + reasonable price + insider conviction. The classic 10-bagger setup.",
                    "color": "darkgreen"}
        if pct >= 0.55:
            return {"head": "GARP candidate with caveats",
                    "explain": f"{total}/{max_score}. Some Lynch signals present. Build small, add on confirmation.",
                    "color": "green"}
        if pct >= 0.30:
            return {"head": "Either expensive or not growing",
                    "explain": f"{total}/{max_score}. Lynch wouldn't bite without the growth/price combo.",
                    "color": "amber"}
        return {"head": "No GARP setup here",
                "explain": f"{total}/{max_score}.",
                "color": "red"}

    if profile_id == "fisher":
        if pct >= 0.75:
            return {"head": "Decadal compounder candidate",
                    "explain": f"{total}/{max_score}. Sustained high growth + superior margins + clean balance sheet. Own for years.",
                    "color": "darkgreen"}
        if pct >= 0.55:
            return {"head": "Fisher-lite — has the goods on most fronts",
                    "explain": f"{total}/{max_score}. Quality and growth present, watch the missing pieces.",
                    "color": "green"}
        if pct >= 0.30:
            return {"head": "Not Fisher quality",
                    "explain": f"{total}/{max_score}.",
                    "color": "amber"}
        return {"head": "No quality-growth thesis",
                "explain": f"{total}/{max_score}.",
                "color": "red"}

    # Generic verdict for every other profile (inflection, canslim, magic_formula,
    # dividend, minervini, and anything added later). Uses the profile's own name so
    # the headline stays specific even without bespoke copy — replaces the old "—"
    # placeholder that left five profiles with blank grey verdict cards.
    pname = PROFILES.get(profile_id, {}).get("name", profile_id).split(" — ")[0]
    article = "an" if pname[:1].upper() in "AEIOU" else "a"
    gaps = ", ".join(it["label"].split(" (")[0] for it in items if not it["pass"])[:140]
    if pct >= 0.80:
        return {"head": f"Strong {pname} fit",
                "explain": f"{total}/{max_score}. Clears nearly every {pname} criterion — high-conviction match for this style.",
                "color": "darkgreen"}
    if pct >= 0.60:
        return {"head": f"Good {pname} fit, minor gaps",
                "explain": f"{total}/{max_score}. Missing: {gaps or 'a few secondary checks'}. Worth a look if those gaps are tolerable.",
                "color": "green"}
    if pct >= 0.40:
        return {"head": f"Partial {pname} fit",
                "explain": f"{total}/{max_score}. Some signals present but too many gaps. Missing: {gaps}.",
                "color": "amber"}
    return {"head": f"Not {article} {pname} name",
            "explain": f"{total}/{max_score}. Fails the core {pname} tests. Pass for this style.",
            "color": "red"}


def best_profile(scores: dict) -> str:
    """Return the profile id with the highest pct score."""
    if not scores:
        return ""
    return max(scores, key=lambda k: scores[k].get("pct", 0))


def summary_grid(scores: dict) -> list[dict]:
    """For each profile, return a compact summary row for display."""
    out = []
    for pid, sc in scores.items():
        out.append({
            "profile": sc["profile_name"],
            "score": f"{sc['total']}/{sc['max']}",
            "pct": sc["pct"],
            "verdict": sc["verdict"]["head"],
            "color": sc["verdict"]["color"],
        })
    return out
