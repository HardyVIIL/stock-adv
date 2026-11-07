"""Andmete laadimine Yahoo Finance'ist (yfinance)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

INFO_KEYS = [
    "longName", "shortName", "sector", "industry", "currency", "marketCap",
    "currentPrice", "regularMarketPrice", "previousClose",
    "trailingPE", "forwardPE", "pegRatio", "trailingPegRatio", "priceToBook",
    "enterpriseToEbitda", "returnOnEquity", "returnOnAssets", "profitMargins",
    "operatingMargins", "grossMargins", "revenueGrowth", "earningsGrowth",
    "debtToEquity", "currentRatio", "freeCashflow", "sharesOutstanding",
    "totalCash", "totalDebt", "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
]


@dataclass
class Snapshot:
    ticker: str
    info: dict
    fcf_history: list[float] = field(default_factory=list)  # aastane FCF, vanim -> uusim
    prices: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def name(self) -> str:
        return self.info.get("longName") or self.info.get("shortName") or self.ticker

    @property
    def price(self) -> float | None:
        p = self.info.get("currentPrice") or self.info.get("regularMarketPrice")
        if p is None and not self.prices.empty:
            p = float(self.prices["Close"].iloc[-1])
        return p


def _fcf_history(t: yf.Ticker) -> list[float]:
    try:
        cf = t.cashflow
    except Exception:
        return []
    if cf is None or cf.empty or "Free Cash Flow" not in cf.index:
        return []
    row = cf.loc["Free Cash Flow"].dropna()
    row = row.sort_index()  # veerud on kuupäevad
    return [float(v) for v in row.values]


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
    return Snapshot(ticker=ticker, info=info, fcf_history=_fcf_history(t), prices=prices)
