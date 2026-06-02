"""Concurrent diagnose orchestrator.

Replaces 5-7 serial fetches with 1 concurrent pull. Returns one dict
containing everything Stock Pro needs to render.

Before:
    quote = data.get_enriched_quote(sym)        # ~2s
    tr    = trends.get_annual_trends(sym)        # ~1.5s
    qf    = quality_flags.all_quality_flags(sym) # ~1.5s
    insider = data.get_insider_transactions(sym) # ~1s
    peers = [data.get_quote(p) for p in peer_syms[:6]] # ~6s serial
    hist  = data.get_price_history(sym)          # ~0.5s
                                                ─────
                                                 ~12s

After: ~3-4s via ThreadPoolExecutor + shared financials cache.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lib import data, financials, trends, profiles, quality_flags, valuation, narrative


def diagnose(symbol: str, n_peers: int = 6) -> dict[str, Any]:
    """Run the full diagnose pipeline concurrently. Returns one dict."""
    if not symbol or not symbol.strip():
        return {
            "symbol": "",
            "error": "No ticker provided",
            "quote": {},
            "financials": {},
            "trends": {},
            "scores": {},
            "quality_flags": {},
            "rdcf": None,
            "thesis": {},
            "insider_df": None,
            "peers_data": [],
            "peer_symbols": [],
            "price_history": None,
            "timings": {},
        }
    sym = symbol.upper()
    timings: dict[str, float] = {}
    t0 = time.time()

    # ---- Phase 1: parallel network fetches ----
    def run_quote():
        s = time.time()
        try: return data.get_enriched_quote(sym)
        finally: timings["quote"] = time.time() - s

    def run_fin():
        s = time.time()
        try: return financials.get_all(sym)
        finally: timings["financials"] = time.time() - s

    def run_insider():
        s = time.time()
        try: return data.get_insider_transactions(sym)
        finally: timings["insider"] = time.time() - s

    def run_hist():
        s = time.time()
        try: return data.get_price_history(sym)
        finally: timings["history"] = time.time() - s

    with ThreadPoolExecutor(max_workers=4) as ex:
        fut_quote   = ex.submit(run_quote)
        fut_fin     = ex.submit(run_fin)
        fut_insider = ex.submit(run_insider)
        fut_hist    = ex.submit(run_hist)
        quote = fut_quote.result()
        fin = fut_fin.result()
        insider_df = fut_insider.result()
        price_history = fut_hist.result()

    if not quote or "error" in quote:
        return {
            "symbol": sym,
            "error": quote.get("error", "fetch failed") if quote else "no quote",
            "timings": timings,
        }

    # ---- Phase 2: peers in parallel ----
    s = time.time()
    peer_syms = data.get_peers(sym)
    peers_data = []
    if peer_syms:
        with ThreadPoolExecutor(max_workers=min(n_peers, 8)) as ex:
            futs = {ex.submit(data.get_quote, p): p for p in peer_syms[:n_peers]}
            for fut in futs:
                try:
                    pq = fut.result()
                    if pq and "error" not in pq:
                        peers_data.append(pq)
                except Exception:
                    pass
    timings["peers"] = time.time() - s

    # ---- Phase 3: trends + quality_flags (no extra network — use prefetched fin) ----
    def run_trends():
        s = time.time()
        try: return trends.get_annual_trends(sym, _financials=fin)
        finally: timings["trends"] = time.time() - s

    def run_qflags():
        s = time.time()
        try: return quality_flags.all_quality_flags(sym, _financials=fin, _quote=quote)
        finally: timings["quality_flags"] = time.time() - s

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_tr = ex.submit(run_trends)
        fut_qf = ex.submit(run_qflags)
        tr = fut_tr.result()
        qf = fut_qf.result()

    # ---- Phase 4: scoring + RDCF + thesis (pure compute, serial) ----
    s = time.time()
    scores = profiles.score_all_profiles(quote, tr)

    rdcf = None
    if quote.get("fcf") and quote["fcf"] > 0 and quote.get("price") and quote.get("shares_out"):
        net_cash = (quote.get("total_cash") or 0) - (quote.get("total_debt") or 0)
        rdcf = valuation.reverse_dcf(
            price=quote["price"], fcf_base=quote["fcf"], shares=quote["shares_out"],
            high_years=10, net_cash=net_cash,
        )

    thesis = narrative.build_thesis(quote, tr, scores, qf, rdcf)
    timings["scoring"] = time.time() - s
    timings["total"] = time.time() - t0

    # Auto-snapshot for forward-return tracking (silent, best-effort)
    try:
        from lib import db
        db.save_snapshot(sym, quote.get("price"), scores)
    except Exception:
        pass

    return {
        "symbol": sym,
        "quote": quote,
        "financials": fin,
        "trends": tr,
        "scores": scores,
        "quality_flags": qf,
        "rdcf": rdcf,
        "thesis": thesis,
        "insider_df": insider_df,
        "peers_data": peers_data,
        "peer_symbols": peer_syms,
        "price_history": price_history,
        "timings": timings,
        "error": None,
    }


def format_timings(timings: dict) -> str:
    """One-line summary like 'total 3.2s — quote 0.8 fin 1.2 insider 0.5 ...'."""
    total = timings.get("total", 0)
    parts = [f"{k} {v:.1f}" for k, v in timings.items() if k != "total"]
    return f"⚡ total {total:.1f}s · " + " · ".join(parts)
