"""Aktsiate evalueerimise dashboard.  Käivita:  streamlit run app.py  (või ./run.sh)

Ülesehitus:
  💼 Minu portfell   – väärtus, bull/bear stsenaariumid, kasvu allikad, võrdlus indeksiga
  📋 Aktsiate võrdlus – riski/tulu kaart ja koondtabel
  🔍 Aktsia analüüs   – bull vs bear kokkuvõte ja detailid (kasv, fundamentaal, DCF, tehniline)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

from stock_eval import benchmark as bm
from stock_eval.data import fetch_snapshot
from stock_eval.dcf import DCFAssumptions, estimate_discount_rate, estimate_growth, run_dcf
from stock_eval.fundamentals import CATEGORIES, TECH_CATEGORY
from stock_eval.growth import sector_pe
from stock_eval.portfolio import (aggregate_lots, apply_splits, fx_symbol, holdings_table, normalize_currency,
                                  read_lots, weighted_score)
from stock_eval.scoring import evaluate, rating

st.set_page_config(page_title="Aktsiate evalueerija", page_icon="📈", layout="wide")
PORTFOLIO_FILE = Path(__file__).parent / "portfolio.csv"  # isiklik, .gitignore's
BASE_CURRENCY = "EUR"
GREEN, RED, BLUE, GREY = "#27ae60", "#e74c3c", "#2e86de", "#7f8c8d"
REC = {"strong_buy": "Tugev ost", "buy": "Ost", "hold": "Hoia", "underperform": "Alla turu",
       "sell": "Müü", "strong_sell": "Tugev müük"}


# ====================================================================== andmed
@st.cache_data(ttl=3600, show_spinner=False)
def load(ticker: str):
    return fetch_snapshot(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def fx_rate(currency: str, base: str = BASE_CURRENCY) -> float | None:
    if currency == base:
        return 1.0
    try:
        h = yf.Ticker(fx_symbol(currency, base)).history(period="5d")
        return float(h["Close"].dropna().iloc[-1]) if not h.empty else None
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def load_closes(tickers: tuple[str, ...], start: str) -> pd.DataFrame:
    return bm.download_closes(list(tickers), start)


def fmt_big(v: float | None) -> str:
    if v is None:
        return "—"
    for div, suf in ((1e12, " T"), (1e9, " mld"), (1e6, " mln")):
        if abs(v) >= div:
            return f"{v / div:,.2f}{suf}"
    return f"{v:,.0f}"


def score_col(label: str):
    return st.column_config.ProgressColumn(label, min_value=0, max_value=100, format="%.0f")


NUM2 = st.column_config.NumberColumn(format="%.2f")
NUM0 = st.column_config.NumberColumn(format="%.0f")
PCT = st.column_config.NumberColumn(format="percent")


# ====================================================================== külgriba
with st.sidebar:
    st.header("Aktsiad")
    source = st.radio("Allikas", ["Minu Yahoo portfell", "Käsitsi"], horizontal=True,
                      index=0 if PORTFOLIO_FILE.exists() else 1)
    portfolio = lots_raw = None
    if source == "Minu Yahoo portfell":
        up = st.file_uploader("Yahoo Finance eksport (quotes.csv)", type="csv",
                              help="Yahoo Finance → My Portfolio → vali portfell → Export")
        if up is not None:
            PORTFOLIO_FILE.write_bytes(up.getvalue())
        if PORTFOLIO_FILE.exists():
            try:
                lots_raw = read_lots(PORTFOLIO_FILE)
                portfolio = aggregate_lots(lots_raw)
                st.caption(f"Laetud {len(portfolio)} tickerit failist {PORTFOLIO_FILE.name}")
            except Exception as e:
                st.error(f"Faili ei õnnestunud lugeda: {e}")
        else:
            st.info("Laadi üles Yahoo portfelli CSV eksport.")
        extra = st.text_input("Lisa võrdluseks tickereid (valikuline)", "")
        tickers = (portfolio["Ticker"].tolist() if portfolio is not None else []) + \
            [t.strip().upper() for t in extra.split(",") if t.strip()]
    else:
        raw = st.text_area("Tickerid (koma või reavahetusega)", "AAPL, MSFT, GOOGL, NVDA, ASML, KO",
                           help="Yahoo Finance tähised, nt Tallinna börs: LHV1T.TL, Helsingi: NOKIA.HE")
        tickers = [t.strip().upper() for t in raw.replace("\n", ",").split(",") if t.strip()]
    tickers = list(dict.fromkeys(tickers))

    horizon = st.radio("**Ajahorisont**", [1, 3, 5], index=1, horizontal=True, format_func=lambda y: f"{y} a",
                       help="Oodatav hind, bull/bear stsenaariumid, kasvu allikad ja kasvupotentsiaali skoor")

    with st.expander("⚖️ Koondskoori kaalud"):
        weights = {"fundamental": st.slider("Fundamentaalanalüüs", 0, 100, 40, 5),
                   "dcf": st.slider("DCF", 0, 100, 20, 5),
                   "technical": st.slider("Tehniline analüüs", 0, 100, 15, 5),
                   "growth": st.slider("Kasvupotentsiaal", 0, 100, 25, 5)}

    with st.expander("📈 Kasvumudeli eeldused"):
        g_auto = st.checkbox("Automaatne (analüütikute kasvuprognoosid)", value=True)
        growth_over: dict = {}
        if not g_auto:
            growth_over["growth"] = st.slider("Kasumi (EPS) kasv 1. aastal, %", -10.0, 40.0, 12.0, 1.0) / 100
            growth_over["exit_pe"] = st.slider("P/E 5 aasta pärast", 6.0, 50.0, 20.0, 1.0)
        st.caption("Bull/bear: bear = kasv ½ −2 %-p ja P/E −30%; bull = kasv ×1,25 +2 %-p ja P/E +20%; "
                   "tõenäosused 25/50/25.")

    with st.expander("💰 DCF eeldused"):
        auto = st.checkbox("Automaatsed (kasv ajaloost, diskonto CAPM-ist)", value=True)
        dcf_over: dict = {}
        if not auto:
            dcf_over["growth"] = st.slider("FCF kasv (1. etapp), %", -10.0, 30.0, 8.0, 0.5) / 100
            dcf_over["discount_rate"] = st.slider("Diskontomäär (WACC), %", 5.0, 16.0, 9.0, 0.25) / 100
        dcf_over["terminal_growth"] = st.slider("Terminaalne kasv, %", 0.0, 4.0, 2.5, 0.25) / 100
        dcf_over["years"] = st.select_slider("Prognoosiperiood (aastat)", [5, 8, 10, 15], 10)

    with st.expander("📊 Võrdlusindeks"):
        bench = st.selectbox("Peamine võrdlusindeks", list(bm.BENCHMARKS), format_func=bm.BENCHMARKS.get)
        bench_extra = st.multiselect("Graafikul lisaks", [b for b in bm.BENCHMARKS if b != bench],
                                     default=[b for b in ("SPY",) if b != bench], format_func=bm.BENCHMARKS.get)
        include_received = st.checkbox("Arvesta tulemustasu / tasuta saadud aktsiaid", value=False,
                                       help="0-hinnaga read, mis pole tükeldused.")

    if st.button("🔄 Värskenda andmeid"):
        load.clear()
        load_closes.clear()
        fx_rate.clear()

st.title("📈 Aktsiate evalueerija")
if not tickers:
    st.info("Lisa külgribale vähemalt üks ticker või laadi üles Yahoo portfell.")
    st.stop()

# ====================================================================== hindamine
evals, errors = {}, []
progress = st.progress(0.0, "Laen andmeid…")
for i, t in enumerate(tickers):
    progress.progress((i + 1) / len(tickers), f"Laen {t}…")
    try:
        evals[t] = evaluate(load(t), weights, dcf_over, horizon, growth_over)
    except Exception as e:  # ühe tickeri viga ei tohi kogu lehte murda
        errors.append(f"**{t}**: {e}")
progress.empty()
if not evals:
    for e in errors:
        st.warning(e)
    st.stop()

splits = {t: e.snapshot.splits for t, e in evals.items()}
split_notes: list[str] = []
lots = None
if lots_raw is not None:
    # Tükeldustega aktsiate ajalooline (tükeldustega korrigeeritud) hind, et tuvastada, kas ostuhind on
    # failis juba ümber arvutatud
    first_lot = lots_raw["Kuupäev"].min()
    split_tickers = tuple(sorted(t for t, ev in splits.items() if pd.notna(first_lot) and any(
        pd.Timestamp(w) > first_lot for w, _ in ev)))
    split_px = load_closes(split_tickers, (first_lot - pd.Timedelta(days=10)).date().isoformat()) \
        if split_tickers else pd.DataFrame()

    def price_at(t, day):
        if t not in split_px.columns:
            return None
        s = split_px[t].dropna()
        v = s.asof(day) if not s.empty else None
        return float(v) if v is not None and pd.notna(v) else None

    lots, split_notes = apply_splits(lots_raw, splits, price_at)
    portfolio = aggregate_lots(lots)

summary = pd.DataFrame([e.summary_row() for e in evals.values()]).sort_values(
    "Koondskoor", ascending=False, na_position="last")
currencies = {t: e.snapshot.info.get("currency") for t, e in evals.items()}
has_portfolio = portfolio is not None and (portfolio["Kogus"] > 0).any()

SUMMARY_CONFIG = {
    "Hind": NUM2, "Sisemine väärtus": NUM2, "Turvamarginaal": PCT,
    "Fundamentaal": score_col("Fundamentaal"), "DCF": score_col("DCF"), "Tehniline": score_col("Tehniline"),
    "Rule of 40": st.column_config.NumberColumn(format="%.0f", help="Käibe kasv % + FCF marginaal %"),
    "Analüütikute siht 12k": NUM2, "Potentsiaal 12k": PCT, f"Oodatav hind {horizon}a": NUM2,
    "Oodatav tootlus a/a": PCT, "Kasvupotentsiaal": score_col("Kasvupotentsiaal"),
    "Bull/bear": st.column_config.ProgressColumn("Bull/bear", min_value=0, max_value=100, format="%.0f",
                                                 help="Argumentide tasakaal: 100 = ainult bull, 0 = ainult bear"),
    f"Bear {horizon}a": PCT, f"Bull {horizon}a": PCT,
    "Tulu/risk": st.column_config.NumberColumn(format="%.1f", help="Bull tõus / bear langus; >2 hea"),
    "Koondskoor": score_col("Koondskoor"),
}


# ====================================================================== 💼 portfell
def portfolio_tab():
    for note in split_notes:
        st.info("✂️ " + note + ". Soovi korral lisa Yahoos tükelduse rida (0-hinnaga).")
    for e in errors:
        st.warning(e)
    fx = {c: r for c in {normalize_currency(c)[0] for c in currencies.values() if c}
          if (r := fx_rate(c)) is not None}
    h = holdings_table(portfolio, {t: e.snapshot.price for t, e in evals.items()},
                       {t: e.total for t, e in evals.items()}, currencies, fx, BASE_CURRENCY)
    val_col = f"Väärtus ({BASE_CURRENCY})"
    get = lambda t, f: f(evals[t]) if t in evals else None
    h["Hinnang"] = h["Koondskoor"].map(rating)
    h["Vaade"] = h["Ticker"].map(lambda t: get(t, lambda e: e.bullbear.verdict))
    h["Siht 12k"] = h["Ticker"].map(lambda t: get(t, lambda e: e.growth.analyst.mean if e.growth.analyst else None))
    h["Potentsiaal 12k"] = h["Siht 12k"] / h["Hind"] - 1
    h["Oodatav tootlus a/a"] = h["Ticker"].map(
        lambda t: get(t, lambda e: getattr(e.growth.projection(horizon), "annual_return", None)))
    for name in ("Bear", "Base", "Bull"):
        h[f"{name} %"] = h["Ticker"].map(
            lambda t, n=name: get(t, lambda e: getattr(e.bullbear.scenario(n), "change", None)))

    total = h[val_col].sum()
    to_base = h[val_col] / h["Turuväärtus"]
    pl = (h["Kasum/kahjum"] * to_base).sum(min_count=1)
    inv = (h["Investeeritud"] * to_base).sum(min_count=1)
    ps = weighted_score(h)

    def wavg(col):
        x = h.dropna(subset=[col, "Osakaal"])
        return (x[col] * x["Osakaal"]).sum() / x["Osakaal"].sum() if x["Osakaal"].sum() else None

    # Stsenaariumid portfelli tasandil (positsioonid ilma prognoosita jäävad samaks)
    scen_val = {n: (h[val_col] * (1 + h[f"{n} %"].fillna(0))).sum() for n in ("Bear", "Base", "Bull")}
    exp_val = 0.25 * scen_val["Bear"] + 0.5 * scen_val["Base"] + 0.25 * scen_val["Bull"]

    c = st.columns(5)
    c[0].metric("Portfelli väärtus", f"{total:,.0f} €")
    c[1].metric("Kasum/kahjum", f"{pl:+,.0f} €" if pd.notna(pl) else "—",
                f"{pl / inv:+.1%}" if pd.notna(pl) and inv else None)
    c[2].metric("Koondskoor", f"{ps:.0f}" if ps is not None else "—", rating(ps), delta_color="off")
    up12 = wavg("Potentsiaal 12k")
    c[3].metric("Analüütikud 12 k", f"{up12:+.1%}" if up12 is not None else "—",
                help="Analüütikute keskmise sihthinna potentsiaal, kaalutud osakaaluga")
    c[4].metric(f"Oodatav väärtus {horizon} a", f"{exp_val:,.0f} €", f"{exp_val / total - 1:+.0%}",
                help="Bear/base/bull stsenaariumide tõenäosustega (25/50/25) kaalutud väärtus, dividendideta")

    s1, s2, s3 = st.columns(3)
    for col, n, emoji in ((s1, "Bear", "🐻"), (s2, "Base", "⚖️"), (s3, "Bull", "🐂")):
        col.metric(f"{emoji} {n} {horizon} a pärast", f"{scen_val[n]:,.0f} €", f"{scen_val[n] / total - 1:+.0%}")
    st.caption("Väärtused eurodes praeguse kursiga. Stsenaariumid on kasumipõhise mudeli variandid (vt külgriba "
               "„Kasvumudeli eeldused”), mitte garantii.")

    t_pos, t_bb, t_src, t_bench = st.tabs(["Positsioonid", "🐂🐻 Bull / bear", "Kasvu allikad",
                                           "Võrdlus indeksiga"])
    with t_pos:
        show_all = st.toggle("Näita kõiki veerge", key="pos_all")
        cols = None if show_all else ["Ticker", val_col, "Osakaal", "Tootlus", "Koondskoor", "Vaade",
                                      "Potentsiaal 12k", "Oodatav tootlus a/a", "Bear %", "Bull %"]
        st.dataframe(h, hide_index=True, width="stretch", column_order=cols, column_config={
            "Kogus": st.column_config.NumberColumn(format="%.4g"), "Keskmine ostuhind": NUM2,
            "Investeeritud": NUM2, "Hind": NUM2, "Turuväärtus": NUM2,
            "Kasum/kahjum": st.column_config.NumberColumn(format="%+.2f"), "Tootlus": PCT, val_col: NUM0,
            "Osakaal": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
            "Siht 12k": NUM2, "Potentsiaal 12k": PCT, "Oodatav tootlus a/a": PCT,
            "Bear %": PCT, "Base %": PCT, "Bull %": PCT, "Koondskoor": score_col("Koondskoor")})
        weak = h[h["Koondskoor"] < 40]
        if not weak.empty:
            st.info("Nõrga koondskooriga (<40): " + ", ".join(
                f"{r.Ticker} ({r.Osakaal:.0%})" for r in weak.itertuples()) + " — vaata „Aktsia analüüs”.")

    with t_bb:
        bb = h.dropna(subset=["Base %"]).sort_values("Osakaal", ascending=True)
        if bb.empty:
            st.info("Stsenaariume ei saanud arvutada.")
        else:
            fig = go.Figure()
            fig.add_bar(y=bb["Ticker"], x=bb["Bull %"] - bb["Bear %"], base=bb["Bear %"], orientation="h",
                        marker_color="rgba(46,134,222,0.25)", name="Bear … bull vahemik",
                        hovertemplate="%{y}: %{base:+.0%} … %{x:+.0%}<extra></extra>")
            fig.add_scatter(y=bb["Ticker"], x=bb["Bear %"], mode="markers", name="Bear",
                            marker=dict(color=RED, size=9, symbol="line-ns-open", line_width=3))
            fig.add_scatter(y=bb["Ticker"], x=bb["Base %"], mode="markers", name="Base",
                            marker=dict(color=BLUE, size=10, symbol="diamond"))
            fig.add_scatter(y=bb["Ticker"], x=bb["Bull %"], mode="markers", name="Bull",
                            marker=dict(color=GREEN, size=9, symbol="line-ns-open", line_width=3))
            fig.add_vline(x=0, line_color=GREY, line_dash="dot")
            fig.update_layout(height=max(320, 28 * len(bb)), margin=dict(t=40, b=10), legend_orientation="h",
                              xaxis_tickformat="+.0%", title=f"Hinnamuutus {horizon} aastaga: bear / base / bull "
                              "(suurem positsioon ülal)")
            st.plotly_chart(fig, width="stretch")
            counts = h["Vaade"].value_counts()
            st.markdown(" · ".join(f"{k}: **{v}**" for k, v in counts.items() if k and k != "—"))
            st.caption("Vaade tuleb automaatsete bull- ja bear-argumentide tasakaalust (vt „Aktsia analüüs”).")

    with t_src:
        growth_sources(h, val_col)

    with t_bench:
        benchmark_section(h)


def growth_sources(h: pd.DataFrame, val_col: str):
    parts = []
    for tkr, val in zip(h["Ticker"], h[val_col]):
        dd = evals[tkr].growth.decompose(horizon) if tkr in evals else None
        if not dd or pd.isna(val):
            continue
        k = val / dd.price0
        parts.append({"Ticker": tkr, "Käibe kasv": dd.revenue_part * k, "Marginaal": dd.margin_part * k,
                      "Aktsiate arv": dd.buyback_part * k, "P/E muutus": dd.pe_effect * k,
                      "Dividendid": dd.dividends * k})
    if not parts:
        st.info("Kasumipõhist prognoosi ei saanud ühelegi positsioonile teha.")
        return
    pdf = pd.DataFrame(parts).set_index("Ticker")
    pdf["Kokku"] = pdf.sum(axis=1)
    pdf = pdf.sort_values("Kokku", ascending=False)
    tot = pdf.sum()
    cols = st.columns(6)
    for col, name in zip(cols, ["Käibe kasv", "Marginaal", "Aktsiate arv", "P/E muutus", "Dividendid", "Kokku"]):
        col.metric(name, f"{tot[name]:+,.0f} €")
    fig = go.Figure()
    for name, color in {"Käibe kasv": GREEN, "Marginaal": "#16a085", "Aktsiate arv": "#8e44ad",
                        "P/E muutus": "#e67e22", "Dividendid": BLUE}.items():
        fig.add_bar(name=name, x=pdf.index, y=pdf[name], marker_color=color)
    fig.add_scatter(name="Kokku", x=pdf.index, y=pdf["Kokku"], mode="markers",
                    marker=dict(symbol="diamond", size=10, color="#2c3e50"))
    fig.update_layout(barmode="relative", height=380, margin=dict(t=30, b=10), legend_orientation="h",
                      title=f"Oodatav väärtuse muutus positsioonide kaupa (base), {horizon} a (€)")
    st.plotly_chart(fig, width="stretch")
    top = pdf["Kokku"].head(3)
    st.caption(f"Kõige rohkem kasvu: " + ", ".join(f"{t} ({v:+,.0f} €)" for t, v in top.items())
               + f". Kasumi kasv kokku {tot['Käibe kasv'] + tot['Marginaal'] + tot['Aktsiate arv']:+,.0f} €, "
               f"P/E muutus {tot['P/E muutus']:+,.0f} €.")


def benchmark_section(h: pd.DataFrame):
    dl = bm.dated_lots(lots)
    if dl.empty:
        st.info("Võrdluseks on vaja ostukuupäevi (Yahoo eksporti veerg Trade Date).")
        return
    bench_list = [bench] + bench_extra
    cur_all = {**currencies, **{b: "USD" for b in bench_list}}
    fx_syms = bm.fx_symbols({c for c in cur_all.values() if c})
    start = (dl["Kuupäev"].min() - pd.Timedelta(days=10)).date().isoformat()
    hist_start = (pd.Timestamp.today() - pd.DateOffset(years=5, days=10)).date().isoformat()
    with st.spinner("Laen hinnaajalugu…"):
        closes = load_closes(tuple(sorted(set(h["Ticker"]) | set(bench_list) | set(fx_syms.values()))),
                             min(start, hist_start))
    try:
        cmp = bm.lot_comparison(dl, {t: e.snapshot.price for t, e in evals.items()}, currencies, closes,
                                bench, splits=splits, include_received=include_received)
    except ValueError as e:
        st.warning(str(e))
        return

    view = st.radio("Vaade", ["Minu ostud vs indeks", "Praeguse koosseisu ajalugu"], horizontal=True,
                    label_visibility="collapsed")
    if view == "Minu ostud vs indeks":
        if cmp.empty:
            st.info("Võrdlust ei saanud teha.")
            return
        inv, val, idx = cmp["Investeeritud €"].sum(), cmp["Väärtus €"].sum(), cmp["Indeksis oleks €"].sum()
        b = st.columns(4)
        b[0].metric("Investeeritud", f"{inv:,.0f} €")
        b[1].metric("Minu aktsiad praegu", f"{val:,.0f} €", f"{val / inv - 1:+.1%}")
        b[2].metric(f"Kui oleks ostnud {bench}", f"{idx:,.0f} €", f"{idx / inv - 1:+.1%}")
        b[3].metric("Vahe", f"{val - idx:+,.0f} €", "ületas indeksit" if val > idx else "indeks oli parem",
                    delta_color="normal" if val > idx else "inverse")
        won = (cmp["Vahe €"] > 0).sum()
        st.markdown(f"**{won} / {len(cmp)}** positsiooni on ületanud indeksit ({bm.BENCHMARKS[bench]}).")
        fig = go.Figure(go.Bar(x=cmp["Ticker"], y=cmp["Vahe €"],
                               marker_color=[GREEN if v > 0 else RED for v in cmp["Vahe €"]],
                               hovertemplate="%{x}: %{y:+,.0f} €<extra></extra>"))
        fig.update_layout(height=300, margin=dict(t=30, b=10), title=f"Vahe vs {bench} (€)")
        st.plotly_chart(fig, width="stretch")
        with st.expander("Tabel"):
            st.dataframe(cmp.drop(columns=["Saadud aktsiad"]), hide_index=True, width="stretch", column_config={
                "Esimene ost": st.column_config.DateColumn(format="DD.MM.YYYY"), "Investeeritud €": NUM0,
                "Väärtus €": NUM0, "Indeksis oleks €": NUM0, "Tootlus": PCT, "Indeksi tootlus": PCT,
                "Vahe €": st.column_config.NumberColumn(format="%+.0f"), "Vahe %-p": PCT})
        st.caption("Iga ost on võrreldud sama summaga (eurodes) samal päeval indeksis; valuutakursid mõlemal "
                   "poolel, dividendideta. " + ("Tulemustasu aktsiad on kaasatud saamise päeva turuväärtusega."
                                                if include_received else
                                                "Tulemustasu/tasuta saadud aktsiad on välja jäetud."))
    else:
        period = st.radio("Periood", [1, 3, 5], index=1, horizontal=True, format_func=lambda y: f"{y} a",
                          key="hist_period")
        eur = bm.to_eur(closes, cur_all)
        hist = bm.composition_history(eur, dict(zip(h["Ticker"], h["Osakaal"].fillna(0))), bench_list,
                                      closes.index[-1] - pd.DateOffset(years=period))
        if hist.empty:
            st.info("Ajalugu ei saanud arvutada.")
            return
        fig = go.Figure()
        for c in hist.columns:
            fig.add_scatter(x=hist.index, y=hist[c], name=c, line=dict(width=3 if c == "Minu portfell" else 1.5))
        fig.update_layout(height=380, margin=dict(t=30, b=10), legend_orientation="h",
                          title=f"Praegune koosseis vs indeksid, {period} a (algus = 100, eurodes)")
        st.plotly_chart(fig, width="stretch")
        yrs = (hist.index[-1] - hist.index[0]).days / 365.25
        stats = pd.DataFrame({"Kokku": hist.iloc[-1] / 100 - 1, "Aastas": (hist.iloc[-1] / 100) ** (1 / yrs) - 1,
                              "Suurim langus": [bm.max_drawdown(hist[c]) for c in hist.columns]}, index=hist.columns)
        st.dataframe(stats, width="stretch", column_config={c: PCT for c in stats.columns})
        st.caption("Praegused osakaalud kogu perioodi vältel – mitte sinu tegelikud tehingud. Tagantjärele tarkuse "
                   "viga: portfellis on sageli need aktsiad, mis on hästi läinud.")


# ====================================================================== 📋 võrdlus
def comparison_tab():
    if not has_portfolio:
        for e in errors:
            st.warning(e)
    rr = summary.dropna(subset=[f"Bear {horizon}a", f"Bull {horizon}a"])
    if not rr.empty:
        fig = go.Figure(go.Scatter(
            x=rr[f"Bear {horizon}a"], y=rr[f"Bull {horizon}a"], mode="markers+text", text=rr["Ticker"],
            textposition="top center",
            marker=dict(size=14, color=rr["Koondskoor"], colorscale="RdYlGn", cmin=20, cmax=80,
                        colorbar=dict(title="Koond-<br>skoor"), line=dict(width=1, color="#2c3e50")),
            hovertemplate="%{text}<br>Bear %{x:+.0%}<br>Bull %{y:+.0%}<extra></extra>"))
        fig.add_vline(x=0, line_dash="dot", line_color=GREY)
        fig.add_hline(y=0, line_dash="dot", line_color=GREY)
        fig.update_layout(height=460, margin=dict(t=40, b=10), xaxis_tickformat="+.0%", yaxis_tickformat="+.0%",
                          xaxis_title=f"Bear stsenaarium ({horizon} a) → väiksem risk paremal",
                          yaxis_title=f"Bull stsenaarium ({horizon} a) → suurem tõusuruum ülal",
                          title="Riski / tulu kaart: parim nurk on üleval paremal")
        st.plotly_chart(fig, width="stretch")

    show_all = st.toggle("Näita kõiki veerge", key="cmp_all")
    cols = None if show_all else ["Ticker", "Nimi", "Hind", "Koondskoor", "Hinnang", "Vaade", "Bull/bear",
                                  "Potentsiaal 12k", f"Bear {horizon}a", f"Bull {horizon}a", "Tulu/risk",
                                  "Rule of 40"]
    st.dataframe(summary, hide_index=True, width="stretch", column_order=cols, column_config=SUMMARY_CONFIG)
    st.download_button("⬇️ Laadi alla CSV", summary.to_csv(index=False).encode("utf-8"), "aktsiate_hinnang.csv",
                       "text/csv")

    with st.expander("Fundamentaalkategooriad"):
        rows = [{"Ticker": t, "Kategooria": c, "Skoor": e.fundamentals["categories"].get(c)}
                for t, e in evals.items() for c in CATEGORIES + [TECH_CATEGORY]]
        cat = pd.DataFrame(rows).dropna()
        fig = go.Figure()
        for c in CATEGORIES + [TECH_CATEGORY]:
            sub = cat[cat["Kategooria"] == c]
            fig.add_bar(name=c, x=sub["Ticker"], y=sub["Skoor"])
        fig.update_layout(barmode="group", height=320, yaxis_range=[0, 100], margin=dict(t=10, b=10),
                          legend_orientation="h")
        st.plotly_chart(fig, width="stretch")


# ====================================================================== 🔍 aktsia
def stock_tab():
    sel = st.selectbox("Vali aktsia", summary["Ticker"].tolist(),
                       format_func=lambda t: f"{t} — {evals[t].snapshot.name}")
    ev = evals[sel]
    snap, gr, bbr = ev.snapshot, ev.growth, ev.bullbear
    cur = snap.info.get("currency") or ""
    a = gr.analyst

    c = st.columns(5)
    c[0].metric("Hind", f"{snap.price:,.2f} {cur}" if snap.price else "—")
    c[1].metric("Koondskoor", f"{ev.total:.0f}" if ev.total is not None else "—", rating(ev.total),
                delta_color="off")
    c[2].metric("Vaade", bbr.verdict, f"{bbr.balance:.0f}/100 bull" if bbr.balance is not None else None,
                delta_color="off")
    c[3].metric("Analüütikud 12 k", f"{a.mean:,.2f}" if a else "—", f"{a.upside:+.0%}" if a else None)
    ec = bbr.expected_change
    c[4].metric(f"Oodatav {horizon} a", f"{bbr.expected_price:,.2f}" if bbr.expected_price else "—",
                f"{ec:+.0%}" if ec is not None else None, help="Bear/base/bull 25/50/25 kaalutud hind")
    st.caption(f"{snap.name} · {snap.info.get('sector') or ''} · {snap.info.get('industry') or ''} · "
               f"turuväärtus {fmt_big(snap.info.get('marketCap'))}")

    tabs = st.tabs(["🐂🐻 Bull vs bear", "📈 Kasvupotentsiaal", "🏦 Fundamentaal", "💰 DCF", "📉 Tehniline"])
    with tabs[0]:
        bull_bear_view(ev, cur)
    with tabs[1]:
        growth_view(ev, cur, sel)
    with tabs[2]:
        fundamentals_view(ev)
    with tabs[3]:
        dcf_view(ev)
    with tabs[4]:
        technical_view(ev)


def bull_bear_view(ev, cur: str):
    bbr, snap, a = ev.bullbear, ev.snapshot, ev.growth.analyst
    left, right = st.columns([1, 1])
    with left:
        # Osaskoorid
        parts = {"Fundamentaal": ev.fundamentals["score"], "DCF": ev.dcf.score if ev.dcf else None,
                 "Tehniline": ev.technical["score"], "Kasvupotentsiaal": ev.growth.score(horizon)}
        fig = go.Figure(go.Bar(
            x=[v if v is not None else 0 for v in parts.values()], y=list(parts), orientation="h",
            marker_color=[GREEN if (v or 0) >= 55 else RED if (v or 0) < 40 else "#f39c12" for v in parts.values()],
            text=[f"{v:.0f}" if v is not None else "—" for v in parts.values()], textposition="auto"))
        fig.update_layout(height=220, xaxis_range=[0, 100], margin=dict(t=30, b=10, l=10, r=10),
                          title="Osaskoorid (0–100)")
        st.plotly_chart(fig, width="stretch")
    with right:
        bal = bbr.balance
        if bal is not None:
            fig = go.Figure(go.Indicator(
                mode="gauge+number", value=bal, number=dict(suffix=" / 100"),
                title=dict(text=bbr.verdict), gauge=dict(
                    axis=dict(range=[0, 100]), bar=dict(color="#2c3e50"),
                    steps=[dict(range=[0, 35], color="rgba(231,76,60,0.35)"),
                           dict(range=[35, 65], color="rgba(243,156,18,0.3)"),
                           dict(range=[65, 100], color="rgba(39,174,96,0.35)")])))
            fig.update_layout(height=220, margin=dict(t=40, b=10, l=30, r=30))
            st.plotly_chart(fig, width="stretch")

    # Argumendid
    bc, rc = st.columns(2)
    with bc:
        st.markdown(f"#### 🐂 Bull-argumendid ({len(bbr.bull_points)})")
        for p in sorted(bbr.bull_points, key=lambda p: -p.weight):
            st.markdown(f"- **{p.theme}:** {p.text}" + (" ⭐" if p.weight >= 1.5 else ""))
        if not bbr.bull_points:
            st.caption("Puuduvad")
    with rc:
        st.markdown(f"#### 🐻 Bear-argumendid ({len(bbr.bear_points)})")
        for p in sorted(bbr.bear_points, key=lambda p: -p.weight):
            st.markdown(f"- **{p.theme}:** {p.text}" + (" ⭐" if p.weight >= 1.5 else ""))
        if not bbr.bear_points:
            st.caption("Puuduvad")
    st.caption("⭐ = suurema kaaluga argument. Argumendid tulevad automaatselt näitajatest; need ei asenda "
               "uudiseid, juhtkonna kommentaare ega konkurentsiolukorra hinnangut.")

    # Stsenaariumid
    st.markdown(f"#### Stsenaariumid {horizon} aasta peale")
    if not bbr.scenarios:
        st.info(ev.growth.model_reason or "Stsenaariume ei saanud arvutada.")
        return
    rows = [{"Stsenaarium": {"Bear": "🐻 Bear", "Base": "⚖️ Base", "Bull": "🐂 Bull"}[s.name],
             "Tõenäosus": s.probability, "Kasumi kasv 1. a": s.growth, "P/E 5 a pärast": s.exit_pe,
             "Hind": s.price, "Muutus": s.change, "Tootlus a/a": s.annual_return} for s in bbr.scenarios]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "Tõenäosus": PCT, "Kasumi kasv 1. a": PCT, "P/E 5 a pärast": st.column_config.NumberColumn(format="%.1f"),
        "Hind": NUM2, "Muutus": PCT, "Tootlus a/a": PCT})
    rr = bbr.reward_risk
    bear, bull = bbr.scenario("Bear"), bbr.scenario("Bull")
    if rr is not None:
        st.markdown(f"**Tulu/risk suhe {rr:.1f}** — bull-stsenaariumis {bull.change:+.0%}, bear-stsenaariumis "
                    f"{bear.change:+.0%}. " + ("Asümmeetria on soodne (>2)." if rr > 2 else
                                               "Asümmeetria on ebasoodne (<1)." if rr < 1 else "Asümmeetria on mõõdukas."))
    else:
        st.markdown(f"**Ka bear-stsenaarium ei too mudeli järgi langust** ({bear.change:+.0%}) — tasub kontrollida, "
                    "kas analüütikute prognoosid on realistlikud.")

    # Lehvikgraafik
    hist = snap.prices["Close"].tail(504)
    last = hist.index[-1]
    end = last + pd.DateOffset(years=horizon)
    fig = go.Figure()
    fig.add_scatter(x=hist.index, y=hist.values, name="Hind", line=dict(color=GREY))
    fig.add_scatter(x=[last, end, end, last], y=[snap.price, bull.price, bear.price, snap.price], fill="toself",
                    fillcolor="rgba(46,134,222,0.12)", line=dict(width=0), name="Bear … bull", hoverinfo="skip")
    for s, color in ((bear, RED), (bbr.scenario("Base"), BLUE), (bull, GREEN)):
        fig.add_scatter(x=[last, end], y=[snap.price, s.price], mode="lines+markers+text", name=s.name,
                        line=dict(color=color, dash="dash"), text=["", f"{s.name} {s.price:,.0f}"],
                        textposition="middle right")
    if a and a.low and a.high:
        x1 = last + pd.DateOffset(years=1)
        fig.add_scatter(x=[x1] * 3, y=[a.low, a.mean, a.high], mode="markers", name="Analüütikud 12 k",
                        marker=dict(symbol="line-ew-open", size=16, color="#8e44ad", line_width=3))
    fig.update_layout(height=420, margin=dict(t=30, b=10, r=80), legend_orientation="h",
                      title=f"Hinnarada ja stsenaariumid ({cur})")
    st.plotly_chart(fig, width="stretch")


def growth_view(ev, cur: str, sel: str):
    snap, gr = ev.snapshot, ev.growth
    a = gr.analyst
    st.markdown("#### Analüütikute konsensus (12 kuud)")
    if not a:
        st.info("Analüütikute sihthinnad puuduvad (või katab aktsiat alla 3 analüütiku).")
    else:
        g = st.columns(4)
        g[0].metric("Keskmine sihthind", f"{a.mean:,.2f} {cur}", f"{a.upside:+.1%}")
        g[1].metric("Vahemik", f"{a.low:,.2f} – {a.high:,.2f}" if a.low and a.high else "—")
        g[2].metric("Analüütikuid", a.count)
        g[3].metric("Konsensus", REC.get(a.recommendation_key or "", a.recommendation_key or "—"),
                    f"{a.recommendation:.2f} (1 = tugev ost, 5 = müü)" if a.recommendation else None,
                    delta_color="off")

    st.markdown("#### Kasumipõhine prognoos (EPS × P/E)")
    if not gr.projections:
        st.info(gr.model_reason or "Prognoosi ei saanud teha.")
        return
    st.markdown(f"**Lähtekasum** (järgmise 12 k EPS): {gr.eps0:,.2f} {cur} · **kasv**: {gr.growth:.1%} 1. aastal, "
                f"aeglustub 5 aastaga 6%-ni · **P/E**: praegu {gr.pe_now:.1f} → 5 a pärast {gr.exit_pe:.1f} · "
                f"**dividenditootlus**: {gr.dividend_yield:.1%}")
    if gr.growth_sources:
        st.caption("Kasvu allikad: " + " · ".join(f"{k} {v:+.1%}" for k, v in gr.growth_sources.items()))
    rows = [{"Horisont": f"{p.years} a", "EPS": p.eps, "P/E": p.pe, "Oodatav hind": p.price,
             "Muutus": p.price / snap.price - 1, "Tootlus a/a (koos div.)": p.annual_return} for p in gr.projections]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "EPS": NUM2, "P/E": st.column_config.NumberColumn(format="%.1f"), "Oodatav hind": NUM2, "Muutus": PCT,
        "Tootlus a/a (koos div.)": PCT})

    st.markdown("#### Miks just selline hind? Kust tuleb väärtuse kasv")
    yrs = st.radio("Selgituse horisont", [1, 3, 5], index=2, horizontal=True, format_func=lambda y: f"{y} a",
                   key=f"explain_{sel}")
    d = gr.decompose(yrs)
    if not d:
        return
    pct = lambda r: f"{r - 1:+.0%}"
    share_txt = ("tagasiostud suurendavad kasumit aktsia kohta" if gr.share_change < -0.002 else
                 "uute aktsiate emissioon (aktsiapõhised tasud, ülevõtmised) lahjendab kasumit aktsia kohta"
                 if gr.share_change > 0.002 else "aktsiate arv on püsinud sisuliselt samana")
    pe_txt = (" — kõrge P/E kahaneb, kui kasv aeglustub" if d.pe_ratio < 1 else
              " — madal P/E tõuseb, kui turg firmat ümber hindab" if d.pe_ratio > 1 else "")
    st.markdown(f"""
Aktsia hind = **kasum aktsia kohta (EPS) × P/E** (mitu aastat kasumit investorid aktsia eest maksavad).

| | Praegu | {yrs} a pärast | Muutus |
|---|---|---|---|
| Kasum aktsia kohta (EPS, järgmised 12 k) | {gr.eps0:,.2f} | {gr.eps0 * d.eps_ratio:,.2f} | {pct(d.eps_ratio)} |
| P/E | {gr.pe_now:.1f} | {gr.pe_now * d.pe_ratio:.1f} | {pct(d.pe_ratio)} |
| **Hind** | **{d.price0:,.2f}** | **{d.price_n:,.2f}** | **{pct(d.price_n / d.price0)}** |

**Kasum aktsia kohta muutub {pct(d.eps_ratio)}, sest:**
- **käive** kasvab {pct(d.rev_ratio)} — käibeprognoos {gr.rev_growth if gr.rev_growth is not None else gr.growth:.1%} 1. aastal, aeglustub 5 aastaga 6%-ni;
- **kasumimarginaal** muutub {pct(d.margin_ratio)} — kasumiprognoos ({gr.growth:.1%}) on {"kiirem" if d.margin_ratio > 1 else "aeglasem"} kui käibe kasv;
- **aktsiate arv** muutub {pct(d.share_ratio)} — ajalooline trend {gr.share_change:+.1%} aastas ({share_txt}).

**P/E muutub {pct(d.pe_ratio)}**: praegune {gr.pe_now:.1f} liigub 5 aastaga poole võrra sektori tavapärase taseme
(~{sector_pe(snap.info):.0f}) suunas{pe_txt}.
""")
    steps = [("Käibe kasv", d.revenue_part), ("Marginaal", d.margin_part), ("Aktsiate arv", d.buyback_part),
             ("P/E muutus", d.pe_effect)]
    fig = go.Figure(go.Waterfall(
        x=["Hind praegu"] + [s[0] for s in steps] + [f"Hind {yrs} a pärast", "Dividendid", "Kokku"],
        measure=["absolute"] + ["relative"] * len(steps) + ["total", "relative", "total"],
        y=[d.price0] + [s[1] for s in steps] + [0, d.dividends, 0],
        text=[f"{d.price0:,.0f}"] + [f"{s[1]:+,.0f}" for s in steps] +
             [f"{d.price_n:,.0f}", f"{d.dividends:+,.0f}", f"{d.price_n + d.dividends:,.0f}"],
        textposition="outside", increasing=dict(marker_color=GREEN), decreasing=dict(marker_color=RED),
        totals=dict(marker_color=BLUE), connector=dict(line=dict(color="#95a5a6", width=1))))
    fig.update_layout(height=400, margin=dict(t=40, b=10), showlegend=False,
                      title=f"Kust tuleb hinnamuutus {yrs} aastaga ({cur} aktsia kohta)")
    st.plotly_chart(fig, width="stretch")
    drivers = {"käibe kasv": d.revenue_part, "marginaali muutus": d.margin_part,
               "aktsiate arvu muutus": d.buyback_part, "P/E muutus": d.pe_effect, "dividendid": d.dividends}
    pos, neg = max(drivers, key=drivers.get), min(drivers, key=drivers.get)
    st.info(f"**Suurim kasvu allikas:** {pos} ({drivers[pos]:+,.0f} {cur}). "
            + (f"**Suurim pidur:** {neg} ({drivers[neg]:+,.0f} {cur})." if drivers[neg] < 0 else ""))
    req = gr.required_growth(yrs)
    if req is not None:
        verdict = "eeldus on sellest kõrgem ✅" if gr.growth >= req else "eeldus jääb sellest alla ⚠️"
        st.markdown(f"**Mida praegune hind eeldab?** Et aktsia annaks {yrs} aastaga **10% aastas**, peaks kasum "
                    f"aktsia kohta kasvama keskmiselt **{req:.1%} aastas**. Mudeli 1. aasta kasvueeldus on "
                    f"{gr.growth:.1%} — {verdict}")
    sens = gr.sensitivity(yrs)
    if sens:
        with st.expander(f"Tundlikkus — oodatav hind {yrs} a pärast teiste eeldustega"):
            label = {0.75: "P/E −25%", 1.0: "P/E mudeli järgi", 1.25: "P/E +25%"}
            tbl = pd.DataFrame({label[f]: {f"kasv {gr.growth + g:.0%}": v for g, v in row.items()}
                                for f, row in sens.items()}).T
            st.dataframe(tbl.map(lambda v: f"{v:,.2f} ({v / d.price0 - 1:+.0%})"), width="stretch")
    s = gr.score(horizon)
    st.caption(f"Kasvupotentsiaali skoor ({horizon} a): {s:.0f}/100 — keskmine analüütikute 12 k potentsiaalist "
               "(−10% → 0, +30% → 100) ja mudeli aastatootlusest (−5% → 0, +20% → 100)." if s is not None else "")


def fundamentals_view(ev):
    cats = ev.fundamentals["categories"]
    cols = st.columns(len(cats))
    for col, (c, s) in zip(cols, cats.items()):
        col.metric(c, f"{s:.0f}" if s is not None else "—")
    tech = ev.fundamentals.get("tech")
    if tech:
        st.markdown(f"**Tehnoloogianäitajad** — ärimudel: {tech['model']} (topeltkaaluga)")
        st.dataframe(pd.DataFrame(tech["metrics"]), hide_index=True, width="stretch",
                     column_config={"Skoor": score_col("Skoor")})
        st.markdown("**Üldised näitajad**")
    st.dataframe(pd.DataFrame(ev.fundamentals["metrics"]), hide_index=True, width="stretch",
                 column_config={"Skoor": score_col("Skoor")})


def dcf_view(ev):
    snap = ev.snapshot
    if not ev.dcf:
        st.info(f"DCF pole saadaval: {ev.dcf_reason}")
        return
    d, a = ev.dcf, ev.dcf.assumptions
    m = st.columns(4)
    m[0].metric("Sisemine väärtus", f"{d.intrinsic_per_share:,.2f}")
    mos = d.margin_of_safety
    m[1].metric("Turvamarginaal", f"{mos:+.0%}" if mos is not None else "—")
    m[2].metric("Baas-FCF", fmt_big(d.base_fcf))
    m[3].metric("Omakapitali väärtus", fmt_big(d.equity_value))
    st.markdown(f"**Eeldused:** FCF kasv {a.growth:.1%} (1.–{a.years // 2}. a, siis aeglustub) · diskonto "
                f"{a.discount_rate:.1%} · terminaalne kasv {a.terminal_growth:.1%} · {a.years} aastat")
    if auto:
        st.caption(f"Automaatne: kasv = käibe kasv a/a ({estimate_growth(snap.fcf_history, snap.info):.1%}); "
                   f"diskonto = 4,5% + beeta × 5,5% ({estimate_discount_rate(snap.info.get('beta')):.1%})")
    if d.enterprise_value and d.pv_terminal / d.enterprise_value > 0.75:
        st.warning(f"Terminaalväärtus on {d.pv_terminal / d.enterprise_value:.0%} ettevõtte väärtusest — tulemus "
                   "on eelduste suhtes väga tundlik.")
    hist = snap.fcf_history
    fig = go.Figure()
    fig.add_bar(x=[f"A-{len(hist) - i}" for i in range(len(hist))], y=hist, name="Ajalooline FCF", marker_color=GREY)
    fig.add_bar(x=[f"+{i + 1}" for i in range(len(d.projected_fcf))], y=d.projected_fcf, name="Prognoositud FCF",
                marker_color=BLUE)
    fig.update_layout(height=300, margin=dict(t=30, b=10), title="Vaba rahavoog", legend_orientation="h")
    st.plotly_chart(fig, width="stretch")
    with st.expander("Tundlikkus: diskontomäär × terminaalne kasv"):
        rates = [a.discount_rate + x for x in (-0.02, -0.01, 0, 0.01, 0.02)]
        grid = {}
        for tg in [a.terminal_growth + x for x in (-0.01, -0.005, 0, 0.005, 0.01)]:
            grid[f"g={tg:.1%}"] = {f"{r:.1%}": (run_dcf(d.base_fcf, snap.info["sharesOutstanding"],
                                                        snap.info.get("totalCash") or 0, snap.info.get("totalDebt") or 0,
                                                        DCFAssumptions(a.growth, r, tg, a.years)).intrinsic_per_share
                                                if r > tg else None) for r in rates}
        st.dataframe(pd.DataFrame(grid).T.style.format("{:,.2f}", na_rep="—"), width="stretch")


def technical_view(ev):
    tech = ev.technical
    if tech["score"] is None:
        st.info("Tehniliseks analüüsiks on liiga vähe hinnaajalugu.")
        return
    df = tech["data"]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                                 name="Hind"), 1, 1)
    fig.add_trace(go.Scatter(x=df.index, y=df["SMA50"], name="SMA50", line=dict(width=1.5)), 1, 1)
    fig.add_trace(go.Scatter(x=df.index, y=df["SMA200"], name="SMA200", line=dict(width=1.5)), 1, 1)
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI", line=dict(color="#8e44ad")), 2, 1)
    fig.add_hline(y=70, line_dash="dot", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", row=2, col=1)
    fig.add_trace(go.Bar(x=df.index, y=df["MACD_hist"], name="MACD hist", marker_color="#95a5a6"), 3, 1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD"], name="MACD", line=dict(width=1)), 3, 1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD_signal"], name="Signaal", line=dict(width=1)), 3, 1)
    fig.update_layout(height=620, xaxis_rangeslider_visible=False, margin=dict(t=20, b=10), legend_orientation="h")
    st.plotly_chart(fig, width="stretch")
    st.dataframe(pd.DataFrame(tech["signals"]), hide_index=True, width="stretch",
                 column_config={"Skoor": score_col("Skoor")})


# ====================================================================== leht
names = (["💼 Minu portfell"] if has_portfolio else []) + ["📋 Aktsiate võrdlus", "🔍 Aktsia analüüs"]
main_tabs = dict(zip(names, st.tabs(names)))
if has_portfolio:
    with main_tabs["💼 Minu portfell"]:
        portfolio_tab()
with main_tabs["📋 Aktsiate võrdlus"]:
    comparison_tab()
with main_tabs["🔍 Aktsia analüüs"]:
    stock_tab()

st.divider()
st.caption("⚠️ Automaatne analüüsitööriist, mitte investeerimisnõuanne. Andmed (Yahoo Finance) võivad olla viitega "
           "või vigased; mudelid tuginevad lihtsustatud eeldustele.")
