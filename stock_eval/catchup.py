"""Järelejõudmine indeksile: kas indeksist maha jäänud positsioon jõuab N aastaga järele?

Iga positsiooni kohta (eurodes, ostupõhisest võrdlusest):
  V = praegune väärtus, I = väärtus, kui sama raha oleks samadel päevadel pandud indeksisse.
Kui indeks kasvab edaspidi r_i aastas, siis järelejõudmiseks peab aktsia tootma
  r_vaja = (I / V)^(1/N) × (1 + r_i) − 1   aastas.
Seda võrreldakse aktsia bear/base/bull stsenaariumide aastatootlusega (koos dividendiga).

Tõenäosus on ligikaudne: stsenaariumid loetakse jaotuse 15. / 50. / 85. protsentiiliks ja nende vahel
interpoleeritakse lineaarselt (väljaspool piiratud 5…95%). See on mudeli eelduste peegeldus, mitte statistika.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

PCTL = (0.15, 0.50, 0.85)  # bear, base, bull
TAIL = (0.05, 0.95)         # jaotuse äärmused (stsenaariumide vahe võrra väljaspool bear/bull)


def scenario_cdf(x: float, bear: float, base: float, bull: float) -> float:
    """Tükiti lineaarne jaotusfunktsioon läbi punktide (bear,15%), (base,50%), (bull,85%).

    Sabad: bear-ist allapoole langeb 15% → 5% sama vahemaa jooksul kui bear…base; bull-ist ülespoole
    tõuseb 85% → 95% sama vahemaa jooksul kui base…bull; edasi konstant.
    """
    bear, base, bull = sorted((bear, base, bull))
    lo, hi = bear - max(base - bear, 1e-9), bull + max(bull - base, 1e-9)
    xs = (lo, bear, base, bull, hi)
    ps = (TAIL[0], *PCTL, TAIL[1])
    if x <= xs[0]:
        return ps[0]
    if x >= xs[-1]:
        return ps[-1]
    for x0, x1, p0, p1 in zip(xs, xs[1:], ps, ps[1:]):
        if x0 <= x <= x1:
            return p0 + (p1 - p0) * (x - x0) / (x1 - x0) if x1 > x0 else p1
    return 0.5


@dataclass
class CatchUp:
    value: float
    index_value: float
    index_return: float
    years: int
    bear: float | None
    base: float | None
    bull: float | None

    @property
    def gap(self) -> float:
        return self.value - self.index_value

    @property
    def behind(self) -> bool:
        return self.gap < 0

    @property
    def required_return(self) -> float | None:
        """Aastatootlus, millega positsioon on N aasta pärast indeksiga võrdne."""
        if self.value <= 0 or self.index_value <= 0:
            return None
        return (self.index_value / self.value) ** (1 / self.years) * (1 + self.index_return) - 1

    @property
    def probability(self) -> float | None:
        """Ligikaudne tõenäosus, et positsioon on N aasta pärast indeksiga vähemalt võrdne."""
        req = self.required_return
        if req is None or None in (self.bear, self.base, self.bull):
            return None
        return 1 - scenario_cdf(req, self.bear, self.base, self.bull)

    def gap_after(self, annual: float | None) -> float | None:
        if annual is None:
            return None
        return self.value * (1 + annual) ** self.years - self.index_value * (1 + self.index_return) ** self.years

    @property
    def years_to_catch_up(self) -> float | None:
        """Mitu aastat base-stsenaariumi tempoga kulub järelejõudmiseks (None = ei jõua / pole maas)."""
        if not self.behind or self.base is None or self.base <= self.index_return:
            return None
        return math.log(self.index_value / self.value) / math.log((1 + self.base) / (1 + self.index_return))

    @property
    def verdict(self) -> str:
        return verdict_for(self.probability, self.behind)


def verdict_for(p: float | None, behind: bool) -> str:
    """Hinnang tõenäosuse järgi, et positsioon on horisondi lõpus indeksiga vähemalt võrdne."""
    if p is None:
        return "— (prognoos puudub)"
    if behind:
        if p >= 0.6:
            return "🟢 Tõenäoliselt jõuab järele"
        if p >= 0.35:
            return "🟡 Võib järele jõuda"
        return "🔴 Ebatõenäoline"
    if p >= 0.6:
        return "🟢 Tõenäoliselt püsib ees"
    if p >= 0.35:
        return "🟡 Võib edumaa kaotada"
    return "🔴 Tõenäoliselt jääb alla"
