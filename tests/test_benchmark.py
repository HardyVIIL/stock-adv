import pandas as pd
import pytest

from stock_eval.benchmark import composition_history, dated_lots, lot_comparison, max_drawdown, to_eur
from stock_eval.portfolio import aggregate_lots, apply_splits

D = pd.Timestamp


def _closes():
    idx = pd.bdate_range("2024-01-01", "2024-12-31")
    n = len(idx)
    return pd.DataFrame({
        "AAA": [100.0] * n,                         # aktsia (USD), ostuhind sisestatud käsitsi
        "QQQ": [100.0 + 100.0 * i / (n - 1) for i in range(n)],   # 100 -> 200
        "USDEUR=X": [1.0] * (n // 2) + [0.5] * (n - n // 2),     # dollar nõrgeneb poole võrra
        "SWED": [10.0] * n,
    }, index=idx)


def lots(rows):
    return pd.DataFrame(rows, columns=["Ticker", "Kuupäev", "Kogus", "Ostuhind", "Komisjon"])


def test_lot_vs_index_in_eur():
    l = lots([("AAA", D("2024-01-01"), 10, 100.0, 0.0)])
    df = lot_comparison(l, {"AAA": 300.0}, {"AAA": "USD"}, _closes(), "QQQ")
    r = df.iloc[0]
    assert r["Investeeritud €"] == pytest.approx(1000)       # 1000 USD * 1.0
    assert r["Väärtus €"] == pytest.approx(10 * 300 * 0.5)   # 1500 €
    assert r["Indeksis oleks €"] == pytest.approx(1000 / 100 * 200 * 0.5)  # 1000 €
    assert r["Vahe €"] == pytest.approx(500)


def test_received_shares_excluded_by_default_and_split_lots_add_no_cost():
    l = lots([("SWED", D("2024-01-02"), 100, 0.0, 0.0),        # tulemustasu
              ("AAA", D("2024-01-01"), 2, 100.0, 0.0),
              ("AAA", D("2024-06-03"), 2, 0.0, 0.0)])          # tükelduse rida
    splits = {"AAA": [(D("2024-06-01"), 2.0)]}
    c, cur = _closes(), {"AAA": "EUR", "SWED": "EUR"}
    df = lot_comparison(l, {"AAA": 100.0, "SWED": 10.0}, cur, c, "QQQ", splits=splits).set_index("Ticker")
    assert "SWED" not in df.index
    assert df.loc["AAA", "Investeeritud €"] == pytest.approx(200)
    assert df.loc["AAA", "Väärtus €"] == pytest.approx(400)
    inc = lot_comparison(l, {"AAA": 100.0, "SWED": 10.0}, cur, c, "QQQ", splits=splits,
                         include_received=True).set_index("Ticker")
    assert inc.loc["SWED", "Investeeritud €"] == pytest.approx(1000)  # 100 * turuhind 10


def test_apply_splits_only_when_not_recorded():
    l = lots([("NOW", D("2022-01-25"), 2, 510.0, 11.0), ("PANW", D("2024-07-01"), 2, 340.0, 0.0),
              ("PANW", D("2024-12-18"), 2, 0.0, 0.0)])
    splits = {"NOW": [(D("2025-12-18"), 5.0)], "PANW": [(D("2024-12-16"), 2.0)]}
    out, notes = apply_splits(l, splits)
    agg = aggregate_lots(out).set_index("Ticker")
    assert agg.loc["NOW", "Kogus"] == 10 and agg.loc["NOW", "Investeeritud"] == pytest.approx(1031)
    assert agg.loc["PANW", "Kogus"] == 4  # kasutaja oli tükelduse ise lisanud
    assert len(notes) == 1 and "NOW" in notes[0]


def test_dated_lots_drops_watchlist():
    l = lots([("A", D("2024-01-01"), 1, 1.0, 0), ("B", pd.NaT, 0, None, 0)])
    assert list(dated_lots(l)["Ticker"]) == ["A"]


def test_composition_history_and_drawdown():
    c = _closes()
    eur = to_eur(c, {"AAA": "USD", "QQQ": "USD", "SWED": "EUR"})
    h = composition_history(eur, {"SWED": 1.0}, ["QQQ"], c.index[0])
    assert h["Minu portfell"].iloc[-1] == pytest.approx(100)
    assert h.iloc[0].tolist() == [100.0, 100.0]
    assert max_drawdown(pd.Series([100, 120, 60, 90])) == pytest.approx(-0.5)
