"""Monte Carlo simulatsioon: kas positsioon jõuab N aastaga indeksile järele (või püsib ees)?

Mudel (ühefaktoriline, logaritmilised tootlused, horisondi lõppväärtus otse):
  indeks:  X_i = T·ln(1 + r_i)  + σ_i·√T·Z_m
  aktsia:  X_s = T·ln(1 + base) + σ_eff·√T·(ρ·Z_m + √(1−ρ²)·ε)
  σ_eff   = max(σ_pikk, s_mudel·√T),  σ_pikk = ½·σ_ajalooline + ½·35%
           (viimase 3 a kõikumine ei püsi tavaliselt 5 a; äärmused tõmmatakse keskmise poole)
           s_mudel = bear/bull aastatootluste vahe (15./85. protsentiil). Ajalooline kõikumine ja
           kasvuprognoosi ebakindlus kirjeldavad suuresti sama asja (hind kõigub, sest tulevik on
           ebakindel), seega võetakse suurem, mitte summa.
  Z_m, ε ~ Normal(0, 1);  Z_m on kõigile aktsiatele ühine (turg), ε iga aktsia oma.

σ_s, σ_i ja ρ arvutatakse viimase 3 aasta nädalatootlustest (nädal vähendab Euroopa/USA kauplemisaegade
nihke mõju). Kõik tootlused on mediaanid (geomeetrilised): 50% radadest on üle base-stsenaariumi.
Valuutakursside edasist muutust ei simuleerita.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

Z85 = 1.0364  # standardnormaaljaotuse 85. protsentiil
DEFAULT_SIGMA, DEFAULT_RHO = 0.40, 0.6
LONG_RUN_SIGMA, SHRINK = 0.35, 0.5  # ajalooline volatiilsus tõmmatakse poole võrra pikaajalise taseme poole


@dataclass
class MarketStats:
    sigma: float          # aastane volatiilsus
    rho: float            # korrelatsioon indeksiga
    weeks: int            # mitme nädala andmetest
    estimated: bool = True

    def tracking_error(self, sigma_i: float) -> float:
        return math.sqrt(max(self.sigma ** 2 + sigma_i ** 2 - 2 * self.rho * self.sigma * sigma_i, 0.0))


def market_stats(closes: pd.DataFrame, tickers: list[str], bench: str, years: int = 3,
                 min_weeks: int = 52) -> tuple[dict[str, MarketStats], float]:
    """Volatiilsus ja korrelatsioon indeksiga nädalatootlustest. Tagastab (aktsiate statistika, σ_indeks)."""
    start = closes.index[-1] - pd.DateOffset(years=years)
    wk = closes[closes.index >= start].resample("W-FRI").last()
    rets = np.log(wk / wk.shift(1)).iloc[1:]
    b = rets[bench].dropna()
    sigma_i = float(b.std() * math.sqrt(52))
    out = {}
    for t in tickers:
        if t not in rets.columns:
            out[t] = MarketStats(DEFAULT_SIGMA, DEFAULT_RHO, 0, estimated=False)
            continue
        pair = pd.concat([rets[t], b], axis=1).dropna()
        if len(pair) < min_weeks:
            out[t] = MarketStats(DEFAULT_SIGMA, DEFAULT_RHO, len(pair), estimated=False)
            continue
        out[t] = MarketStats(float(pair.iloc[:, 0].std() * math.sqrt(52)),
                             float(pair.iloc[:, 0].corr(pair.iloc[:, 1])), len(pair))
    return out, sigma_i


def model_drift(bear: float | None, base: float | None, bull: float | None,
                fallback: float) -> tuple[float, float, bool]:
    """(μ, s_mudel, kas prognoos olemas). Prognoosita eeldame indeksiga sama mediaantootlust."""
    if base is None or base <= -1:
        return math.log(1 + fallback), 0.0, False
    mu = math.log(1 + base)
    if bear is None or bull is None or bear <= -1 or bull <= -1:
        return mu, 0.0, True
    return mu, max((math.log(1 + bull) - math.log(1 + bear)) / (2 * Z85), 0.0), True


def long_run_sigma(sigma_hist: float) -> float:
    return (1 - SHRINK) * sigma_hist + SHRINK * LONG_RUN_SIGMA


def effective_sigma(sigma_hist: float, s_model: float, years: int) -> float:
    """Aastane kõikumine simulatsioonis: suurem pikaajalisest volatiilsusest ja kasvuprognoosi ebakindlusest."""
    return max(long_run_sigma(sigma_hist), s_model * math.sqrt(years))


@dataclass
class SimResult:
    tickers: list[str]
    gaps: np.ndarray        # (n_sim, n_pos): positsiooni väärtus − indeksi väärtus horisondi lõpus, €
    years: int

    def prob_ahead(self) -> np.ndarray:
        return (self.gaps >= 0).mean(axis=0)

    def percentiles(self, q=(10, 50, 90)) -> np.ndarray:
        return np.percentile(self.gaps, q, axis=0)

    @property
    def total(self) -> np.ndarray:
        return self.gaps.sum(axis=1)


def simulate(positions: list[dict], sigma_i: float, index_return: float, years: int,
             n: int = 10_000, seed: int = 42) -> SimResult:
    """positions: dict(ticker, value, index_value, bear, base, bull, stats: MarketStats)."""
    rng = np.random.default_rng(seed)
    k = len(positions)
    z_m = rng.standard_normal(n)                  # ühine turuliikumine
    eps = rng.standard_normal((n, k))             # iga aktsia oma liikumine
    T = years
    x_i = T * math.log(1 + index_return) + sigma_i * math.sqrt(T) * z_m
    gaps = np.empty((n, k))
    for j, p in enumerate(positions):
        st = p["stats"]
        mu, s_mod, _ = model_drift(p.get("bear"), p.get("base"), p.get("bull"), index_return)
        rho = max(-0.99, min(0.99, st.rho))
        z_s = rho * z_m + math.sqrt(1 - rho ** 2) * eps[:, j]
        x_s = T * mu + effective_sigma(st.sigma, s_mod, T) * math.sqrt(T) * z_s
        gaps[:, j] = p["value"] * np.exp(x_s) - p["index_value"] * np.exp(x_i)
    return SimResult([p["ticker"] for p in positions], gaps, years)
