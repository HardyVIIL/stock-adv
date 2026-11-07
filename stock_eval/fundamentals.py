"""Fundamentaalanalüüs: suhtarvud -> skoorid 0..100."""
from __future__ import annotations

from dataclasses import dataclass


def linear_score(value: float | None, bad: float, good: float) -> float | None:
    """Lineaarne skoor: `bad` -> 0, `good` -> 100, vahepeal interpoleeritud.

    Töötab ka siis, kui `good < bad` (nt P/E: madalam on parem).
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    frac = (v - bad) / (good - bad)
    return max(0.0, min(100.0, frac * 100.0))


@dataclass(frozen=True)
class MetricRule:
    key: str
    label: str
    category: str
    bad: float
    good: float
    fmt: str = "{:.2f}"
    scale: float = 1.0           # väärtuse korrutaja enne hindamist (nt % -> murdosa)
    negative_is_bad: bool = False  # nt negatiivne P/E = kahjum -> skoor 0


RULES: list[MetricRule] = [
    # Hindamine (madalam = odavam)
    MetricRule("trailingPE", "P/E (TTM)", "Hindamine", bad=40, good=10, negative_is_bad=True),
    MetricRule("forwardPE", "P/E (ootus)", "Hindamine", bad=35, good=10, negative_is_bad=True),
    MetricRule("peg", "PEG", "Hindamine", bad=3, good=1, negative_is_bad=True),
    MetricRule("enterpriseToEbitda", "EV/EBITDA", "Hindamine", bad=25, good=8, negative_is_bad=True),
    MetricRule("priceToBook", "P/B", "Hindamine", bad=10, good=1.5, negative_is_bad=True),
    # Kasumlikkus
    MetricRule("returnOnEquity", "ROE", "Kasumlikkus", bad=0.0, good=0.25, fmt="{:.1%}"),
    MetricRule("profitMargins", "Puhaskasumi marginaal", "Kasumlikkus", bad=0.0, good=0.25, fmt="{:.1%}"),
    MetricRule("operatingMargins", "Ärikasumi marginaal", "Kasumlikkus", bad=0.0, good=0.30, fmt="{:.1%}"),
    # Kasv
    MetricRule("revenueGrowth", "Käibe kasv (a/a)", "Kasv", bad=-0.05, good=0.20, fmt="{:.1%}"),
    MetricRule("earningsGrowth", "Kasumi kasv (a/a)", "Kasv", bad=-0.10, good=0.25, fmt="{:.1%}"),
    # Finantstervis (yfinance annab D/E protsentides)
    MetricRule("debtToEquity", "Võlg/omakapital", "Finantstervis", bad=2.0, good=0.3, scale=0.01, negative_is_bad=True),
    MetricRule("currentRatio", "Lühiajaline likviidsus", "Finantstervis", bad=0.8, good=2.0),
]

CATEGORIES = ["Hindamine", "Kasumlikkus", "Kasv", "Finantstervis"]


def _value(info: dict, key: str):
    if key == "peg":
        return info.get("pegRatio") or info.get("trailingPegRatio")
    return info.get(key)


def evaluate_fundamentals(info: dict) -> dict:
    """Tagastab {'metrics': [...], 'categories': {kat: skoor}, 'score': koondskoor|None}."""
    metrics = []
    by_cat: dict[str, list[float]] = {c: [] for c in CATEGORIES}
    for r in RULES:
        raw = _value(info, r.key)
        val = None if raw is None else float(raw) * r.scale
        if val is not None and val != val:
            val = None
        if val is not None and r.negative_is_bad and val < 0:
            score = 0.0
        else:
            score = linear_score(val, r.bad, r.good)
        if score is not None:
            by_cat[r.category].append(score)
        metrics.append({
            "Kategooria": r.category,
            "Näitaja": r.label,
            "Väärtus": None if val is None else r.fmt.format(val),
            "Skoor": None if score is None else round(score),
        })
    categories = {c: (sum(v) / len(v) if v else None) for c, v in by_cat.items()}
    available = [s for s in categories.values() if s is not None]
    total = sum(available) / len(available) if available else None
    return {"metrics": metrics, "categories": categories, "score": total}
