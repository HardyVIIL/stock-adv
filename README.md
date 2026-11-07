# Aktsiate evalueerija

Interaktiivne dashboard, mis hindab aktsiaid automaatselt kolme meetodiga ja annab igale skoori 0–100.
Andmed tulevad Yahoo Finance'ist (`yfinance`, API-võtit pole vaja).

## Käivitamine

```bash
./run.sh
```

Avaneb <http://localhost:8501>. Külgribal saab muuta jälgimisnimekirja, meetodite kaale ja DCF eeldusi.

## Meetodid

| Meetod | Mida hinnatakse | Moodul |
|---|---|---|
| **Fundamentaalanalüüs** | Hindamine (P/E, PEG, EV/EBITDA, P/B), kasumlikkus (ROE, marginaalid), kasv (käive, kasum), finantstervis (D/E, likviidsus). Iga näitaja → 0–100 lineaarse skaala järgi, kategooriad keskmistatakse. | `stock_eval/fundamentals.py` |
| **DCF** | Kaheetapiline FCF mudel: baas = viimase aasta FCF aruandest; kasv = käibe kasv (piiratud −5%…20%), mis teises pooles sulandub terminaalsesse kasvu; diskonto CAPM-ist (4,5% + β·5,5%, piiratud 7–14%). Skoor tuleb turvamarginaalist (−50% → 0, +40% → 100). Pankadele ja negatiivse FCF-iga ettevõtetele DCF-i ei arvutata. | `stock_eval/dcf.py` |
| **Tehniline analüüs** | Hind vs SMA200, SMA50/200 rist, RSI(14), MACD, 6 kuu momentum, volatiilsus. | `stock_eval/technical.py` |

Koondskoor = kaalutud keskmine (vaikimisi 50/30/20). Puuduv osaskoor jäetakse välja ja kaalud normaliseeritakse.
Hinnangud: ≥70 Tugev, ≥55 Hea, ≥40 Neutraalne, alla selle Nõrk.

Lävendid (mis on "hea" ja "halb" väärtus) on `RULES` loendis failis `fundamentals.py` — muuda neid oma strateegia järgi.

## Testid

```bash
.venv/bin/python -m pytest -q
```

## Hoiatus

Automaatne analüüsitööriist, mitte investeerimisnõuanne. Yahoo andmed võivad olla viitega või vigased
ning DCF tulemus on eelduste (eriti kasvu ja diskontomäära) suhtes väga tundlik.
