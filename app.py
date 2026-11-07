"""Aktsiate evalueerimise dashboard.  Käivita:  streamlit run app.py"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from pathlib import Path

import yfinance as yf

from stock_eval.data import fetch_snapshot
from stock_eval.dcf import estimate_discount_rate, estimate_growth
from stock_eval.fundamentals import CATEGORIES
from stock_eval.portfolio import fx_symbol, holdings_table, normalize_currency, parse_yahoo_csv, weighted_score
from stock_eval.scoring import evaluate, rating

st.set_page_config(page_title="Aktsiate evalueerija", page_icon="📈", layout="wide")
PORTFOLIO_FILE = Path(__file__).parent / "portfolio.csv"  # isiklik, .gitignore's
BASE_CURRENCY = "EUR"


@st.cache_data(ttl=3600, show_spinner=False)
def load(ticker: str):
    return fetch_snapshot(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def fx_rate(currency: str, base: str = BASE_CURRENCY) -> float | None:
    """Viimane valuutakurss currency -> base Yahoo'st."""
    if currency == base:
        return 1.0
    try:
        h = yf.Ticker(fx_symbol(currency, base)).history(period="5d")
        return float(h["Close"].dropna().iloc[-1]) if not h.empty else None
    except Exception:
        return None


def fmt_big(v: float | None) -> str:
    if v is None:
        return "—"
    for div, suf in ((1e12, " T"), (1e9, " mld"), (1e6, " mln")):
        if abs(v) >= div:
            return f"{v / div:,.2f}{suf}"
    return f"{v:,.0f}"


# ---------------- Külgriba ----------------
with st.sidebar:
    st.header("Aktsiad")
    source = st.radio("Allikas", ["Minu Yahoo portfell", "Käsitsi"], horizontal=True,
                      index=0 if PORTFOLIO_FILE.exists() else 1)
    portfolio = None
    if source == "Minu Yahoo portfell":
        up = st.file_uploader("Yahoo Finance eksport (quotes.csv)", type="csv",
                              help="Yahoo Finance → My Portfolio → vali portfell → Export")
        if up is not None:
            PORTFOLIO_FILE.write_bytes(up.getvalue())  # jäetakse meelde järgmiseks korraks
        if PORTFOLIO_FILE.exists():
            try:
                portfolio = parse_yahoo_csv(PORTFOLIO_FILE)
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

    st.header("Kaalud")
    w_f = st.slider("Fundamentaalanalüüs", 0, 100, 50, 5)
    w_d = st.slider("DCF", 0, 100, 30, 5)
    w_t = st.slider("Tehniline analüüs", 0, 100, 20, 5)
    weights = {"fundamental": w_f, "dcf": w_d, "technical": w_t}

    st.header("DCF eeldused")
    auto = st.checkbox("Automaatsed (kasv ajaloost, diskonto CAPM-ist)", value=True)
    dcf_over: dict = {}
    if not auto:
        dcf_over["growth"] = st.slider("FCF kasv (1. etapp), %", -10.0, 30.0, 8.0, 0.5) / 100
        dcf_over["discount_rate"] = st.slider("Diskontomäär (WACC), %", 5.0, 16.0, 9.0, 0.25) / 100
    dcf_over["terminal_growth"] = st.slider("Terminaalne kasv, %", 0.0, 4.0, 2.5, 0.25) / 100
    dcf_over["years"] = st.select_slider("Prognoosiperiood (aastat)", [5, 8, 10, 15], 10)

    if st.button("Värskenda andmeid"):
        load.clear()

st.title("📈 Aktsiate evalueerija")
st.caption("Fundamentaalanalüüs · DCF hindamine · Tehniline analüüs — andmed: Yahoo Finance")

if not tickers:
    st.info("Lisa külgribale vähemalt üks ticker.")
    st.stop()

# ---------------- Andmed + hindamine ----------------
evals, errors = {}, []
progress = st.progress(0.0, "Laen andmeid…")
for i, t in enumerate(tickers):
    progress.progress((i + 1) / len(tickers), f"Laen {t}…")
    try:
        evals[t] = evaluate(load(t), weights, dcf_over)
    except Exception as e:  # võrgu- või andmeviga ühe tickeri puhul ei tohi kogu lehte murda
        errors.append(f"**{t}**: {e}")
progress.empty()
for e in errors:
    st.warning(e)
if not evals:
    st.stop()

# ---------------- Koondtabel ----------------
summary = pd.DataFrame([e.summary_row() for e in evals.values()]).sort_values(
    "Koondskoor", ascending=False, na_position="last")
score_col = lambda label: st.column_config.ProgressColumn(label, min_value=0, max_value=100, format="%.0f")

# ---------------- Minu portfell ----------------
if portfolio is not None and (portfolio["Kogus"] > 0).any():
    st.subheader("Minu portfell")
    currencies = {t: e.snapshot.info.get("currency") for t, e in evals.items()}
    fx = {}
    for c in {normalize_currency(c)[0] for c in currencies.values() if c}:
        rate = fx_rate(c)
        if rate is not None:
            fx[c] = rate
    h = holdings_table(portfolio, {t: e.snapshot.price for t, e in evals.items()},
                       {t: e.total for t, e in evals.items()}, currencies, fx, BASE_CURRENCY)
    h["Hinnang"] = h["Koondskoor"].map(rating)
    val_col = f"Väärtus ({BASE_CURRENCY})"

    # Kasum/kahjum baasvaluutas (praeguse kursiga)
    to_base = h[val_col] / h["Turuväärtus"]
    pl_base = (h["Kasum/kahjum"] * to_base).sum(min_count=1)
    inv_base = (h["Investeeritud"] * to_base).sum(min_count=1)
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Portfelli väärtus ({BASE_CURRENCY})", f"{h[val_col].sum():,.2f}")
    c2.metric(f"Kasum/kahjum ({BASE_CURRENCY})", f"{pl_base:+,.2f}" if pd.notna(pl_base) else "—",
              f"{pl_base / inv_base:+.1%}" if pd.notna(pl_base) and inv_base else None)
    ps = weighted_score(h)
    c3.metric("Portfelli koondskoor", f"{ps:.0f}" if ps is not None else "—", rating(ps), delta_color="off")
    missing = sorted({normalize_currency(c)[0] for c in h["Valuuta"] if c} - set(fx) - {BASE_CURRENCY})
    st.caption(f"Väärtused on teisendatud eurodesse praeguse kursiga. Kasum/kahjum ei arvesta valuutakursi "
               f"muutust ostuhetkest." + (f" Kurss puudub: {', '.join(missing)}." if missing else ""))

    st.dataframe(h, hide_index=True, width="stretch", column_config={
        "Kogus": st.column_config.NumberColumn(format="%.4g"),
        "Keskmine ostuhind": st.column_config.NumberColumn(format="%.2f"),
        "Investeeritud": st.column_config.NumberColumn(format="%.2f"),
        "Hind": st.column_config.NumberColumn(format="%.2f"),
        "Turuväärtus": st.column_config.NumberColumn(format="%.2f"),
        "Kasum/kahjum": st.column_config.NumberColumn(format="%+.2f"),
        "Tootlus": st.column_config.NumberColumn(format="percent"),
        f"Väärtus ({BASE_CURRENCY})": st.column_config.NumberColumn(format="%.2f"),
        "Osakaal": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
        "Koondskoor": score_col("Koondskoor"),
    })
    weak = h[h["Koondskoor"] < 40]
    if not weak.empty:
        st.info("Nõrga koondskooriga positsioonid (<40): " + ", ".join(
            f"{r.Ticker} ({r.Osakaal:.0%} portfellist)" for r in weak.itertuples()) +
            " — vaata detailvaatest, milline osaskoor neid alla tõmbab.")
    st.divider()

st.subheader("Koondvaade")
st.dataframe(
    summary,
    hide_index=True,
    width="stretch",
    column_config={
        "Hind": st.column_config.NumberColumn(format="%.2f"),
        "Sisemine väärtus": st.column_config.NumberColumn(format="%.2f"),
        "Turvamarginaal": st.column_config.NumberColumn(format="percent"),
        "Fundamentaal": score_col("Fundamentaal"),
        "DCF": score_col("DCF"),
        "Tehniline": score_col("Tehniline"),
        "Koondskoor": score_col("Koondskoor"),
    },
)
st.download_button("Laadi alla CSV", summary.to_csv(index=False).encode("utf-8"),
                   "aktsiate_hinnang.csv", "text/csv")

# Kategooriate võrdlus
cat_rows = []
for t, e in evals.items():
    for c in CATEGORIES:
        cat_rows.append({"Ticker": t, "Kategooria": c, "Skoor": e.fundamentals["categories"][c]})
cat_df = pd.DataFrame(cat_rows).dropna()
if not cat_df.empty:
    fig = go.Figure()
    for c in CATEGORIES:
        sub = cat_df[cat_df["Kategooria"] == c]
        fig.add_bar(name=c, x=sub["Ticker"], y=sub["Skoor"])
    fig.update_layout(barmode="group", height=320, yaxis_range=[0, 100], margin=dict(t=30, b=10),
                      title="Fundamentaalkategooriad", legend_orientation="h")
    st.plotly_chart(fig, width="stretch")

# ---------------- Detailvaade ----------------
st.divider()
st.subheader("Detailvaade")
sel = st.selectbox("Vali aktsia", summary["Ticker"].tolist(),
                   format_func=lambda t: f"{t} — {evals[t].snapshot.name}")
ev = evals[sel]
snap = ev.snapshot
cur = snap.info.get("currency") or ""

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Hind", f"{snap.price:,.2f} {cur}" if snap.price else "—")
c2.metric("Turuväärtus", fmt_big(snap.info.get("marketCap")))
c3.metric("Koondskoor", f"{ev.total:.0f}" if ev.total is not None else "—", rating(ev.total), delta_color="off")
c4.metric("Sisemine väärtus (DCF)", f"{ev.dcf.intrinsic_per_share:,.2f}" if ev.dcf else "—")
mos = ev.dcf.margin_of_safety if ev.dcf else None
c5.metric("Turvamarginaal", f"{mos:+.0%}" if mos is not None else "—")

tab_f, tab_d, tab_t = st.tabs(["Fundamentaalanalüüs", "DCF hindamine", "Tehniline analüüs"])

with tab_f:
    st.caption(f"{snap.info.get('sector') or ''} · {snap.info.get('industry') or ''}")
    cols = st.columns(len(CATEGORIES))
    for col, c in zip(cols, CATEGORIES):
        s = ev.fundamentals["categories"][c]
        col.metric(c, f"{s:.0f}" if s is not None else "—")
    st.dataframe(pd.DataFrame(ev.fundamentals["metrics"]), hide_index=True, width="stretch",
                 column_config={"Skoor": score_col("Skoor")})

with tab_d:
    if not ev.dcf:
        st.info(f"DCF pole saadaval: {ev.dcf_reason}")
    else:
        d = ev.dcf
        a = d.assumptions
        st.markdown(
            f"**Eeldused:** FCF kasv {a.growth:.1%} (1.–{a.years // 2}. a, siis sulandub) · "
            f"diskonto {a.discount_rate:.1%} · terminaalne kasv {a.terminal_growth:.1%} · {a.years} aastat"
        )
        if auto:
            st.caption(f"Automaatne: kasv = käibe kasv a/a (varuna FCF CAGR) "
                       f"({estimate_growth(snap.fcf_history, snap.info):.1%}); "
                       f"diskonto = 4,5% + beeta × 5,5% ({estimate_discount_rate(snap.info.get('beta')):.1%})")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Baas-FCF", fmt_big(d.base_fcf))
        m2.metric("PV rahavood", fmt_big(d.pv_fcf))
        m3.metric("PV terminaalväärtus", fmt_big(d.pv_terminal))
        m4.metric("Omakapitali väärtus", fmt_big(d.equity_value))
        if d.enterprise_value and d.pv_terminal / d.enterprise_value > 0.75:
            st.warning(f"Terminaalväärtus moodustab {d.pv_terminal / d.enterprise_value:.0%} "
                       "ettevõtte väärtusest — tulemus on eelduste suhtes väga tundlik.")

        hist = snap.fcf_history
        fig = go.Figure()
        fig.add_bar(x=[f"A-{len(hist) - i}" for i in range(len(hist))], y=hist, name="Ajalooline FCF",
                    marker_color="#7f8c8d")
        fig.add_bar(x=[f"+{i + 1}" for i in range(len(d.projected_fcf))], y=d.projected_fcf,
                    name="Prognoositud FCF", marker_color="#2e86de")
        fig.update_layout(height=320, margin=dict(t=30, b=10), title="Vaba rahavoog", legend_orientation="h")
        st.plotly_chart(fig, width="stretch")

        # Tundlikkustabel: diskonto x terminaalne kasv
        from stock_eval.dcf import DCFAssumptions, run_dcf
        rates = [a.discount_rate + x for x in (-0.02, -0.01, 0, 0.01, 0.02)]
        tgs = [a.terminal_growth + x for x in (-0.01, -0.005, 0, 0.005, 0.01)]
        grid = {}
        for tg in tgs:
            row = {}
            for r in rates:
                if r <= tg:
                    row[f"{r:.1%}"] = None
                    continue
                res = run_dcf(d.base_fcf, snap.info["sharesOutstanding"], snap.info.get("totalCash") or 0,
                              snap.info.get("totalDebt") or 0, DCFAssumptions(a.growth, r, tg, a.years))
                row[f"{r:.1%}"] = res.intrinsic_per_share
            grid[f"g={tg:.1%}"] = row
        st.markdown("**Tundlikkus** — sisemine väärtus aktsia kohta (veerud: diskontomäär)")
        st.dataframe(pd.DataFrame(grid).T.style.format("{:,.2f}", na_rep="—"), width="stretch")

with tab_t:
    tech = ev.technical
    if tech["score"] is None:
        st.info("Tehniliseks analüüsiks on liiga vähe hinnaajalugu.")
    else:
        df = tech["data"]
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2],
                            vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"],
                                     close=df["Close"], name="Hind"), 1, 1)
        fig.add_trace(go.Scatter(x=df.index, y=df["SMA50"], name="SMA50", line=dict(width=1.5)), 1, 1)
        fig.add_trace(go.Scatter(x=df.index, y=df["SMA200"], name="SMA200", line=dict(width=1.5)), 1, 1)
        fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI", line=dict(color="#8e44ad")), 2, 1)
        fig.add_hline(y=70, line_dash="dot", row=2, col=1)
        fig.add_hline(y=30, line_dash="dot", row=2, col=1)
        fig.add_trace(go.Bar(x=df.index, y=df["MACD_hist"], name="MACD hist", marker_color="#95a5a6"), 3, 1)
        fig.add_trace(go.Scatter(x=df.index, y=df["MACD"], name="MACD", line=dict(width=1)), 3, 1)
        fig.add_trace(go.Scatter(x=df.index, y=df["MACD_signal"], name="Signaal", line=dict(width=1)), 3, 1)
        fig.update_layout(height=650, xaxis_rangeslider_visible=False, margin=dict(t=20, b=10),
                          legend_orientation="h")
        st.plotly_chart(fig, width="stretch")
        st.dataframe(pd.DataFrame(tech["signals"]), hide_index=True, width="stretch",
                     column_config={"Skoor": score_col("Skoor")})

st.divider()
st.caption("⚠️ Tegu on automaatse analüüsitööriistaga, mitte investeerimisnõuandega. Andmed võivad olla "
           "viitega, puudulikud või vigased; mudelid tuginevad lihtsustatud eeldustele.")
