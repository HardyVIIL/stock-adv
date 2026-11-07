"""Aktsiate evalueerimise dashboard.  Käivita:  streamlit run app.py"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from stock_eval.data import fetch_snapshot
from stock_eval.dcf import estimate_discount_rate, estimate_growth
from stock_eval.fundamentals import CATEGORIES
from stock_eval.scoring import evaluate, rating

st.set_page_config(page_title="Aktsiate evalueerija", page_icon="📈", layout="wide")


@st.cache_data(ttl=3600, show_spinner=False)
def load(ticker: str):
    return fetch_snapshot(ticker)


def fmt_big(v: float | None) -> str:
    if v is None:
        return "—"
    for div, suf in ((1e12, " T"), (1e9, " mld"), (1e6, " mln")):
        if abs(v) >= div:
            return f"{v / div:,.2f}{suf}"
    return f"{v:,.0f}"


# ---------------- Külgriba ----------------
with st.sidebar:
    st.header("Jälgimisnimekiri")
    raw = st.text_area("Tickerid (koma või reavahetusega)", "AAPL, MSFT, GOOGL, NVDA, ASML, KO",
                       help="Yahoo Finance tähised, nt Tallinna börs: LHV1T.TL, Helsingi: NOKIA.HE")
    tickers = list(dict.fromkeys(t.strip().upper() for t in raw.replace("\n", ",").split(",") if t.strip()))

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

st.subheader("Koondvaade")
score_col = lambda label: st.column_config.ProgressColumn(label, min_value=0, max_value=100, format="%.0f")
st.dataframe(
    summary,
    hide_index=True,
    use_container_width=True,
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
    st.plotly_chart(fig, use_container_width=True)

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
    st.dataframe(pd.DataFrame(ev.fundamentals["metrics"]), hide_index=True, use_container_width=True,
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
        st.plotly_chart(fig, use_container_width=True)

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
        st.dataframe(pd.DataFrame(grid).T.style.format("{:,.2f}", na_rep="—"), use_container_width=True)

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
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(pd.DataFrame(tech["signals"]), hide_index=True, use_container_width=True,
                     column_config={"Skoor": score_col("Skoor")})

st.divider()
st.caption("⚠️ Tegu on automaatse analüüsitööriistaga, mitte investeerimisnõuandega. Andmed võivad olla "
           "viitega, puudulikud või vigased; mudelid tuginevad lihtsustatud eeldustele.")
