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


def apply_splits(lots: pd.DataFrame, splits: dict[str, list[tuple[pd.Timestamp, float]]],
                 handled_window_days: int = 45) -> tuple[pd.DataFrame, list[str]]:
    """Korrigeerib aktsiate tükeldused, mida failis pole märgitud.

    Kui pärast tükeldust (−5…+45 päeva) on samal tickeril 0-hinnaga rida, eeldame, et kasutaja on
    tükelduse ise lisanud (Yahoo tavapärane viis) ja jätame selle puutumata. Muidu korrutatakse
    tükeldusele eelnevate ostude kogus suhtega ja ostuhind jagatakse sellega.
    """
    lots = lots.copy()
    notes = []
    for t, events in splits.items():
        mine = lots["Ticker"] == t
        for when, ratio in events:
            if not ratio or ratio == 1:
                continue
            when = pd.Timestamp(when).tz_localize(None) if pd.Timestamp(when).tzinfo else pd.Timestamp(when)
            zero = mine & (lots["Ostuhind"] == 0) & lots["Kuupäev"].between(
                when - pd.Timedelta(days=5), when + pd.Timedelta(days=handled_window_days))
            before = mine & (lots["Kuupäev"] < when) & (lots["Kogus"] > 0)
            if zero.any() or not before.any():
                continue
            lots.loc[before, "Kogus"] *= ratio
            lots.loc[before, "Ostuhind"] /= ratio
            notes.append(f"{t}: tükeldus {ratio:g}:1 ({when.date()}) polnud failis märgitud – "
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
