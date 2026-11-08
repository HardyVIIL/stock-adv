import math

import numpy as np
import pandas as pd
import pytest

from stock_eval.montecarlo import MarketStats, market_stats, model_drift, simulate


def pos(t="A", value=1000.0, index_value=1000.0, bear=None, base=None, bull=None, sigma=0.3, rho=0.8):
    return {"ticker": t, "value": value, "index_value": index_value, "bear": bear, "base": base, "bull": bull,
            "stats": MarketStats(sigma, rho, 150)}


def test_equal_start_equal_drift_is_coin_flip():
    r = simulate([pos(base=0.09)], sigma_i=0.2, index_return=0.09, years=5, n=40_000)
    assert r.prob_ahead()[0] == pytest.approx(0.5, abs=0.02)


def test_no_forecast_assumes_index_drift():
    mu, s, has = model_drift(None, None, None, 0.08)
    assert mu == pytest.approx(math.log(1.08)) and s == 0 and not has


def test_perfect_correlation_same_vol_is_deterministic():
    # sama volatiilsus, ρ≈1 (piiratud 0,99), mudeli ebakindlus 0 -> suhe indeksiga peaaegu deterministlik
    # σ_ajalooline 5% -> pikaajaline ½·5% + ½·35% = 20% = indeksi σ
    ahead = simulate([pos(value=900, base=0.15, sigma=0.05, rho=1.0)], sigma_i=0.2, index_return=0.09, years=5)
    assert ahead.prob_ahead()[0] > 0.97
    behind = simulate([pos(value=900, base=0.05, sigma=0.05, rho=1.0)], sigma_i=0.2, index_return=0.09, years=5)
    assert behind.prob_ahead()[0] < 0.03


def test_higher_volatility_widens_range_and_scenarios_add_uncertainty():
    lo = simulate([pos(base=0.10, sigma=0.25)], 0.2, 0.09, 5, n=20_000)
    hi = simulate([pos(base=0.10, sigma=0.80)], 0.2, 0.09, 5, n=20_000)
    w = lambda r: np.subtract(*np.percentile(r.gaps[:, 0], [90, 10]))
    assert w(hi) > w(lo)
    wide = simulate([pos(base=0.10, bear=-0.10, bull=0.35, sigma=0.25)], 0.2, 0.09, 5, n=20_000)
    assert w(wide) > w(lo)  # s_mudel·√T = 0,196·2,24 = 0,44 > pikaajaline 0,30


def test_effective_sigma_takes_max_not_sum():
    from stock_eval.montecarlo import effective_sigma
    assert effective_sigma(0.45, 0.10, 5) == pytest.approx(0.40)          # ½·45% + ½·35%
    assert effective_sigma(0.20, 0.15, 5) == pytest.approx(0.15 * math.sqrt(5))


def test_portfolio_total_is_sum_and_market_is_shared():
    r = simulate([pos("A", base=0.1), pos("B", base=0.1)], 0.2, 0.09, 5, n=1000)
    assert np.allclose(r.total, r.gaps.sum(axis=1))
    assert np.corrcoef(r.gaps[:, 0], r.gaps[:, 1])[0, 1] > 0  # ühine turg + ühine indeks


def test_market_stats_from_prices():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2022-01-03", periods=900)
    m = rng.normal(0, 0.01, 900)
    a = 0.9 * m + rng.normal(0, 0.005, 900)
    closes = pd.DataFrame({"IDX": 100 * np.exp(np.cumsum(m)), "A": 50 * np.exp(np.cumsum(a)),
                           "NEW": [np.nan] * 850 + list(10 * np.exp(np.cumsum(a[-50:])))}, index=idx)
    stats, sigma_i = market_stats(closes, ["A", "NEW", "MISSING"], "IDX")
    assert sigma_i == pytest.approx(0.01 * math.sqrt(252), rel=0.25)
    assert stats["A"].rho > 0.8 and stats["A"].estimated
    assert not stats["NEW"].estimated and not stats["MISSING"].estimated
