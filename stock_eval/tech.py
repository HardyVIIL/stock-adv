"""Tehnoloogiafirmade näitajad: Rule of 40, aktsiapõhised tasud (SBC), brutomarginaal, EV/Sales, laovarud.

Arvutused põhinevad viimasel majandusaastal (aastaaruanded), v.a EV/Sales (Yahoo jooksev).
"""
from __future__ import annotations

from .fundamentals import linear_score

TECH_SECTORS = {"Technology", "Communication Services"}
TECH_INDUSTRY_WORDS = ("Software", "Semiconductor", "Internet", "Computer", "Communication Equipment",
                       "Electronic", "Information Technology")
# Brutomarginaali skaala (halb, hea) ärimudeli järgi
GROSS_MARGIN_SCALE = {"software": (0.55, 0.80), "semis": (0.30, 0.60), "hardware": (0.10, 0.40),
                      "internet": (0.30, 0.65)}


def is_tech(info: dict) -> bool:
    industry = info.get("industry") or ""
    return info.get("sector") in TECH_SECTORS and (
        info.get("sector") == "Technology" or any(w in industry for w in TECH_INDUSTRY_WORDS))


def business_model(info: dict) -> str:
    ind = info.get("industry") or ""
    if "Software" in ind or "Information Technology" in ind:
        return "software"
    if "Semiconductor" in ind:
        return "semis"
    if "Internet" in ind or info.get("sector") == "Communication Services":
        return "internet"
    return "hardware"


MODEL_LABEL = {"software": "Tarkvara", "semis": "Kiibid", "hardware": "Riistvara", "internet": "Internet"}


def _last(xs: list[float], back: int = 0) -> float | None:
    return xs[-1 - back] if len(xs) > back else None


def tech_metrics(info: dict, st: dict) -> dict:
    """Arvutab toorväärtused. Puuduvad on None."""
    rev, gp, sbc, fcf, inv = (st.get(k, []) for k in ("revenue", "gross_profit", "sbc", "fcf", "inventory"))
    r0, r1 = _last(rev), _last(rev, 1)
    m: dict[str, float | None] = {}
    m["rev_growth"] = r0 / r1 - 1 if r0 and r1 else None
    m["fcf_margin"] = _last(fcf) / r0 if r0 and _last(fcf) is not None else None
    m["sbc_pct"] = _last(sbc) / r0 if r0 and _last(sbc) is not None else None
    m["fcf_margin_ex_sbc"] = (m["fcf_margin"] - m["sbc_pct"]
                              if m["fcf_margin"] is not None and m["sbc_pct"] is not None else None)
    m["rule40"] = (m["rev_growth"] + m["fcf_margin"]) * 100 \
        if m["rev_growth"] is not None and m["fcf_margin"] is not None else None
    m["rule40_ex_sbc"] = (m["rev_growth"] + m["fcf_margin_ex_sbc"]) * 100 \
        if m["rev_growth"] is not None and m["fcf_margin_ex_sbc"] is not None else None
    gm = [g / r for g, r in zip(gp[-3:], rev[-3:]) if r] if len(gp) == len(rev) else []
    m["gross_margin"] = gm[-1] if gm else info.get("grossMargins")
    m["gross_margin_trend"] = gm[-1] - gm[0] if len(gm) >= 2 else None
    ev_s = info.get("enterpriseToRevenue")
    g = m["rev_growth"] if m["rev_growth"] is not None else info.get("revenueGrowth")
    m["ev_sales"] = ev_s
    m["ev_sales_per_growth"] = ev_s / (g * 100) if ev_s and g and g > 0 else None
    i0, i1 = _last(inv), _last(inv, 1)
    m["inventory_vs_revenue"] = (i0 / i1 - 1) - m["rev_growth"] \
        if i0 and i1 and m["rev_growth"] is not None else None
    return m


def evaluate_tech(info: dict, statements: dict) -> dict | None:
    """Tagastab {'metrics': [...], 'score', 'model', 'raw'} või None, kui firma pole tehnoloogiafirma."""
    if not is_tech(info):
        return None
    m = tech_metrics(info, statements)
    model = business_model(info)
    gm_bad, gm_good = GROSS_MARGIN_SCALE[model]
    rows = [
        ("Rule of 40 (kasv + FCF marginaal)", m["rule40"], "{:.0f}", linear_score(m["rule40"], 10, 50),
         "≥40 tugev; tasakaal kasvu ja kasumlikkuse vahel"),
        ("Rule of 40 ilma SBC-ta", m["rule40_ex_sbc"], "{:.0f}", None,
         "Sama, aga aktsiapõhised tasud arvatud rahavoost maha (rangem)"),
        ("Käibe kasv (viimane aasta)", m["rev_growth"], "{:.1%}", None, ""),
        ("FCF marginaal", m["fcf_margin"], "{:.1%}", None, ""),
        ("Aktsiapõhised tasud % käibest", m["sbc_pct"], "{:.1%}", linear_score(m["sbc_pct"], 0.25, 0.03),
         "Lahjendab aktsionäre; <5% hea, >15% kõrge"),
        ("Brutomarginaal", m["gross_margin"], "{:.1%}", linear_score(m["gross_margin"], gm_bad, gm_good),
         f"{MODEL_LABEL[model]}: hea ≥{gm_good:.0%}, nõrk ≤{gm_bad:.0%}"),
        ("Brutomarginaali muutus (2 a)", m["gross_margin_trend"], "{:+.1%}",
         linear_score(m["gross_margin_trend"], -0.05, 0.03), "Langus on varajane hoiatusmärk"),
        ("EV/Sales", m["ev_sales"], "{:.1f}", None, ""),
        ("EV/Sales ÷ kasv %", m["ev_sales_per_growth"], "{:.2f}",
         linear_score(m["ev_sales_per_growth"], 1.0, 0.2), "Kasvuga korrigeeritud hind; <0,3 odav, >0,8 kallis"),
    ]
    if model in ("semis", "hardware"):
        rows.append(("Laovarude kasv − käibe kasv", m["inventory_vs_revenue"], "{:+.0%}",
                     linear_score(m["inventory_vs_revenue"], 0.30, 0.0),
                     "Paisuv ladu ennustab tihti nõudluse langust"))
    metrics, scores = [], []
    for label, val, fmt, score, comment in rows:
        if score is not None:
            scores.append(score)
        metrics.append({"Näitaja": label, "Väärtus": None if val is None else fmt.format(val),
                        "Skoor": None if score is None else round(score), "Kommentaar": comment})
    return {"metrics": metrics, "score": sum(scores) / len(scores) if scores else None,
            "model": MODEL_LABEL[model], "raw": m}
