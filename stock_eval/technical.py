"""Tehniline analüüs: indikaatorid ja skoor 0..100."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .fundamentals import linear_score


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilderi RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    sig = line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def add_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    df = prices.copy()
    c = df["Close"]
    df["SMA50"] = c.rolling(50).mean()
    df["SMA200"] = c.rolling(200).mean()
    df["RSI"] = rsi(c)
    m = macd(c)
    df["MACD"], df["MACD_signal"], df["MACD_hist"] = m["macd"], m["signal"], m["hist"]
    return df


def evaluate_technical(prices: pd.DataFrame) -> dict:
    """Tagastab {'signals': [...], 'score': float|None, 'data': df_indikaatoritega}."""
    if prices is None or prices.empty or len(prices) < 60:
        return {"signals": [], "score": None, "data": prices}
    df = add_indicators(prices)
    last = df.iloc[-1]
    close = float(last["Close"])
    signals = []

    def add(name, value, score, comment):
        signals.append({"Signaal": name, "Väärtus": value, "Skoor": None if score is None else round(score),
                        "Kommentaar": comment})

    if not np.isnan(last["SMA200"]):
        diff = close / last["SMA200"] - 1
        add("Hind vs SMA200", f"{diff:+.1%}", linear_score(diff, -0.15, 0.10),
            "Pikaajaline tõusutrend" if diff > 0 else "Allpool pikaajalist trendi")
        cross = last["SMA50"] > last["SMA200"]
        add("SMA50 vs SMA200", "kuldne rist" if cross else "surmarist", 100 if cross else 0,
            "Lühike trend üle pika" if cross else "Lühike trend alla pika")
    elif not np.isnan(last["SMA50"]):
        diff = close / last["SMA50"] - 1
        add("Hind vs SMA50", f"{diff:+.1%}", linear_score(diff, -0.10, 0.05), "SMA200 jaoks vähe ajalugu")

    r = float(last["RSI"])
    if r > 70:
        rs, rc = 30, "Üleostetud"
    elif r < 30:
        rs, rc = 40, "Ülemüüdud (võimalik põrge, aga nõrk trend)"
    else:
        rs, rc = 100 - abs(r - 55) * 2.5, "Neutraalne tsoon"
    add("RSI(14)", f"{r:.0f}", rs, rc)

    up = last["MACD"] > last["MACD_signal"]
    add("MACD", f"{last['MACD_hist']:+.2f}", 75 if up else 25,
        "MACD üle signaaljoone" if up else "MACD alla signaaljoone")

    lookback = min(126, len(df) - 1)
    mom = close / float(df["Close"].iloc[-lookback - 1]) - 1
    add("Momentum 6 kuud", f"{mom:+.1%}", linear_score(mom, -0.20, 0.25), "")

    vol = float(df["Close"].pct_change().tail(252).std() * np.sqrt(252))
    add("Volatiilsus (aastane)", f"{vol:.0%}", linear_score(vol, 0.60, 0.15),
        "Madal" if vol < 0.25 else "Kõrge" if vol > 0.45 else "Keskmine")

    window = df["Close"].tail(252)
    hi, lo = float(window.max()), float(window.min())
    pos = (close - lo) / (hi - lo) if hi > lo else 0.5
    add("52 nädala vahemik", f"{pos:.0%} põhjast", None, f"{lo:.2f} – {hi:.2f}")

    scores = [s["Skoor"] for s in signals if s["Skoor"] is not None]
    return {"signals": signals, "score": sum(scores) / len(scores) if scores else None, "data": df}
