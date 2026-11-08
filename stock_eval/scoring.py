"""Osaskooride kombineerimine koondhinnanguks."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from .data import Snapshot
from .dcf import DCFResult, evaluate_dcf
from .fundamentals import evaluate_fundamentals
from .growth import GrowthResult, evaluate_growth
from .technical import evaluate_technical

DEFAULT_WEIGHTS = {"fundamental": 0.40, "dcf": 0.20, "technical": 0.15, "growth": 0.25}


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
    growth: GrowthResult
    horizon: int
    total: float | None

    @cached_property
    def bullbear(self):
        from .scenarios import analyze
        return analyze(self, self.horizon)

    def summary_row(self) -> dict:
        s = self.snapshot
        d = self.dcf
        g = self.growth
        a = g.analyst
        p = g.projection(self.horizon)
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
            "Rule of 40": (self.fundamentals.get("tech") or {}).get("raw", {}).get("rule40"),
            "Analüütikute siht 12k": a.mean if a else None,
            "Potentsiaal 12k": a.upside if a else None,
            f"Oodatav hind {self.horizon}a": p.price if p else None,
            "Oodatav tootlus a/a": p.annual_return if p else None,
            "Kasvupotentsiaal": g.score(self.horizon),
            "Bull/bear": self.bullbear.balance,
            "Vaade": self.bullbear.verdict,
            f"Bear {self.horizon}a": _chg(self.bullbear.scenario("Bear")),
            f"Bull {self.horizon}a": _chg(self.bullbear.scenario("Bull")),
            "Tulu/risk": self.bullbear.reward_risk,
            "Koondskoor": self.total,
            "Hinnang": rating(self.total),
        }


def _chg(scn):
    return scn.change if scn else None


def evaluate(snapshot: Snapshot, weights: dict[str, float] | None = None,
             dcf_overrides: dict | None = None, horizon: int = 3,
             growth_overrides: dict | None = None) -> Evaluation:
    weights = weights or DEFAULT_WEIGHTS
    fund = evaluate_fundamentals(snapshot.info, snapshot.statements)
    dcf, reason = evaluate_dcf(snapshot.info, snapshot.fcf_history, snapshot.price, **(dcf_overrides or {}))
    tech = evaluate_technical(snapshot.prices)
    growth = evaluate_growth(snapshot.info, snapshot.estimates, snapshot.price,
                             statements=snapshot.statements, **(growth_overrides or {}))
    total = combine({"fundamental": fund["score"], "dcf": dcf.score if dcf else None,
                     "technical": tech["score"], "growth": growth.score(horizon)}, weights)
    return Evaluation(snapshot, fund, dcf, reason, tech, growth, horizon, total)
