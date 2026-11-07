import io

import pandas as pd
import pytest

from stock_eval.portfolio import holdings_table, parse_yahoo_csv, weighted_score

YAHOO_CSV = """Symbol,Current Price,Date,Time,Change,Open,High,Low,Volume,Trade Date,Purchase Price,Quantity,Commission,High Limit,Low Limit,Comment
AAPL,342.37,2026/11/06,16:00 EST,-5.1,338.7,345.8,336.1,52000000,20240115,180.0,10,1.0,,,
AAPL,342.37,2026/11/06,16:00 EST,-5.1,338.7,345.8,336.1,52000000,20250310,220.0,5,0,,,
LHV1T.TL,3.24,2026/11/06,17:30 EET,0.01,3.2,3.3,3.2,100000,20230601,3.5,1000,0,,,
NVDA,186.64,2026/11/06,16:00 EST,1.2,185,188,184,1000000,,,,,,,
"""


def test_parse_aggregates_lots_and_keeps_watchlist():
    p = parse_yahoo_csv(io.StringIO(YAHOO_CSV)).set_index("Ticker")
    assert p.loc["AAPL", "Kogus"] == 15
    assert p.loc["AAPL", "Investeeritud"] == pytest.approx(10 * 180 + 1 + 5 * 220)
    assert p.loc["AAPL", "Keskmine ostuhind"] == pytest.approx(2901 / 15)
    assert p.loc["NVDA", "Kogus"] == 0 and pd.isna(p.loc["NVDA", "Investeeritud"])
    assert list(p.index) == ["AAPL", "LHV1T.TL", "NVDA"]


def test_parse_rejects_wrong_file():
    with pytest.raises(ValueError):
        parse_yahoo_csv(io.StringIO("a,b\n1,2\n"))


def test_holdings_and_weighted_score():
    p = parse_yahoo_csv(io.StringIO(YAHOO_CSV))
    h = holdings_table(p, {"AAPL": 300.0, "LHV1T.TL": 3.0, "NVDA": 186.0}, {"AAPL": 80, "LHV1T.TL": 40})
    assert "NVDA" not in h["Ticker"].values  # jälgimisnimekiri pole positsioon
    a = h.set_index("Ticker").loc["AAPL"]
    assert a["Turuväärtus"] == 4500 and a["Kasum/kahjum"] == pytest.approx(4500 - 2901)
    assert h["Osakaal"].sum() == pytest.approx(1)
    assert weighted_score(h) == pytest.approx((80 * 4500 + 40 * 3000) / 7500)


def test_weights_use_fx_conversion():
    p = parse_yahoo_csv(io.StringIO(YAHOO_CSV))
    h = holdings_table(p, {"AAPL": 300.0, "LHV1T.TL": 3.0}, {"AAPL": 80, "LHV1T.TL": 40},
                       {"AAPL": "USD", "LHV1T.TL": "EUR"}, {"USD": 0.5})
    v = h.set_index("Ticker")["Väärtus (EUR)"]
    assert v["AAPL"] == 2250 and v["LHV1T.TL"] == 3000
    assert h.set_index("Ticker").loc["LHV1T.TL", "Osakaal"] == pytest.approx(3000 / 5250)
    assert weighted_score(h) == pytest.approx((80 * 2250 + 40 * 3000) / 5250)


def test_pence_quoted_and_missing_rate():
    p = pd.DataFrame({"Ticker": ["X", "Y"], "Kogus": [100.0, 1.0], "Keskmine ostuhind": [None, None],
                      "Investeeritud": [None, None]})
    h = holdings_table(p, {"X": 200.0, "Y": 10.0}, {}, {"X": "GBp", "Y": "JPY"}, {"GBP": 1.2})
    v = h.set_index("Ticker")["Väärtus (EUR)"]
    assert v["X"] == pytest.approx(100 * 200 * 0.01 * 1.2)
    assert pd.isna(v["Y"])
