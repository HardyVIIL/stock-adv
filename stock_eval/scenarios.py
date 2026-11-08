"""Bull / bear analüüs: stsenaariumid (bear/base/bull) ja automaatsed argumendid poolt ja vastu.

Stsenaariumid kasutavad sama EPS × P/E mudelit (vt growth.py), muutes kahte eeldust:
  * Bear: kasumi kasv poole väiksem (−2 %-p), P/E horisondi lõpus 30% madalam – ja mitte kunagi
          kõrgem kui praegu (bear ei eelda, et turg hakkab firmat kõrgemalt hindama)
  * Base: mudeli eeldused
  * Bull: kasumi kasv 25% suurem (+2 %-p), P/E horisondi lõpus 20% kõrgem
Tõenäosused 25 / 50 / 25 annavad kaalutud oodatava hinna. 12 kuu vaates kasutatakse ka
analüütikute madalaimat / keskmist / kõrgeimat sihthinda.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .growth import GrowthResult, growth_path, pe_path, sector_pe

SCENARIOS = (  # nimi, kasvu kordaja, kasvu nihe, P/E kordaja, tõenäosus
    ("Bear", 0.50, -0.02, 0.70, 0.25),
    ("Base", 1.00, 0.00, 1.00, 0.50),
    ("Bull", 1.25, 0.02, 1.20, 0.25),
)


@dataclass
class Scenario:
    name: str
    growth: float
    exit_pe: float
    probability: float
    price: float
    change: float          # hinnamuutus kokku
    annual_return: float   # aastas, koos dividendiga


@dataclass
class Point:
    side: str      # "bull" / "bear"
    theme: str     # Hindamine, Kasv, Kasumlikkus, Bilanss, Trend, Analüütikud
    text: str
    weight: float = 1.0


@dataclass
class BullBear:
    years: int
    price: float | None
    scenarios: list[Scenario] = field(default_factory=list)
    points: list[Point] = field(default_factory=list)

    def scenario(self, name: str) -> Scenario | None:
        return next((s for s in self.scenarios if s.name == name), None)

    @property
    def expected_price(self) -> float | None:
        if not self.scenarios:
            return None
        return sum(s.price * s.probability for s in self.scenarios)

    @property
    def expected_change(self) -> float | None:
        ep = self.expected_price
        return ep / self.price - 1 if ep and self.price else None

    @property
    def reward_risk(self) -> float | None:
        """(bull tõus) / (bear langus). >2 hea asümmeetria; None, kui bear ei lange."""
        bull, bear = self.scenario("Bull"), self.scenario("Bear")
        if not bull or not bear or bear.change >= 0:
            return None
        return max(bull.change, 0) / -bear.change

    @property
    def bull_points(self) -> list[Point]:
        return [p for p in self.points if p.side == "bull"]

    @property
    def bear_points(self) -> list[Point]:
        return [p for p in self.points if p.side == "bear"]

    @property
    def balance(self) -> float | None:
        """Argumentide tasakaal 0..100 (100 = ainult bull-argumendid)."""
        b = sum(p.weight for p in self.bull_points)
        r = sum(p.weight for p in self.bear_points)
        return 100 * b / (b + r) if b + r else None

    @property
    def verdict(self) -> str:
        bal = self.balance
        if bal is None:
            return "—"
        if bal >= 65:
            return "🐂 Pigem bullish"
        if bal <= 35:
            return "🐻 Pigem bearish"
        return "⚖️ Tasakaalus"


def scenarios(gr: GrowthResult, years: int) -> list[Scenario]:
    if gr.eps0 is None or gr.growth is None or gr.exit_pe is None or not gr.pe_now or not gr.price0:
        return []
    out = []
    for name, gmul, gadd, pemul, prob in SCENARIOS:
        g = max(-0.15, min(0.45, gr.growth * gmul + gadd))
        exit_pe = gr.exit_pe * pemul
        if name == "Bear":
            exit_pe = min(exit_pe, gr.pe_now * 0.9)
        eps = gr.eps0
        for gk in growth_path(g, years):
            eps *= 1 + gk
        price = eps * pe_path(gr.pe_now, exit_pe, years)[-1]
        ann = (price / gr.price0) ** (1 / years) - 1 + gr.dividend_yield if price > 0 else -1.0
        out.append(Scenario(name, g, exit_pe, prob, price, price / gr.price0 - 1, ann))
    return out


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def collect_points(ev) -> list[Point]:
    """Koostab argumendid hindamise (scoring.Evaluation) andmetest."""
    info, snap, gr = ev.snapshot.info, ev.snapshot, ev.growth
    pts: list[Point] = []
    add = lambda side, theme, text, w=1.0: pts.append(Point(side, theme, text, w))
    price = snap.price

    # Analüütikud
    a = gr.analyst
    if a:
        rec = {"strong_buy": "tugev ost", "buy": "ost", "hold": "hoia", "underperform": "alla turu",
               "sell": "müü"}.get(a.recommendation_key or "", a.recommendation_key or "")
        if a.upside >= 0.15:
            add("bull", "Analüütikud", f"Keskmine sihthind {a.mean:,.2f} ehk {a.upside:+.0%} "
                f"({a.count} analüütikut, konsensus: {rec})", 1.5)
        elif a.upside <= 0.0:
            add("bear", "Analüütikud", f"Hind on juba üle keskmise sihthinna ({a.upside:+.0%}, {a.count} analüütikut)",
                1.5)
        if a.low and price and a.low / price - 1 <= -0.20:
            add("bear", "Analüütikud", f"Pessimistlikum analüütik näeb hinda {a.low:,.2f} ({a.low / price - 1:+.0%})",
                0.5)

    # Kasv
    tech = (ev.fundamentals.get("tech") or {}).get("raw", {})
    rg = tech.get("rev_growth") if tech.get("rev_growth") is not None else _num(info.get("revenueGrowth"))
    if rg is not None:
        if rg >= 0.15:
            add("bull", "Kasv", f"Käive kasvab kiiresti: {rg:+.0%} aastas", 1.5)
        elif rg < 0.03:
            add("bear", "Kasv", f"Käibe kasv on aeglane: {rg:+.0%} aastas", 1.5)
    eg = snap.estimates.get("eps_growth_1y")
    if eg is not None:
        if eg >= 0.15:
            add("bull", "Kasv", f"Analüütikud ootavad järgmisel aastal kasumi kasvu {eg:+.0%}")
        elif eg < 0:
            add("bear", "Kasv", f"Analüütikud ootavad järgmisel aastal kasumi langust ({eg:+.0%})")

    # Tehnoloogianäitajad
    r40 = tech.get("rule40")
    if r40 is not None:
        if r40 >= 40:
            add("bull", "Kasumlikkus", f"Rule of 40 = {r40:.0f} (≥40: kasv ja rahavoog tasakaalus)", 1.5)
        elif r40 < 25:
            add("bear", "Kasumlikkus", f"Rule of 40 = {r40:.0f} (alla 25: nõrk kasvu ja kasumlikkuse kombinatsioon)",
                1.5)
    sbc = tech.get("sbc_pct")
    if sbc is not None and sbc > 0.15:
        add("bear", "Kasumlikkus", f"Aktsiapõhised tasud on {sbc:.0%} käibest – lahjendab aktsionäre")
    gmt = tech.get("gross_margin_trend")
    if gmt is not None:
        if gmt <= -0.02:
            add("bear", "Kasumlikkus", f"Brutomarginaal langeb ({gmt:+.1%} 2 aastaga)")
        elif gmt >= 0.02:
            add("bull", "Kasumlikkus", f"Brutomarginaal paraneb ({gmt:+.1%} 2 aastaga)")
    inv = tech.get("inventory_vs_revenue")
    if inv is not None and inv > 0.20:
        add("bear", "Bilanss", f"Laovarud kasvavad käibest {inv:.0%} kiiremini – võimalik nõudluse jahtumine", 1.5)

    # Kasumlikkus (üldine)
    pm = _num(info.get("profitMargins"))
    if pm is not None:
        if pm >= 0.20:
            add("bull", "Kasumlikkus", f"Kõrge puhaskasumi marginaal ({pm:.0%})")
        elif pm < 0.05:
            add("bear", "Kasumlikkus", f"Madal puhaskasumi marginaal ({pm:.0%})")
    roe = _num(info.get("returnOnEquity"))
    if roe is not None and roe >= 0.20:
        add("bull", "Kasumlikkus", f"Kõrge omakapitali tootlus (ROE {roe:.0%})")

    # Hindamine
    if gr.pe_now:
        ref = sector_pe(info)
        if gr.pe_now > 1.5 * ref:
            add("bear", "Hindamine", f"Kallis: P/E {gr.pe_now:.0f} vs sektori tavapärane ~{ref:.0f}", 1.5)
        elif gr.pe_now < 0.4 * ref:
            add("bull", "Hindamine", f"Väga madal P/E {gr.pe_now:.0f} (sektoris ~{ref:.0f}) – kas tõeliselt odav "
                "või näeb turg riske, mida numbrid ei näita", 0.5)
        elif gr.pe_now < 0.8 * ref:
            add("bull", "Hindamine", f"Soodne: P/E {gr.pe_now:.0f} vs sektori tavapärane ~{ref:.0f}", 1.5)
    peg = _num(info.get("pegRatio")) or _num(info.get("trailingPegRatio"))
    if peg is not None and peg > 0:
        if peg <= 1.2:
            add("bull", "Hindamine", f"PEG {peg:.1f} – hind on kasvuga võrreldes mõistlik")
        elif peg >= 2.5:
            add("bear", "Hindamine", f"PEG {peg:.1f} – maksad kasvu eest palju")
    if ev.dcf and ev.dcf.margin_of_safety is not None:
        mos = ev.dcf.margin_of_safety
        if mos >= 0.20:
            add("bull", "Hindamine", f"DCF sisemine väärtus on hinnast kõrgem (turvamarginaal {mos:+.0%})")
        elif mos <= -0.30:
            add("bear", "Hindamine", f"DCF järgi on hind rahavoogudest kõrgel (turvamarginaal {mos:+.0%})")

    # Bilanss
    de = _num(info.get("debtToEquity"))
    if de is not None:
        if 0 <= de / 100 < 0.5:
            add("bull", "Bilanss", f"Vähe võlga (võlg/omakapital {de / 100:.2f})", 0.5)
        elif de / 100 > 1.5:
            add("bear", "Bilanss", f"Palju võlga (võlg/omakapital {de / 100:.2f})")
    if gr.share_change <= -0.01:
        add("bull", "Bilanss", f"Tagasiostud vähendavad aktsiate arvu {gr.share_change:+.1%} aastas")
    elif gr.share_change >= 0.02:
        add("bear", "Bilanss", f"Aktsiate arv kasvab {gr.share_change:+.1%} aastas (lahjendus)")
    if gr.dividend_yield >= 0.03:
        add("bull", "Bilanss", f"Dividenditootlus {gr.dividend_yield:.1%}")

    # Trend
    df = ev.technical.get("data")
    if df is not None and not df.empty and "SMA200" in df:
        last = df.iloc[-1]
        close, sma200, rsi = float(last["Close"]), _num(last["SMA200"]), _num(last["RSI"])
        if sma200:
            if close > sma200 and _num(last["SMA50"]) and last["SMA50"] > sma200:
                add("bull", "Trend", f"Tõusutrend: hind {close / sma200 - 1:+.0%} üle 200 päeva keskmise")
            elif close < sma200:
                add("bear", "Trend", f"Langustrend: hind {close / sma200 - 1:+.0%} alla 200 päeva keskmise")
        if rsi is not None and rsi > 70:
            add("bear", "Trend", f"Üleostetud (RSI {rsi:.0f}) – lühiajalise tagasilöögi risk", 0.5)
        elif rsi is not None and rsi < 30:
            add("bull", "Trend", f"Ülemüüdud (RSI {rsi:.0f}) – võimalik põrge", 0.5)
        n = min(126, len(df) - 1)
        mom = close / float(df["Close"].iloc[-n - 1]) - 1
        if mom >= 0.20:
            add("bull", "Trend", f"Tugev hoog: {mom:+.0%} 6 kuuga", 0.5)
        elif mom <= -0.15:
            add("bear", "Trend", f"Nõrk hoog: {mom:+.0%} 6 kuuga", 0.5)
        vol = float(df["Close"].pct_change().tail(252).std() * 252 ** 0.5)
        if vol > 0.50:
            add("bear", "Trend", f"Väga kõikuv aktsia (aastane volatiilsus {vol:.0%})", 0.5)
    return pts


def analyze(ev, years: int) -> BullBear:
    gr = ev.growth
    return BullBear(years=years, price=ev.snapshot.price, scenarios=scenarios(gr, years),
                    points=collect_points(ev))
