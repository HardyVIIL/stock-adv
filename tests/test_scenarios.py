import pandas as pd
import pytest

from stock_eval.data import Snapshot
from stock_eval.growth import evaluate_growth
from stock_eval.scenarios import BullBear, Point, Scenario, analyze, scenarios
from stock_eval.scoring import evaluate


def _gr(pe_now=20.0, growth=0.10, exit_pe=20.0):
    return evaluate_growth({"forwardEps": 100.0 / pe_now}, {}, price=100.0, growth=growth, exit_pe=exit_pe)


def test_scenarios_ordered_and_bear_never_expands_pe():
    s = {x.name: x for x in scenarios(_gr(), 3)}
    assert s["Bear"].price < s["Base"].price < s["Bull"].price
    assert s["Base"].price == pytest.approx(_gr().projection(3).price)
    cheap = {x.name: x for x in scenarios(_gr(pe_now=5.0, exit_pe=8.0), 3)}
    assert cheap["Bear"].exit_pe <= 5.0 * 0.9 + 1e-9
    assert sum(x.probability for x in s.values()) == pytest.approx(1)


def test_balance_verdict_and_reward_risk():
    bb = BullBear(3, 100.0, [Scenario("Bear", 0, 0, 0.25, 80, -0.2, 0), Scenario("Base", 0, 0, 0.5, 110, 0.1, 0),
                             Scenario("Bull", 0, 0, 0.25, 150, 0.5, 0)],
                  [Point("bull", "Kasv", "x", 1.5), Point("bull", "Trend", "y", 0.5), Point("bear", "Hind", "z", 1.0)])
    assert bb.balance == pytest.approx(200 / 3)
    assert bb.verdict.endswith("bullish")
    assert bb.reward_risk == pytest.approx(2.5)
    assert bb.expected_price == pytest.approx(0.25 * 80 + 0.5 * 110 + 0.25 * 150)
    assert BullBear(3, 100.0).verdict == "—"


def test_points_from_evaluation():
    idx = pd.bdate_range("2024-01-01", periods=300)
    close = pd.Series([100 * 1.003 ** i for i in range(300)], index=idx)
    prices = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close})
    info = {"sector": "Technology", "industry": "Software - Application", "forwardEps": 1.0, "currentPrice": 240.0,
            "revenueGrowth": 0.30, "profitMargins": 0.02, "targetMeanPrice": 300, "numberOfAnalystOpinions": 10,
            "debtToEquity": 10}
    ev = evaluate(Snapshot("T", info, [], prices, {"eps_growth_1y": 0.2}), horizon=3)
    bb = ev.bullbear
    texts = " | ".join(p.text for p in bb.points)
    assert "Käive kasvab kiiresti" in texts and "Kallis: P/E" in texts and "Madal puhaskasumi" in texts
    assert "Tõusutrend" in texts
    assert bb.scenarios and ev.summary_row()["Vaade"] == bb.verdict
