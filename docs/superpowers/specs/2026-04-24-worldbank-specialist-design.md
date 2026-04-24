# World Bank Country Economy Specialist — Design Spec

**Date:** 2026-04-24
**Status:** Awaiting implementation plan

---

## Overview

Add a `worldbank` specialist to the existing newsletter pipeline so users can ask for any country's macroeconomic profile in any language. The orchestrator translates the country name to an ISO-3 code, the specialist fetches World Bank REST API data, and the existing renderers produce charts and tables — no new chart types, no new architectural layers.

---

## Goals

- Any free-text country reference ("Ungarn", "Hungary", "Hongrie", "Macaristan") resolves to the correct country automatically via the orchestrator LLM
- Five core macroeconomic indicators always shown for single-country requests
- All four existing viz types (Figur/Tabel/Søjlediagram/Cirkeldiagram) work with World Bank data
- No API key required — World Bank REST API is free and open
- No new dependencies — use `urllib` / `requests` (already in env via Flask)

---

## Architecture

The World Bank feature is a pure extension — no existing files break.

**New file:** `newsletter_agent/specialists/worldbank.py`

**Modified files:**
- `newsletter_agent/orchestrator.py` — add `worldbank` to specialist list, add indicator reference, add ISO code instruction, add `years` field to series spec
- `newsletter_agent/routing.py` — add country economy keyword triggers
- `templates/index.html` — add "Lande & Økonomi" prompt category with 3–4 example prompts

**Unchanged:** `pipeline.py`, all renderers, all processors, `app.py`, `reviewer.py`

---

## Data Source

**World Bank REST API**
- Base URL: `https://api.worldbank.org/v2/country/{iso3}/indicator/{code}?format=json&mrv={years}&per_page=100`
- No authentication required
- Returns JSON: array of `[metadata, [{"date": "2023", "value": 2.4}, ...]]`
- `mrv=N` = most recent N annual values

**Core indicators (always fetched for single-country requests):**

| Danish label | WB Indicator Code |
|---|---|
| BNP-vækst | NY.GDP.MKTP.KD.ZG |
| Inflation (CPI) | FP.CPI.TOTL.ZG |
| Arbejdsløshed | SL.UEM.TOTL.ZS |
| Offentlig gæld (% af BNP) | GC.DOD.TOTL.GD.ZS |
| Betalingsbalance (% af BNP) | BN.CAB.XOKA.GD.ZS |

Additional indicators may be requested via free-text brief — the orchestrator maps them to WB codes from the reference list in the system prompt.

---

## Series Manifest Format

The orchestrator emits `worldbank` series entries using this structure:

```
"ticker": "NY.GDP.MKTP.KD.ZG"   // World Bank indicator code
"source": "worldbank"
"label": "BNP-vækst"
"country": "HUN"                 // ISO-3 code — orchestrator resolves this
"years": 20                      // years of history (default 20, max 30)
"unit": "%"
```

`period_days` is ignored by this specialist. `years` replaces it.

---

## worldbank.py Specialist — Behaviour

1. Groups series by `country` code, fetches each indicator in a loop
2. Converts WB date strings (`"2023"`) to `pd.Timestamp("2023-01-01")` before returning DataFrames
3. Uses `ffill(limit=1)` — fills at most 1 year forward (accounts for publication lag, not more)
4. Auto-appends to every chart note: `"Verdensbank-data publiceres typisk med 1–2 års efterslæb."`
5. Returns standard `SpecialistResult` dict — identical interface to all other specialists

---

## Orchestrator Changes

**New specialist option:** `"worldbank"` added to the specialists list.

**Country resolution rule added to system prompt:**
- Translate any country name (any language) to ISO-3 code before emitting the manifest
- For ambiguous names (Congo, Korea, Arabia), default to the larger/more commonly referenced country and add a parenthetical to the chart title (e.g. "Sydkorea (Republikken Korea)")

**`years` field:** documented as the time-horizon override for worldbank series (integer, default 20).

**Indicator reference:** all five core WB codes listed in the system prompt with their Danish labels so the LLM emits correct codes.

---

## Routing

New keywords added to `routing.py` triggering a `worldbank` hint:
- Country names (sample set to catch common patterns): "økonomi", "BNP", "vækst", "arbejdsløshed", "inflation i [country]", "gæld", "betalingsbalance"
- Routing hint: `"For landespørgsmål: brug worldbank-specialisten med landets ISO-3-kode"`

---

## UI — New Prompt Category

New section "Lande & Økonomi" added in `index.html` between the existing Makro & Inflation and Global Økonomi categories.

Example prompts (with IDs 16–18):

| ID | Button label | Brief |
|---|---|---|
| 16 | Ungarns Økonomi | Vis Ungarns makroøkonomiske profil — BNP-vækst, inflation, arbejdsløshed, offentlig gæld og betalingsbalance |
| 17 | Danmark vs. Sverige | Sammenlign Danmark og Sverige — BNP-vækst, inflation og offentlig gæld de seneste 20 år |
| 18 | Kinas Makroprofil | Vis Kinas makroøkonomiske udvikling — BNP-vækst, inflation og betalingsbalance de seneste 20 år |

All three use `BRIEF_PERIODS[n] = 0` (LLM picks, expected `years=20`). Viz types default to `['A', 'D']` for single-country, `['bar', 'A']` for comparisons.

---

## Error Handling

- **Country not found:** if World Bank returns no data for an ISO code, specialist logs `[worldbank] No data for {iso3}` and skips — existing "no data" warning path handles gracefully
- **Indicator unavailable:** some countries lack certain indicators (e.g. government debt for small nations). Specialist skips missing indicators silently; chart note records which were omitted
- **Network error:** wrapped in try/except, logs and returns empty result — pipeline continues with whatever data was fetched

---

## Loopholes Resolved

| Issue | Resolution |
|---|---|
| Annual data vs monthly pipeline assumptions | Specialist converts year strings to Jan-1 timestamps; uses `ffill(limit=1)` |
| `period_days` meaningless for annual data | Specialist reads `years` field instead; `period_days` ignored |
| Type D before/after logic breaks with annual data | Specialist tags DataFrames with `freq="A"` metadata; `_build_table` uses year-based lookback when this flag is present |
| World Bank series already in % — YoY transform must not apply | Orchestrator prompt explicitly states: worldbank series always use `y_label="%"`, never `"YoY %"` |
| X-axis shows "Jan 2020" instead of "2020" | `freq="A"` metadata flag triggers year-only tick formatting in Type A renderer |
| Routing collision — macro keywords fire without country context | worldbank routing hint only activates when a country name co-occurs with an economic keyword |
| `requests` not explicitly in requirements.txt | Added explicitly before deploy — not guaranteed by transitive dependencies |
| Data publication lag not communicated | Auto-appended note on every chart |
| Ambiguous country names | LLM defaults to larger country + parenthetical in title |

---

## Out of Scope (this spec)

- Peer comparison across 3+ countries (2-country comparison covered via multi-series manifest)
- Sub-national / regional data
- World Bank indicators beyond the five core + brief-requested extras
- Annual report / company analysis feature (separate spec)
