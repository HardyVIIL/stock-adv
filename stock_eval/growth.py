"""Kasvupotentsiaal: analüütikute 12 kuu sihthind ja kasumipõhine hinnaprognoos 1–5 aastaks.

Mudel (EPS × P/E):
  * Lähtekasum = järgmise 12 kuu EPS ootus (forwardEps), varuna jooksva aasta / TTM EPS.
  * Kasv = analüütikute EPS- ja käibe kasvuprognooside keskmine (varuna TTM käibe kasv),
    piiratud -10%..30%, ja sulandub 5 aastaga lineaarselt 6%-ni (kiire kasv ei kesta igavesti).
  * P/E liigub 5 aastaga praeguselt (hind / EPS) poole võrra sektori tüüpilise P/E suunas
    (praegune piiratud 6..40; tõus kuni 1,5×) — erandlikult kõrged ja madalad kordajad kipuvad
    normaliseeruma.
  * Oodatav hind aastal n = EPS_n × P/E_n; aastane tootlus lisab dividenditootluse.
"""
from __future__ import annotations

import math
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
    pe: float = 0.0       # P/E sel aastal


@dataclass
class Decomposition:
    """Kust tuleb hinna muutus horisondil (summad aktsia kohta, aktsia valuutas).

    Hind_n / Hind_0 = (EPS_n / EPS_0) × (P/E_n / P/E_0)
    EPS_n / EPS_0   = käive × marginaal / aktsiate arv
    """
    years: int
    price0: float
    price_n: float
    eps_ratio: float
    pe_ratio: float
    rev_ratio: float
    share_ratio: float     # aktsiate arv n aasta pärast / praegu (<1 = tagasiostud)
    margin_ratio: float
    eps_effect: float      # hinnamuutus kasumi kasvust (P/E jäänuks samaks)
    pe_effect: float       # hinnamuutus P/E muutusest
    dividends: float       # kogunenud dividendid (lihtsustatult: hind × tootlus × aastad)
    revenue_part: float    # eps_effect jaotus: käibe kasv
    margin_part: float     #                    marginaali muutus
    buyback_part: float    #                    aktsiate arvu muutus

    @property
    def total_gain(self) -> float:
        return self.price_n - self.price0 + self.dividends


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
    price0: float | None = None
    rev_growth: float | None = None    # käibe kasv 1. aastal (sulandub nagu EPS)
    share_change: float = 0.0          # aktsiate arvu aastane muutus (ajalooline, piiratud ±5%)

    def projection(self, years: int) -> Projection | None:
        return next((p for p in self.projections if p.years == years), None)

    def decompose(self, years: int) -> Decomposition | None:
        p = self.projection(years)
        if not p or not self.price0 or not self.eps0 or not self.pe_now:
            return None
        eps_ratio, pe_ratio = p.eps / self.eps0, p.pe / self.pe_now
        rev_ratio = 1.0
        for g in growth_path(self.rev_growth if self.rev_growth is not None else self.growth, years):
            rev_ratio *= 1 + g
        share_ratio = (1 + self.share_change) ** years
        margin_ratio = eps_ratio * share_ratio / rev_ratio
        eps_effect = self.price0 * (eps_ratio - 1)
        pe_effect = self.price0 * eps_ratio * (pe_ratio - 1)
        # EPS mõju jagatakse komponentide vahel nende logaritmilise osakaalu järgi
        logs = {"rev": _ln(rev_ratio), "margin": _ln(margin_ratio), "buyback": -_ln(share_ratio)}
        tot = sum(logs.values())
        share = {k: (v / tot if tot else 0.0) for k, v in logs.items()}
        return Decomposition(
            years=years, price0=self.price0, price_n=p.price, eps_ratio=eps_ratio, pe_ratio=pe_ratio,
            rev_ratio=rev_ratio, share_ratio=share_ratio, margin_ratio=margin_ratio,
            eps_effect=eps_effect, pe_effect=pe_effect, dividends=self.price0 * self.dividend_yield * years,
            revenue_part=eps_effect * share["rev"], margin_part=eps_effect * share["margin"],
            buyback_part=eps_effect * share["buyback"],
        )

    def required_growth(self, years: int, target_return: float = 0.10) -> float | None:
        """Kasumi (EPS) aastane kasv, mida on vaja `target_return` aastatootluseks, kui P/E käitub mudeli järgi."""
        p = self.projection(years)
        if not p or not self.pe_now:
            return None
        price_growth = 1 + target_return - self.dividend_yield
        if price_growth <= 0:
            return None
        return price_growth * (self.pe_now / p.pe) ** (1 / years) - 1

    def sensitivity(self, years: int, growth_deltas=(-0.05, 0.0, 0.05),
                    pe_factors=(0.75, 1.0, 1.25)) -> dict | None:
        """Oodatav hind, kui kasv ±5 %-p ja lõpp-P/E ±25%."""
        if self.eps0 is None or self.growth is None or self.exit_pe is None or self.pe_now is None:
            return None
        out = {}
        for f in pe_factors:
            row = {}
            for d in growth_deltas:
                eps = self.eps0
                for g in growth_path(self.growth + d, years):
                    eps *= 1 + g
                pe = pe_path(self.pe_now, self.exit_pe * f, years)[-1]
                row[d] = eps * pe
            out[f] = row
        return out

    def model_score(self, years: int) -> float | None:
        p = self.projection(years)
        return linear_score(p.annual_return, -0.05, 0.20) if p else None

    def score(self, years: int) -> float | None:
        parts = [s for s in (self.analyst.score if self.analyst else None, self.model_score(years))
                 if s is not None]
        return sum(parts) / len(parts) if parts else None


def _ln(x: float) -> float:
    return math.log(x) if x and x > 0 else 0.0


def share_change_rate(shares: list[float]) -> float:
    """Aktsiate arvu aastane muutus ajaloost (negatiivne = tagasiostud), piiratud -5%..+5%."""
    s = [x for x in shares if x and x > 0]
    # Aasta-aastased muutused; üle ±30% hüpped on tükelduste jäljed aruannetes, mitte päris muutus
    yoy = [b / a for a, b in zip(s, s[1:]) if 0.7 < b / a < 1.3]
    if not yoy:
        return 0.0
    r = math.prod(yoy) ** (1 / len(yoy)) - 1
    return min(0.05, max(-0.05, r))


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
    # P/E tõus piiratud 1,5-kordseks: väga madal P/E peegeldab sageli riske, mida turg näeb
    return min((min(40.0, max(6.0, pe)) + ref) / 2, pe * 1.5)


def pe_path(pe_now: float, pe_end: float, years: int) -> list[float]:
    """P/E igal aastal: lineaarne liikumine praeguselt lõppväärtuseni FADE_YEARS jooksul."""
    return [pe_now + (pe_end - pe_now) * min(1.0, k / FADE_YEARS) for k in range(1, years + 1)]


def evaluate_growth(info: dict, estimates: dict, price: float | None,
                    growth: float | None = None, exit_pe: float | None = None,
                    statements: dict | None = None) -> GrowthResult:
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
    res.price0 = price
    rg = estimates.get("rev_growth_1y", _f(info.get("revenueGrowth")))
    res.rev_growth = min(0.40, max(-0.20, rg)) if rg is not None else None
    res.share_change = share_change_rate((statements or {}).get("shares", []))
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
            res.projections.append(Projection(year, eps, target, ann, pe))
    return res
