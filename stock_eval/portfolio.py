"""Yahoo Finance portfelli CSV ekspordi lugemine.

Yahoo Finance: My Portfolio -> vali portfell -> "Export" annab faili `quotes.csv`, kus on veerud
Symbol, Current Price, ..., Trade Date, Purchase Price, Quantity, Commission, ...
Igal ostul (lot) on eraldi rida; jälgimisnimekirja rea puhul on Quantity tühi.
"""
from __future__ import annotations

import pandas as pd

COLUMNS = ["Ticker", "Kogus", "Keskmine ostuhind", "Investeeritud"]


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def parse_yahoo_csv(source) -> pd.DataFrame:
    """Loeb Yahoo ekspordi (failitee või failiobjekt) ja koondab ostud tickeri kaupa.

    Tagastab DataFrame'i veergudega Ticker, Kogus, Keskmine ostuhind, Investeeritud.
    Tickerid ilma koguseta (jälgimisnimekiri) jäävad sisse koguse 0-ga.
    """
    df = pd.read_csv(source)
    df.columns = [c.strip() for c in df.columns]
    if "Symbol" not in df.columns:
        raise ValueError("Failis puudub veerg 'Symbol' – kas see on Yahoo Finance portfelli eksport?")
    df["Symbol"] = df["Symbol"].astype(str).str.strip().str.upper()
    df = df[df["Symbol"].ne("") & df["Symbol"].ne("NAN")]
    qty = _num(df["Quantity"]) if "Quantity" in df.columns else pd.Series(0.0, index=df.index)
    price = _num(df["Purchase Price"]) if "Purchase Price" in df.columns else pd.Series(float("nan"), index=df.index)
    comm = _num(df["Commission"]).fillna(0) if "Commission" in df.columns else 0.0
    lots = pd.DataFrame({
        "Ticker": df["Symbol"],
        "Kogus": qty.fillna(0),
        "cost": (qty * price).fillna(0) + comm,
        "priced_qty": qty.where(price.notna()).fillna(0),
    })
    agg = lots.groupby("Ticker", sort=False).sum()
    agg["Keskmine ostuhind"] = (agg["cost"] / agg["priced_qty"]).where(agg["priced_qty"] > 0)
    agg["Investeeritud"] = agg["cost"].where(agg["priced_qty"] > 0)
    return agg.reset_index()[COLUMNS]


def holdings_table(portfolio: pd.DataFrame, prices: dict[str, float | None],
                   scores: dict[str, float | None]) -> pd.DataFrame:
    """Lisab portfellile turuväärtuse, kasumi/kahjumi, osakaalu ja koondskoori."""
    df = portfolio[portfolio["Kogus"] > 0].copy()
    df["Hind"] = df["Ticker"].map(prices)
    df["Turuväärtus"] = df["Kogus"] * df["Hind"]
    df["Kasum/kahjum"] = df["Turuväärtus"] - df["Investeeritud"]
    df["Tootlus"] = df["Kasum/kahjum"] / df["Investeeritud"]
    total = df["Turuväärtus"].sum()
    df["Osakaal"] = df["Turuväärtus"] / total if total else None
    df["Koondskoor"] = df["Ticker"].map(scores)
    return df.sort_values("Turuväärtus", ascending=False)


def weighted_score(holdings: pd.DataFrame) -> float | None:
    """Portfelli koondskoor, kaalutud turuväärtusega."""
    h = holdings.dropna(subset=["Koondskoor", "Turuväärtus"])
    w = h["Turuväärtus"].sum()
    return float((h["Koondskoor"] * h["Turuväärtus"]).sum() / w) if w else None
