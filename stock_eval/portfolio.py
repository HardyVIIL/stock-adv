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


def read_lots(source) -> pd.DataFrame:
    """Loeb Yahoo ekspordi read: Ticker, Kuupäev, Kogus, Ostuhind, Komisjon (iga ost eraldi).

    Jälgimisnimekirja read jäävad sisse koguse 0-ga; puuduv kuupäev/hind on NaT/NaN.
    """
    df = pd.read_csv(source)
    df.columns = [c.strip() for c in df.columns]
    if "Symbol" not in df.columns:
        raise ValueError("Failis puudub veerg 'Symbol' – kas see on Yahoo Finance portfelli eksport?")
    df["Symbol"] = df["Symbol"].astype(str).str.strip().str.upper()
    df = df[df["Symbol"].ne("") & df["Symbol"].ne("NAN")]
    nan = pd.Series(float("nan"), index=df.index)
    dates = _num(df["Trade Date"]) if "Trade Date" in df.columns else nan
    return pd.DataFrame({
        "Ticker": df["Symbol"],
        "Kuupäev": pd.to_datetime(dates.astype("Int64").astype(str), format="%Y%m%d", errors="coerce"),
        "Kogus": (_num(df["Quantity"]) if "Quantity" in df.columns else nan).fillna(0),
        "Ostuhind": _num(df["Purchase Price"]) if "Purchase Price" in df.columns else nan,
        "Komisjon": (_num(df["Commission"]) if "Commission" in df.columns else nan).fillna(0),
    }).reset_index(drop=True)


def _naive_day(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return (ts.tz_localize(None) if ts.tzinfo else ts).normalize()


def apply_splits(lots: pd.DataFrame, splits: dict[str, list[tuple[pd.Timestamp, float]]],
                 price_at=None, handled_window_days: int = 45) -> tuple[pd.DataFrame, list[str]]:
    """Korrigeerib aktsiate tükeldused, mida failis pole märgitud.

    Iga tükeldusele eelnev ost (ostupäev < tükelduse päev) vaadatakse eraldi:
      1. Kui `price_at(ticker, kuupäev)` annab tolle päeva tükeldustega korrigeeritud turuhinna, siis
         võrreldakse sellega ostuhinda: kui ostuhind on lähemal korrigeeritud hinnale, on rida juba
         korrigeeritud (kasutaja on kogused ise ümber arvutanud) ja jääb puutumata; kui lähemal
         korrigeerimata hinnale (× tükelduse suhe), korrigeeritakse.
      2. Kui turuhinda pole (või ostuhind on 0): kui tükelduse järel (−5…+45 päeva) on 0-hinnaga rida,
         loetakse tükeldus failis märgituks; muidu korrigeeritakse.
    """
    import math

    lots = lots.copy()
    notes = []
    for t, events in splits.items():
        events = [(_naive_day(w), r) for w, r in events if r and r != 1]
        if not events:
            continue
        mine = lots["Ticker"] == t
        adjusted_rows = 0
        for idx in lots.index[mine & (lots["Kogus"] > 0) & lots["Kuupäev"].notna()]:
            day = _naive_day(lots.at[idx, "Kuupäev"])
            later = [(w, r) for w, r in events if day < w]
            if not later:
                continue
            # 1) Tükeldus märgitud eraldi 0-hinnaga reaga (Yahoo tavapärane viis) -> ära puutu
            recorded = [(w, r) for w, r in later if (mine & (lots["Ostuhind"] == 0) & lots["Kuupäev"].between(
                w - pd.Timedelta(days=5), w + pd.Timedelta(days=handled_window_days))).any()]
            later = [x for x in later if x not in recorded]
            if not later:
                continue
            cum = math.prod(r for _, r in later)
            paid = lots.at[idx, "Ostuhind"]
            # 2) Ostuhind juba ümber arvutatud? Võrdle tolle päeva korrigeeritud turuhinnaga
            market = price_at(t, day) if price_at is not None and paid and paid > 0 else None
            if market:
                rec_cum = math.prod(r for _, r in recorded)  # turuhind on korrigeeritud ka märgitud tükeldusteks
                m = market * rec_cum
                if abs(math.log(paid / m)) <= abs(math.log(paid / (m * cum))):
                    continue
            lots.at[idx, "Kogus"] *= cum
            lots.at[idx, "Ostuhind"] /= cum
            adjusted_rows += 1
        if adjusted_rows:
            ratios = ", ".join(f"{r:g}:1 ({w.date()})" for w, r in events)
            notes.append(f"{t}: tükeldus {ratios} polnud {adjusted_rows} ostureal arvestatud – "
                         f"kogused korrigeeritud automaatselt")
    return lots, notes


def aggregate_lots(lots: pd.DataFrame) -> pd.DataFrame:
    """Koondab ostud tickeri kaupa: Ticker, Kogus, Keskmine ostuhind, Investeeritud."""
    qty, price = lots["Kogus"], lots["Ostuhind"]
    tmp = pd.DataFrame({
        "Ticker": lots["Ticker"],
        "Kogus": qty,
        "cost": (qty * price).fillna(0) + lots["Komisjon"],
        "priced_qty": qty.where(price.notna()).fillna(0),
    })
    agg = tmp.groupby("Ticker", sort=False).sum()
    agg["Keskmine ostuhind"] = (agg["cost"] / agg["priced_qty"]).where(agg["priced_qty"] > 0)
    agg["Investeeritud"] = agg["cost"].where(agg["priced_qty"] > 0)
    return agg.reset_index()[COLUMNS]


def parse_yahoo_csv(source) -> pd.DataFrame:
    """Loeb Yahoo ekspordi ja koondab ostud tickeri kaupa (ilma tükelduste korrigeerimiseta)."""
    return aggregate_lots(read_lots(source))


def fx_symbol(currency: str, base: str) -> str:
    """Yahoo valuutapaari tähis, nt SEK -> EUR: 'SEKEUR=X'."""
    return f"{currency}{base}=X"


def normalize_currency(currency: str | None) -> tuple[str | None, float]:
    """Yahoo noteerib osa börse alamühikus (GBp = penn, ZAc = sent). Tagastab (valuuta, kordaja)."""
    if currency in ("GBp", "GBX"):
        return "GBP", 0.01
    if currency in ("ZAc", "ILA"):
        return {"ZAc": "ZAR", "ILA": "ILS"}[currency], 0.01
    return currency, 1.0


def holdings_table(portfolio: pd.DataFrame, prices: dict[str, float | None],
                   scores: dict[str, float | None], currencies: dict[str, str | None] | None = None,
                   fx: dict[str, float] | None = None, base: str = "EUR") -> pd.DataFrame:
    """Lisab portfellile turuväärtuse, kasumi/kahjumi, osakaalu ja koondskoori.

    `currencies`: ticker -> noteerimisvaluuta; `fx`: valuuta -> kurss baasvaluutasse.
    Osakaal ja kaalutud skoor arvutatakse baasvaluutas, et eri valuutas positsioonid oleks võrreldavad.
    """
    currencies = currencies or {}
    fx = fx or {}
    df = portfolio[portfolio["Kogus"] > 0].copy()
    df["Valuuta"] = df["Ticker"].map(lambda t: currencies.get(t) or "")
    df["Hind"] = df["Ticker"].map(prices)
    df["Turuväärtus"] = df["Kogus"] * df["Hind"]
    df["Kasum/kahjum"] = df["Turuväärtus"] - df["Investeeritud"]
    df["Tootlus"] = df["Kasum/kahjum"] / df["Investeeritud"]

    def to_base(row) -> float | None:
        cur, mult = normalize_currency(row["Valuuta"] or base)
        rate = 1.0 if cur == base else fx.get(cur)
        return None if rate is None or pd.isna(row["Turuväärtus"]) else row["Turuväärtus"] * mult * rate

    col = f"Väärtus ({base})"
    df[col] = df.apply(to_base, axis=1).astype(float)
    total = df[col].sum()
    df["Osakaal"] = df[col] / total if total else None
    df["Koondskoor"] = df["Ticker"].map(scores)
    return df.sort_values(col, ascending=False, na_position="last")


def weighted_score(holdings: pd.DataFrame) -> float | None:
    """Portfelli koondskoor, kaalutud osakaaluga (baasvaluutas)."""
    h = holdings.dropna(subset=["Koondskoor", "Osakaal"])
    w = h["Osakaal"].sum()
    return float((h["Koondskoor"] * h["Osakaal"]).sum() / w) if w else None
