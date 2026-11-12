"""Engine tests: textbook prices and Greeks, bump-and-reprice, hand-worked VaR and ES, Euler allocation."""

import numpy as np
import pytest
from scipy.stats import norm

from riskdesk.engine.backtest import kupiec_pof, traffic_light
from riskdesk.engine.book import build_book
from riskdesk.engine.instruments import Position, bs_greeks, bs_price, sensitivities, value
from riskdesk.engine.market import generate_history, _snapshot
from riskdesk.engine import risk
from riskdesk.engine.stress import historical_windows, stress_positions


@pytest.fixture(scope="module")
def market():
    names, vols, rets, dvol = generate_history(n_days=750, seed=42)
    return _snapshot(names, vols, rets, dvol)


# --- pricing against textbook values (S=100, K=100, T=1, r=5%, sigma=20%) ---

def test_call_price_matches_textbook():
    assert bs_price(100, 100, 1.0, 0.05, 0.0, 0.2, True) == pytest.approx(10.4506, abs=1e-4)


def test_put_price_matches_textbook():
    assert bs_price(100, 100, 1.0, 0.05, 0.0, 0.2, False) == pytest.approx(5.5735, abs=1e-4)


def test_put_call_parity():
    c = bs_price(100, 105, 0.5, 0.03, 0.01, 0.25, True)
    p = bs_price(100, 105, 0.5, 0.03, 0.01, 0.25, False)
    lhs = c - p
    rhs = 100 * np.exp(-0.01 * 0.5) - 105 * np.exp(-0.03 * 0.5)
    assert lhs == pytest.approx(rhs, abs=1e-9)


def test_call_greeks_match_textbook():
    g = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.0, 0.2, True)
    assert g["delta"] == pytest.approx(0.6368, abs=1e-4)
    assert g["gamma"] == pytest.approx(0.018762, abs=1e-6)
    assert g["vega"] == pytest.approx(37.524, abs=1e-3)
    assert g["theta"] == pytest.approx(-6.414, abs=1e-3)
    assert g["rho"] == pytest.approx(53.2325, abs=1e-3)


@pytest.mark.parametrize("is_call", [True, False])
def test_greeks_match_bump_and_reprice(is_call):
    S, K, T, r, q, sig = 100.0, 95.0, 0.75, 0.04, 0.0, 0.25
    h, hv = 1e-3, 1e-4
    g = bs_greeks(S, K, T, r, q, sig, is_call)
    p = lambda s, v: float(bs_price(s, K, T, r, q, v, is_call))
    delta_bump = (p(S + h, sig) - p(S - h, sig)) / (2 * h)
    gamma_bump = (p(S + h, sig) - 2 * p(S, sig) + p(S - h, sig)) / h**2
    vega_bump = (p(S, sig + hv) - p(S, sig - hv)) / (2 * hv)
    assert g["delta"] == pytest.approx(delta_bump, abs=1e-5)
    assert g["gamma"] == pytest.approx(gamma_bump, abs=1e-4)
    assert g["vega"] == pytest.approx(vega_bump, abs=1e-3)


def test_option_at_expiry_is_intrinsic():
    assert bs_price(110.0, 100.0, 0.0, 0.04, 0.0, 0.2, True) == pytest.approx(10.0)
    assert bs_price(90.0, 100.0, 0.0, 0.04, 0.0, 0.2, False) == pytest.approx(10.0)


def test_position_delta_cash_for_cash_equity():
    p = Position("c", "D", "cash", "EQ_ALPHA", qty=1000)
    assert sensitivities(p, 120.0)["delta_cash"] == pytest.approx(120_000.0)


def test_fx_forward_value_zero_at_fair_forward(market):
    # A forward struck at the fair forward is worth ~0 at inception-like inputs
    from riskdesk.engine.instruments import RATE_DOMESTIC
    S, rf, T = 1.10, 0.02, 1.0
    K = S * np.exp((RATE_DOMESTIC - rf) * T)
    p = Position("f", "FX", "fx_fwd", "FX_EURUSD", qty=1_000_000, strike=K, expiry=T, rf=rf)
    assert float(value(p, S)) == pytest.approx(0.0, abs=1e-6)


# --- VaR, ES, Euler allocation ---

def test_parametric_var_matches_hand_calculation(market):
    p = Position("x", "D", "cash", "EQ_ALPHA", qty=1000)
    idx = market.spot_index("EQ_ALPHA")
    sigma = np.std(market.rets[-250:, idx], ddof=1)
    expected = norm.ppf(0.99) * sigma * 1000 * market.spots["EQ_ALPHA"]
    assert risk.parametric_var([p], market) == pytest.approx(expected, rel=1e-6)


def test_parametric_es_matches_normal_formula(market):
    p = Position("x", "D", "cash", "EQ_ALPHA", qty=1000)
    idx = market.spot_index("EQ_ALPHA")
    sigma = np.std(market.rets[-250:, idx], ddof=1) * 1000 * market.spots["EQ_ALPHA"]
    expected = sigma * norm.pdf(norm.ppf(0.975)) / 0.025
    assert risk.parametric_es([p], market) == pytest.approx(expected, rel=1e-6)


def test_component_var_sums_to_parametric_var(market):
    book = build_book(market)
    comp = risk.component_var(book, market)
    assert sum(comp.values()) == pytest.approx(risk.parametric_var(book, market), rel=1e-9)


def test_monte_carlo_agrees_with_parametric_for_linear_book(market):
    cash = [p for p in build_book(market) if p.kind == "cash"]
    mc, _ = risk.monte_carlo_var(cash, market, paths=50_000)
    assert mc == pytest.approx(risk.parametric_var(cash, market), rel=0.03)


def test_es_is_at_least_var(market):
    book = build_book(market)
    assert risk.historical_es(book, market) >= risk.historical_var(book, market)


def test_stress_includes_both_directions(market):
    book = build_book(market)
    rows = stress_positions(book, market)
    names = [r["name"] for r in rows]
    assert any(n.endswith("[reversed]") for n in names)
    assert len(historical_windows(market)) == 3


# --- backtesting ---

def test_kupiec_accepts_expected_exception_count():
    assert kupiec_pof(250, 2)["reject_model_at_5pct"] is False


def test_kupiec_rejects_too_many_exceptions():
    assert kupiec_pof(250, 20)["reject_model_at_5pct"] is True


@pytest.mark.parametrize("x, zone", [(0, "green"), (4, "green"), (5, "amber"), (9, "amber"), (10, "red")])
def test_basel_traffic_light_zones(x, zone):
    assert traffic_light(x, 250) == zone
