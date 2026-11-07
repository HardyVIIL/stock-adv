"""Andmete laadimine Yahoo Finance'ist (yfinance)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

INFO_KEYS = [
    "longName", "shortName", "sector", "industry", "currency", "marketCap",
    "currentPrice", "regularMarketPrice", "previousClose",
    "trailingPE", "forwardPE", "pegRatio", "trailingPegRatio", "priceToBook",
    "enterpriseToEbitda", "enterpriseToRevenue", "returnOnEquity", "returnOnAssets", "profitMargins",
    "operatingMargins", "grossMargins", "revenueGrowth", "earningsGrowth",
    "debtToEquity", "currentRatio", "freeCashflow", "sharesOutstanding",
    "totalCash", "totalDebt", "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    # analüütikute ootused
    "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice",
    "numberOfAnalystOpinions", "recommendationMean", "recommendationKey",
    "trailingEps", "forwardEps", "epsCurrentYear", "dividendYield", "payoutRatio",
]


def _estimates(t: yf.Ticker) -> dict:
    """Analüütikute kasvuprognoosid: EPS ja käibe kasv järgmisel aastal, pikaajaline kasv (LTG)."""
    out = {}

    def cell(df, row, col):
        try:
            v = df.loc[row, col]
            return float(v) if v == v else None
        except Exception:
            return None

    try:
        g = t.growth_estimates
        if g is not None and not g.empty:
            out["eps_growth_0y"] = cell(g, "0y", "stockTrend")
            out["eps_growth_1y"] = cell(g, "+1y", "stockTrend")
            out["ltg"] = cell(g, "LTG", "stockTrend")
    except Exception:
        pass
    try:
        r = t.revenue_estimate
        if r is not None and not r.empty:
            out["rev_growth_0y"] = cell(r, "0y", "growth")
            out["rev_growth_1y"] = cell(r, "+1y", "growth")
    except Exception:
        pass
    return {k: v for k, v in out.items() if v is not None}


@dataclass
class Snapshot:
    ticker: str
    info: dict
    fcf_history: list[float] = field(default_factory=list)  # aastane FCF, vanim -> uusim
    prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    estimates: dict = field(default_factory=dict)  # analüütikute kasvuprognoosid
    statements: dict = field(default_factory=dict)  # aastased aruanderead (vt _statements)
    splits: list = field(default_factory=list)  # [(kuupäev, suhe)], nt 5.0 = 5:1 tükeldus

    @property
    def name(self) -> str:
        return self.info.get("longName") or self.info.get("shortName") or self.ticker

    @property
    def price(self) -> float | None:
        p = self.info.get("currentPrice") or self.info.get("regularMarketPrice")
        if p is None and not self.prices.empty:
            p = float(self.prices["Close"].iloc[-1])
        return p


def _row(df: pd.DataFrame | None, name: str) -> list[float]:
    if df is None or df.empty or name not in df.index:
        return []
    return [float(v) for v in df.loc[name].dropna().sort_index().values]


def _statements(t: yf.Ticker) -> dict[str, list[float]]:
    """Aastased read aruannetest (vanim -> uusim): käive, brutokasum, SBC, FCF, laovarud."""
    out: dict[str, list[float]] = {}
    for attr, rows in (("income_stmt", {"revenue": "Total Revenue", "gross_profit": "Gross Profit"}),
                       ("cashflow", {"sbc": "Stock Based Compensation", "fcf": "Free Cash Flow"}),
                       ("balance_sheet", {"inventory": "Inventory"})):
        try:
            df = getattr(t, attr)
        except Exception:
            df = None
        for key, name in rows.items():
            out[key] = _row(df, name)
    return out


def fetch_snapshot(ticker: str, period: str = "2y") -> Snapshot:
    """Laeb ühe tickeri põhinäitajad, FCF ajaloo ja hinnaajaloo.

    Tõstab ValueError, kui tickerit ei leita.
    """
    ticker = ticker.strip().upper()
    t = yf.Ticker(ticker)
    prices = t.history(period=period, auto_adjust=True)
    try:
        raw = t.info or {}
    except Exception:
        raw = {}
    if prices.empty and not raw.get("regularMarketPrice"):
        raise ValueError(f"Tickerit '{ticker}' ei leitud või andmed puuduvad")
    info = {k: raw.get(k) for k in INFO_KEYS}
    statements = _statements(t)
    try:
        sp = t.splits
        splits = [(pd.Timestamp(d).tz_localize(None), float(r)) for d, r in sp.items()] if sp is not None else []
    except Exception:
        splits = []
    return Snapshot(ticker=ticker, info=info, fcf_history=statements.get("fcf", []), prices=prices,
                    estimates=_estimates(t), statements=statements,
                    splits=splits)
