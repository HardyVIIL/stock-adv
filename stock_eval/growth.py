"""Kasvupotentsiaal: analüütikute 12 kuu sihthind ja kasumipõhine hinnaprognoos 1–5 aastaks.

Mudel (EPS × P/E):
  * Lähtekasum = järgmise 12 kuu EPS ootus (forwardEps), varuna jooksva aasta / TTM EPS.
  * Kasv = analüütikute EPS- ja käibe kasvuprognooside keskmine (varuna TTM käibe kasv),
    piiratud -10%..30%, ja sulandub 5 aastaga lineaarselt 6%-ni (kiire kasv ei kesta igavesti).
  * P/E liigub 5 aastaga praeguselt (hind / EPS) poole võrra sektori tüüpilise P/E suunas
    (praegune piiratud 6..40) — erandlikult kõrged ja madalad kordajad kipuvad normaliseeruma.
  * Oodatav hind aastal n = EPS_n × P/E_n; aastane tootlus lisab dividenditootluse.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .fundamentals import linear_score

MARKET_PE = 17.0
SECTOR_PE = {  # tüüpilised pikaajalised ootuse P/E-d (ligikaudsed)
    "Financial Services": 11.0, "Energy": 11.0, "Basic Materials": 13.0, "Utilities": 16.0,
    "Real Estate": 16.0, "Communication Services": 17.0, "Industrials": 19.0, "Consumer Cyclical": 19.0,
    "Consumer Defensive": 20.0, "Healthcare": 19.0, "Technology": 22.0,
}
LONG_RUN_GROWTH = 0.06
FADE_YEARS = 5
HORIZONS = (1, 3, 5)


@dataclass
class AnalystView:
    mean: float
    low: float | None
    high: float | None
    count: int
    recommendation: float | None   # 1 = tugev ost ... 5 = müü
    recommendation_key: str | None
    upside: float                  # (keskmine siht - hind) / hind

    @property
    def score(self) -> float:
        return linear_score(self.upside, -0.10, 0.30)


@dataclass
class Projection:
    years: int
    eps: float
    price: float
    annual_return: float  # hinnatõus + dividend, aastas


@dataclass
class GrowthResult:
    analyst: AnalystView | None
    eps0: float | None
    growth: float | None
    exit_pe: float | None          # P/E 5 aasta pärast
    dividend_yield: float
    pe_now: float | None = None    # hind / järgmise 12 k EPS
    projections: list[Projection] = field(default_factory=list)
    model_reason: str | None = None
    growth_sources: dict = field(default_factory=dict)

    def projection(self, years: int) -> Projection | None:
        return next((p for p in self.projections if p.years == years), None)

    def model_score(self, years: int) -> float | None:
        p = self.projection(years)
        return linear_score(p.annual_return, -0.05, 0.20) if p else None

    def score(self, years: int) -> float | None:
        parts = [s for s in (self.analyst.score if self.analyst else None, self.model_score(years))
                 if s is not None]
        return sum(parts) / len(parts) if parts else None


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def analyst_view(info: dict, price: float | None, min_analysts: int = 3) -> AnalystView | None:
    mean, n = _f(info.get("targetMeanPrice")), int(info.get("numberOfAnalystOpinions") or 0)
    if not price or not mean or n < min_analysts:
        return None
    return AnalystView(
        mean=mean, low=_f(info.get("targetLowPrice")), high=_f(info.get("targetHighPrice")), count=n,
        recommendation=_f(info.get("recommendationMean")), recommendation_key=info.get("recommendationKey"),
        upside=mean / price - 1,
    )


def estimate_growth(info: dict, estimates: dict) -> tuple[float | None, dict]:
    sources = {
        "EPS kasv järgmine aasta (analüütikud)": estimates.get("eps_growth_1y"),
        "Käibe kasv järgmine aasta (analüütikud)": estimates.get("rev_growth_1y"),
        "Pikaajaline kasv (analüütikud)": estimates.get("ltg"),
    }
    sources = {k: v for k, v in sources.items() if v is not None}
    if not sources and _f(info.get("revenueGrowth")) is not None:
        sources["Käibe kasv viimane aasta"] = _f(info.get("revenueGrowth"))
    if not sources:
        return None, {}
    g = sum(sources.values()) / len(sources)
    return min(0.30, max(-0.10, g)), sources


def growth_path(g: float, years: int) -> list[float]:
    """Aastased kasvumäärad: algab g-st ja sulandub FADE_YEARS jooksul LONG_RUN_GROWTH-ni."""
    out = []
    for k in range(1, years + 1):
        frac = min(1.0, (k - 1) / (FADE_YEARS - 1))
        out.append(g + (LONG_RUN_GROWTH - g) * frac)
    return out


def sector_pe(info: dict) -> float:
    return SECTOR_PE.get(info.get("sector") or "", MARKET_PE)


def exit_multiple(info: dict, pe_now: float | None = None) -> float:
    """P/E horisondi (5 a) lõpus: poolel teel praegusest sektori tüüpilise suunas."""
    pe = pe_now if pe_now is not None else _f(info.get("forwardPE"))
    ref = sector_pe(info)
    if pe is None or pe <= 0:
        return ref
    return (min(40.0, max(6.0, pe)) + ref) / 2


def pe_path(pe_now: float, pe_end: float, years: int) -> list[float]:
    """P/E igal aastal: lineaarne liikumine praeguselt lõppväärtuseni FADE_YEARS jooksul."""
    return [pe_now + (pe_end - pe_now) * min(1.0, k / FADE_YEARS) for k in range(1, years + 1)]


def evaluate_growth(info: dict, estimates: dict, price: float | None,
                    growth: float | None = None, exit_pe: float | None = None) -> GrowthResult:
    dy = _f(info.get("dividendYield")) or 0.0
    dy = dy / 100 if dy > 0.2 else dy  # yfinance annab protsentides (5.09 = 5,09%)
    res = GrowthResult(analyst=analyst_view(info, price), eps0=None, growth=None, exit_pe=None,
                       dividend_yield=dy)

    eps0 = next((e for e in (_f(info.get("forwardEps")), _f(info.get("epsCurrentYear")),
                             _f(info.get("trailingEps"))) if e is not None), None)
    if not price:
        res.model_reason = "Hind puudub"
        return res
    if eps0 is None or eps0 <= 0:
        res.model_reason = "Kasum (EPS) puudub või on negatiivne – kasumipõhist prognoosi ei saa teha"
        return res
    g, sources = estimate_growth(info, estimates)
    if growth is not None:
        g, sources = growth, {"Käsitsi määratud": growth}
    if g is None:
        res.model_reason = "Kasvuprognoos puudub"
        return res

    res.eps0, res.growth, res.growth_sources = eps0, g, sources
    res.pe_now = price / eps0
    res.exit_pe = exit_pe if exit_pe is not None else exit_multiple(info, res.pe_now)
    years = max(HORIZONS)
    eps = eps0
    for year, (gk, pe) in enumerate(zip(growth_path(g, years), pe_path(res.pe_now, res.exit_pe, years)), start=1):
        eps *= 1 + gk
        if year in HORIZONS:
            # Hind aasta n lõpus = tollane järgmise 12 kuu EPS × tollane P/E
            target = eps * pe
            ann = (target / price) ** (1 / year) - 1 + dy
            res.projections.append(Projection(year, eps, target, ann))
    return res
