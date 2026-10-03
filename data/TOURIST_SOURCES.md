# Lex Koller tourist-location research

Research pass on which communes are designated tourist locations
(Fremdenverkehrsorte / lieux a vocation touristique) where a non-resident
foreigner may acquire a holiday home, and which are not (closed entirely, like
Zermatt). This note records what is confirmed, the authoritative sources, and
the trap to avoid, so the lists can be completed canton by canton without
redoing the groundwork.

## The legal mechanism

- A non-resident foreigner may acquire a holiday home only in a commune the
  canton has designated a tourist location, under Art. 9 para. 3 BewG (LFAIE).
  The permit is charged to that canton's annual quota.
- Each canton sets its designated communes in an annex to its own implementing
  regulation (Valais: Annex 1 of the Reglement ueber den Erwerb von
  Grundstuecken durch Personen im Ausland). These annexes are the authoritative,
  complete lists. They are cantonal legal texts, revised periodically, not one
  federal dataset.
- Confirmed by the Federal Court in 2C_1082/2016 (2 June 2017): the geographic
  requirement cannot be bypassed, even for a sale between two foreigners.

## Confirmed facts

- **Zermatt (VS): excluded.** The Federal Court held Zermatt is not a designated
  tourist location, "because it needs no tourism promotion," so it has no quota
  and a non-resident foreigner cannot acquire there. This is the textbook total
  exclusion. In `tourist_excluded.csv`.
  Sources: SRF "Bundesgericht: Zermatt ist kein Fremdenverkehrsort"; Federal
  Court 2C_1082/2016.
- **Saas-Fee (VS): designated / open.** Runs its own Fremdenkontrolle office for
  foreign acquisitions, which only a designated location would. In
  `tourist_communes.csv`. Source: 3906.ch commune office pages.
- A 2020 Valais cantonal court ruling (KGVS A1 20 49) applied the same test to
  another commune and found it not designated, but the commune name is redacted
  in the published judgment, so it cannot be added.

## The trap (do not repeat)

General-audience articles routinely conflate two different regimes:

- **Lex Weber** (Second Homes Act): communes over 20 percent second homes are
  frozen to NEW second homes. St. Moritz, Verbier, Gstaad, Davos are frozen.
  They are still OPEN to foreign purchase of existing resale stock.
- **Lex Koller** tourist-location designation: whether a foreigner may buy there
  at all.

A commune being frozen under Lex Weber does NOT make it a Lex Koller exclusion.
Do not move St. Moritz, Verbier, Gstaad, etc. into `tourist_excluded.csv` on the
strength of a blog that lists them as "restricted." Only the cantonal annex (or
a court ruling) establishes a Lex Koller exclusion.

## How to complete the lists

For each of VS, GR, VD, BE, TI (then the smaller cantons), obtain the current
annex of designated communes from the cantonal regulation and:

1. Put designated communes in `tourist_communes.csv` (enables the green
   "designated tourist zone" confirmation).
2. Any resort-like commune in the canton that is NOT in the annex is a candidate
   exclusion; confirm before adding to `tourist_excluded.csv`.
3. Once a canton's positive list is believed complete, a run with
   `TOURIST_STRICT=1` will treat any commune absent from it as not designated.
   Leave strict mode off while the lists are partial.

Authoritative entry points (verify current versions):

- Federal Office of Justice, Lex Koller guidance: bj.admin.ch (Erwerb von
  Grundstuecken durch Personen im Ausland).
- Valais: Reglement / arrete du Conseil d'Etat on lieux touristiques (LALFAIE),
  revised every two years.
- Graubuenden, Vaud, Bern, Ticino: each canton's LFAIE implementing ordinance,
  or the cantonal authority (Grundbuchamt / registre foncier) that issues the
  permits.

Bottom line: today's defensible data is Zermatt excluded, Saas-Fee designated.
Everything else stays "verify" until the cantonal annexes are loaded, which is
the safe default and never produces a false green light.
