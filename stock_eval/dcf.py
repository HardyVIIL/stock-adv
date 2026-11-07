"""Kaheetapiline diskonteeritud rahavoogude (DCF) mudel."""
from __future__ import annotations

from dataclasses import dataclass, field

from .fundamentals import linear_score

RISK_FREE = 0.045
EQUITY_RISK_PREMIUM = 0.055


@dataclass
class DCFAssumptions:
    growth: float                 # 1. etapi aastane FCF kasv
    discount_rate: float          # WACC / nõutav tootlus
    terminal_growth: float = 0.025
    years: int = 10               # prognoosiperiood; teises pooles kasv sulandub terminaalsesse


@dataclass
class DCFResult:
    assumptions: DCFAssumptions
    base_fcf: float
    projected_fcf: list[float] = field(default_factory=list)
    pv_fcf: float = 0.0
    pv_terminal: float = 0.0
    enterprise_value: float = 0.0
    equity_value: float = 0.0
    intrinsic_per_share: float = 0.0
    price: float | None = None

    @property
    def margin_of_safety(self) -> float | None:
        """(sisemine väärtus - hind) / sisemine väärtus. Positiivne = alahinnatud."""
        if self.price is None or self.intrinsic_per_share <= 0:
            return None
        return (self.intrinsic_per_share - self.price) / self.intrinsic_per_share

    @property
    def score(self) -> float | None:
        if self.intrinsic_per_share <= 0:
            return 0.0  # võlg ületab rahavoogude väärtuse
        mos = self.margin_of_safety
        # -50% (üle hinnatud) -> 0, +40% (alahinnatud) -> 100
        return linear_score(mos, -0.5, 0.4) if mos is not None else None


def estimate_discount_rate(beta: float | None) -> float:
    """CAPM: rf + beta * ERP, piiratud vahemikku 7%..14%."""
    b = beta if beta is not None and beta == beta else 1.0
    return min(0.14, max(0.07, RISK_FREE + b * EQUITY_RISK_PREMIUM))


def estimate_growth(fcf_history: list[float], info: dict) -> float:
    """Käibe kasv (a/a); kui puudub, siis ajaloolise FCF CAGR. Piiratud vahemikku -5%..20%.

    Käive on stabiilsem kasvu mõõdik kui FCF, mida moonutavad ühekordsed maksed ja capex-tsüklid.
    """
    rg = info.get("revenueGrowth")
    if rg is not None and rg == rg:
        g = float(rg)
    else:
        hist = [f for f in fcf_history if f is not None]
        if len(hist) >= 3 and hist[0] > 0 and hist[-1] > 0:
            g = (hist[-1] / hist[0]) ** (1 / (len(hist) - 1)) - 1
        else:
            g = 0.05
    return min(0.20, max(-0.05, g))


def base_fcf(fcf_history: list[float], info: dict) -> float | None:
    """Viimase majandusaasta FCF rahavoogude aruandest (OCF - capex).

    Yahoo `info.freeCashflow` on "levered FCF" ja kõigub ebausaldusväärselt
    (nt MSFT 3 mld vs aruandes 67 mld), seega kasutame seda vaid varuvariandina.
    """
    hist = [f for f in fcf_history if f is not None and f == f]
    if hist:
        return hist[-1]
    ttm = info.get("freeCashflow")
    return float(ttm) if ttm is not None and ttm == ttm else None


def run_dcf(fcf0: float, shares: float, cash: float, debt: float,
            a: DCFAssumptions, price: float | None = None) -> DCFResult:
    if a.discount_rate <= a.terminal_growth:
        raise ValueError("Diskontomäär peab olema suurem kui terminaalne kasv")
    half = a.years // 2
    fcf = fcf0
    projected, pv = [], 0.0
    for year in range(1, a.years + 1):
        if year <= half:
            g = a.growth
        else:  # lineaarne sulandumine terminaalsesse kasvu
            step = (year - half) / (a.years - half)
            g = a.growth + (a.terminal_growth - a.growth) * step
        fcf *= 1 + g
        projected.append(fcf)
        pv += fcf / (1 + a.discount_rate) ** year
    terminal = projected[-1] * (1 + a.terminal_growth) / (a.discount_rate - a.terminal_growth)
    pv_terminal = terminal / (1 + a.discount_rate) ** a.years
    ev = pv + pv_terminal
    equity = ev + (cash or 0) - (debt or 0)
    return DCFResult(
        assumptions=a, base_fcf=fcf0, projected_fcf=projected, pv_fcf=pv,
        pv_terminal=pv_terminal, enterprise_value=ev, equity_value=equity,
        intrinsic_per_share=equity / shares, price=price,
    )


def evaluate_dcf(info: dict, fcf_history: list[float], price: float | None,
                 growth: float | None = None, discount_rate: float | None = None,
                 terminal_growth: float = 0.025, years: int = 10) -> tuple[DCFResult | None, str | None]:
    """Tagastab (tulemus, põhjus_miks_puudub)."""
    if info.get("sector") == "Financial Services":
        return None, "FCF-põhine DCF ei sobi pankadele/finantsettevõtetele (vt P/B ja ROE)"
    fcf0 = base_fcf(fcf_history, info)
    shares = info.get("sharesOutstanding")
    if fcf0 is None:
        return None, "FCF andmed puuduvad"
    if fcf0 <= 0:
        return None, "Negatiivne vaba rahavoog – DCF pole rakendatav"
    if not shares:
        return None, "Aktsiate arv puudub"
    a = DCFAssumptions(
        growth=growth if growth is not None else estimate_growth(fcf_history, info),
        discount_rate=discount_rate if discount_rate is not None else estimate_discount_rate(info.get("beta")),
        terminal_growth=terminal_growth,
        years=years,
    )
    try:
        return run_dcf(fcf0, shares, info.get("totalCash") or 0, info.get("totalDebt") or 0, a, price), None
    except ValueError as e:
        return None, str(e)
