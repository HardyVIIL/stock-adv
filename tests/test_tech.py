import pytest

from stock_eval.fundamentals import evaluate_fundamentals
from stock_eval.tech import business_model, evaluate_tech, is_tech, tech_metrics

SAAS = {"sector": "Technology", "industry": "Software - Infrastructure", "enterpriseToRevenue": 10.0}
ST = {"revenue": [80.0, 100.0], "gross_profit": [60.0, 78.0], "sbc": [8.0, 10.0], "fcf": [15.0, 25.0],
      "inventory": []}


def test_detection_and_model():
    assert is_tech(SAAS) and business_model(SAAS) == "software"
    assert business_model({"sector": "Technology", "industry": "Semiconductors"}) == "semis"
    assert is_tech({"sector": "Communication Services", "industry": "Internet Content & Information"})
    assert not is_tech({"sector": "Communication Services", "industry": "Telecom Services"})
    assert not is_tech({"sector": "Consumer Defensive", "industry": "Beverages"})


def test_rule_of_40_and_sbc():
    m = tech_metrics(SAAS, ST)
    assert m["rev_growth"] == pytest.approx(0.25)
    assert m["fcf_margin"] == pytest.approx(0.25)
    assert m["rule40"] == pytest.approx(50)
    assert m["sbc_pct"] == pytest.approx(0.10)
    assert m["rule40_ex_sbc"] == pytest.approx(40)
    assert m["gross_margin"] == pytest.approx(0.78)
    assert m["gross_margin_trend"] == pytest.approx(0.78 - 0.75)
    assert m["ev_sales_per_growth"] == pytest.approx(10 / 25)


def test_inventory_warning_for_hardware():
    info = {"sector": "Technology", "industry": "Computer Hardware"}
    st = {**ST, "inventory": [10.0, 20.0]}  # ladu +100%, käive +25%
    res = evaluate_tech(info, st)
    inv = next(r for r in res["metrics"] if r["Näitaja"].startswith("Laovarude"))
    assert inv["Skoor"] == 0


def test_tech_category_double_weight():
    info = {**SAAS, "returnOnEquity": 0.25}  # kasumlikkus 100 (ainus üldine kategooria)
    res = evaluate_fundamentals(info, ST)
    t = res["categories"]["Tehnoloogia"]
    assert res["score"] == pytest.approx((100 + 2 * t) / 3)
    assert evaluate_fundamentals({"returnOnEquity": 0.25}, ST)["tech"] is None
