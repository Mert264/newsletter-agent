# World Bank Country Economy Specialist — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `worldbank` specialist to the newsletter pipeline so users can ask for any country's macroeconomic profile in any language and receive publication-ready charts from World Bank data.

**Architecture:** New `worldbank.py` specialist fetches World Bank REST API (no key), returns standard `SpecialistResult` dicts with annual DataFrames tagged `freq="A"`. The orchestrator resolves country names to ISO-3 codes. Minimal changes to pipeline, renderer, and UI — no new chart types, no new architectural layers.

**Tech Stack:** Python 3.9, `requests` (add to requirements.txt), World Bank REST API v2, existing Matplotlib renderers, existing Flask SSE pipeline.

---

## File Map

| Action | File | What changes |
|---|---|---|
| Create | `newsletter_agent/specialists/worldbank.py` | New specialist — fetches WB REST API, returns SpecialistResult |
| Create | `tests/test_worldbank.py` | Unit tests for worldbank specialist |
| Modify | `requirements.txt` | Add `requests>=2.31.0` |
| Modify | `newsletter_agent/pipeline.py` | Register `worldbank` in SPECIALIST_MAP |
| Modify | `newsletter_agent/orchestrator.py` | Add worldbank docs to system prompt |
| Modify | `newsletter_agent/routing.py` | Add country economy routing rules |
| Modify | `newsletter_agent/renderers/charts.py` | Force year-only x-axis when `freq="A"` in spec |
| Modify | `templates/index.html` | Add "Lande & Økonomi" prompt section |

---

## Task 1: Add `requests` to requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the dependency**

Open `requirements.txt` and add this line (after `python-dotenv`):

```
requests>=2.31.0
```

- [ ] **Step 2: Verify it installs**

```bash
pip install requests>=2.31.0
```

Expected: already satisfied or freshly installed, no errors.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add requests explicitly to requirements.txt"
```

---

## Task 2: Create `worldbank.py` specialist

**Files:**
- Create: `newsletter_agent/specialists/worldbank.py`
- Create: `tests/test_worldbank.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_worldbank.py`:

```python
import pandas as pd
import pytest
from unittest.mock import patch


MOCK_WB_RESPONSE = [
    {"page": 1, "total": 2},
    [
        {"date": "2023", "value": 2.4},
        {"date": "2022", "value": 3.1},
        {"date": "2021", "value": 5.0},
        {"date": "2020", "value": None},
        {"date": "2019", "value": 4.2},
    ]
]


def _mock_fetch(url, timeout=10):
    class R:
        def raise_for_status(self): pass
        def json(self): return MOCK_WB_RESPONSE
    return R()


def test_fetch_worldbank_returns_specialist_result():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get", side_effect=_mock_fetch):
        result = fetch_worldbank(task)
    assert "dataframes" in result
    assert "kilde" in result
    assert "BNP-vækst" in result["dataframes"]


def test_dates_converted_to_timestamps():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get", side_effect=_mock_fetch):
        result = fetch_worldbank(task)
    df = result["dataframes"]["BNP-vækst"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index[0] == pd.Timestamp("2019-01-01")


def test_none_values_dropped():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get", side_effect=_mock_fetch):
        result = fetch_worldbank(task)
    df = result["dataframes"]["BNP-vækst"]
    assert df.isnull().sum().sum() == 0  # None row was dropped


def test_kilde_contains_worldbank():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get", side_effect=_mock_fetch):
        result = fetch_worldbank(task)
    assert "Verdensbanken" in result["kilde"]


def test_network_error_returns_empty_result():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    import requests as req
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get",
               side_effect=req.RequestException("timeout")):
        result = fetch_worldbank(task)
    assert result["dataframes"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/mertcandogusoy/newsletter-site
python -m pytest tests/test_worldbank.py -v
```

Expected: `ImportError` — `worldbank` module does not exist yet.

- [ ] **Step 3: Implement `worldbank.py`**

Create `newsletter_agent/specialists/worldbank.py`:

```python
# newsletter_agent/specialists/worldbank.py
"""World Bank REST API specialist — no authentication required."""
from __future__ import annotations
import requests
import pandas as pd
from typing import Optional

_WB_BASE = "https://api.worldbank.org/v2/country/{iso3}/indicator/{code}?format=json&mrv={years}&per_page=100"
_LAG_NOTE = "Verdensbank-data publiceres typisk med 1–2 års efterslæb."


def _fetch_indicator(iso3: str, code: str, years: int) -> Optional[pd.DataFrame]:
    """Fetch one World Bank indicator for one country. Returns single-column DataFrame or None."""
    url = _WB_BASE.format(iso3=iso3, code=code, years=years)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        if not payload or len(payload) < 2 or not payload[1]:
            return None
        records = [
            (pd.Timestamp(f"{row['date']}-01-01"), row["value"])
            for row in payload[1]
            if row.get("value") is not None
        ]
        if not records:
            return None
        dates, values = zip(*sorted(records))
        df = pd.DataFrame({"value": values}, index=pd.DatetimeIndex(dates))
        df = df[~df.index.duplicated(keep="last")]
        df = df.ffill(limit=1)
        return df
    except Exception as e:
        print(f"    [worldbank] Failed to fetch {iso3}/{code}: {e}")
        return None


def fetch_worldbank(task: dict) -> dict:
    """Fetch World Bank data series defined in task['series']. Returns SpecialistResult dict."""
    dataframes: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []

    for s in task.get("series", []):
        label   = s.get("label", s.get("ticker", ""))
        iso3    = s.get("country", "WLD")
        code    = s.get("ticker", "")
        years   = int(s.get("years", 20))

        df = _fetch_indicator(iso3, code, years)
        if df is not None and not df.empty:
            df.columns = [label]
            dataframes[label] = df
        else:
            print(f"    [worldbank] No data for {iso3}/{code} — skipping '{label}'")
            skipped.append(label)

    # Inject lag note into every chart spec so renderers pass it through
    for chart in task.get("charts", []):
        existing = chart.get("note", "")
        if _LAG_NOTE not in existing:
            chart["note"] = (existing + " " + _LAG_NOTE).strip()
        # Tag as annual frequency for renderer x-axis and table logic
        chart["freq"] = "A"

    if skipped:
        print(f"    [worldbank] Skipped indicators (no data): {', '.join(skipped)}")

    return {
        "dataframes": dataframes,
        "kilde":      ["Verdensbanken"],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_worldbank.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add newsletter_agent/specialists/worldbank.py tests/test_worldbank.py
git commit -m "feat: add World Bank specialist with annual data and lag note"
```

---

## Task 3: Register worldbank in SPECIALIST_MAP

**Files:**
- Modify: `newsletter_agent/pipeline.py:23-30`

- [ ] **Step 1: Add the import at the top of pipeline.py**

Find the block of specialist imports (around line 10-15) and add:

```python
from newsletter_agent.specialists.worldbank import fetch_worldbank
```

- [ ] **Step 2: Add to SPECIALIST_MAP**

In the `SPECIALIST_MAP` dict (lines 23–30), add:

```python
SPECIALIST_MAP = {
    "energy":      fetch_energy,
    "rates":       fetch_rates,
    "macro":       fetch_macro,
    "commodities": fetch_commodities,
    "equities":    fetch_equities,
    "eurostat":    fetch_eurostat,
    "worldbank":   fetch_worldbank,   # ← add this line
}
```

- [ ] **Step 3: Verify import works**

```bash
python -c "from newsletter_agent.pipeline import SPECIALIST_MAP; print(list(SPECIALIST_MAP.keys()))"
```

Expected output includes `worldbank`.

- [ ] **Step 4: Commit**

```bash
git add newsletter_agent/pipeline.py
git commit -m "feat: register worldbank specialist in pipeline"
```

---

## Task 4: Handle `freq="A"` in Type A renderer (x-axis fix)

**Files:**
- Modify: `newsletter_agent/renderers/charts.py` — `render_type_a` function, around line 256–278

- [ ] **Step 1: Locate the auto date tick block**

Find this block in `render_type_a` (starts with `# Auto date tick density based on date range`):

```python
    # Auto date tick density based on date range
    if len(df.index) >= 2:
        date_range_days = (df.index[-1] - df.index[0]).days
        if date_range_days > 3650:
            ax.xaxis.set_major_locator(mdates.YearLocator(2))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        elif date_range_days > 1825:
```

- [ ] **Step 2: Add annual-frequency override before the existing block**

Insert immediately before `if len(df.index) >= 2:`:

```python
    # Annual data (e.g. World Bank) — always use year-only labels regardless of range
    if spec.get("freq") == "A":
        n_years = len(df.index)
        step = 2 if n_years > 10 else 1
        ax.xaxis.set_major_locator(mdates.YearLocator(step))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, ha="center",
                 fontsize=BRAND["font_size_axis"])
    elif len(df.index) >= 2:
```

Also change the existing `if len(df.index) >= 2:` to `elif len(df.index) >= 2:` so the two blocks are mutually exclusive.

- [ ] **Step 3: Verify the renderer still imports correctly**

```bash
python -c "from newsletter_agent.renderers.charts import render_type_a; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add newsletter_agent/renderers/charts.py
git commit -m "feat: add freq=A x-axis override in Type A renderer for annual data"
```

---

## Task 5: Add worldbank to orchestrator system prompt

**Files:**
- Modify: `newsletter_agent/orchestrator.py` — system prompt, after the Eurostat section

- [ ] **Step 1: Find the insertion point**

Search for `EU STATISTICAL DATA — Eurostat` in `orchestrator.py`. The new worldbank section goes immediately after the Eurostat section ends (after the `NOT available` block).

- [ ] **Step 2: Insert the worldbank section**

Add this block after the Eurostat NOT available section:

```
COUNTRY ECONOMY DATA — World Bank (free, no API key):
Use specialist "worldbank" for any request about a specific country's macroeconomic profile.

Series entry format:
  {"ticker": "<WB_CODE>", "source": "worldbank", "label": "<Danish label>",
   "country": "<ISO3>", "years": 20, "unit": "%"}

COUNTRY RESOLUTION — CRITICAL:
  Translate any country name in ANY language to its ISO-3 code.
  Examples: "Ungarn"→"HUN", "Sverige"→"SWE", "Kina"→"CHN", "USA"→"USA",
            "Frankrig"→"FRA", "Tyrkiet"→"TUR", "Ungarn"→"HUN"
  For ambiguous names (Congo, Korea, Arabia): default to the larger/more commonly
  referenced country and add a parenthetical to the chart title,
  e.g. "Sydkorea (Republikken Korea)".

CORE INDICATORS — always include all five for single-country requests:
  NY.GDP.MKTP.KD.ZG → "BNP-vækst (%)"
  FP.CPI.TOTL.ZG    → "Inflation, CPI (%)"
  SL.UEM.TOTL.ZS    → "Arbejdsløshed (%)"
  GC.DOD.TOTL.GD.ZS → "Offentlig gæld (% af BNP)"
  BN.CAB.XOKA.GD.ZS → "Betalingsbalance (% af BNP)"

WORLDBANK CHART RULES:
  - ALWAYS set y_label="%" — never "YoY %" (data is already in annual %)
  - ALWAYS set years=20 unless user specifies a different time horizon (max 30)
  - period_days is IGNORED by this specialist — use years instead
  - Default chart type: Type A (time series) with companion Type D table
  - For peer comparison (2 countries): include both ISO-3 countries as separate
    series entries with the same indicator code, e.g.:
      {"ticker": "NY.GDP.MKTP.KD.ZG", "country": "DNK", "label": "Danmark — BNP-vækst", ...}
      {"ticker": "NY.GDP.MKTP.KD.ZG", "country": "SWE", "label": "Sverige — BNP-vækst", ...}
  - For Type D companion tables: set col_before="For 10 år siden", col_after="Senest tilgængelige"
```

- [ ] **Step 3: Verify the orchestrator imports correctly**

```bash
python -c "from newsletter_agent.orchestrator import build_task_manifest; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add newsletter_agent/orchestrator.py
git commit -m "feat: add worldbank specialist docs to orchestrator system prompt"
```

---

## Task 6: Add worldbank routing rules

**Files:**
- Modify: `newsletter_agent/routing.py`

- [ ] **Step 1: Add country-detection patterns and routing rule**

In `routing.py`, add after the existing pattern definitions (after `_GDP`):

```python
# Patterns for country economy routing — must have BOTH a country signal AND an economy keyword
# Country signal: explicit country name or geographic indicator NOT matching EU/US
_COUNTRY_ECON_KW  = _re(r"\b(økonomi|makroprofil|makroøkonomisk|landeprofil|bnp|inflation i|gæld|betalingsbalance|arbejdsløshed i|ledighed i)\b")
_NOT_EU_US        = lambda b: not (_EU.search(b) and not re.search(r'\b(eu\b)', b, re.I)) and not _US.search(b)
```

Then add this rule to `ROUTING_RULES` at the end, before the closing bracket:

```python
    # Country economy → World Bank (only when a country-specific economy keyword present,
    # and not already matched as EU or US macro)
    (
        lambda b: _COUNTRY_ECON_KW.search(b) and not _EU.search(b) and not _US.search(b),
        "For landets økonomi: brug specialist='worldbank'. "
        "Oversæt landets navn til ISO-3-kode. Brug y_label='%', years=20. "
        "Inkludér alle 5 kernindikatorer for enkelt-lande-forespørgsler.",
    ),
```

- [ ] **Step 2: Add `import re` if not already present**

Check line 1 of `routing.py` — `import re` is already there. No change needed.

- [ ] **Step 3: Test routing logic manually**

```bash
python -c "
from newsletter_agent.routing import get_routing_hint
print(repr(get_routing_hint('Vis Ungarns økonomi')))
print(repr(get_routing_hint('Vis EU inflation')))
print(repr(get_routing_hint('Vis inflation')))
"
```

Expected:
- Line 1: contains `worldbank`
- Line 2: contains `eurostat`, does NOT contain `worldbank`
- Line 3: empty string `''` — no routing hint (macro keyword only, no country)

- [ ] **Step 4: Commit**

```bash
git add newsletter_agent/routing.py
git commit -m "feat: add worldbank routing rule (country + economy keyword, not EU/US)"
```

---

## Task 7: Add UI prompts and viz type defaults

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Add BRIEFS entries**

Find `const BRIEFS = {` and add inside the object, after the Makro & Inflation entries:

```javascript
  // Lande & Økonomi
  16: "Vis Ungarns makroøkonomiske profil — BNP-vækst, inflation, arbejdsløshed, offentlig gæld og betalingsbalance de seneste 20 år.",
  17: "Sammenlign Danmarks og Sveriges økonomi — BNP-vækst, inflation og offentlig gæld de seneste 20 år.",
  18: "Vis Kinas makroøkonomiske udvikling — BNP-vækst, inflation og betalingsbalance de seneste 20 år.",
```

- [ ] **Step 2: Add BRIEF_PERIODS entries**

Find `const BRIEF_PERIODS = {` and add inside the object:

```javascript
  16: 0,    // World Bank — LLM picks years=20
  17: 0,    // World Bank comparison — LLM picks years=20
  18: 0,    // World Bank — LLM picks years=20
```

- [ ] **Step 3: Add BRIEF_VIZ_TYPES entries**

Find `const BRIEF_VIZ_TYPES = {` and add inside the object:

```javascript
  16: ['A', 'D'],    // single country — time series + table
  17: ['A', 'bar'],  // comparison — time series + bar
  18: ['A', 'D'],    // single country — time series + table
```

- [ ] **Step 4: Add the new prompt category section in HTML**

Find this block in the HTML:

```html
        <div class="prompt-category-block" style="border-top:1px solid #f0f4f4">
          <div class="prompt-category-label">Makro &amp; Inflation</div>
```

Insert a new category block immediately before it:

```html
        <div class="prompt-category-block" style="border-top:1px solid #f0f4f4">
          <div class="prompt-category-label">Lande &amp; Økonomi</div>
          <div class="prompt-group">
            <button class="quick-btn" onclick="setQuick(16)">Ungarns Økonomi</button>
            <button class="quick-btn" onclick="setQuick(17)">Danmark vs. Sverige</button>
            <button class="quick-btn" onclick="setQuick(18)">Kinas Makroprofil</button>
          </div>
        </div>
```

- [ ] **Step 5: Verify HTML parses — start local server**

```bash
lsof -ti :5050 | xargs kill -9 2>/dev/null; python3 app.py &
sleep 2
curl -s http://localhost:5050 | grep -c "Lande"
```

Expected: `1` (the new category appears in the page).

- [ ] **Step 6: Commit**

```bash
git add templates/index.html
git commit -m "feat: add Lande & Økonomi prompt section with 3 World Bank examples"
```

---

## Task 8: End-to-end smoke test

**Files:** none created, verifying the full pipeline works.

- [ ] **Step 1: Start the local server if not running**

```bash
lsof -ti :5050 | xargs kill -9 2>/dev/null
python3 app.py &
sleep 2
```

- [ ] **Step 2: Run a worldbank prompt via API**

```bash
curl -s -X POST http://localhost:5050/run \
  -H "Content-Type: application/json" \
  -d '{"brief": "Vis Ungarns økonomi — BNP-vækst og inflation", "preferred_types": ["A", "D"]}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d)"
```

Expected: HTTP 200, `{"status": "started"}` (pipeline runs async via SSE).

- [ ] **Step 3: Open browser and verify**

Open `http://localhost:5050`, click "Ungarns Økonomi", click "Generer figurer".

Check Live Log for:
- `Specialists activated: worldbank`
- `[worldbank] Done — N series fetched.` (N ≥ 1)
- No `[warn]` lines about missing series

Check figure output:
- At least one Type A chart renders with year-only x-axis labels (e.g. "2005", "2010")
- No "Jan 2005" labels
- Chart note contains "Verdensbank-data publiceres typisk med 1–2 års efterslæb"
- Kilde shows "Verdensbanken"

- [ ] **Step 4: Test peer comparison**

Click "Danmark vs. Sverige", click "Generer figurer".

Check: two country series appear on the same chart with different colours.

- [ ] **Step 5: Test routing collision — should NOT trigger worldbank**

Enter brief: `Vis inflation i USA`. Check Live Log: specialist should be `macro`, NOT `worldbank`.

- [ ] **Step 6: Commit smoke test result note (no code change needed)**

```bash
git commit --allow-empty -m "test: worldbank end-to-end smoke test passed"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ World Bank REST API, no key — Task 2
- ✅ ISO-3 country resolution by LLM — Task 5
- ✅ 5 core indicators — Task 5 (orchestrator prompt)
- ✅ `freq="A"` tag on charts — Task 2 (worldbank.py injects into chart specs)
- ✅ Year-only x-axis — Task 4
- ✅ `ffill(limit=1)` — Task 2
- ✅ Lag note on every chart — Task 2
- ✅ `years` field replaces `period_days` — Task 2 + Task 5
- ✅ Routing collision prevention — Task 6
- ✅ `requests` in requirements.txt — Task 1
- ✅ Ambiguous country names — Task 5 (orchestrator prompt rule)
- ✅ Type D before/after — `_snapshot_value` uses `nearest` lookup which works for annual Jan-1 timestamps; orchestrator instructed to use `col_before="For 10 år siden"` with explicit year label, not a computed date
- ✅ New UI prompts 16–18 — Task 7
- ✅ `SPECIALIST_MAP` registration — Task 3

**Type consistency:** `fetch_worldbank` returns `{"dataframes": dict, "kilde": list}` — matches all other specialists' interface. `freq="A"` is a string set on chart specs (dicts), read as `spec.get("freq")` in renderer — consistent.

**No placeholders found.**
