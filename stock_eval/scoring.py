"""Osaskooride kombineerimine koondhinnanguks."""
from __future__ import annotations

from dataclasses import dataclass

from .data import Snapshot
from .dcf import DCFResult, evaluate_dcf
from .fundamentals import evaluate_fundamentals
from .technical import evaluate_technical

DEFAULT_WEIGHTS = {"fundamental": 0.5, "dcf": 0.3, "technical": 0.2}


def combine(scores: dict[str, float | None], weights: dict[str, float]) -> float | None:
    """Kaalutud keskmine; puuduvad osaskoorid jäetakse välja ja kaalud normaliseeritakse."""
    pairs = [(s, weights.get(k, 0)) for k, s in scores.items() if s is not None and weights.get(k, 0) > 0]
    total_w = sum(w for _, w in pairs)
    if total_w == 0:
        return None
    return sum(s * w for s, w in pairs) / total_w


def rating(score: float | None) -> str:
    if score is None:
        return "—"
    if score >= 70:
        return "Tugev"
    if score >= 55:
        return "Hea"
    if score >= 40:
        return "Neutraalne"
    return "Nõrk"


@dataclass
class Evaluation:
    snapshot: Snapshot
    fundamentals: dict
    dcf: DCFResult | None
    dcf_reason: str | None
    technical: dict
    total: float | None

    def summary_row(self) -> dict:
        s = self.snapshot
        d = self.dcf
        return {
            "Ticker": s.ticker,
            "Nimi": s.name,
            "Sektor": s.info.get("sector") or "—",
            "Hind": s.price,
            "Valuuta": s.info.get("currency") or "",
            "Sisemine väärtus": d.intrinsic_per_share if d else None,
            "Turvamarginaal": d.margin_of_safety if d else None,
            "Fundamentaal": self.fundamentals["score"],
            "DCF": d.score if d else None,
            "Tehniline": self.technical["score"],
            "Koondskoor": self.total,
            "Hinnang": rating(self.total),
        }


def evaluate(snapshot: Snapshot, weights: dict[str, float] | None = None,
             dcf_overrides: dict | None = None) -> Evaluation:
    weights = weights or DEFAULT_WEIGHTS
    fund = evaluate_fundamentals(snapshot.info)
    dcf, reason = evaluate_dcf(snapshot.info, snapshot.fcf_history, snapshot.price, **(dcf_overrides or {}))
    tech = evaluate_technical(snapshot.prices)
    total = combine({"fundamental": fund["score"], "dcf": dcf.score if dcf else None,
                     "technical": tech["score"]}, weights)
    return Evaluation(snapshot, fund, dcf, reason, tech, total)
