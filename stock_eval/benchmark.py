"""Võrdlus indeksiga: kas aktsiavalik on toonud rohkem kui sama raha indeksifondis?

1. Ostupõhine võrdlus: iga ost (Yahoo ekspordi rida) võrreldakse sellega, kui sama summa oleks
   samal päeval pandud indeksisse. Kõik summad eurodes (ostupäeva ja tänase kursiga), nii et
   valuutakursi mõju on mõlemal poolel arvestatud.
2. Praeguse koosseisu ajalugu: kuidas oleks praegune portfell (praeguste osakaaludega)
   viimase 1/3/5 aasta jooksul indeksiga võrreldes käitunud.

Hinnad on hinnatootlused (split'idega korrigeeritud, dividendideta) nii aktsiatel kui indeksil.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from .portfolio import normalize_currency

BENCHMARKS = {
    "QQQ": "Nasdaq-100 (QQQ)",
    "XLK": "S&P 500 tehnoloogia (XLK)",
    "SMH": "Kiibid (SMH)",
    "SPY": "S&P 500 (SPY)",
    "URTH": "MSCI World (URTH)",
}
BASE = "EUR"


def dated_lots(lots: pd.DataFrame) -> pd.DataFrame:
    """Ainult päris ostud (kogus > 0 ja kuupäev olemas)."""
    out = lots[(lots["Kogus"] > 0) & lots["Kuupäev"].notna()].copy()
    out["Ostuhind"] = out["Ostuhind"].fillna(0)
    return out.reset_index(drop=True)


def is_split_lot(lot, splits: list[tuple[pd.Timestamp, float]], window_days: int = 45) -> bool:
    """0-hinnaga rida, mis on tükelduse kirje (−5…+45 päeva pärast tükeldust)."""
    for when, _ in splits:
        when = pd.Timestamp(when)
        when = when.tz_localize(None) if when.tzinfo else when
        if when - pd.Timedelta(days=5) <= lot.Kuupäev <= when + pd.Timedelta(days=window_days):
            return True
    return False


def download_closes(tickers: list[str], start: str) -> pd.DataFrame:
    """Päevased sulgemishinnad (split'idega korrigeeritud, dividendideta), veerg tickeri kohta."""
    data = yf.download(sorted(set(tickers)), start=start, auto_adjust=False, progress=False,
                       group_by="column", threads=True)
    if data is None or data.empty:
        return pd.DataFrame()
    closes = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data[["Close"]].rename(
        columns={"Close": tickers[0]})
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    return closes.ffill()


def fx_symbols(currencies: set[str]) -> dict[str, str]:
    """valuuta -> Yahoo FX tähis eurodesse (EUR-i enda jaoks pole vaja)."""
    out = {}
    for c in currencies:
        cur, _ = normalize_currency(c)
        if cur and cur != BASE:
            out[cur] = f"{cur}{BASE}=X"
    return out


def _asof(series: pd.Series, when: pd.Timestamp) -> float | None:
    s = series.dropna()
    if s.empty:
        return None
    v = s.asof(when)
    if pd.isna(v):  # enne ajaloo algust -> esimene teadaolev väärtus
        v = s.iloc[0]
    return float(v)


def _fx(fx_closes: pd.DataFrame, currency: str | None, when: pd.Timestamp | None) -> tuple[float | None, float]:
    """(kurss eurodesse, alamühiku kordaja). when=None -> viimane kurss."""
    cur, mult = normalize_currency(currency or BASE)
    if cur == BASE:
        return 1.0, mult
    col = f"{cur}{BASE}=X"
    if col not in fx_closes.columns:
        return None, mult
    s = fx_closes[col]
    return (float(s.dropna().iloc[-1]) if when is None else _asof(s, when)), mult


def lot_comparison(lots: pd.DataFrame, prices: dict[str, float | None], currencies: dict[str, str | None],
                   closes: pd.DataFrame, benchmark: str, bench_currency: str = "USD",
                   splits: dict[str, list] | None = None, include_received: bool = False) -> pd.DataFrame:
    """Tickeri kaupa: investeeritud ja praegune väärtus eurodes vs sama raha indeksis samadel päevadel.

    0-hinnaga read: tükelduse kirje -> ei lisa raha (aktsiad kuuluvad varasemale ostule);
    muu (nt tulemustasuna saadud aktsiad) -> vaikimisi välja jäetud, sest need pole ostuotsus.
    include_received=True korral hinnatakse need saamise päeva turuhinnaga, nagu oleks see summa
    samal päeval investeeritud.
    """
    splits = splits or {}
    if benchmark not in closes.columns:
        raise ValueError(f"Indeksi {benchmark} hinnad puuduvad")
    bench = closes[benchmark]
    bench_now = float(bench.dropna().iloc[-1])
    bfx_now, _ = _fx(closes, bench_currency, None)
    rows = {}
    for lot in lots.itertuples():
        t, when = lot.Ticker, lot.Kuupäev
        price_now = prices.get(t)
        fx_then, mult = _fx(closes, currencies.get(t), when)
        fx_now, _ = _fx(closes, currencies.get(t), None)
        bfx_then, _ = _fx(closes, bench_currency, when)
        b_then = _asof(bench, when)
        if None in (fx_then, fx_now, bfx_then, bfx_now, b_then) or price_now is None:
            continue
        unit_cost = lot.Ostuhind
        received = False
        if unit_cost == 0 and not is_split_lot(lot, splits.get(t, [])):
            if not include_received:
                continue
            market = _asof(closes[t], when) if t in closes.columns else None
            if market is None:
                continue
            unit_cost, received = market, True
        cost_eur = (lot.Kogus * unit_cost + lot.Komisjon) * mult * fx_then
        value_eur = lot.Kogus * price_now * mult * fx_now
        bench_value = cost_eur / (b_then * bfx_then) * bench_now * bfx_now
        r = rows.setdefault(t, {"Ticker": t, "Esimene ost": when, "Investeeritud €": 0.0, "Väärtus €": 0.0,
                                "Indeksis oleks €": 0.0, "Saadud aktsiad": False})
        r["Saadud aktsiad"] |= received
        r["Esimene ost"] = min(r["Esimene ost"], when)
        r["Investeeritud €"] += cost_eur
        r["Väärtus €"] += value_eur
        r["Indeksis oleks €"] += bench_value
    df = pd.DataFrame(rows.values())
    if df.empty:
        return df
    df["Tootlus"] = df["Väärtus €"] / df["Investeeritud €"] - 1
    df["Indeksi tootlus"] = df["Indeksis oleks €"] / df["Investeeritud €"] - 1
    df["Vahe €"] = df["Väärtus €"] - df["Indeksis oleks €"]
    df["Vahe %-p"] = df["Tootlus"] - df["Indeksi tootlus"]
    df["Tulemus"] = df["Vahe €"].map(lambda v: "✅ ületas" if v > 0 else "❌ jäi alla")
    return df.sort_values("Vahe €", ascending=False)


def to_eur(closes: pd.DataFrame, currencies: dict[str, str | None]) -> pd.DataFrame:
    """Teisendab hinnaread eurodesse päevase kursiga."""
    out = {}
    for t in closes.columns:
        if t.endswith("=X"):
            continue
        cur, mult = normalize_currency(currencies.get(t) or BASE)
        if cur == BASE:
            out[t] = closes[t] * mult
        elif f"{cur}{BASE}=X" in closes.columns:
            out[t] = closes[t] * mult * closes[f"{cur}{BASE}=X"]
    return pd.DataFrame(out)


def composition_history(eur_closes: pd.DataFrame, weights: dict[str, float], benchmarks: list[str],
                        start: pd.Timestamp) -> pd.DataFrame:
    """Praeguse koosseisu (iga päev samad osakaalud) ja indeksite väärtus, algus = 100, eurodes."""
    px = eur_closes[eur_closes.index >= start]
    rets = px.pct_change().iloc[1:]
    w = pd.Series({t: v for t, v in weights.items() if t in rets.columns and v and v > 0})
    if w.empty or rets.empty:
        return pd.DataFrame()
    r = rets[w.index]
    avail = r.notna()
    daily_w = avail.mul(w, axis=1)
    daily_w = daily_w.div(daily_w.sum(axis=1), axis=0)  # puuduva ajalooga aktsiad jäetakse välja
    port = (r.fillna(0) * daily_w).sum(axis=1)
    out = pd.DataFrame({"Minu portfell": (1 + port).cumprod() * 100})
    for b in benchmarks:
        if b in rets.columns:
            out[BENCHMARKS.get(b, b)] = (1 + rets[b].fillna(0)).cumprod() * 100
    first = pd.DataFrame({c: [100.0] for c in out.columns}, index=[px.index[0]])
    return pd.concat([first, out])


def max_drawdown(series: pd.Series) -> float:
    return float((series / series.cummax() - 1).min())
