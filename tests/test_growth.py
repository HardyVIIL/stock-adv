import pytest

from stock_eval.growth import (LONG_RUN_GROWTH, analyst_view, estimate_growth, evaluate_growth, exit_multiple,
                               growth_path, pe_path)


def test_analyst_view_upside_and_min_count():
    info = {"targetMeanPrice": 120, "targetLowPrice": 90, "targetHighPrice": 150, "numberOfAnalystOpinions": 10}
    a = analyst_view(info, 100)
    assert a.upside == pytest.approx(0.20) and a.score == pytest.approx(75)
    assert analyst_view({**info, "numberOfAnalystOpinions": 2}, 100) is None
    assert analyst_view(info, None) is None


def test_growth_path_fades_to_long_run():
    p = growth_path(0.26, 5)
    assert p[0] == pytest.approx(0.26) and p[-1] == pytest.approx(LONG_RUN_GROWTH)
    assert all(a > b for a, b in zip(p, p[1:]))


def test_estimate_growth_averages_and_clamps():
    g, src = estimate_growth({}, {"eps_growth_1y": 0.10, "rev_growth_1y": 0.20})
    assert g == pytest.approx(0.15) and len(src) == 2
    assert estimate_growth({}, {"eps_growth_1y": 0.9})[0] == 0.30
    assert estimate_growth({"revenueGrowth": 0.05}, {})[0] == pytest.approx(0.05)
    assert estimate_growth({}, {})[0] is None


def test_exit_multiple_reverts_halfway_to_sector():
    assert exit_multiple({"forwardPE": 64, "sector": "Technology"}) == pytest.approx((40 + 22) / 2)
    assert exit_multiple({"forwardPE": 7, "sector": "Financial Services"}) == pytest.approx(9)
    assert exit_multiple({}) == pytest.approx(17)


def test_pe_path_is_gradual():
    p = pe_path(60, 30, 5)
    assert p[0] == pytest.approx(54) and p[-1] == pytest.approx(30)


def test_projection_math_with_manual_inputs():
    info = {"forwardEps": 5.0, "dividendYield": 2.0}  # yfinance: protsentides
    r = evaluate_growth(info, {}, price=100.0, growth=0.06, exit_pe=20.0)  # P/E praegu 20 -> jääb 20
    p1 = r.projection(1)
    assert r.dividend_yield == pytest.approx(0.02) and r.pe_now == pytest.approx(20)
    assert p1.price == pytest.approx(5.0 * 1.06 * 20)
    assert p1.annual_return == pytest.approx(0.06 + 0.02)
    p5 = r.projection(5)
    assert p5.price == pytest.approx(5.0 * 1.06 ** 5 * 20)
    assert r.model_score(5) == pytest.approx((0.08 + 0.05) / 0.25 * 100)


def test_negative_eps_uses_analysts_only():
    info = {"trailingEps": -1, "targetMeanPrice": 130, "numberOfAnalystOpinions": 5}
    r = evaluate_growth(info, {"eps_growth_1y": 0.2}, price=100.0)
    assert not r.projections and "negatiivne" in r.model_reason
    assert r.score(3) == pytest.approx(100)
