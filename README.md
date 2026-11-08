# Aktsiate evalueerija

Interaktiivne dashboard, mis hindab aktsiaid automaatselt kolme meetodiga ja annab igale skoori 0–100.
Andmed tulevad Yahoo Finance'ist (`yfinance`, API-võtit pole vaja).

## Käivitamine

```bash
./run.sh
```

Avaneb <http://localhost:8501>. Külgribal saab muuta jälgimisnimekirja, meetodite kaale ja DCF eeldusi.

## Lehe ülesehitus

| Sakk | Sisu |
|---|---|
| 💼 **Minu portfell** | Väärtus, kasum, koondskoor; bear/base/bull väärtus valitud horisondil; alamsakid: positsioonid, bull/bear vahemikud, kasvu allikad, võrdlus indeksiga |
| 📋 **Aktsiate võrdlus** | Riski/tulu kaart (bear vs bull), koondtabel (kõik veerud lülitiga), fundamentaalkategooriad |
| 🔍 **Aktsia analüüs** | Bull vs bear kokkuvõte (osaskoorid, argumendid poolt ja vastu, stsenaariumid, hinnarada), kasvupotentsiaal, fundamentaal, DCF, tehniline |

Ajahorisont (1/3/5 a) on külgriba ülaosas ja kehtib kõikjal; muud seaded on kokkuvolditavates gruppides.

## Bull / bear analüüs

- **Stsenaariumid** (sama EPS × P/E mudel): bear = kasv ½ −2 %-p ja P/E −30% (mitte kunagi kõrgem kui praegu),
  base = mudel, bull = kasv ×1,25 +2 %-p ja P/E +20%. Tõenäosused 25/50/25 → kaalutud oodatav hind.
  **Tulu/risk** = bull tõus / bear langus (>2 soodne asümmeetria).
- **Argumendid** pannakse automaatselt kokku näitajatest (analüütikud, kasv, Rule of 40, SBC, marginaalid,
  laovarud, P/E vs sektor, PEG, DCF, võlg, tagasiostud/lahjendus, dividend, trend, RSI, volatiilsus);
  olulisemad kaaluvad rohkem. **Vaade** = argumentide tasakaal: ≥65 pigem bullish, ≤35 pigem bearish.

## Oma Yahoo Finance portfell

1. Ava [finance.yahoo.com](https://finance.yahoo.com) → **My Portfolio** → vali portfell.
2. Vajuta **Export** – alla laaditakse fail `quotes.csv`.
3. Dashboardis vali külgribal **Allikas → Minu Yahoo portfell** ja laadi fail üles.

Fail salvestatakse projekti kausta nimega `portfolio.csv` (on `.gitignore`'is, GitHubi ei lähe),
nii et järgmisel käivitamisel laetakse see automaatselt. Portfelli muutudes ekspordi ja laadi uuesti üles.

Portfelli vaates näed iga positsiooni kogust, keskmist ostuhinda, turuväärtust, kasumit/kahjumit,
osakaalu ja koondskoori ning kogu portfelli turuväärtusega kaalutud koondskoori. Mitme valuuta
korral näidatakse summad valuutade kaupa. Ilma koguseta read (jälgimisnimekiri) hinnatakse, aga
positsioonidena ei arvestata.

## Võrdlus indeksiga

Portfelli vaate all on kaks võrdlust (indeks valitakse külgribalt: QQQ, XLK, SMH, SPY, URTH):

- **Minu ostud vs indeks** – iga ost (Yahoo ekspordi rida) võrreldakse sellega, kui sama summa eurodes oleks
  samal päeval pandud indeksisse. Valuutakursid on arvestatud mõlemal poolel, dividende kummalgi mitte.
  See vastab küsimusele: *kas minu aktsiavalik on toonud rohkem kui lihtsalt indeksifond?*
- **Praeguse koosseisu ajalugu** – praegune portfell praeguste osakaaludega 1/3/5 aasta peale vs indeksid,
  koos aastase tootluse ja suurima langusega. NB! Sellel on tagantjärele tarkuse viga: praegu portfellis olevad
  aktsiad on sageli need, mis on hästi läinud.

- **Järelejõudmine** – kas indeksist maas olev positsioon jõuab 3/5/10 aastaga järele (ja kas ees olev püsib ees)?
  Vajalik aastatootlus = (indeksis oleks / praegu)^(1/N) × (1 + indeksi oodatav tootlus) − 1, mida võrreldakse
  aktsia bear/base/bull aastatootlusega. Tõenäosus on ligikaudne (stsenaariumid = 15./50./85. protsentiil).
  Indeksi oodatava tootluse saab külgribal muuta (vaikimisi 9% aastas).

**0-hinnaga read:** kui rida jääb aktsia tükelduse lähedale (−5…+45 päeva), loetakse see tükelduse kirjeks.
Muud 0-hinnaga read (nt tulemustasuna saadud aktsiad) jäetakse võrdlusest vaikimisi välja, sest need pole
ostuotsused (külgribalt saab kaasata).

**Tükeldused:** kui tükeldus on failis märgitud 0-hinnaga reaga, ei muudeta midagi. Muidu võrreldakse iga
tükeldusele eelneva ostu hinda tolle päeva (tükeldustega korrigeeritud) turuhinnaga: kui ostuhind on juba
ümber arvutatud, jääb rida puutumata, muidu korrigeeritakse kogus ja hind automaatselt (dashboard näitab märget).

## Meetodid

| Meetod | Mida hinnatakse | Moodul |
|---|---|---|
| **Fundamentaalanalüüs** | Hindamine (P/E, PEG, EV/EBITDA, P/B), kasumlikkus (ROE, marginaalid), kasv (käive, kasum), finantstervis (D/E, likviidsus). Iga näitaja → 0–100 lineaarse skaala järgi, kategooriad keskmistatakse. | `stock_eval/fundamentals.py` |
| **Tehnoloogianäitajad** | Ainult tehnoloogiafirmadele, topeltkaaluga fundamentaalskooris: Rule of 40 (käibe kasv % + FCF marginaal %), sama ilma aktsiapõhiste tasudeta (SBC), SBC % käibest, brutomarginaal ja selle muutus (skaala sõltub ärimudelist: tarkvara/kiibid/riistvara/internet), EV/Sales ÷ kasv, kiipide ja riistvara puhul laovarude kasv vs käibe kasv. | `stock_eval/tech.py` |
| **DCF** | Kaheetapiline FCF mudel: baas = viimase aasta FCF aruandest; kasv = käibe kasv (piiratud −5%…20%), mis teises pooles sulandub terminaalsesse kasvu; diskonto CAPM-ist (4,5% + β·5,5%, piiratud 7–14%). Skoor tuleb turvamarginaalist (−50% → 0, +40% → 100). Pankadele ja negatiivse FCF-iga ettevõtetele DCF-i ei arvutata. | `stock_eval/dcf.py` |
| **Kasvupotentsiaal** | (1) Analüütikute 12 kuu konsensus: keskmine/madalaim/kõrgeim sihthind, potentsiaal, analüütikute arv ja soovitus. (2) Kasumipõhine prognoos 1/3/5 aastaks: järgmise 12 k EPS × kasv (analüütikute EPS- ja käibeprognoos, sulandub 5 aastaga 6%-ni) × P/E, mis liigub 5 aastaga poole võrra sektori tüüpilise P/E suunas. Annab oodatava hinna ja aastase tootluse (koos dividendiga). Skoor = keskmine analüütikute potentsiaalist (−10%→0, +30%→100) ja mudeli aastatootlusest (−5%→0, +20%→100). Ajahorisont valitakse külgribalt. | `stock_eval/growth.py` |
| **Hinna selgitus** | Kasvupotentsiaali sakis „Miks just selline hind?”: hind = EPS × P/E; EPS muutus jagatakse käibe kasvuks, marginaali muutuseks ja aktsiate arvu muutuseks (tagasiostud/lahjendus, ajaloolise trendi järgi), lisaks P/E muutus ja dividendid. Kosk-graafik, suurim kasvu allikas ja pidur, „mida praegune hind eeldab” (kasv, mis on vaja 10% aastatootluseks) ja tundlikkustabel. Portfelli vaates sama jaotus eurodes positsioonide kaupa. | `stock_eval/growth.py` |
| **Tehniline analüüs** | Hind vs SMA200, SMA50/200 rist, RSI(14), MACD, 6 kuu momentum, volatiilsus. | `stock_eval/technical.py` |

Koondskoor = kaalutud keskmine (vaikimisi fundamentaal 40, DCF 20, tehniline 15, kasvupotentsiaal 25). Puuduv osaskoor jäetakse välja ja kaalud normaliseeritakse.
Hinnangud: ≥70 Tugev, ≥55 Hea, ≥40 Neutraalne, alla selle Nõrk.

Lävendid (mis on "hea" ja "halb" väärtus) on `RULES` loendis failis `fundamentals.py` — muuda neid oma strateegia järgi.

## Testid

```bash
.venv/bin/python -m pytest -q
```

## Hoiatus

Automaatne analüüsitööriist, mitte investeerimisnõuanne. Yahoo andmed võivad olla viitega või vigased
ning DCF tulemus on eelduste (eriti kasvu ja diskontomäära) suhtes väga tundlik.
