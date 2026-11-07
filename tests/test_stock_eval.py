import numpy as np
import pandas as pd
import pytest

from stock_eval.data import Snapshot
from stock_eval.dcf import DCFAssumptions, estimate_discount_rate, estimate_growth, evaluate_dcf, run_dcf
from stock_eval.fundamentals import evaluate_fundamentals, linear_score
from stock_eval.scoring import combine, evaluate, rating
from stock_eval.technical import evaluate_technical, rsi


def test_linear_score_both_directions():
    assert linear_score(25, 0, 25) == 100
    assert linear_score(12.5, 0, 25) == 50
    assert linear_score(-5, 0, 25) == 0
    # madalam parem
    assert linear_score(10, 40, 10) == 100
    assert linear_score(25, 40, 10) == 50
    assert linear_score(None, 0, 1) is None
    assert linear_score(float("nan"), 0, 1) is None


def test_fundamentals_negative_pe_is_zero_and_de_scaled():
    res = evaluate_fundamentals({"trailingPE": -5, "debtToEquity": 30})  # D/E 30% = 0.3 -> parim
    m = {x["Näitaja"]: x for x in res["metrics"]}
    assert m["P/E (TTM)"]["Skoor"] == 0
    assert m["Võlg/omakapital"]["Skoor"] == 100
    assert res["categories"]["Kasv"] is None
    assert res["score"] == pytest.approx(50)


def test_dcf_no_growth_perpetuity_matches_gordon():
    # g=0, tg=0 -> väärtus = FCF / r
    a = DCFAssumptions(growth=0.0, discount_rate=0.10, terminal_growth=0.0, years=10)
    r = run_dcf(100.0, shares=10, cash=0, debt=0, a=a, price=50)
    assert r.enterprise_value == pytest.approx(1000.0)
    assert r.intrinsic_per_share == pytest.approx(100.0)
    assert r.margin_of_safety == pytest.approx(0.5)
    assert r.score == 100


def test_dcf_cash_and_debt_and_fade():
    a = DCFAssumptions(growth=0.10, discount_rate=0.09, terminal_growth=0.02, years=10)
    r = run_dcf(100.0, shares=1, cash=50, debt=200, a=a)
    assert r.equity_value == pytest.approx(r.enterprise_value - 150)
    growth = [r.projected_fcf[i] / (r.projected_fcf[i - 1] if i else 100.0) - 1 for i in range(10)]
    assert growth[0] == pytest.approx(0.10)
    assert growth[-1] == pytest.approx(0.02)
    with pytest.raises(ValueError):
        run_dcf(100, 1, 0, 0, DCFAssumptions(0.05, 0.02, 0.03))


def test_dcf_negative_fcf_returns_reason():
    res, reason = evaluate_dcf({"freeCashflow": -1e9, "sharesOutstanding": 1e6}, [], 10)
    assert res is None and "Negatiivne" in reason


def test_dcf_prefers_statement_fcf_and_skips_financials():
    info = {"freeCashflow": 1.0, "sharesOutstanding": 1e6}
    res, _ = evaluate_dcf(info, [5e6, 6e6], 10)
    assert res.base_fcf == 6e6
    res, reason = evaluate_dcf({**info, "sector": "Financial Services"}, [5e6], 10)
    assert res is None and "finants" in reason


def test_dcf_negative_equity_scores_zero():
    a = DCFAssumptions(growth=0.0, discount_rate=0.10, terminal_growth=0.0, years=10)
    r = run_dcf(1.0, shares=1, cash=0, debt=100, a=a, price=10)
    assert r.intrinsic_per_share < 0 and r.score == 0


def test_estimators_clamped():
    assert estimate_discount_rate(None) == pytest.approx(0.10)
    assert estimate_discount_rate(5) == 0.14
    assert estimate_discount_rate(0) == 0.07
    assert estimate_growth([100, 400, 1600], {}) == 0.20
    assert estimate_growth([], {}) == 0.05


def _prices(trend: float, n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = 100 * np.exp(np.cumsum(trend + rng.normal(0, 0.01, n)))
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close}, index=idx)


def test_rsi_bounds_and_monotonic_rise():
    s = pd.Series(np.arange(1, 60, dtype=float))
    assert rsi(s).iloc[-1] == 100
    r = rsi(_prices(0.0)["Close"]).dropna()
    assert r.between(0, 100).all()


def test_technical_uptrend_beats_downtrend():
    up = evaluate_technical(_prices(0.003))
    down = evaluate_technical(_prices(-0.003))
    assert up["score"] > 60 > down["score"]
    assert evaluate_technical(_prices(0.0, n=30))["score"] is None


def test_combine_renormalizes_missing():
    assert combine({"a": 80, "b": None}, {"a": 1, "b": 1}) == 80
    assert combine({"a": 80, "b": 40}, {"a": 3, "b": 1}) == 70
    assert combine({"a": None}, {"a": 1}) is None
    assert rating(75) == "Tugev" and rating(30) == "Nõrk" and rating(None) == "—"


def test_evaluate_end_to_end_offline():
    info = {"trailingPE": 15, "returnOnEquity": 0.2, "revenueGrowth": 0.08, "freeCashflow": 1e9,
            "sharesOutstanding": 1e8, "totalCash": 1e9, "totalDebt": 5e8, "beta": 1.0, "currentPrice": 80}
    ev = evaluate(Snapshot("TEST", info, [8e8, 9e8, 1e9], _prices(0.001)))
    row = ev.summary_row()
    assert 0 <= row["Koondskoor"] <= 100
    assert row["Sisemine väärtus"] > 0
