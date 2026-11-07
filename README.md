# Aktsiate evalueerija

Interaktiivne dashboard, mis hindab aktsiaid automaatselt kolme meetodiga ja annab igale skoori 0–100.
Andmed tulevad Yahoo Finance'ist (`yfinance`, API-võtit pole vaja).

## Käivitamine

```bash
./run.sh
```

Avaneb <http://localhost:8501>. Külgribal saab muuta jälgimisnimekirja, meetodite kaale ja DCF eeldusi.

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

## Meetodid

| Meetod | Mida hinnatakse | Moodul |
|---|---|---|
| **Fundamentaalanalüüs** | Hindamine (P/E, PEG, EV/EBITDA, P/B), kasumlikkus (ROE, marginaalid), kasv (käive, kasum), finantstervis (D/E, likviidsus). Iga näitaja → 0–100 lineaarse skaala järgi, kategooriad keskmistatakse. | `stock_eval/fundamentals.py` |
| **DCF** | Kaheetapiline FCF mudel: baas = viimase aasta FCF aruandest; kasv = käibe kasv (piiratud −5%…20%), mis teises pooles sulandub terminaalsesse kasvu; diskonto CAPM-ist (4,5% + β·5,5%, piiratud 7–14%). Skoor tuleb turvamarginaalist (−50% → 0, +40% → 100). Pankadele ja negatiivse FCF-iga ettevõtetele DCF-i ei arvutata. | `stock_eval/dcf.py` |
| **Kasvupotentsiaal** | (1) Analüütikute 12 kuu konsensus: keskmine/madalaim/kõrgeim sihthind, potentsiaal, analüütikute arv ja soovitus. (2) Kasumipõhine prognoos 1/3/5 aastaks: järgmise 12 k EPS × kasv (analüütikute EPS- ja käibeprognoos, sulandub 5 aastaga 6%-ni) × P/E, mis liigub 5 aastaga poole võrra sektori tüüpilise P/E suunas. Annab oodatava hinna ja aastase tootluse (koos dividendiga). Skoor = keskmine analüütikute potentsiaalist (−10%→0, +30%→100) ja mudeli aastatootlusest (−5%→0, +20%→100). Ajahorisont valitakse külgribalt. | `stock_eval/growth.py` |
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
