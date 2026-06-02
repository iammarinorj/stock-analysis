"""Paper trading business logic.

Wraps lib.db with valuation logic, performance metrics, and the analyst
book seeder ($100K recommendation auto-loaded on first run).

Live prices come from yfinance via lib.data.get_quote (cached 5min).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import streamlit as st
import yfinance as yf

from lib import db


# ---------------------------------------------------------------------------
# Quoting — single source for current price
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_current_price(symbol: str) -> float | None:
    """Pull live price for a single symbol. None on failure."""
    try:
        t = yf.Ticker(symbol)
        # fast_info is faster than full info
        fi = getattr(t, "fast_info", None)
        if fi:
            for key in ("last_price", "lastPrice", "regular_market_price"):
                v = getattr(fi, key, None)
                if v:
                    return float(v)
        info = t.info or {}
        if info.get("regularMarketPrice"):
            return float(info["regularMarketPrice"])
        h = t.history(period="1d", auto_adjust=False)
        if not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    return None


@st.cache_data(ttl=300, show_spinner=False)
def get_prices_batch(symbols: tuple) -> dict[str, float]:
    """Pull prices for many symbols. Returns {sym: price}."""
    if not symbols:
        return {}
    out = {}
    try:
        tickers = yf.Tickers(" ".join(symbols))
        for s in symbols:
            try:
                t = tickers.tickers.get(s.upper())
                if t is None:
                    continue
                fi = getattr(t, "fast_info", None)
                if fi:
                    for key in ("last_price", "lastPrice", "regular_market_price"):
                        v = getattr(fi, key, None)
                        if v:
                            out[s.upper()] = float(v)
                            break
                if s.upper() not in out:
                    p = get_current_price(s)
                    if p:
                        out[s.upper()] = p
            except Exception:
                continue
    except Exception:
        # Fallback: serial
        for s in symbols:
            p = get_current_price(s)
            if p:
                out[s.upper()] = p
    return out


# ---------------------------------------------------------------------------
# Position + Portfolio valuation
# ---------------------------------------------------------------------------

def position_pnl(pos: dict, current_price: float | None) -> dict:
    """Compute live P&L for an open or closed position."""
    qty = pos["qty"]
    entry = pos["entry_price"]
    cost_basis = qty * entry

    if pos["status"] == "closed":
        exit_p = pos["exit_price"] or 0
        proceeds = qty * exit_p
        pnl = proceeds - cost_basis
        ret = (exit_p / entry - 1) if entry else 0
        return {
            "current_price": exit_p,
            "market_value": proceeds,
            "cost_basis": cost_basis,
            "pnl_abs": pnl,
            "pnl_pct": ret,
            "is_realized": True,
        }

    if current_price is None:
        return {
            "current_price": None,
            "market_value": cost_basis,
            "cost_basis": cost_basis,
            "pnl_abs": 0,
            "pnl_pct": 0,
            "is_realized": False,
            "error": "no price",
        }

    market_value = qty * current_price
    pnl = market_value - cost_basis
    ret = (current_price / entry - 1) if entry else 0
    return {
        "current_price": current_price,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "pnl_abs": pnl,
        "pnl_pct": ret,
        "is_realized": False,
    }


def portfolio_summary(account_id: int) -> dict:
    """Aggregate open positions + cash + closed P&L."""
    acct = db.get_paper_account(account_id)
    if not acct:
        return {"error": "Account not found"}

    open_pos = db.get_paper_positions(account_id, status="open")
    closed_pos = db.get_paper_positions(account_id, status="closed")

    symbols = tuple({p["symbol"] for p in open_pos})
    prices = get_prices_batch(symbols) if symbols else {}

    open_book = []
    open_market_value = 0
    open_cost_basis = 0
    open_pnl = 0
    for p in open_pos:
        price = prices.get(p["symbol"].upper())
        pnl = position_pnl(p, price)
        row = {**p, **pnl}
        open_book.append(row)
        open_market_value += pnl["market_value"]
        open_cost_basis += pnl["cost_basis"]
        open_pnl += pnl["pnl_abs"]

    realized_pnl = 0
    for p in closed_pos:
        pnl = position_pnl(p, None)
        realized_pnl += pnl["pnl_abs"]

    # Options book
    options_book = get_options_book(account_id)
    options_market_value = sum(o["market_value"] for o in options_book)
    options_pnl = sum(o["pnl_abs"] for o in options_book)
    n_options = len(options_book)

    total_value = open_market_value + options_market_value + acct["current_cash"]
    total_pnl = total_value - acct["starting_cash"]
    total_return_pct = total_pnl / acct["starting_cash"] if acct["starting_cash"] else 0

    return {
        "account": acct,
        "open_book": open_book,
        "closed_positions": closed_pos,
        "open_market_value": open_market_value,
        "open_cost_basis": open_cost_basis,
        "open_pnl_abs": open_pnl,
        "open_pnl_pct": open_pnl / open_cost_basis if open_cost_basis else 0,
        "realized_pnl": realized_pnl,
        "cash": acct["current_cash"],
        "total_value": total_value,
        "total_pnl_abs": total_pnl,
        "total_return_pct": total_return_pct,
        "deployed_pct": (open_market_value / total_value) if total_value else 0,
        "n_open": len(open_pos),
        "n_closed": len(closed_pos),
        # Options
        "options_book": options_book,
        "options_market_value": options_market_value,
        "options_pnl": options_pnl,
        "n_options": n_options,
    }


# ---------------------------------------------------------------------------
# Options P&L
# ---------------------------------------------------------------------------

def option_position_pnl(pos: dict, current_premium: float | None) -> dict:
    """Compute P&L for a paper options position (open, closed, or expired).

    Each contract = 100 shares.
    LONG: cost = qty * 100 * entry_premium; market_value = qty * 100 * current_premium
    SHORT: received = qty * 100 * entry_premium; liability = qty * 100 * current_premium
    """
    qty = pos["qty"]
    entry = pos["entry_premium"]
    multiplier = qty * 100

    if pos["status"] == "expired":
        # Long loses all; short keeps all
        if pos["side"] == "long":
            return {
                "current_premium": 0.0,
                "market_value": 0.0,
                "cost_basis": multiplier * entry,
                "pnl_abs": -(multiplier * entry),
                "pnl_pct": -1.0,
                "is_realized": True,
            }
        else:  # short expired worthless — full profit
            return {
                "current_premium": 0.0,
                "market_value": 0.0,
                "cost_basis": multiplier * entry,
                "pnl_abs": multiplier * entry,
                "pnl_pct": 1.0,
                "is_realized": True,
            }

    if pos["status"] == "closed":
        exit_p = pos.get("exit_premium") or 0
        if pos["side"] == "long":
            cost = multiplier * entry
            proceeds = multiplier * exit_p
            pnl = proceeds - cost
            ret = (exit_p / entry - 1) if entry else 0
        else:  # short
            received = multiplier * entry
            buyback = multiplier * exit_p
            pnl = received - buyback
            ret = (1 - exit_p / entry) if entry else 0
        return {
            "current_premium": exit_p,
            "market_value": multiplier * exit_p,
            "cost_basis": multiplier * entry,
            "pnl_abs": pnl,
            "pnl_pct": ret,
            "is_realized": True,
        }

    # Open position
    if current_premium is None:
        return {
            "current_premium": None,
            "market_value": multiplier * entry,
            "cost_basis": multiplier * entry,
            "pnl_abs": 0,
            "pnl_pct": 0,
            "is_realized": False,
            "error": "no price",
        }

    market_value = multiplier * current_premium
    cost = multiplier * entry
    if pos["side"] == "long":
        pnl = market_value - cost
        ret = (current_premium / entry - 1) if entry else 0
    else:  # short
        pnl = cost - market_value  # received - liability
        ret = (1 - current_premium / entry) if entry else 0

    return {
        "current_premium": current_premium,
        "market_value": market_value,
        "cost_basis": cost,
        "pnl_abs": pnl,
        "pnl_pct": ret,
        "is_realized": False,
    }


def get_options_book(account_id: int) -> list[dict]:
    """Get open options with live P&L attached via options.get_contract_price."""
    from lib import options as opts_mod

    positions = db.get_paper_options(account_id, status="open")
    book = []
    for pos in positions:
        current_premium = None
        try:
            price_data = opts_mod.get_contract_price(
                pos["symbol"], pos["expiry"], pos["opt_type"], pos["strike"]
            )
            if price_data:
                current_premium = price_data.get("mid") or price_data.get("last") or 0
        except Exception:
            pass
        pnl = option_position_pnl(pos, current_premium)
        book.append({**pos, **pnl})
    return book


def benchmark_return_since(start_iso: str, benchmark: str = "SPY") -> float | None:
    """Return % return of benchmark since account opened. Used for alpha calc."""
    try:
        from datetime import datetime
        start = datetime.fromisoformat(start_iso.replace("Z", ""))
        t = yf.Ticker(benchmark)
        # Pull from start to today
        h = t.history(start=start.strftime("%Y-%m-%d"), auto_adjust=False)
        if h.empty or len(h) < 2:
            return None
        first = float(h["Close"].iloc[0])
        last = float(h["Close"].iloc[-1])
        return (last / first) - 1
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Seeder: the analyst's $100K book
# ---------------------------------------------------------------------------

# v2 book — after self-critique + Sivers ralph loop
# Removed: AAMI (no defensible thesis), DECK (3% too small to matter)
# Added: OLED, IDCC, IRWD — early-stage chokepoint plays with REAL pricing power,
# at multi-year value discounts (NOT extended like Sivers).
ANALYST_BOOK = [
    # (symbol, dollar_amount, target_price, stop_price, thesis)
    ("AVGO",  10000, 580, 355,  "Custom AI silicon chokepoint. Google TPU 78% of ASIC rev. $100B AI rev target by 2027."),
    ("META",   9000, 800, 520,  "Quality compounder at value. Q1 +33% rev, +61% NI. AI capex $145B fuels Reality Labs + Llama monetization."),
    ("VST",    8000, 230, 135,  "Cheapest power play (PEG 0.49). 2.1GW Meta nuclear PPA + 3,800MW AWS deal."),
    ("AU",     9000, 140,  80,  "Gold producer at AISC $1,405 selling at $4,915/oz. FwdPE 9. Real-assets hedge."),
    ("CRDO",   7000, 320, 175,  "AECs tripling revenue, 69% gross margin. Displacing optical modules at hyperscale."),
    ("ALAB",   6000, 440, 260,  "AI connectivity ICs. +93% rev, 76% gross margin. NVIDIA + AMD attach."),
    ("ANET",   7000, 200, 130,  "Datacenter networking chokepoint. 32% ROE, Meta+MSFT anchor."),
    ("HALO",   7000, 105,  58,  "ENHANZE royalty stream guiding $1.13-1.17B (+30%). FwdPE 6.9. Single best risk-reward."),
    ("CDNS",   5000, 480, 320,  "EDA duopoly with SNPS. Chokepoint for all chip design. 86% gross margin."),
    ("APP",    6000, 700, 430,  "Mobile ad-tech AI. AI Axon engine moat. 88% gross margin, 78% op margin."),
    ("NVDA",   5000, 290, 180,  "AI foundation. PEG 0.66, +85% rev growth. Smaller size lets core book lead."),
    ("AAOI",   4000, 260, 140,  "Photonics inflection. +51% rev, gross margin 15→30%, Microsoft anchor, $324M backlog."),
    ("CEG",    5000, 400, 255,  "Microsoft Three Mile Island restart. Nuclear renaissance pure-play."),
    # NEW — contrarian / under-the-radar chokepoint plays at value entries (not extended)
    ("OLED",   4000, 130,  75,  "Display IP chokepoint. GM 74%, OpM 30%, ROE 13%, FwdPE 19, PEG 1.00, Insider 8.2%. -22% vs 200DMA = contrarian entry. Royalty business OUT OF FAVOR."),
    ("IDCC",   3000, 380, 215,  "5G/6G/Wi-Fi IP licensing chokepoint. GM 85%, OpM 40%, ROE 36%, FwdPE 23. -21% vs 200DMA. Pristine balance sheet, NOT extended."),
    ("IRWD",   2000, 7.50, 2.80, "GI drug chokepoint (LINZESS + apraglutide launch). FwdPE 2.7 (!!), GM 75%, OpM 68%, rev +159%. Microcap so 2% size."),
]

ANALYST_BOOK_NAME = "Analyst Recommendation Book (May 2026)"


def preview_profile_portfolio(
    profile_id: str,
    n_positions: int = 15,
    total_capital: float = 100000.0,
    include_foreign: bool = False,
    min_mkt_cap: str = "+Small (over $300mln)",
    sizing: str = "equal",
    universe_limit: int = 1000,
    progress_cb=None,
) -> dict:
    """Build a PREVIEW of what auto-building from a profile would create.

    Doesn't write to db. Returns the proposed positions list with live prices,
    quantities, and fit scores so the user can review before locking in.

    universe_limit: how big a candidate pool to pull (default 1000). Big pool
    spans multiple sort orders to avoid alphabetical bias.

    progress_cb: optional callable(label, pct_complete 0-1) for UI feedback.

    sizing:
      'equal'       -> total / N per position
      'fit-weighted' -> higher fit score gets larger allocation
    """
    from lib import backtest, screener, profiles

    # 1. Pull large candidate universe (6 sort orders, union'd)
    if progress_cb: progress_cb("Pulling candidate universe…", 0.05)
    universe = backtest.get_auto_universe(
        profile_id=profile_id,
        include_foreign=include_foreign,
        min_mkt_cap=min_mkt_cap,
        limit=universe_limit,
        _progress_cb=(lambda lbl, pct: progress_cb(lbl, 0.05 + pct * 0.45)) if progress_cb else None,
    )
    if not universe:
        return {"error": f"No tickers passed the {profile_id} screen.", "positions": []}

    # 2. Pull the screener metric data with a LARGE limit so we score the full universe.
    style_for_profile = {
        "buffett": "quality_compounder",
        "graham": "deep_value",
        "lynch": "garp",
        "fisher": "quality_compounder",
        "inflection": "inflection",
        "canslim": "growth",
        "magic_formula": "deep_value",
        "dividend": "high_yield",
        "minervini": "momentum",
    }.get(profile_id, "quality_compounder")

    if progress_cb: progress_cb(f"Scoring {len(universe)} tickers…", 0.55)
    screen_df = None
    try:
        # Pull a large pool — enough to cover most of the universe set we found
        pool_size = max(800, len(universe))
        screen_df = screener.run_combined_screen(style_for_profile, limit=pool_size)
        if screen_df is not None and not screen_df.empty:
            screen_df = screener.add_fit_score(screen_df, style_for_profile)
            # Subset to tickers in our universe
            screen_df = screen_df[screen_df["Ticker"].isin(universe)]
            if progress_cb: progress_cb(f"Got metrics on {len(screen_df)} of {len(universe)}", 0.80)
    except Exception:
        screen_df = None

    # 3. Pull live prices for the universe + sector/company from screen df
    if progress_cb: progress_cb(f"Pulling live prices for {len(universe)} tickers…", 0.85)
    prices = get_prices_batch(tuple(universe))

    # 4. Build the proposed positions list
    candidates = []
    for sym in universe:
        price = prices.get(sym.upper())
        if not price:
            continue
        row = {
            "symbol": sym,
            "price": price,
            "company": "",
            "sector": "",
            "fit": 50,  # default
        }
        if screen_df is not None and not screen_df.empty:
            match = screen_df[screen_df["Ticker"] == sym]
            if not match.empty:
                row["company"] = str(match.iloc[0].get("Company") or "")[:35]
                row["sector"] = str(match.iloc[0].get("Sector") or "")
                row["fit"] = int(match.iloc[0].get("Fit") or 50)
        candidates.append(row)

    if not candidates:
        return {"error": "No live prices for screen results.", "positions": []}

    # 5. Sort by fit, take top N
    candidates.sort(key=lambda r: -r["fit"])
    selected = candidates[:n_positions]

    # 6. Compute sizing
    if sizing == "fit-weighted":
        total_fit = sum(c["fit"] for c in selected) or 1
        for c in selected:
            c["allocation"] = total_capital * (c["fit"] / total_fit)
    else:  # equal weight
        per_pos = total_capital / len(selected)
        for c in selected:
            c["allocation"] = per_pos

    for c in selected:
        c["qty"] = round(c["allocation"] / c["price"], 4)
        c["actual_cost"] = c["qty"] * c["price"]

    # 7. Build a default thesis line for each based on profile
    profile_name = profiles.PROFILES.get(profile_id, {}).get("name", profile_id)
    for c in selected:
        c["thesis"] = (
            f"Auto-selected by {profile_name} screen. "
            f"Fit score: {c['fit']}/100. "
            f"Sector: {c['sector'] or 'N/A'}."
        )

    total_allocated = sum(c["actual_cost"] for c in selected)
    cash_remaining = total_capital - total_allocated

    return {
        "profile_id": profile_id,
        "profile_name": profile_name,
        "n_positions": len(selected),
        "total_capital": total_capital,
        "total_allocated": total_allocated,
        "cash_remaining": cash_remaining,
        "sizing": sizing,
        "positions": selected,
        "error": None,
    }


def lock_in_profile_portfolio(preview: dict, account_name: str,
                              notes: str = "") -> int:
    """Take the preview dict and actually create the paper account + open all positions.

    Returns the new account_id.
    """
    if preview.get("error"):
        raise ValueError(preview["error"])
    if not preview.get("positions"):
        raise ValueError("No positions in preview.")

    # Create account
    account_id = db.create_paper_account(
        name=account_name,
        starting_cash=preview["total_capital"],
        notes=notes or f"Auto-built from {preview['profile_name']} profile.",
    )

    # Open each position at the price we previewed
    n_opened = 0
    for p in preview["positions"]:
        try:
            db.open_paper_position(
                account_id=account_id,
                symbol=p["symbol"],
                qty=p["qty"],
                entry_price=p["price"],
                target_price=p["price"] * 1.30,  # 30% upside target default
                stop_price=p["price"] * 0.80,    # 20% stop default
                thesis=p["thesis"],
            )
            n_opened += 1
        except Exception as e:
            pass  # cash might run out due to rounding; skip & continue

    return account_id


def seed_analyst_book(force: bool = False) -> int:
    """Create the analyst $100K book and fill it at current market prices.
    Returns the account_id. If already exists and not force, returns the existing id.
    """
    existing = db.paper_account_by_name(ANALYST_BOOK_NAME)
    if existing and not force:
        return existing["id"]
    if existing and force:
        db.delete_paper_account(existing["id"])

    account_id = db.create_paper_account(
        name=ANALYST_BOOK_NAME,
        starting_cash=100000.0,
        notes="Auto-seeded from the May 2026 $100K portfolio recommendation",
    )

    # Pull current prices for all symbols in one batch
    symbols = tuple(b[0] for b in ANALYST_BOOK)
    prices = get_prices_batch(symbols)

    n_filled = 0
    for symbol, dollars, target, stop, thesis in ANALYST_BOOK:
        price = prices.get(symbol.upper())
        if not price:
            price = get_current_price(symbol)
        if not price:
            continue
        qty = round(dollars / price, 4)
        try:
            db.open_paper_position(
                account_id=account_id,
                symbol=symbol,
                qty=qty,
                entry_price=price,
                target_price=target,
                stop_price=stop,
                thesis=thesis,
            )
            n_filled += 1
        except Exception as e:
            print(f"Skip {symbol}: {e}")

    return account_id
