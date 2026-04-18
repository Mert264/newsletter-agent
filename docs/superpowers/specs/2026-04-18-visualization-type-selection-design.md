# Design Spec: User-Selectable Visualization Types + New Data Sources

**Date:** 2026-04-18  
**Status:** Approved — ready for implementation

---

## 1. Problem Statement

The newsletter agent currently lets the LLM decide chart type automatically. Users have no way to steer visualization style before generation, and no way to adjust a specific figure after generation without re-running the full pipeline. Additionally, the agent lacks support for:
- Compositional/percentage-breakdown charts (energy mix, sector shares)
- Horizontal ranking charts (AI adoption by sector)
- EU statistical data (Eurostat)
- US energy mix data (EIA)
- Accurate unit-harmonized cross-source comparisons (e.g., EU gas EUR/MWh vs US gas USD/MMBtu)

---

## 2. Approved Design

### 2.1 UI — Visualization Type Panel

**Position:** Left sidebar (210px fixed column), to the left of the brief card. The top row becomes a 2-column grid: `210px 1fr`.

**Options (top to bottom):**

| Option | Sub-options | Chart type | Use case |
|--------|-------------|------------|----------|
| Figur | — | A (time series line) | Price trends, macro indicators over time |
| Søjlediagram | Lodret | B (vertical bar) | Cross-entity comparison, small N |
| | Vandret | G (horizontal bar) | Rankings, many entities, long labels |
| | Stablet | F (100% stacked bar) | Composition/share over multiple years |
| Tabel | — | D (snapshot table) | Key-numbers snapshot, before/after |
| Cirkeldiagram | — | P (pie chart) | Single-year composition, sum = 100% |

**Interaction rules:**
- Multi-select: any combination of top-level options can be selected simultaneously
- Søjlediagram sub-options are single-select (only one sub-type active at a time); selecting the parent auto-selects Lodret as default
- Selections are passed to the orchestrator as `preferred_types` — an ordered list of chart type codes (e.g. `["A", "G", "D"]`)
- The LLM treats preferred_types as a preference, not a hard constraint: if data is fundamentally incompatible with the chosen type (e.g., pie on a time series), it falls back to the most appropriate type and logs a warning

**Visual style:** No emojis. SVG icons only. Uppercase section headers. Consistent with existing Maj Invest green (#11716c) brand.

---

### 2.2 Per-Figure Re-Render

After the pipeline runs and figures are displayed, each figure card shows a re-render row with 6 buttons:

`Figur | Lodret | Vandret | Stablet | Tabel | Cirkel`

The currently-active type is highlighted (green background). Clicking a different type triggers a **full single-figure re-run** (Approach Y):

- A new LLM call is made with the same brief + same series constraints, but `preferred_types` overridden to the selected type
- Data is re-fetched for that specialist only
- Only that figure card is replaced; other figures are untouched
- The figure card shows a spinner during the ~10–15 second re-run
- Endpoint: `POST /rerender` with `{figure_id, chart_type, original_brief, series_context}`

---

### 2.3 New Chart Types

#### Type F — 100% Stacked Bar
- **Input:** Wide DataFrame, string index (year labels), columns = categories
- **Rendering:** Each row normalised to 100%. Segment labels shown for segments ≥ 6%. Legend below chart.
- **Use for:** Energy mix by fuel type, sector share over years, portfolio composition
- **Already implemented** in `renderers/charts.py`

#### Type G — Horizontal Bar
- **Input:** DataFrame, string/entity index, single value column
- **Rendering:** Bars sorted descending (largest at top). Value labels at bar ends.
- **Use for:** AI adoption by sector, renewable share by country, ranking comparisons
- **Already implemented** in `renderers/charts.py`

#### Type P — Pie Chart (new)
- **Input:** Single-column DataFrame or dict of {label: value}; values normalised to 100%
- **Rendering:** Segments with % labels for slices ≥ 5%. Legend to the right. Single year shown in title.
- **Use for:** Energy mix snapshot for one specific year, market share at a point in time
- **Constraint:** Only meaningful for compositional data (entries sum to ~100%). Orchestrator must validate.

---

### 2.4 New Data Sources

#### EIA (US Energy Information Administration)
- **Access:** Free REST API. API key stored as `EIA_API_KEY` Railway env var.
- **Specialist:** `energy` (extended), source type `"eia"` or `"eia_mix"`
- **Key series (MSN codes):**
  - `PATOBUS` — Petroleum (Quadrillion BTU, annual)
  - `NNTCBUS` — Natural gas (Quadrillion BTU, annual)
  - `CLTCBUS` — Coal (Quadrillion BTU, annual)
  - `NUETBUS` — Nuclear (Quadrillion BTU, annual)
  - `RETCBUS` — Renewables (Quadrillion BTU, annual)
- **Shortcut:** `source="eia_mix"` auto-fetches all five as a wide DataFrame (Type F ready)
- **Already implemented** in `specialists/energy.py`

#### Eurostat (EU Statistical Office)
- **Access:** Free REST API. No API key required.
- **Specialist:** `eurostat` (new), source types `"eurostat_ts"` (time series) or `"eurostat_mix"` (cross-sectional)
- **Shortcut dataset IDs:** `eu_energy_mix`, `eu_gdp_growth`, `eu_unemployment`, `eu_hicp`
- **Already implemented** in `specialists/eurostat.py`

---

### 2.5 Unit Conversion System

**Problem:** Cross-source gas comparisons mix EUR/MWh (TTF) and USD/MMBtu (Henry Hub).  
**Solution:** A `converters.py` module applies named conversions before rendering.

#### Physical conversion factors (fixed constants):
- `USD_MMBtu → USD_MWh`: multiply by **3.41214** (1 MWh = 3.41214 MMBtu)
- `EUR_MWh → USD_MWh`: multiply by EUR/USD exchange rate (date-matched)
- `USD_MCF → USD_MWh`: multiply by **0.03531** (1 MCF ≈ 0.03531 MWh, natural gas standard)

#### Date-matched FX conversion:
When a conversion requires EUR/USD, the pipeline fetches `EURUSD=X` via yfinance for the full period, aligns by date (outer join + forward-fill), and applies element-wise multiplication. This ensures each data point uses the exchange rate from its own date — not a single spot rate.

#### Chart note (auto-generated):
The conversion details are always surfaced to the user in the chart's note field. Format:
> *"Henry Hub omregnet fra USD/MMBtu til USD/MWh (faktor: 3.412). TTF omregnet fra EUR/MWh til USD/MWh (EUR/USD dato-matchet, seneste: 1.082)."*

#### Standard gas y-axis unit: **USD/MWh**
All gas price comparisons use USD/MWh as the common unit. This is the European standard and avoids the confusion of USD/MMBtu which is unfamiliar to EU readers.

#### Orchestrator instruction (in system prompt):
When series from different sources are plotted together, the LLM must specify a `conversion` field per series that requires harmonisation. Example:
```json
{"ticker": "NG=F", "source": "yfinance", "label": "Henry Hub",
 "unit": "USD/MMBtu", "conversion": "USD_MMBtu_to_USD_MWh"}
```
The pipeline `converters.py` reads this field and applies the conversion before rendering.

---

### 2.6 Dataset Routing — Hybrid System

A `routing.py` module applies deterministic keyword rules first; the LLM orchestrator handles anything that doesn't match.

#### Rule table (priority order):

| Keywords in brief | Routed to | Source |
|---|---|---|
| EU / European / Eurozone + energy / energimix / forbrug | `eurostat` | `eu_energy_mix` |
| EU / European / Eurozone + inflation / HICP / CPI | `eurostat` | `eu_hicp` |
| EU / European / Eurozone + unemployment / ledighed | `eurostat` | `eu_unemployment` |
| EU / European / Eurozone + GDP / BNP / growth | `eurostat` | `eu_gdp_growth` |
| US / American / USA + energy mix / energimix / fuel breakdown | `energy` | `eia_mix` |
| Gas / natural gas / naturgas (cross-region comparison) | Both `energy` + FX conversion | `NG=F` + `TTF=F` → USD/MWh |
| Oil / crude / råolie prices | `energy` | `BZ=F`, `CL=F` via yfinance |
| Stocks / aktier / equities / index / indices | `equities` | yfinance |
| Bonds / yields / renter | `rates` / `macro` | FRED |
| Inflation / CPI / PCE (US) | `macro` | FRED |

#### Fallback:
If no rule matches, the LLM orchestrator selects the specialist and source freely, as it does today.

#### Implementation note:
`routing.py` returns a `routing_hint: dict` that is appended to the orchestrator prompt as a structured constraint block. The LLM can override if it has strong reason to, but must follow routing hints by default.

---

## 3. Architecture Changes

### Files to create:
- `newsletter_agent/renderers/charts.py` — add `render_type_p` (pie)
- `newsletter_agent/processors/converters.py` — unit conversion logic (date-matched FX)
- `newsletter_agent/routing.py` — keyword-based dataset routing

### Files to modify:
- `newsletter_agent/pipeline.py` — wire Type P, handle `conversion` field per series, call routing
- `newsletter_agent/orchestrator.py` — add `preferred_types` param, new chart types, conversion rules
- `newsletter_agent/specialists/energy.py` — already done (EIA)
- `newsletter_agent/specialists/eurostat.py` — already done
- `newsletter_agent/renderers/charts.py` — already done (F, G)
- `newsletter_agent/pipeline.py` — already done (F, G routing)
- `app.py` — add `POST /rerender` endpoint; pass `preferred_types` from UI to pipeline
- `templates/index.html` — visualization type panel (left sidebar), per-figure re-render buttons

### Data flow with preferred_types:
```
User selects types in UI
  → preferred_types = ["A", "G"] passed to /run
  → orchestrator receives preferred_types in prompt
  → LLM generates TaskManifest honouring preferred_types
  → pipeline renders figures
  → figure cards shown with active type highlighted

User clicks re-render button on figure N
  → POST /rerender {figure_id=N, chart_type="G", ...}
  → single-figure orchestrator call (same brief, forced type)
  → only figure N replaced
```

---

## 4. Out of Scope

- BlackRock, JPMorgan, ICE real-time data (institutional walls, no free API)
- Ramp AI Index (PDF-only, no API)
- EIB Investment Survey (annual Excel, no live API) — can be added as static bundled data later
- Interactive chart editing (drag, zoom) — static PNG output remains the format
- Multi-currency support beyond EUR/USD (can extend converters.py later)

---

## 5. Success Criteria

1. User can select Figur + Vandret before running and the pipeline respects those types
2. Clicking "Stablet" under a generated figure re-renders only that figure in ~15 sec
3. A brief about "EU energimix 2024" produces a Type F stacked bar using Eurostat data
4. A brief about "US energimix de seneste 10 år" produces a Type F using EIA data
5. A brief comparing EU TTF gas vs US Henry Hub produces a single chart in USD/MWh with a note explaining the date-matched conversion
6. Chart notes always show the conversion factors and FX rate used
