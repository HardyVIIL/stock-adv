import pytest

from stock_eval.catchup import CatchUp, scenario_cdf


def test_required_return_math():
    cu = CatchUp(value=800, index_value=1000, index_return=0.09, years=5, bear=0.0, base=0.12, bull=0.25)
    req = cu.required_return
    assert 800 * (1 + req) ** 5 == pytest.approx(1000 * 1.09 ** 5)
    assert cu.behind and cu.gap == -200


def test_cdf_hits_scenario_percentiles_and_tails():
    assert scenario_cdf(0.0, 0.0, 0.1, 0.2) == pytest.approx(0.15)
    assert scenario_cdf(0.1, 0.0, 0.1, 0.2) == pytest.approx(0.50)
    assert scenario_cdf(0.2, 0.0, 0.1, 0.2) == pytest.approx(0.85)
    assert scenario_cdf(-1.0, 0.0, 0.1, 0.2) == pytest.approx(0.05)
    assert scenario_cdf(1.0, 0.0, 0.1, 0.2) == pytest.approx(0.95)
    assert scenario_cdf(0.05, 0.0, 0.1, 0.2) == pytest.approx(0.325)


def test_probability_and_verdicts():
    # vaja täpselt base -> 50%
    cu = CatchUp(1000, 1000, 0.10, 5, 0.0, 0.10, 0.20)
    assert cu.probability == pytest.approx(0.5)
    easy = CatchUp(950, 1000, 0.05, 5, 0.06, 0.12, 0.20)
    assert easy.probability > 0.6 and easy.verdict.startswith("🟢")
    hard = CatchUp(500, 1000, 0.10, 5, -0.05, 0.05, 0.12)
    assert hard.probability < 0.35 and "Ebatõenäoline" in hard.verdict
    assert CatchUp(500, 1000, 0.1, 5, None, None, None).probability is None


def test_years_to_catch_up_and_gap_after():
    cu = CatchUp(800, 1000, 0.08, 5, 0.0, 0.15, 0.25)
    n = cu.years_to_catch_up
    assert 800 * 1.15 ** n == pytest.approx(1000 * 1.08 ** n)
    assert cu.gap_after(0.08) == pytest.approx(-200 * 1.08 ** 5)
    assert CatchUp(800, 1000, 0.10, 5, 0, 0.05, 0.1).years_to_catch_up is None
