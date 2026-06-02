"""v2 — Heuristic bull/bear thesis synthesizer.

Takes quote + trends + multi-profile scores + quality flags + reverse DCF
and produces:
  - 3-5 bullet bull case
  - 3-5 bullet bear case
  - "thesis breaks if X" trigger list
  - one-line overall stance

No LLM call — deterministic heuristics so the user trusts it. The output
gives the user a starting point to refine, not a final answer.
"""
from __future__ import annotations

from typing import Any


def _safe(v, default=None):
    if v is None:
        return default
    try:
        if isinstance(v, float) and v != v:  # NaN
            return default
    except Exception:
        pass
    return v


def build_thesis(
    quote: dict,
    trends: dict,
    profile_scores: dict,
    quality_flags: dict | None = None,
    reverse_dcf: dict | None = None,
) -> dict[str, Any]:
    """Construct bull/bear/triggers from all available signals."""
    bull: list[str] = []
    bear: list[str] = []
    breaks_if: list[str] = []

    symbol = quote.get("symbol", "")
    price = _safe(quote.get("price"))
    name = quote.get("name") or symbol

    # ---- BULL POINTS ----

    # Best profile fit
    best_pid = max(profile_scores, key=lambda k: profile_scores[k].get("pct", 0))
    best = profile_scores[best_pid]
    if best["pct"] >= 0.6:
        bull.append(f"Strong fit for **{best['profile_name']}** style: {best['total']}/{best['max']} ({best['pct']*100:.0f}%) — {best['verdict']['head'].lower()}.")

    # Trends — rising margins, rising ROIC, rising FCF
    rising_metrics = [m for m, t in trends.get("trends", {}).items()
                      if t.get("direction") == "rising" and m in ("operating_margin", "roic", "fcf", "gross_margin", "revenue")]
    if rising_metrics:
        bull.append(f"Multi-year rising trajectory in: {', '.join(rising_metrics).replace('_', ' ')}.")

    # Reverse DCF: low implied growth = priced for failure
    if reverse_dcf and reverse_dcf.get("implied_growth") is not None:
        g = reverse_dcf["implied_growth"]
        if g < 0.05:
            bull.append(f"Reverse DCF implies just {g*100:.1f}% annual growth needed to justify price — large margin of safety on growth assumption.")
        elif g < 0.10:
            bull.append(f"Reverse DCF implies modest {g*100:.1f}% growth needed — fairly priced if business is stable.")

    # Insider conviction
    if quote.get("insider_cluster_buy"):
        bull.append(f"Cluster insider buying (last 6mo): {quote.get('insider_buys_6mo', 0)} buys vs {quote.get('insider_sells_6mo', 0)} sells.")

    # Strong quality flags
    if quality_flags:
        p = quality_flags.get("piotroski", {})
        if p.get("score") is not None and p["score"] >= 7:
            bull.append(f"Piotroski F-Score {p['score']}/9 (strong financial health).")
        a = quality_flags.get("altman", {})
        a_score = a.get("score")
        if a_score is not None and a_score > 2.99:
            bull.append(f"Altman Z {a_score:.2f} — well outside distress zone.")

    # Analyst conviction
    rec = (quote.get("recommend") or "").lower()
    if "strong_buy" in rec or "buy" in rec:
        n = quote.get("n_analysts") or 0
        if n > 5:
            bull.append(f"Sell-side consensus is {rec.upper()} across {n} analysts.")

    # Technical confirmation
    px = quote.get("price"); dma200 = quote.get("dma_200"); dma50 = quote.get("dma_50")
    if px and dma200 and dma50 and px > dma50 > dma200:
        bull.append("Price > 50DMA > 200DMA — Stage 2 uptrend confirmed.")

    # Buybacks (from trends)
    sh_change = trends.get("metrics", {}).get("shares_change", [])
    recent_sh = [v for v in sh_change[:3] if v is not None]
    if recent_sh and sum(recent_sh) / len(recent_sh) < -0.005:
        bull.append("Per-share value compounding — share count shrinking.")

    # ---- BEAR POINTS ----

    # Worst profile fit signals
    worst_pid = min(profile_scores, key=lambda k: profile_scores[k].get("pct", 1))
    worst = profile_scores[worst_pid]
    if worst["pct"] < 0.30 and best["pct"] < 0.55:
        bear.append(f"Fails most profiles — best is {best['profile_name']} at only {best['pct']*100:.0f}%.")

    # Falling metrics (real alpha killer)
    falling_metrics = [m for m, t in trends.get("trends", {}).items()
                       if t.get("direction") == "falling" and m in ("operating_margin", "roic", "gross_margin", "fcf")]
    if falling_metrics:
        bear.append(f"Deteriorating fundamentals — falling: {', '.join(falling_metrics).replace('_', ' ')}.")
        breaks_if.append(f"Decline in {falling_metrics[0].replace('_', ' ')} accelerates next quarter.")

    # Reverse DCF: high implied growth = priced for perfection
    if reverse_dcf and reverse_dcf.get("implied_growth") is not None:
        g = reverse_dcf["implied_growth"]
        if g > 0.20:
            bear.append(f"Reverse DCF needs {g*100:.0f}% growth/yr — perfection pricing with asymmetric downside.")
            breaks_if.append(f"Revenue growth slows below {g*100:.0f}% sustained.")

    # Insider distribution
    sells = quote.get("insider_sells_6mo", 0) or 0
    buys = quote.get("insider_buys_6mo", 0) or 0
    if sells > buys * 3 and sells > 3:
        bear.append(f"Insider distribution — {sells} sells vs {buys} buys last 6mo.")

    # Quality flag warnings
    if quality_flags:
        p = quality_flags.get("piotroski", {})
        if p.get("score") is not None and p["score"] <= 3:
            bear.append(f"Piotroski F-Score {p['score']}/9 — weak financial health.")
        a = quality_flags.get("altman", {})
        a_score = a.get("score")
        if a_score is not None and a_score < 1.81:
            bear.append(f"Altman Z {a_score:.2f} — distress risk per the model.")
        b = quality_flags.get("beneish", {})
        if b.get("flagged"):
            bear.append(f"Beneish M-score flag (screening signal only — high false-positive rate; review accruals and revenue recognition before acting).")

    # Leverage warning
    nde_vals = trends.get("metrics", {}).get("nd_ebitda", [])
    last_nde = next((v for v in nde_vals if v is not None), None)
    if last_nde is not None and last_nde > 4:
        bear.append(f"Net Debt/EBITDA {last_nde:.1f}x — elevated leverage limits flexibility.")
        breaks_if.append(f"Earnings disappoint and covenants tighten.")

    # Technical breakdown
    if px and dma200 and px < dma200 * 0.95:
        bear.append(f"Price below 200DMA by {(1 - px/dma200)*100:.1f}% — Stage 3/4 territory, falling-knife risk.")
        breaks_if.append("Price loses 200DMA support and accelerates downward.")

    # Concentration risk: very high single profile score with weak others
    if best["pct"] > 0.7 and worst["pct"] < 0.2:
        bear.append(f"Thesis is single-style dependent — works for {best['profile_name']} but {worst['profile_name']} screams to pass.")

    # ---- DEFAULT BREAKS_IF (always add these) ----
    if not breaks_if:
        breaks_if.append("Next earnings prints below estimates with no guidance raise.")
    breaks_if.append("Operating margin contracts for 2 consecutive quarters.")
    breaks_if.append("Net Debt/EBITDA crosses 3x.")

    # ---- OVERALL STANCE ----
    stance = _overall_stance(profile_scores, len(bull), len(bear), quality_flags, reverse_dcf)

    return {
        "symbol": symbol,
        "name": name,
        "stance": stance,
        "bull": bull or ["No clear bull catalysts visible — need to investigate the thesis manually."],
        "bear": bear or ["No obvious red flags — but absence of evidence ≠ evidence of absence."],
        "breaks_if": breaks_if,
        "best_profile": best_pid,
        "summary": _one_line_summary(name, symbol, stance, best),
    }


def _overall_stance(profile_scores: dict, n_bull: int, n_bear: int,
                    quality_flags: dict | None, reverse_dcf: dict | None) -> dict:
    """Synthesize an overall stance. Defensive against None values."""
    try:
        return _overall_stance_inner(profile_scores, n_bull, n_bear, quality_flags, reverse_dcf)
    except Exception as e:
        return {"label": "WATCH", "color": "amber",
                "rationale": f"Score calc partial (some metrics unavailable): {e}"}


def _overall_stance_inner(profile_scores: dict, n_bull: int, n_bear: int,
                          quality_flags: dict | None, reverse_dcf: dict | None) -> dict:
    """Synthesize an overall stance."""
    # Profile-weighted score (max of all profiles is the strongest fit)
    best_pct = max(s.get("pct", 0) for s in profile_scores.values())
    best_pid = max(profile_scores, key=lambda k: profile_scores[k].get("pct", 0))

    # Quality flag adjustment
    qa = 0
    if quality_flags:
        ps = quality_flags.get("piotroski", {}).get("score")
        if ps is not None and ps >= 7:
            qa += 0.1
        az = quality_flags.get("altman", {}).get("score")
        if az is not None:
            if az > 2.99:
                qa += 0.05
            elif az < 1.81:
                qa -= 0.15
        if quality_flags.get("beneish", {}).get("flagged"):
            qa -= 0.15

    # Reverse DCF adjustment
    rd_adj = 0
    if reverse_dcf and reverse_dcf.get("implied_growth") is not None:
        g = reverse_dcf["implied_growth"]
        if g < 0.05:
            rd_adj += 0.1
        elif g > 0.25:
            rd_adj -= 0.15

    # Bull/bear balance
    bb = (n_bull - n_bear) * 0.04

    score = max(0, min(1, best_pct + qa + rd_adj + bb))

    if score > 0.75:
        return {"label": "STRONG BUY", "color": "darkgreen",
                "rationale": f"Strong fit for {profile_scores[best_pid]['profile_name']} with confirming signals."}
    if score > 0.55:
        return {"label": "BUY", "color": "green",
                "rationale": f"Solid {profile_scores[best_pid]['profile_name']} setup with mixed confirmation."}
    if score > 0.40:
        return {"label": "WATCH", "color": "amber",
                "rationale": "Some thesis present but conviction signals incomplete."}
    if score > 0.25:
        return {"label": "PASS", "color": "red",
                "rationale": "Weak fit across all styles. Better setups elsewhere."}
    return {"label": "AVOID", "color": "red",
            "rationale": "Multiple red flags. Don't catch a falling knife."}


def executive_summary(quote: dict, trends: dict, thesis: dict,
                      vpct: dict | None = None, quality_flags: dict | None = None,
                      technicals: dict | None = None, options: dict | None = None,
                      rdcf: dict | None = None) -> list[str]:
    """Build a short, readable research-note summary (2-4 paragraphs) entirely from
    the data we already pulled — no LLM. Each item is a paragraph (markdown allowed)."""
    name = quote.get("name") or quote.get("symbol", "")
    sym = quote.get("symbol", "")
    sector = quote.get("sector") or "—"
    industry = quote.get("industry") or "—"
    price = _safe(quote.get("price"))
    paras: list[str] = []

    def pct(v, d=1):
        return f"{v*100:.{d}f}%" if isinstance(v, (int, float)) else "n/a"

    # ---- Para 1: what it is + where it's valued ----
    fpe = _safe(quote.get("pe_forward")) or _safe(quote.get("pe_trailing"))
    p1 = f"**{name} ({sym})** is a {sector.lower()} company"
    if industry and industry != "—":
        p1 += f" in {industry.lower()}"
    if price:
        p1 += f", trading at **${price:.2f}**"
    if fpe and fpe > 0:
        p1 += f" (≈{fpe:.1f}× forward earnings)"
    p1 += "."
    if vpct and vpct.get("percentile") is not None:
        pp = int(round(vpct["percentile"]))
        # ordinal suffix: 1st, 2nd, 3rd, 21st... (11-13 are always 'th')
        suf = "th" if 10 <= pp % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(pp % 10, "th")
        read = ("rich versus its own 5-year range" if pp >= 80 else
                "above its historical norm" if pp >= 60 else
                "cheap versus its own history" if pp <= 35 else
                "near its historical norm")
        p1 += f" Its P/E sits in the **{pp}{suf} percentile** of its own 5-year range — {read}."
    paras.append(p1)

    # ---- Para 2: quality, growth, trajectory ----
    roe = _safe(quote.get("roe")); om = _safe(quote.get("operating_margin"))
    gm = _safe(quote.get("gross_margin")); rg = _safe(quote.get("rev_growth"))
    bits = []
    if roe is not None: bits.append(f"ROE {pct(roe)}")
    if om is not None: bits.append(f"operating margin {pct(om)}")
    if gm is not None: bits.append(f"gross margin {pct(gm)}")
    if rg is not None: bits.append(f"revenue growth {pct(rg)} YoY")
    p2 = ""
    if bits:
        p2 = "On fundamentals: " + ", ".join(bits) + "."
    tr = trends.get("trends", {}) if trends else {}
    rising = [m.replace("_", " ") for m in ("revenue", "operating_margin", "roic", "fcf", "gross_margin")
              if tr.get(m, {}).get("direction") == "rising"]
    falling = [m.replace("_", " ") for m in ("revenue", "operating_margin", "roic", "fcf", "gross_margin")
               if tr.get(m, {}).get("direction") == "falling"]
    if rising:
        p2 += f" Multi-year trends are **improving** in {', '.join(rising)}."
    if falling:
        p2 += f" **Watch** the declining trend in {', '.join(falling)}."
    if quality_flags:
        pf = quality_flags.get("piotroski", {}).get("score")
        az = quality_flags.get("altman", {}).get("score")
        q = []
        if pf is not None: q.append(f"Piotroski {pf}/9")
        if az is not None: q.append(f"Altman Z {az:.1f}")
        if q:
            p2 += f" Financial-health checks: {', '.join(q)}."
    if p2:
        paras.append(p2.strip())

    # ---- Balance sheet / capital return ----
    nde_vals = (trends.get("metrics", {}) if trends else {}).get("nd_ebitda", [])
    last_nde = next((v for v in nde_vals if v is not None), None)
    div_y = _safe(quote.get("div_yield"))
    sh_change = (trends.get("metrics", {}) if trends else {}).get("shares_change", [])
    recent_sh = [v for v in sh_change[:3] if v is not None]
    bs_bits = []
    if last_nde is not None:
        bs_bits.append(f"net debt is {last_nde:.1f}× EBITDA" if last_nde >= 0 else "it holds a net-cash position")
    if recent_sh and sum(recent_sh) / len(recent_sh) < -0.005:
        bs_bits.append("the share count is shrinking (buybacks)")
    elif recent_sh and sum(recent_sh) / len(recent_sh) > 0.02:
        bs_bits.append("shares outstanding are rising (dilution)")
    if div_y and div_y > 0:
        bs_bits.append(f"it pays a {pct(div_y)} dividend")
    if bs_bits:
        paras.append("On the balance sheet and capital return: " + "; ".join(bs_bits) + ".")

    # ---- Technicals ----
    if technicals and technicals.get("trend_stage"):
        t = technicals
        p_t = f"Technically, the chart is in a **{t['trend_stage'].lower()}**"
        if t.get("rsi") is not None:
            r = t["rsi"]
            tag = "overbought" if r >= 70 else "oversold" if r <= 30 else "neutral"
            p_t += f", RSI(14) at {r:.0f} ({tag})"
        if t.get("macd"):
            p_t += f", MACD {'bullish' if t['macd'].get('bullish') else 'bearish'}"
        p_t += "."
        if t.get("from_52w_high") is not None:
            p_t += f" Price is **{t['from_52w_high']*100:+.0f}%** from its 52-week high"
            if t.get("from_52w_low") is not None:
                p_t += f" and {t['from_52w_low']*100:+.0f}% off the low"
            p_t += "."
        rets = t.get("returns", {})
        mom = ", ".join(f"{k} {v*100:+.0f}%" for k, v in rets.items())
        if mom:
            p_t += f" Momentum: {mom}."
        paras.append(p_t)

    # ---- Options-implied ----
    if options and options.get("expected_move_pct") is not None:
        o = options
        p_o = (f"The **options market** implies a move of about **±{o['expected_move_pct']*100:.1f}%** "
               f"(≈${o.get('expected_move_abs', 0):.2f}) by {o.get('expiry')}")
        if o.get("atm_iv"):
            p_o += f", with at-the-money implied volatility of {o['atm_iv']*100:.0f}%"
        p_o += "."
        pc = o.get("pc_oi_ratio")
        if pc is not None:
            lean = "bearish" if pc > 1.2 else "bullish" if pc < 0.7 else "balanced"
            p_o += f" Put/call open interest is {pc:.2f} ({lean} positioning)"
            if o.get("max_pain"):
                p_o += f"; max-pain sits at ${o['max_pain']:.0f}"
            p_o += "."
        paras.append(p_o)

    # ---- Valuation (reverse DCF) ----
    if rdcf and rdcf.get("implied_growth") is not None:
        g = rdcf["implied_growth"]
        verdict = (rdcf.get("verdict") or "").rstrip(".")
        paras.append(f"On valuation, a reverse-DCF says today's price already bakes in roughly "
                     f"**{g*100:.1f}%/yr** growth for a decade — {verdict.lower()}.")

    # ---- Para 3: the Street + our read ----
    rec = (quote.get("recommend") or "").replace("_", " ").strip()
    n_an = quote.get("n_analysts")
    tgt = _safe(quote.get("target_median"))
    p3 = ""
    if rec:
        p3 = f"Sell-side consensus is **{rec.upper()}**"
        if n_an:
            p3 += f" across {int(n_an)} analysts"
        if tgt and price:
            up = (tgt / price - 1) * 100
            p3 += f", with a median price target of ${tgt:.2f} (**{up:+.0f}%** vs today)"
        p3 += "."
    stance = thesis.get("stance", {})
    best_pid = thesis.get("best_profile")
    scores = None
    if stance:
        p3 += (f" Our scorecards read this as a **{stance.get('label','—')}**"
               f" — {stance.get('rationale','').rstrip('.')}.")
    bear = thesis.get("bear") or []
    if bear and not bear[0].startswith("No obvious"):
        p3 += f" Chief risk to monitor: {bear[0].rstrip('.')}."
    if p3:
        paras.append(p3.strip())

    return paras


def _one_line_summary(name: str, symbol: str, stance: dict, best: dict) -> str:
    return (
        f"{name} ({symbol}): {stance['label']} — "
        f"best fit is {best['profile_name']} ({best['pct']*100:.0f}%). {stance['rationale']}"
    )


# ---------------------------------------------------------------------------
# Three-pillar grade bar
# ---------------------------------------------------------------------------

def compute_grade_bar(
    quote: dict,
    trends: dict,
    quality_flags: dict | None = None,
    reverse_dcf: dict | None = None,
) -> dict[str, dict]:
    """Return a three-pillar assessment: valuation, quality, momentum.

    Each pillar has: grade (str), color (str), emoji (str), detail (str).
    """

    # --- Valuation ---
    val_grade, val_color, val_emoji, val_detail = "Fair", "yellow", "\U0001f7e1", ""
    implied_growth = None
    if reverse_dcf and reverse_dcf.get("implied_growth") is not None:
        implied_growth = reverse_dcf["implied_growth"]

    pe_fwd = _safe(quote.get("pe_forward"))
    pe_trail = _safe(quote.get("pe_trailing"))
    pe = pe_fwd or pe_trail

    # Determine valuation grade
    expensive_signals = 0
    cheap_signals = 0
    detail_parts: list[str] = []

    if implied_growth is not None:
        if implied_growth > 0.25:
            expensive_signals += 2
            detail_parts.append(f"needs {implied_growth*100:.0f}%/yr growth")
        elif implied_growth < 0.08:
            cheap_signals += 2
            detail_parts.append(f"needs only {implied_growth*100:.0f}%/yr growth")
        else:
            detail_parts.append(f"implies {implied_growth*100:.0f}%/yr growth")

    if pe is not None and pe > 0:
        if pe > 40:
            expensive_signals += 1
            detail_parts.append(f"P/E {pe:.0f}x")
        elif pe < 15:
            cheap_signals += 1
            detail_parts.append(f"P/E {pe:.0f}x")
        else:
            detail_parts.append(f"P/E {pe:.0f}x")

    if expensive_signals >= 2:
        val_grade, val_color, val_emoji = "Expensive", "red", "\U0001f534"
    elif cheap_signals >= 2:
        val_grade, val_color, val_emoji = "Cheap", "green", "\U0001f7e2"
    elif expensive_signals >= 1 and cheap_signals == 0:
        val_grade, val_color, val_emoji = "Expensive", "red", "\U0001f534"
    elif cheap_signals >= 1 and expensive_signals == 0:
        val_grade, val_color, val_emoji = "Cheap", "green", "\U0001f7e2"

    val_detail = ", ".join(detail_parts) if detail_parts else "insufficient data"

    # --- Quality ---
    q_grade, q_color, q_emoji, q_detail = "OK", "yellow", "\U0001f7e1", ""
    piotroski_score = None
    roe = _safe(quote.get("roe"))
    gm = _safe(quote.get("gross_margin"))
    om = _safe(quote.get("operating_margin"))

    if quality_flags:
        ps = quality_flags.get("piotroski", {}).get("score")
        if ps is not None:
            piotroski_score = ps

    q_parts: list[str] = []
    strong_signals = 0
    weak_signals = 0

    if piotroski_score is not None:
        q_parts.append(f"Piotroski {piotroski_score}/9")
        if piotroski_score >= 7:
            strong_signals += 1
        elif piotroski_score <= 3:
            weak_signals += 1

    if roe is not None:
        q_parts.append(f"ROE {roe*100:.0f}%")
        if roe > 0.15:
            strong_signals += 1
        elif roe < 0.05:
            weak_signals += 1

    # Check margin trends
    tr_dict = trends.get("trends", {}) if trends else {}
    margins_rising = any(
        tr_dict.get(m, {}).get("direction", "").startswith("rising")
        for m in ("gross_margin", "operating_margin")
    )
    margins_falling = any(
        tr_dict.get(m, {}).get("direction", "").startswith("falling")
        for m in ("gross_margin", "operating_margin")
    )
    if margins_rising:
        q_parts.append("margins rising")
        strong_signals += 1
    elif margins_falling:
        q_parts.append("margins falling")
        weak_signals += 1

    if strong_signals >= 2 and weak_signals == 0:
        q_grade, q_color, q_emoji = "Strong", "green", "\U0001f7e2"
    elif weak_signals >= 2 or (weak_signals >= 1 and strong_signals == 0):
        q_grade, q_color, q_emoji = "Weak", "red", "\U0001f534"

    q_detail = ", ".join(q_parts) if q_parts else "insufficient data"

    # --- Momentum ---
    m_grade, m_color, m_emoji, m_detail = "Mixed", "yellow", "\U0001f7e1", ""
    price = _safe(quote.get("price"))
    dma200 = _safe(quote.get("dma_200"))
    dma50 = _safe(quote.get("dma_50"))
    rsi = _safe(quote.get("rsi_14"))

    m_parts: list[str] = []
    above_200 = False
    below_200 = False

    if price and dma200:
        if price > dma200:
            above_200 = True
            m_parts.append("above 200DMA")
        else:
            below_200 = True
            m_parts.append("below 200DMA")

    if price and dma50 and dma200:
        if price > dma50 > dma200:
            m_parts.append("Stage 2")

    if rsi is not None:
        m_parts.append(f"RSI {rsi:.0f}")

    if above_200 and (rsi is None or 30 <= rsi <= 70):
        m_grade, m_color, m_emoji = "Uptrend", "green", "\U0001f7e2"
    elif above_200 and rsi is not None and rsi > 70:
        m_grade, m_color, m_emoji = "Overbought", "yellow", "\U0001f7e1"
    elif below_200:
        m_grade, m_color, m_emoji = "Downtrend", "red", "\U0001f534"

    m_detail = ", ".join(m_parts) if m_parts else "insufficient data"

    return {
        "valuation": {"grade": val_grade, "color": val_color, "emoji": val_emoji, "detail": val_detail},
        "quality": {"grade": q_grade, "color": q_color, "emoji": q_emoji, "detail": q_detail},
        "momentum": {"grade": m_grade, "color": m_color, "emoji": m_emoji, "detail": m_detail},
    }


def bottom_line_summary(
    quote: dict,
    trends: dict,
    thesis: dict,
    reverse_dcf: dict | None = None,
    grade_bar: dict | None = None,
) -> str:
    """Return a 2-3 sentence plain-English bottom-line summary of the stock.

    Uses data from quote, trends, thesis, and reverse_dcf. Factual, no jargon.
    """
    name = quote.get("name") or quote.get("symbol", "")
    symbol = quote.get("symbol", "")
    price = _safe(quote.get("price"))
    roe = _safe(quote.get("roe"))
    gm = _safe(quote.get("gross_margin"))
    om = _safe(quote.get("operating_margin"))
    rev_growth = _safe(quote.get("rev_growth"))
    rec = (quote.get("recommend") or "").replace("_", " ").strip().upper()
    piotroski = None
    if thesis.get("stance"):
        stance_label = thesis["stance"].get("label", "WATCH")
    else:
        stance_label = "WATCH"

    # Quality description
    quality_bits: list[str] = []
    if gm is not None and gm > 0.40:
        quality_bits.append("strong margins")
    if roe is not None and roe > 0.15:
        quality_bits.append(f"ROE {roe*100:.0f}%")

    # Check for buybacks from trends
    sh_change = (trends.get("metrics", {}) if trends else {}).get("shares_change", [])
    recent_sh = [v for v in (sh_change or [])[:3] if v is not None]
    if recent_sh and sum(recent_sh) / len(recent_sh) < -0.005:
        quality_bits.append("buybacks")

    # Piotroski from grade_bar detail
    if grade_bar and "Piotroski" in grade_bar.get("quality", {}).get("detail", ""):
        quality_bits.append(grade_bar["quality"]["detail"].split(",")[0].strip())

    # Build sentence 1: quality assessment
    parts: list[str] = []
    if quality_bits:
        q_str = ", ".join(quality_bits)
        if grade_bar and grade_bar["valuation"]["grade"] == "Expensive":
            parts.append(f"{name} is a high-quality business ({q_str}) trading at a premium")
        elif grade_bar and grade_bar["valuation"]["grade"] == "Cheap":
            parts.append(f"{name} is a quality business ({q_str}) trading at a discount")
        else:
            parts.append(f"{name} shows solid fundamentals ({q_str})")
    else:
        if grade_bar and grade_bar["quality"]["grade"] == "Weak":
            parts.append(f"{name} has weak fundamentals")
        else:
            parts.append(f"{name} has mixed fundamentals")

    # Build sentence 2: valuation context from reverse DCF
    if reverse_dcf and reverse_dcf.get("implied_growth") is not None:
        ig = reverse_dcf["implied_growth"] * 100
        rg = (rev_growth or 0) * 100
        if price:
            parts.append(
                f"the market needs {ig:.0f}% annual growth for a decade to justify "
                f"today's price of ${price:.0f}"
            )
        if rev_growth is not None:
            if rg > ig:
                parts.append(f"it grew {rg:.0f}% last year, exceeding the bar")
            elif abs(rg - ig) < 3:
                parts.append(f"it grew {rg:.0f}% last year, roughly matching expectations")
            else:
                parts.append(f"it grew {rg:.0f}% last year, so you're paying up for acceleration")

    # Build sentence 3: momentum + consensus
    momentum_bits: list[str] = []
    if grade_bar:
        mg = grade_bar["momentum"]["grade"]
        if mg == "Uptrend":
            momentum_bits.append("in an uptrend")
        elif mg == "Downtrend":
            momentum_bits.append("in a downtrend")
        else:
            momentum_bits.append("showing mixed momentum")

    if rec and rec not in ("—", ""):
        momentum_bits.append(f"analyst consensus at {rec}")

    if momentum_bits:
        parts.append("the stock is " + " with ".join(momentum_bits))

    # Assemble into sentences
    if len(parts) >= 3:
        result = f"{parts[0]} — {parts[1]}. {parts[2].capitalize()}. {parts[3].capitalize()}." if len(parts) >= 4 else f"{parts[0]} — {parts[1]}. {parts[2].capitalize()}."
    elif len(parts) == 2:
        result = f"{parts[0]} — {parts[1]}."
    else:
        result = f"{parts[0]}."

    return result
