"""Unit tests for pure computational functions in lib/scoring, lib/valuation, lib/quality_flags.

Uses synthetic data only -- no network calls, no yfinance, no streamlit runtime.
Run: python -m pytest tests/test_pure.py -v
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Stub out streamlit before importing any lib modules that use it at top level.
sys.modules.setdefault("streamlit", MagicMock())

import pandas as pd
import pytest

from lib.scoring import score, MAX_SCORE, SCORECARD_ITEMS, _diagnose
from lib.valuation import forward_dcf, reverse_dcf, projection_dcf, mos_bands
from lib.quality_flags import compute_piotroski, compute_altman_z, compute_beneish_m


# ===========================================================================
# Fixtures / helpers
# ===========================================================================

def _perfect_quote() -> dict:
    """A quote dict that should pass ALL 16 scoring criteria -> MAX_SCORE (21)."""
    return {
        # Valuation
        "fcf": 1_000_000_000,
        "market_cap": 10_000_000_000,       # FCF yield = 10% > 5%
        "pe_forward": 12.0,                  # < 20
        "pe_trailing": 14.0,
        "peg": 0.7,                          # < 1
        "ev_ebitda": 9.0,                    # < 15
        "pb": 2.5,                           # < 4
        "roe": 0.22,                         # > 15%
        # Quality
        "total_debt": 2_000_000_000,
        "total_cash": 1_500_000_000,
        "ebitda": 3_000_000_000,             # ND/EBITDA = (2B-1.5B)/3B = 0.17 < 2
        "ocf": 1_200_000_000,               # FCF/OCF = 1B/1.2B = 83% > 70%
        "operating_margin": 0.25,            # > 15%
        "gross_margin": 0.55,                # > 40%
        # Catalyst
        "held_insiders": 0.08,               # > 3%
        "rev_growth": 0.15,                  # > 10%
        "recommend": "buy",
        "n_analysts": 20,
        # Technical
        "price": 120.0,
        "dma_200": 100.0,                    # price > 200DMA
        "rsi_14": 55.0,                      # 30-70
        "short_float": 0.04,                 # < 10%
    }


def _terrible_quote() -> dict:
    """A quote that fails everything -> total 0."""
    return {
        "fcf": -500_000_000,                 # negative FCF -> fcf_yield fails
        "market_cap": 10_000_000_000,
        "pe_forward": 80.0,                  # very expensive
        "pe_trailing": 90.0,
        "peg": 3.5,                          # expensive
        "ev_ebitda": 40.0,                   # expensive
        "pb": 10.0,                          # expensive, and roe < 15% so no quality override
        "roe": 0.03,                         # weak
        "total_debt": 20_000_000_000,
        "total_cash": 500_000_000,
        "ebitda": 2_000_000_000,             # ND/EBITDA = 9.75 >> 2
        "ocf": 800_000_000,                 # positive OCF so fcf/ocf = -500/800 = negative -> fails > 70%
        "operating_margin": 0.03,            # < 15%
        "gross_margin": 0.20,                # < 40%
        "held_insiders": 0.005,              # < 3%
        "rev_growth": -0.05,                 # negative
        "recommend": "sell",
        "n_analysts": 10,
        "price": 50.0,
        "dma_200": 80.0,                     # below 200DMA
        "rsi_14": 20.0,                      # oversold < 30
        "short_float": 0.25,                 # > 10%
    }


def _mixed_quote() -> dict:
    """Passes valuation + quality mostly, fails catalyst + tech -> moderate."""
    return {
        "fcf": 800_000_000,
        "market_cap": 10_000_000_000,       # yield 8% pass
        "pe_forward": 15.0,                  # pass
        "peg": 0.9,                          # pass
        "ev_ebitda": 12.0,                   # pass
        "pb": 3.0,                           # pass
        "roe": 0.18,                         # pass
        "total_debt": 3_000_000_000,
        "total_cash": 2_000_000_000,
        "ebitda": 2_000_000_000,             # ND/EBITDA = 0.5 pass
        "ocf": 1_000_000_000,               # FCF/OCF = 80% pass
        "operating_margin": 0.20,            # pass
        "gross_margin": 0.45,                # pass
        # Catalyst: all fail
        "held_insiders": 0.01,
        "rev_growth": 0.02,
        "recommend": "hold",
        # Technical: all fail
        "price": 90.0,
        "dma_200": 100.0,
        "rsi_14": 75.0,                      # overbought
        "short_float": 0.15,                 # > 10%
    }


def _make_financials_piotroski(all_pass: bool = True) -> dict:
    """Build a 2-year financials dict for Piotroski.

    Columns are fiscal year-end timestamps (newest first, as yfinance provides).
    Rows are field names (index).
    """
    cur = pd.Timestamp("2024-06-30")
    prev = pd.Timestamp("2023-06-30")

    if all_pass:
        inc = pd.DataFrame({
            cur: [200, 600, 1000],
            prev: [150, 500, 900],
        }, index=["Net Income", "Gross Profit", "Total Revenue"])
        bal = pd.DataFrame({
            cur: [5000, 800, 2000, 900, 100],
            prev: [5000, 1000, 1800, 1000, 105],
        }, index=["Total Assets", "Long Term Debt", "Current Assets",
                  "Current Liabilities", "Ordinary Shares Number"])
        cf = pd.DataFrame({
            cur: [300],
            prev: [200],
        }, index=["Operating Cash Flow"])
    else:
        # All fail
        inc = pd.DataFrame({
            cur: [-50, 300, 800],
            prev: [100, 500, 1000],
        }, index=["Net Income", "Gross Profit", "Total Revenue"])
        bal = pd.DataFrame({
            cur: [5000, 1500, 1500, 1200, 120],
            prev: [4000, 1000, 2000, 1000, 100],
        }, index=["Total Assets", "Long Term Debt", "Current Assets",
                  "Current Liabilities", "Ordinary Shares Number"])
        cf = pd.DataFrame({
            cur: [-100],
            prev: [200],
        }, index=["Operating Cash Flow"])

    return {"income": inc, "balance": bal, "cashflow": cf}


def _make_financials_altman(zone: str = "safe") -> dict:
    """Build financials for Altman Z-score testing."""
    cur = pd.Timestamp("2024-06-30")

    if zone == "safe":
        # Z = 1.2*(3000/10000) + 1.4*(4000/10000) + 3.3*(2000/10000) + 0.6*(MVE/4000) + 1.0*(12000/10000)
        inc = pd.DataFrame({cur: [12000, 2000]}, index=["Total Revenue", "EBIT"])
        bal = pd.DataFrame({cur: [10000, 3000, 4000, 4000]},
                           index=["Total Assets", "Working Capital",
                                  "Retained Earnings",
                                  "Total Liabilities Net Minority Interest"])
    elif zone == "grey":
        inc = pd.DataFrame({cur: [8000, 1000]}, index=["Total Revenue", "EBIT"])
        bal = pd.DataFrame({cur: [10000, 1000, 2000, 6000]},
                           index=["Total Assets", "Working Capital",
                                  "Retained Earnings",
                                  "Total Liabilities Net Minority Interest"])
    else:  # distress
        inc = pd.DataFrame({cur: [5000, 200]}, index=["Total Revenue", "EBIT"])
        bal = pd.DataFrame({cur: [10000, -500, -1000, 9000]},
                           index=["Total Assets", "Working Capital",
                                  "Retained Earnings",
                                  "Total Liabilities Net Minority Interest"])

    return {"income": inc, "balance": bal, "info": {}}


def _make_financials_beneish(flagged: bool = False) -> dict:
    """Build 2-year financials for Beneish M-score testing."""
    cur = pd.Timestamp("2024-06-30")
    prev = pd.Timestamp("2023-06-30")

    if not flagged:
        # Clean company: stable ratios -> M << -1.78
        inc = pd.DataFrame({
            cur: [1000, 400, 100, 200],
            prev: [900, 360, 90, 180],
        }, index=["Total Revenue", "Cost Of Revenue",
                  "Selling General And Administration", "Net Income"])
        bal = pd.DataFrame({
            cur: [100, 5000, 2000, 1500, 500, 200, 800, 600],
            prev: [90, 4500, 1800, 1400, 450, 180, 750, 550],
        }, index=["Accounts Receivable", "Total Assets", "Current Assets",
                  "Net PPE", "Cash And Cash Equivalents",
                  "Other Short Term Investments", "Long Term Debt",
                  "Current Liabilities"])
        cf = pd.DataFrame({
            cur: [150, 250],
            prev: [140, 220],
        }, index=["Depreciation Amortization Depletion", "Operating Cash Flow"])
    else:
        # Manipulator signals: receivables ballooning, margins deteriorating,
        # accruals high (NI >> OCF), asset quality deteriorating
        inc = pd.DataFrame({
            cur: [1500, 900, 50, 300],
            prev: [1000, 500, 80, 200],
        }, index=["Total Revenue", "Cost Of Revenue",
                  "Selling General And Administration", "Net Income"])
        bal = pd.DataFrame({
            cur: [400, 8000, 2000, 1000, 200, 100, 3000, 1500],
            prev: [100, 5000, 2500, 1500, 500, 200, 1500, 800],
        }, index=["Accounts Receivable", "Total Assets", "Current Assets",
                  "Net PPE", "Cash And Cash Equivalents",
                  "Other Short Term Investments", "Long Term Debt",
                  "Current Liabilities"])
        cf = pd.DataFrame({
            cur: [50, 50],
            prev: [150, 200],
        }, index=["Depreciation Amortization Depletion", "Operating Cash Flow"])

    return {"income": inc, "balance": bal, "cashflow": cf}


# ===========================================================================
# TestScoring
# ===========================================================================

class TestScoring:
    """Tests for lib.scoring.score() and _diagnose()."""

    def test_max_score_constant(self):
        """MAX_SCORE should be 21 (sum of all weights)."""
        assert MAX_SCORE == 21

    def test_perfect_score(self):
        """A quote passing all criteria should get total == MAX_SCORE."""
        result = score(_perfect_quote())
        assert result["total"] == MAX_SCORE
        assert result["pct"] == pytest.approx(1.0)
        assert result["mode"] == "absolute"

    def test_terrible_score(self):
        """A quote failing everything should get total == 0."""
        result = score(_terrible_quote())
        assert result["total"] == 0
        assert result["pct"] == pytest.approx(0.0)

    def test_mixed_breakdown(self):
        """Mixed quote: val and qual should be strong, cat and tech weak."""
        result = score(_mixed_quote())
        by_cat = result["by_cat"]
        # Val: max 7, should pass most (FCF yield 2 + fwd_pe 2 + peg 1 + ev/ebitda 1 + pb 1 = 7)
        assert by_cat["val"]["s"] == 7
        assert by_cat["val"]["m"] == 7
        # Qual: max 7, should pass most (roic 2 + leverage 2 + fcf_conv 1 + op_margin 1 + gross 1 = 7)
        assert by_cat["qual"]["s"] == 7
        assert by_cat["qual"]["m"] == 7
        # Cat: max 4, should fail all (insider 0, rev 0, analyst 0)
        assert by_cat["cat"]["s"] == 0
        # Tech: max 3, should fail all
        assert by_cat["tech"]["s"] == 0

    def test_missing_fields_none(self):
        """Empty dict triggers the crash guard — returns early with zero score."""
        result = score({})
        assert result["total"] == 0
        assert result["pct"] == 0
        # Crash guard returns empty items for truly empty quote
        # Pass a quote with at least one field to test graceful degradation
        result2 = score({"price": 100})
        assert result2["total"] >= 0
        for item in SCORECARD_ITEMS:
            assert item["id"] in result2["items"]
            assert result2["items"][item["id"]]["pass"] is False

    def test_zero_values(self):
        """Zero values for market_cap, ebitda, etc. should not crash.

        Note: pb=0 passes in absolute mode (pb < 4 is True for 0) by design.
        We just ensure no exceptions are raised and total is very low.
        """
        q = {"fcf": 0, "market_cap": 0, "ebitda": 0, "ocf": 0,
             "pe_forward": 0, "pb": 0, "roe": 0}
        result = score(q)
        # pb=0 passes (< 4) in absolute mode; pe_forward=0 fails (requires 0 < pe)
        # This should not crash; total should be at most 1 (the pb item, weight=1)
        assert result["total"] <= 1

    def test_negative_fcf(self):
        """Negative FCF should fail fcf_yield and fcf_conv."""
        q = _perfect_quote()
        q["fcf"] = -100_000_000
        result = score(q)
        assert result["items"]["fcf_yield"]["pass"] is False
        assert result["items"]["fcf_conv"]["pass"] is False

    def test_verdict_strong_undervalued(self):
        """v>=0.6, q>=0.6, c>=0.6 -> 'Strong undervalued case'."""
        by_cat = {
            "val": {"s": 5, "m": 7, "pct": 5 / 7},
            "qual": {"s": 5, "m": 7, "pct": 5 / 7},
            "cat": {"s": 3, "m": 4, "pct": 3 / 4},
            "tech": {"s": 2, "m": 3, "pct": 2 / 3},
        }
        total = 15
        pct = total / MAX_SCORE
        v = _diagnose(by_cat, total, pct)
        assert v["head"] == "Strong undervalued case"
        assert v["color"] == "darkgreen"

    def test_verdict_value_trap(self):
        """v>=0.6, q<0.4 -> 'Value trap risk'."""
        by_cat = {
            "val": {"s": 5, "m": 7, "pct": 5 / 7},
            "qual": {"s": 2, "m": 7, "pct": 2 / 7},
            "cat": {"s": 1, "m": 4, "pct": 1 / 4},
            "tech": {"s": 1, "m": 3, "pct": 1 / 3},
        }
        total = 9
        pct = total / MAX_SCORE
        v = _diagnose(by_cat, total, pct)
        assert "Value trap" in v["head"]
        assert v["color"] == "red"

    def test_verdict_quality_full_price(self):
        """q>=0.6, v<0.4 -> 'Quality but full price'."""
        by_cat = {
            "val": {"s": 2, "m": 7, "pct": 2 / 7},
            "qual": {"s": 5, "m": 7, "pct": 5 / 7},
            "cat": {"s": 2, "m": 4, "pct": 2 / 4},
            "tech": {"s": 2, "m": 3, "pct": 2 / 3},
        }
        total = 11
        pct = total / MAX_SCORE
        v = _diagnose(by_cat, total, pct)
        assert "Quality but full price" in v["head"]
        assert v["color"] == "amber"

    def test_verdict_no_data(self):
        """total==0 -> 'No data'."""
        by_cat = {
            "val": {"s": 0, "m": 7, "pct": 0},
            "qual": {"s": 0, "m": 7, "pct": 0},
            "cat": {"s": 0, "m": 4, "pct": 0},
            "tech": {"s": 0, "m": 3, "pct": 0},
        }
        v = _diagnose(by_cat, 0, 0)
        assert v["head"] == "No data"

    def test_verdict_quality_compounder(self):
        """v>=0.8, q>=0.8 (but not all cat>=0.6) -> 'Quality compounder on sale'."""
        by_cat = {
            "val": {"s": 6, "m": 7, "pct": 6 / 7},
            "qual": {"s": 6, "m": 7, "pct": 6 / 7},
            "cat": {"s": 1, "m": 4, "pct": 1 / 4},
            "tech": {"s": 2, "m": 3, "pct": 2 / 3},
        }
        total = 15
        pct = total / MAX_SCORE
        v = _diagnose(by_cat, total, pct)
        assert "Quality compounder" in v["head"]
        assert v["color"] == "green"

    def test_sector_relative_mode(self):
        """When sector_medians is provided, mode should be 'sector'."""
        q = _perfect_quote()
        sm = {
            "sector": "Technology",
            "n": 25,
            "peers_used": ["AAPL", "MSFT"],
            "medians": {
                "fcf_yield": 0.04,
                "pe_forward": 25.0,
                "ev_ebitda": 18.0,
            },
        }
        result = score(q, sector_medians=sm)
        assert result["mode"] == "sector"
        assert result["sector"] == "Technology"
        # FCF yield 10% > sector median 4% -> still passes
        assert result["items"]["fcf_yield"]["pass"] is True
        # PE 12 < sector median 25 -> still passes
        assert result["items"]["fwd_pe"]["pass"] is True

    def test_sector_medians_tighter_threshold(self):
        """Sector median can make a criterion fail that passes absolutely."""
        q = _perfect_quote()
        q["pe_forward"] = 18.0  # passes absolute (<20) but fails if sector median is 15
        sm = {
            "sector": "Industrials",
            "medians": {"pe_forward": 15.0},
        }
        result = score(q, sector_medians=sm)
        assert result["items"]["fwd_pe"]["pass"] is False

    def test_insider_cluster_buy_signal(self):
        """When cluster buy data is present, it overrides ownership % logic."""
        q = _perfect_quote()
        q["insider_cluster_buy"] = True
        q["insider_buys_6mo"] = 5
        q["insider_sells_6mo"] = 1
        q["held_insiders"] = 0.01  # would fail the % check
        result = score(q)
        assert result["items"]["insider_own"]["pass"] is True

    def test_rsi_boundaries(self):
        """RSI exactly 30 and 70 should pass (in range [30, 70])."""
        q = _perfect_quote()
        q["rsi_14"] = 30.0
        r1 = score(q)
        assert r1["items"]["rsi_ok"]["pass"] is True

        q["rsi_14"] = 70.0
        r2 = score(q)
        assert r2["items"]["rsi_ok"]["pass"] is True

        q["rsi_14"] = 29.9
        r3 = score(q)
        assert r3["items"]["rsi_ok"]["pass"] is False

    def test_pb_quality_override(self):
        """P/B > 4 should still pass if ROE > 15% (quality premium) in absolute mode."""
        q = _perfect_quote()
        q["pb"] = 6.0  # > 4
        q["roe"] = 0.25  # > 15%
        result = score(q)
        assert result["items"]["pb"]["pass"] is True

    def test_pb_fails_expensive_no_quality(self):
        """P/B > 4 with ROE < 15% should fail in absolute mode."""
        q = _perfect_quote()
        q["pb"] = 6.0
        q["roe"] = 0.10
        result = score(q)
        assert result["items"]["pb"]["pass"] is False


# ===========================================================================
# TestValuation
# ===========================================================================

class TestValuation:
    """Tests for lib.valuation forward_dcf, reverse_dcf, projection_dcf, mos_bands."""

    def test_forward_dcf_basic(self):
        """Forward DCF with known inputs should produce correct fair value."""
        result = forward_dcf(
            fcf_base=100,
            growth_high=0.15,
            high_years=10,
            growth_terminal=0.03,
            discount=0.10,
            shares=10,
            net_cash=50,
        )
        assert "error" not in result
        assert result["fair_value_per_share"] > 0
        assert result["equity_value"] > 0
        assert result["pv_high_stage"] > 0
        assert result["pv_terminal"] > 0
        assert 0 < result["terminal_pct_of_value"] < 1

    def test_forward_dcf_manual_verification(self):
        """Verify the DCF math by hand for a simple case."""
        # 0% growth, 10% discount, 5 years, 3% terminal, FCF=100, shares=1, no cash
        result = forward_dcf(
            fcf_base=100,
            growth_high=0.0,
            high_years=5,
            growth_terminal=0.03,
            discount=0.10,
            shares=1,
            net_cash=0,
        )
        # With 0% growth, each year FCF = 100
        # PV high stage = 100/(1.1) + 100/(1.1^2) + ... + 100/(1.1^5)
        expected_pv_high = sum(100 / (1.10 ** y) for y in range(1, 6))
        # Terminal: fcf_terminal = 100 * 1.03 = 103; TV = 103/(0.10-0.03) = 1471.43
        # PV terminal = 1471.43 / (1.10^5)
        terminal_fcf = 100 * 1.03
        tv = terminal_fcf / (0.10 - 0.03)
        expected_pv_terminal = tv / (1.10 ** 5)
        expected_fv = expected_pv_high + expected_pv_terminal

        assert result["pv_high_stage"] == pytest.approx(expected_pv_high, rel=1e-6)
        assert result["pv_terminal"] == pytest.approx(expected_pv_terminal, rel=1e-6)
        assert result["fair_value_per_share"] == pytest.approx(expected_fv, rel=1e-6)

    def test_forward_dcf_net_cash_impact(self):
        """Net cash should increase fair value per share."""
        base_args = dict(
            fcf_base=100, growth_high=0.10, high_years=10,
            growth_terminal=0.03, discount=0.10, shares=10,
        )
        r_no_cash = forward_dcf(**base_args, net_cash=0)
        r_with_cash = forward_dcf(**base_args, net_cash=500)
        assert r_with_cash["fair_value_per_share"] > r_no_cash["fair_value_per_share"]
        diff = r_with_cash["fair_value_per_share"] - r_no_cash["fair_value_per_share"]
        assert diff == pytest.approx(500 / 10, rel=1e-6)

    def test_forward_dcf_error_negative_fcf(self):
        """Negative FCF should return error dict."""
        result = forward_dcf(
            fcf_base=-100, growth_high=0.10, high_years=10,
            growth_terminal=0.03, discount=0.10, shares=10,
        )
        assert "error" in result

    def test_forward_dcf_error_zero_shares(self):
        """Zero shares should return error dict."""
        result = forward_dcf(
            fcf_base=100, growth_high=0.10, high_years=10,
            growth_terminal=0.03, discount=0.10, shares=0,
        )
        assert "error" in result

    def test_forward_dcf_error_discount_lte_terminal(self):
        """Discount <= terminal growth should return error (Gordon formula invalid)."""
        result = forward_dcf(
            fcf_base=100, growth_high=0.10, high_years=10,
            growth_terminal=0.10, discount=0.10, shares=10,
        )
        assert "error" in result

    def test_reverse_dcf_roundtrip(self):
        """If forward DCF at 15% growth gives fair value X, reverse DCF at price X
        should recover ~15% implied growth."""
        fwd = forward_dcf(
            fcf_base=100, growth_high=0.15, high_years=10,
            growth_terminal=0.025, discount=0.09, shares=10, net_cash=0,
        )
        fair_price = fwd["fair_value_per_share"]

        rev = reverse_dcf(
            price=fair_price, fcf_base=100, shares=10,
            high_years=10, growth_terminal=0.025, discount=0.09, net_cash=0,
        )
        assert "error" not in rev
        assert rev["implied_growth"] == pytest.approx(0.15, abs=1e-4)

    def test_reverse_dcf_low_price_low_growth(self):
        """A low price relative to FCF should imply low/negative growth."""
        rev = reverse_dcf(
            price=15, fcf_base=100, shares=10,
            high_years=10, growth_terminal=0.025, discount=0.09, net_cash=0,
        )
        assert "error" not in rev
        # Price = 15 per share, total = 150, but FCF = 100 already.
        # This implies near-zero or negative growth.
        assert rev["implied_growth"] < 0.05

    def test_reverse_dcf_high_price_high_growth(self):
        """A high price relative to FCF should imply high growth."""
        # Use a price that implies ~25% growth but stays within bisection range [-10%, 50%]
        # Forward DCF at 25% growth:
        fwd = forward_dcf(100, 0.25, 10, 0.025, 0.09, 10, 0)
        price = fwd["fair_value_per_share"]
        rev = reverse_dcf(
            price=price, fcf_base=100, shares=10,
            high_years=10, growth_terminal=0.025, discount=0.09, net_cash=0,
        )
        assert "error" not in rev
        assert rev["implied_growth"] > 0.20

    def test_reverse_dcf_error_invalid_inputs(self):
        """Zero or negative inputs should return error."""
        assert "error" in reverse_dcf(price=0, fcf_base=100, shares=10)
        assert "error" in reverse_dcf(price=100, fcf_base=0, shares=10)
        assert "error" in reverse_dcf(price=100, fcf_base=100, shares=0)

    def test_reverse_dcf_verdict_colors(self):
        """Verify verdict color logic based on implied growth ranges."""
        # Low growth -> green
        fwd_low = forward_dcf(100, 0.03, 10, 0.025, 0.09, 10, 0)
        rev_low = reverse_dcf(fwd_low["fair_value_per_share"], 100, 10,
                              10, 0.025, 0.09, 0)
        assert rev_low["color"] == "green"

        # High growth -> amber or red
        fwd_high = forward_dcf(100, 0.20, 10, 0.025, 0.09, 10, 0)
        rev_high = reverse_dcf(fwd_high["fair_value_per_share"], 100, 10,
                               10, 0.025, 0.09, 0)
        assert rev_high["color"] in ("amber", "red")

    def test_projection_dcf_basic(self):
        """Projection DCF for a pre-profit company should produce fair value."""
        result = projection_dcf(
            price=50.0,
            revenue_today=500,
            rev_growth_high=0.30,
            high_years=10,
            target_fcf_margin=0.20,
            margin_ramp_years=5,
            discount=0.12,
            growth_terminal=0.03,
            shares=100,
            net_cash=200,
        )
        assert "error" not in result
        assert result["fair_value_per_share"] > 0
        assert result["last_year_revenue"] > 500
        assert result["last_year_fcf"] > 0
        # Margin ramp: by year 5, margin = target; after that stays at target
        assert result["last_year_fcf"] == pytest.approx(
            result["last_year_revenue"] * 0.20, rel=1e-6
        )

    def test_projection_dcf_margin_ramp(self):
        """Verify margin ramps linearly from 0 to target over margin_ramp_years."""
        result = projection_dcf(
            price=10, revenue_today=100, rev_growth_high=0.0,
            high_years=5, target_fcf_margin=0.20, margin_ramp_years=5,
            discount=0.10, growth_terminal=0.03, shares=1, net_cash=0,
        )
        # With 0% growth, revenue stays at 100 each year.
        # Year 1: margin = 0.20 * (1/5) = 0.04, FCF = 4
        # Year 2: margin = 0.20 * (2/5) = 0.08, FCF = 8
        # ...
        # Year 5: margin = 0.20 * (5/5) = 0.20, FCF = 20
        # PV high = 4/1.1 + 8/1.1^2 + 12/1.1^3 + 16/1.1^4 + 20/1.1^5
        expected_pv = sum(
            (100 * 0.20 * (y / 5)) / (1.10 ** y) for y in range(1, 6)
        )
        assert result["pv_high_stage"] == pytest.approx(expected_pv, rel=1e-6)

    def test_projection_dcf_margin_of_safety(self):
        """MoS should be positive when fair > price, negative when fair < price."""
        r1 = projection_dcf(
            price=10, revenue_today=1000, rev_growth_high=0.20,
            high_years=10, target_fcf_margin=0.25, margin_ramp_years=3,
            discount=0.10, growth_terminal=0.03, shares=1, net_cash=0,
        )
        # Fair value should be >> 10 given huge revenue base
        assert r1["margin_of_safety"] > 0

    def test_projection_dcf_error_invalid(self):
        """Invalid inputs should return error."""
        result = projection_dcf(
            price=0, revenue_today=100, rev_growth_high=0.10,
            high_years=10, target_fcf_margin=0.20, margin_ramp_years=5,
            discount=0.10, growth_terminal=0.03, shares=1, net_cash=0,
        )
        assert "error" in result

    def test_mos_bands(self):
        """mos_bands should return 75%, 67%, 50% of fair value."""
        bands = mos_bands(100.0)
        assert bands["fair_value"] == 100.0
        assert bands["25_pct_mos"] == pytest.approx(75.0)
        assert bands["33_pct_mos"] == pytest.approx(67.0)
        assert bands["50_pct_mos"] == pytest.approx(50.0)

    def test_mos_bands_zero(self):
        """mos_bands with zero fair value should return zeros."""
        bands = mos_bands(0.0)
        assert bands["fair_value"] == 0.0
        assert bands["25_pct_mos"] == 0.0


# ===========================================================================
# TestQualityFlags
# ===========================================================================

class TestQualityFlags:
    """Tests for lib.quality_flags Piotroski, Altman, Beneish."""

    # --- Piotroski ---

    def test_piotroski_all_pass(self):
        """All 9 checks passing should give score 9."""
        fin = _make_financials_piotroski(all_pass=True)
        result = compute_piotroski("TEST", _financials=fin)
        assert result["score"] == 9
        assert result["grade"] == "Strong"
        assert result["color"] == "green"
        # Verify all checks are True
        for key, val in result["checks"].items():
            assert val is True, f"Check {key} should pass"

    def test_piotroski_all_fail(self):
        """All checks failing should give score 0."""
        fin = _make_financials_piotroski(all_pass=False)
        result = compute_piotroski("TEST", _financials=fin)
        assert result["score"] == 0
        assert result["grade"] == "Weak"
        assert result["color"] == "red"
        for key, val in result["checks"].items():
            assert val is False, f"Check {key} should fail"

    def test_piotroski_mixed(self):
        """Modify the all-pass fixture to fail specific checks."""
        fin = _make_financials_piotroski(all_pass=True)
        cur = fin["income"].columns[0]
        prev = fin["income"].columns[1]

        # Fail: NI negative (also breaks roa_up and ocf_gt_ni since ocf > ni checks)
        fin["income"].loc["Net Income", cur] = -10
        # Fail: OCF negative
        fin["cashflow"].loc["Operating Cash Flow", cur] = -50
        # Fail: LTD increasing
        fin["balance"].loc["Long Term Debt", cur] = 2000
        fin["balance"].loc["Long Term Debt", prev] = 500

        result = compute_piotroski("TEST", _financials=fin)
        assert result["checks"]["ni_positive"] is False
        assert result["checks"]["ocf_positive"] is False
        assert result["checks"]["ltd_down"] is False
        # Score should be between 1 and 8 (several checks fail due to cascading effects)
        assert 0 < result["score"] < 9

    def test_piotroski_missing_data(self):
        """Empty DataFrames should return an error, not crash."""
        fin = {"income": pd.DataFrame(), "balance": pd.DataFrame(), "cashflow": pd.DataFrame()}
        result = compute_piotroski("TEST", _financials=fin)
        assert result["score"] is None
        assert "error" in result

    def test_piotroski_single_year(self):
        """Only 1 year of data -> error (needs 2 for YoY)."""
        cur = pd.Timestamp("2024-06-30")
        inc = pd.DataFrame({"Net Income": [100]}, index=[cur]).T
        bal = pd.DataFrame({"Total Assets": [1000]}, index=[cur]).T
        cf = pd.DataFrame({"Operating Cash Flow": [150]}, index=[cur]).T
        fin = {"income": inc, "balance": bal, "cashflow": cf}
        result = compute_piotroski("TEST", _financials=fin)
        assert result["score"] is None
        assert "error" in result

    # --- Altman Z ---

    def test_altman_safe_zone(self):
        """Z > 2.99 -> Safe."""
        fin = _make_financials_altman("safe")
        # Market cap for D component: MVE / Liabilities = D
        # Need large market cap: D = MVE / 4000; want D ~ 3.0, so MVE ~ 12000
        quote = {"market_cap": 12000}
        result = compute_altman_z("TEST", _financials=fin, _quote=quote)
        assert result["score"] is not None
        assert result["score"] > 2.99
        assert result["grade"] == "Safe"
        assert result["color"] == "green"

    def test_altman_grey_zone(self):
        """Z between 1.81 and 2.99 -> Grey."""
        fin = _make_financials_altman("grey")
        # A = WC/A = 1000/10000 = 0.1
        # B = RE/A = 2000/10000 = 0.2
        # C = EBIT/A = 1000/10000 = 0.1
        # E = Rev/A = 8000/10000 = 0.8
        # Need 1.2*0.1 + 1.4*0.2 + 3.3*0.1 + 0.6*D + 1.0*0.8
        # = 0.12 + 0.28 + 0.33 + 0.6D + 0.8 = 1.53 + 0.6D
        # For Z ~ 2.5: 0.6D = 0.97, D = 1.62, MVE = 1.62 * 6000 = 9720
        quote = {"market_cap": 9720}
        result = compute_altman_z("TEST", _financials=fin, _quote=quote)
        assert result["score"] is not None
        assert 1.81 < result["score"] < 2.99
        assert result["grade"] == "Grey zone"
        assert result["color"] == "amber"

    def test_altman_distress_zone(self):
        """Z < 1.81 -> Distress."""
        fin = _make_financials_altman("distress")
        # A = -500/10000 = -0.05
        # B = -1000/10000 = -0.1
        # C = 200/10000 = 0.02
        # E = 5000/10000 = 0.5
        # 1.2*(-0.05) + 1.4*(-0.1) + 3.3*0.02 + 0.6D + 1.0*0.5
        # = -0.06 + (-0.14) + 0.066 + 0.6D + 0.5 = 0.366 + 0.6D
        # For Z < 1.81: 0.6D < 1.444, D < 2.41, MVE < 2.41 * 9000 = 21690
        # Use small MVE to make Z clearly in distress: MVE=2000, D = 2000/9000 = 0.222
        # Z = 0.366 + 0.6*0.222 = 0.366 + 0.133 = 0.499
        quote = {"market_cap": 2000}
        result = compute_altman_z("TEST", _financials=fin, _quote=quote)
        assert result["score"] is not None
        assert result["score"] < 1.81
        assert result["grade"] == "Distress risk"
        assert result["color"] == "red"

    def test_altman_formula_verification(self):
        """Verify Z = 1.2A + 1.4B + 3.3C + 0.6D + 1.0E with known components."""
        fin = _make_financials_altman("safe")
        quote = {"market_cap": 12000}
        result = compute_altman_z("TEST", _financials=fin, _quote=quote)

        comps = result["components"]
        expected_z = (1.2 * comps["WC/Assets"] + 1.4 * comps["RE/Assets"]
                      + 3.3 * comps["EBIT/Assets"] + 0.6 * comps["MVE/Liab"]
                      + 1.0 * comps["Sales/Assets"])
        assert result["score"] == pytest.approx(expected_z, rel=1e-3)

    def test_altman_missing_data(self):
        """Missing statements should return error."""
        fin = {"income": pd.DataFrame(), "balance": pd.DataFrame(), "info": {}}
        result = compute_altman_z("TEST", _financials=fin)
        assert result["score"] is None
        assert "error" in result

    # --- Beneish M ---

    def test_beneish_clean(self):
        """Clean company: M < -1.78."""
        fin = _make_financials_beneish(flagged=False)
        result = compute_beneish_m("TEST", _financials=fin)
        assert result["score"] is not None
        assert result["score"] < -1.78
        assert result["flagged"] is False
        assert result["grade"] == "Clean"
        assert result["color"] == "green"

    def test_beneish_flagged(self):
        """Manipulator signals: M > -1.78."""
        fin = _make_financials_beneish(flagged=True)
        result = compute_beneish_m("TEST", _financials=fin)
        assert result["score"] is not None
        assert result["score"] > -1.78
        assert result["flagged"] is True
        assert result["grade"] == "FLAGGED — possible manipulator"
        assert result["color"] == "red"

    def test_beneish_missing_data(self):
        """Missing or empty financials -> error."""
        fin = {"income": pd.DataFrame(), "balance": pd.DataFrame(), "cashflow": pd.DataFrame()}
        result = compute_beneish_m("TEST", _financials=fin)
        assert result["score"] is None
        assert "error" in result

    def test_beneish_single_year(self):
        """Only 1 year -> error (needs 2 for YoY ratios)."""
        cur = pd.Timestamp("2024-06-30")
        inc = pd.DataFrame({"Total Revenue": [1000]}, index=[cur]).T
        bal = pd.DataFrame({"Total Assets": [5000]}, index=[cur]).T
        cf = pd.DataFrame({"Operating Cash Flow": [200]}, index=[cur]).T
        fin = {"income": inc, "balance": bal, "cashflow": cf}
        result = compute_beneish_m("TEST", _financials=fin)
        assert result["score"] is None
        assert "error" in result
