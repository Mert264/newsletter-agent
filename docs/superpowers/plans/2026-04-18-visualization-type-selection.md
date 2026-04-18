# Visualization Type Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user-selectable visualization types (panel + per-figure re-render), pie chart renderer, unit conversion with date-matched FX, hybrid routing, and `/rerender` endpoint.

**Architecture:** Visualization preferences flow from UI → `/run` as `preferred_types` list → orchestrator prompt → LLM honours them in TaskManifest. Per-figure re-render hits a new `/rerender` endpoint that re-fetches data for one specialist and re-renders with the overridden type. Unit conversions are applied in `run()` after specialist data is fetched, using `converters.py` which fetches live date-matched FX series via yfinance.

**Tech Stack:** Flask (SSE + REST), Matplotlib, pandas, yfinance (FX), Anthropic Claude API. Types F and G already implemented. EIA + Eurostat specialists already implemented.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `newsletter_agent/renderers/charts.py` | Modify | Add `render_type_p` (pie chart) |
| `newsletter_agent/processors/converters.py` | Create | Unit conversion with date-matched FX |
| `newsletter_agent/routing.py` | Create | Keyword-based dataset routing hint |
| `newsletter_agent/pipeline.py` | Modify | Wire Type P, apply conversions, call routing, store rerender context |
| `newsletter_agent/orchestrator.py` | Modify | Accept `preferred_types` + routing hint; expose `conversion` field and Type P in prompt |
| `app.py` | Modify | Accept `preferred_types` in `/run`; add `POST /rerender` |
| `templates/index.html` | Modify | Viz type panel (left sidebar); per-figure re-render buttons |
| `tests/test_renderers.py` | Create | Tests for render_type_p |
| `tests/test_converters.py` | Create | Tests for converters.py |
| `tests/test_routing.py` | Create | Tests for routing.py |

---

## Task 1: Pie Chart Renderer (Type P)

**Files:**
- Modify: `newsletter_agent/renderers/charts.py`
- Create: `tests/test_renderers.py`

- [ ] **Step 1.1: Create test file**

```python
# tests/test_renderers.py
import os
import tempfile
import pandas as pd
import pytest
from newsletter_agent.renderers.charts import render_type_p, render_type_f, render_type_g


def _tmp(suffix=".png"):
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.close()
    return f.name


SPEC = {
    "title": "Test Chart",
    "x_label": "År",
    "y_label": "Pct. af total",
    "note": "Test note.",
    "kilde": "Test",
}


def test_render_type_p_single_column():
    df = pd.DataFrame(
        {"value": [40.0, 25.0, 20.0, 15.0]},
        index=["Olie", "Gas", "Kul", "Vedvarende"],
    )
    out = _tmp()
    result = render_type_p(df, {**SPEC, "title": "Energimix 2024"}, out)
    assert os.path.exists(result)
    assert os.path.getsize(result) > 10_000
    os.unlink(result)


def test_render_type_p_wide_uses_latest_row():
    # Wide df: index=years, columns=categories — should use last row
    df = pd.DataFrame(
        {"Olie": [50.0, 42.0], "Gas": [30.0, 28.0], "Vedvarende": [20.0, 30.0]},
        index=["2020", "2024"],
    )
    out = _tmp()
    result = render_type_p(df, {**SPEC, "snapshot_year": "2024"}, out)
    assert os.path.exists(result)
    os.unlink(result)


def test_render_type_p_normalises_to_100():
    # Values don't need to sum to 100 — renderer normalises
    df = pd.DataFrame(
        {"value": [400.0, 300.0, 200.0, 100.0]},
        index=["A", "B", "C", "D"],
    )
    out = _tmp()
    result = render_type_p(df, SPEC, out)
    assert os.path.exists(result)
    os.unlink(result)
```

- [ ] **Step 1.2: Run tests — expect ImportError or AttributeError (render_type_p not yet defined)**

```bash
cd /Users/mertcandogusoy/newsletter-site
python3 -m pytest tests/test_renderers.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'render_type_p'`

- [ ] **Step 1.3: Add `render_type_p` to `newsletter_agent/renderers/charts.py`**

Insert before the final `render_type_e` function (after `render_type_g`):

```python
def render_type_p(df: pd.DataFrame, spec: dict, output_path: str) -> str:
    """
    Type P — Pie chart (single-year composition snapshot).
    df: index = category labels, single value column.
        OR wide df (index=years, columns=categories) — uses snapshot_year row or latest.
    Values are normalised to 100% internally.
    """
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=BRAND["figure_dpi"])

    # Wide df: pick one row
    if df.shape[1] > 1:
        snapshot_year = str(spec.get("snapshot_year", df.index[-1]))
        row = df.loc[snapshot_year] if snapshot_year in df.index else df.iloc[-1]
        series = row.dropna()
        title_str = f"{spec['title']} ({snapshot_year})"
    else:
        series = df.iloc[:, 0].dropna()
        title_str = spec["title"]

    series = series[series > 0]
    if series.empty:
        plt.close(fig)
        return output_path

    colors = [_color_for(i) for i in range(len(series))]
    wedges, _, autotexts = ax.pie(
        series.values,
        labels=None,
        autopct=lambda p: f"{p:.1f}%" if p >= 5 else "",
        colors=colors,
        startangle=90,
        wedgeprops={"edgecolor": "white", "linewidth": 1.2},
        pctdistance=0.75,
    )
    for at in autotexts:
        at.set_fontsize(7)
        at.set_color("white")
        at.set_fontweight("600")

    ax.set_title(title_str, fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"], pad=8)
    fig.patch.set_facecolor(BRAND["background"])

    ax.legend(wedges, series.index, fontsize=BRAND["font_size_label"],
              loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False)

    bottom_frac = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom_frac, 0.78, 1.0])
    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path
```

- [ ] **Step 1.4: Run tests — expect all pass**

```bash
python3 -m pytest tests/test_renderers.py -v
```

Expected:
```
test_renderers.py::test_render_type_p_single_column PASSED
test_renderers.py::test_render_type_p_wide_uses_latest_row PASSED
test_renderers.py::test_render_type_p_normalises_to_100 PASSED
```

- [ ] **Step 1.5: Add `render_type_p` to `CHART_RENDERER_MAP` in `pipeline.py`**

In `newsletter_agent/pipeline.py`, change the import line:
```python
from newsletter_agent.renderers.charts import render_type_a, render_type_b, render_type_c, render_type_e, render_type_f, render_type_g, render_type_p
```

And add to `CHART_RENDERER_MAP`:
```python
CHART_RENDERER_MAP = {
    "A": render_type_a,
    "B": render_type_b,
    "C": render_type_c,
    "E": render_type_e,
    "F": render_type_f,
    "G": render_type_g,
    "P": render_type_p,
}
```

- [ ] **Step 1.6: Add Type P handler in `_render_figure` in `pipeline.py`**

In `_render_figure`, add after the `elif chart_type == "G":` block and before the `else:` block:

```python
    # ── Type P — Pie chart (composition snapshot) ─────────────────────────
    elif chart_type == "P":
        if len(dfs) == 1:
            wide = list(dfs.values())[0]
            if isinstance(wide.index, pd.DatetimeIndex):
                wide = wide.copy()
                wide.index = wide.index.year.astype(str)
        else:
            parts = {}
            for lbl, df in dfs.items():
                s = df.iloc[:, 0].dropna()
                if isinstance(s.index, pd.DatetimeIndex):
                    s.index = s.index.year.astype(str)
                parts[lbl] = s
            wide = pd.DataFrame(parts).dropna(how="all")
        if wide is None or wide.empty:
            print(f"    [warn] No data for Type P chart '{chart_spec.get('title')}' — skipping.")
            return None
        path = render_type_p(wide, render_spec, output_path)
```

- [ ] **Step 1.7: Verify import works**

```bash
python3 -c "from newsletter_agent.pipeline import CHART_RENDERER_MAP; print(list(CHART_RENDERER_MAP.keys()))"
```

Expected: `['A', 'B', 'C', 'E', 'F', 'G', 'P']`

- [ ] **Step 1.8: Commit**

```bash
git add newsletter_agent/renderers/charts.py newsletter_agent/pipeline.py tests/test_renderers.py
git commit -m "feat: add pie chart renderer (Type P) and wire into pipeline"
```

---

## Task 2: Unit Conversion with Date-Matched FX

**Files:**
- Create: `newsletter_agent/processors/converters.py`
- Create: `tests/test_converters.py`

- [ ] **Step 2.1: Write failing tests**

```python
# tests/test_converters.py
import pandas as pd
import pytest
from newsletter_agent.processors.converters import apply_conversions


def _make_series(values, dates=None):
    if dates is None:
        dates = pd.date_range("2024-01-01", periods=len(values), freq="MS")
    return pd.DataFrame({"value": values}, index=dates)


def test_physical_conversion_USD_MMBtu_to_USD_MWh():
    """Henry Hub at 2 USD/MMBtu should become 2 × 3.41214 = 6.824 USD/MWh."""
    dfs = {"Henry Hub": _make_series([2.0, 3.0, 4.0])}
    specs = [{"label": "Henry Hub", "conversion": "USD_MMBtu_to_USD_MWh"}]
    converted, note = apply_conversions(dfs, specs, period_days=90)
    result = converted["Henry Hub"].iloc[0, 0]
    assert abs(result - 2.0 * 3.41214) < 0.001
    assert "3.41" in note
    assert "Henry Hub" in note


def test_no_conversion_when_field_absent():
    """Series without conversion field must be returned unchanged."""
    dfs = {"TTF": _make_series([30.0, 31.0])}
    specs = [{"label": "TTF"}]  # no "conversion" key
    converted, note = apply_conversions(dfs, specs, period_days=60)
    assert converted["TTF"].iloc[0, 0] == 30.0
    assert note == ""


def test_unknown_label_skipped():
    """Labels in specs that don't exist in dfs are silently skipped."""
    dfs = {"Henry Hub": _make_series([2.0])}
    specs = [{"label": "Missing Series", "conversion": "USD_MMBtu_to_USD_MWh"}]
    converted, note = apply_conversions(dfs, specs, period_days=30)
    assert "Missing Series" not in converted
    assert converted["Henry Hub"].iloc[0, 0] == 2.0


def test_conversion_note_format():
    """Note must mention the series name and conversion direction."""
    dfs = {"Henry Hub": _make_series([2.0])}
    specs = [{"label": "Henry Hub", "conversion": "USD_MMBtu_to_USD_MWh"}]
    _, note = apply_conversions(dfs, specs, period_days=30)
    assert "USD/MWh" in note
    assert "Henry Hub" in note
```

- [ ] **Step 2.2: Run tests — expect ImportError**

```bash
python3 -m pytest tests/test_converters.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'newsletter_agent.processors.converters'`

- [ ] **Step 2.3: Create `newsletter_agent/processors/converters.py`**

```python
# newsletter_agent/processors/converters.py
"""
Unit conversion for cross-source series.
Applies named conversions (physical constants + date-matched FX) before rendering.
"""
import pandas as pd
import yfinance as yf
from datetime import date, timedelta
from newsletter_agent.config import YF_LOCK

# Fixed physical conversion factors
_PHYSICAL = {
    "USD_MMBtu_to_USD_MWh": 3.41214,  # 1 MWh = 3.41214 MMBtu
}


def _fetch_fx(ticker: str, period_days: int) -> pd.Series:
    """Fetch daily FX close prices for the given period."""
    end = date.today()
    start = end - timedelta(days=period_days)
    try:
        with YF_LOCK:
            raw = yf.download(ticker, start=str(start), end=str(end),
                              progress=False, auto_adjust=True)
        if raw.empty:
            return pd.Series(dtype=float)
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"].iloc[:, 0]
        else:
            close = raw["Close"]
        return close.squeeze()
    except Exception as e:
        print(f"    [converters] FX fetch failed for {ticker}: {e}")
        return pd.Series(dtype=float)


def apply_conversions(dfs: dict, series_specs: list, period_days: int) -> tuple:
    """
    Apply unit conversions specified in series_specs[i]["conversion"].

    Supported conversion names:
      "USD_MMBtu_to_USD_MWh"  — multiply by 3.41214 (physical constant)
      "EUR_MWh_to_USD_MWh"    — multiply by date-matched EUR/USD rate from yfinance

    Returns:
      (converted_dfs: dict, note: str)
      converted_dfs is a shallow copy of dfs with converted DataFrames replaced.
      note is a Danish-language explanation of all conversions applied, for chart footer.
    """
    converted = dict(dfs)
    notes = []

    # Pre-fetch EUR/USD only if any series needs it (avoid unnecessary API call)
    eur_usd: pd.Series | None = None
    if any(s.get("conversion") == "EUR_MWh_to_USD_MWh" for s in series_specs):
        eur_usd = _fetch_fx("EURUSD=X", period_days)

    for spec in series_specs:
        label = spec.get("label", "")
        conversion = spec.get("conversion", "")
        if not conversion or label not in converted:
            continue

        df = converted[label]
        series = df.iloc[:, 0].copy()

        if conversion == "USD_MMBtu_to_USD_MWh":
            factor = _PHYSICAL["USD_MMBtu_to_USD_MWh"]
            converted[label] = (series * factor).to_frame(name=label)
            notes.append(
                f"{label} omregnet fra USD/MMBtu til USD/MWh (faktor: {factor})"
            )

        elif conversion == "EUR_MWh_to_USD_MWh":
            if eur_usd is not None and not eur_usd.empty:
                # Outer join + forward-fill for date alignment
                aligned = (
                    series.to_frame("v")
                    .join(eur_usd.rename("fx"), how="outer")
                    .ffill()
                    .dropna()
                )
                converted[label] = (aligned["v"] * aligned["fx"]).to_frame(name=label)
                latest_rate = float(eur_usd.iloc[-1])
                latest_date = eur_usd.index[-1].strftime("%-d %b %Y")
                notes.append(
                    f"{label} omregnet fra EUR/MWh til USD/MWh "
                    f"(EUR/USD dato-matchet, seneste: {latest_rate:.3f}, {latest_date})"
                )
            else:
                notes.append(
                    f"{label}: EUR/USD-kurs ikke tilgængelig — ingen konvertering anvendt"
                )

    note = ". ".join(notes) + "." if notes else ""
    return converted, note
```

- [ ] **Step 2.4: Run tests — expect all pass**

```bash
python3 -m pytest tests/test_converters.py -v
```

Expected:
```
test_converters.py::test_physical_conversion_USD_MMBtu_to_USD_MWh PASSED
test_converters.py::test_no_conversion_when_field_absent PASSED
test_converters.py::test_unknown_label_skipped PASSED
test_converters.py::test_conversion_note_format PASSED
```

- [ ] **Step 2.5: Commit**

```bash
git add newsletter_agent/processors/converters.py tests/test_converters.py
git commit -m "feat: add unit conversion module with date-matched FX (EUR/USD)"
```

---

## Task 3: Hybrid Dataset Routing

**Files:**
- Create: `newsletter_agent/routing.py`
- Create: `tests/test_routing.py`

- [ ] **Step 3.1: Write failing tests**

```python
# tests/test_routing.py
from newsletter_agent.routing import get_routing_hint


def test_eu_energy_triggers_eurostat():
    hint = get_routing_hint("Vis EU's energimix over de seneste 10 år")
    assert "eurostat" in hint.lower()
    assert "eu_energy_mix" in hint


def test_us_energy_triggers_eia():
    hint = get_routing_hint("USA's energiforbrug fordelt på brændstofstype")
    assert "eia_mix" in hint


def test_cross_region_gas_triggers_conversion():
    hint = get_routing_hint("Sammenlign EU TTF naturgas med US Henry Hub gaspriser")
    assert "EUR_MWh_to_USD_MWh" in hint
    assert "USD_MMBtu_to_USD_MWh" in hint


def test_eu_inflation_triggers_eurostat_hicp():
    hint = get_routing_hint("EU inflation og HICP siden 2022")
    assert "eu_hicp" in hint


def test_eu_unemployment_triggers_eurostat():
    hint = get_routing_hint("Eurozone ledighed fra 2020 til i dag")
    assert "eu_unemployment" in hint


def test_unrelated_brief_returns_empty():
    hint = get_routing_hint("S&P 500 og Nasdaq performance siden 2023")
    assert hint == ""


def test_eu_gdp_triggers_eurostat():
    hint = get_routing_hint("EU BNP vækst og ECB renten")
    assert "eu_gdp_growth" in hint
```

- [ ] **Step 3.2: Run tests — expect ImportError**

```bash
python3 -m pytest tests/test_routing.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'newsletter_agent.routing'`

- [ ] **Step 3.3: Create `newsletter_agent/routing.py`**

```python
# newsletter_agent/routing.py
"""
Hybrid dataset routing: deterministic keyword rules produce a routing_hint string
that is injected into the orchestrator prompt. LLM can override if data contradicts.
"""
import re


def _re(pattern: str):
    return re.compile(pattern, re.IGNORECASE)


_EU   = _re(r"\b(eu|europe[an]*|eurozone|europ[aæ]|eu27)\b")
_US   = _re(r"\b(us|usa|american?|united states|amerikans?k)\b")
_NRG  = _re(r"\b(energy|energi|energimix|brændstofstype|fuel|forbrug)\b")
_GAS  = _re(r"\b(gas|naturgas|natural gas)\b")
_TTF  = _re(r"\bttf\b")
_HH   = _re(r"\b(henry hub|hh)\b")
_INFL = _re(r"\b(inflation|hicp|prisvækst)\b")
_UNEM = _re(r"\b(unemployment|ledighed|arbejdsløs)\b")
_GDP  = _re(r"\b(gdp|bnp|growth|vækst)\b")

ROUTING_RULES: list[tuple] = [
    # EU energy mix → Eurostat
    (
        lambda b: _EU.search(b) and _NRG.search(b),
        "For EU-energidata: brug specialist='eurostat', ticker='eu_energy_mix', "
        "source='eurostat_mix'. Visualiser med type='F' (stablet søjle).",
    ),
    # EU inflation → Eurostat HICP
    (
        lambda b: _EU.search(b) and _INFL.search(b),
        "For EU-inflation: brug specialist='eurostat', ticker='eu_hicp', "
        "source='eurostat_ts'. Type='A'.",
    ),
    # EU unemployment → Eurostat
    (
        lambda b: _EU.search(b) and _UNEM.search(b),
        "For EU-ledighed: brug specialist='eurostat', ticker='eu_unemployment', "
        "source='eurostat_ts'. Type='A'.",
    ),
    # EU GDP → Eurostat
    (
        lambda b: _EU.search(b) and _GDP.search(b),
        "For EU-BNP/vækst: brug specialist='eurostat', ticker='eu_gdp_growth', "
        "source='eurostat_ts'. Type='A'.",
    ),
    # US energy mix → EIA
    (
        lambda b: _US.search(b) and _NRG.search(b),
        "For US-energimix: brug specialist='energy', source='eia_mix', "
        "label='Energimix USA'. Type='F' (stablet søjle).",
    ),
    # Cross-region gas → conversion required
    (
        lambda b: _GAS.search(b) and (_TTF.search(b) or _EU.search(b)) and (_HH.search(b) or _US.search(b)),
        "For EU/US-gassammenligning: brug TTF=F (EUR/MWh, conversion='EUR_MWh_to_USD_MWh') "
        "og NG=F (USD/MMBtu, conversion='USD_MMBtu_to_USD_MWh'). Fælles y-akse: USD/MWh. Type='A'.",
    ),
]


def get_routing_hint(brief: str) -> str:
    """
    Match brief against keyword rules.
    Returns a routing hint string for injection into the orchestrator prompt,
    or empty string if no rules match.
    """
    matched = []
    for predicate, hint in ROUTING_RULES:
        try:
            if predicate(brief):
                matched.append(hint)
        except Exception:
            pass
    if not matched:
        return ""
    lines = "\n".join(f"- {h}" for h in matched)
    return f"\nROUTING HINTS (følg disse medmindre data klart modsiger dem):\n{lines}\n"
```

- [ ] **Step 3.4: Run tests — expect all pass**

```bash
python3 -m pytest tests/test_routing.py -v
```

Expected: all 7 tests PASSED

- [ ] **Step 3.5: Commit**

```bash
git add newsletter_agent/routing.py tests/test_routing.py
git commit -m "feat: add hybrid keyword routing for dataset selection"
```

---

## Task 4: Pipeline Wiring — Conversions, Routing, Re-render Context

**Files:**
- Modify: `newsletter_agent/pipeline.py`
- Modify: `newsletter_agent/orchestrator.py`

- [ ] **Step 4.1: Add imports to `pipeline.py`**

At the top of `newsletter_agent/pipeline.py`, add after existing imports:

```python
from newsletter_agent.processors.converters import apply_conversions
from newsletter_agent.routing import get_routing_hint
```

- [ ] **Step 4.2: Update `build_task_manifest` call in `orchestrator.py` to accept preferred_types and routing_hint**

In `newsletter_agent/orchestrator.py`, replace:

```python
def build_task_manifest(brief: str) -> dict:
    """Parse a topic brief into a TaskManifest dict via one LLM call."""
    import json as _json, os as _os
    prompt = f"Topic brief: {brief}"
    manifest = call_llm(prompt)
```

With:

```python
def build_task_manifest(brief: str, preferred_types: list = None, routing_hint: str = "") -> dict:
    """Parse a topic brief into a TaskManifest dict via one LLM call."""
    import json as _json, os as _os
    parts = [f"Topic brief: {brief}"]
    if preferred_types:
        parts.append(
            f"PREFERRED CHART TYPES (in priority order — honour these unless data is fundamentally incompatible): {preferred_types}"
        )
    if routing_hint:
        parts.append(routing_hint)
    prompt = "\n".join(parts)
    manifest = call_llm(prompt)
```

- [ ] **Step 4.3: Update `run()` in `pipeline.py` to call routing + apply conversions + store rerender context**

In `newsletter_agent/pipeline.py`, replace the `run()` function signature and Step 1:

```python
def run(brief: str, output_dir: str = "output", preferred_types: list = None) -> list:
    """
    Main pipeline entry point.
    brief: free-form topic string from department.
    output_dir: where to save PNG files and manifest.json.
    preferred_types: optional list of chart type codes e.g. ["A", "G"] — passed to orchestrator.
    Returns list of FigurePackage dicts.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Orchestrate — 1 LLM call → TaskManifest
    print("\n[1/4] Orchestrating — asking Lead Agent to plan figures...")
    routing_hint = get_routing_hint(brief)
    if routing_hint:
        print(f"      [routing] Hint injected: {routing_hint.strip()[:80]}...")
    manifest = build_task_manifest(brief, preferred_types=preferred_types, routing_hint=routing_hint)
    specialists = manifest.get("specialists", [])
    print(f"      Specialists activated: {', '.join(specialists)}")
```

Then after Step 2 (after `specialist_results` is populated), add the conversion step:

```python
    # Step 2b: Apply unit conversions (date-matched FX where needed)
    for spec_name in specialists:
        series_specs = manifest.get(spec_name, {}).get("series", [])
        if not any(s.get("conversion") for s in series_specs):
            continue
        period_days = max(
            (c.get("period_days", 730) for c in manifest.get(spec_name, {}).get("charts", [])),
            default=730,
        )
        print(f"  [{spec_name}] Applying unit conversions...")
        converted_dfs, conv_note = apply_conversions(
            specialist_results[spec_name]["dataframes"], series_specs, period_days
        )
        specialist_results[spec_name]["dataframes"] = converted_dfs
        if conv_note:
            specialist_results[spec_name]["conversion_note"] = conv_note
            print(f"  [{spec_name}] Conversion: {conv_note[:80]}...")
```

- [ ] **Step 4.4: Append conversion note to chart spec note before rendering**

In `_render_figure`, after `render_spec = {**chart_spec, "kilde": kilde_str}`, add:

```python
    # Append any unit conversion note to the chart's note field
    conv_note = specialist_result.get("conversion_note", "")
    if conv_note:
        existing_note = render_spec.get("note", "").rstrip(". ")
        render_spec = {**render_spec, "note": f"{existing_note} {conv_note}".strip()}
```

- [ ] **Step 4.5: Store rerender context alongside figures**

In `run()`, after Step 3 sets up the packages list and before the Step 5 manifest save, build `rerender_context.json`:

```python
    # Build rerender context — one entry per figure, stored for /rerender endpoint
    rerender_ctx = []
    fig_ctx_idx = 0
    for spec_name in specialists:
        result = specialist_results[spec_name]
        for chart_spec in result["chart_specs"]:
            rerender_ctx.append({
                "figure_id":   fig_ctx_idx,
                "specialist":  spec_name,
                "series_specs": manifest.get(spec_name, {}).get("series", []),
                "chart_spec":  chart_spec,
                "brief":       brief,
            })
            fig_ctx_idx += 1

    ctx_path = os.path.join(output_dir, "rerender_context.json")
    with open(ctx_path, "w") as f:
        import json as _json2
        _json2.dump(rerender_ctx, f, indent=2)
```

- [ ] **Step 4.6: Include rerender context in the `/run` "done" event figures payload**

In `app.py`'s `do_run()` function, update the figures list to include rerender context. First, load the context file:

```python
            # Load rerender context to attach to each figure
            import json as _json
            ctx_path = os.path.join(OUTPUT_DIR, "rerender_context.json")
            rerender_ctx = {}
            if os.path.exists(ctx_path):
                with open(ctx_path) as f:
                    for entry in _json.load(f):
                        rerender_ctx[entry["figure_id"]] = entry

            figures = [
                {
                    "path":          os.path.basename(p["path"]),
                    "title":         p["metadata"]["title"],
                    "note":          p["metadata"]["note"],
                    "kilde":         p["metadata"]["kilde"],
                    "reviewer_flag": p["metadata"].get("reviewer_flag", ""),
                    "chart_type":    p["metadata"].get("chart_type", "A"),
                    "figure_id":     i,
                    "rerender_ctx":  rerender_ctx.get(i, {}),
                }
                for i, p in enumerate(packages)
            ]
```

- [ ] **Step 4.7: Verify pipeline still imports cleanly**

```bash
python3 -c "
from newsletter_agent.pipeline import run, CHART_RENDERER_MAP, SPECIALIST_MAP
from newsletter_agent.orchestrator import build_task_manifest
print('pipeline OK — chart types:', list(CHART_RENDERER_MAP.keys()))
print('specialists:', list(SPECIALIST_MAP.keys()))
"
```

Expected:
```
pipeline OK — chart types: ['A', 'B', 'C', 'E', 'F', 'G', 'P']
specialists: ['energy', 'rates', 'macro', 'commodities', 'equities', 'eurostat']
```

- [ ] **Step 4.8: Commit**

```bash
git add newsletter_agent/pipeline.py newsletter_agent/orchestrator.py
git commit -m "feat: wire conversions + routing into pipeline; add rerender context"
```

---

## Task 5: Orchestrator System Prompt Updates

**Files:**
- Modify: `newsletter_agent/orchestrator.py`

- [ ] **Step 5.1: Add `conversion` field documentation to the series spec example in SYSTEM_PROMPT**

In `newsletter_agent/orchestrator.py`, in the SYSTEM_PROMPT, find the series example block:

```json
      {
        "ticker": "BZ=F",             // yfinance ticker OR fred series_id OR "eia" OR "gie"
        "source": "yfinance",         // "yfinance" | "fred" | "eia" | "gie"
        "label": "Brent Crude",       // human-readable label for chart legend
        "region": "Global",           // region label shown on chart
        "unit": "USD/barrel"          // exact unit string for axis label
      }
```

Replace with:

```json
      {
        "ticker": "BZ=F",             // yfinance ticker OR fred series_id OR EIA MSN code
        "source": "yfinance",         // "yfinance" | "fred" | "eia" | "eia_mix" | "eurostat_ts" | "eurostat_mix"
        "label": "Brent Crude",       // human-readable label for chart legend
        "region": "Global",           // region label shown on chart
        "unit": "USD/barrel",         // exact unit string for axis label
        "conversion": ""              // OPTIONAL: "USD_MMBtu_to_USD_MWh" | "EUR_MWh_to_USD_MWh"
                                      // Set when this series needs unit conversion before plotting.
                                      // USD_MMBtu_to_USD_MWh: for Henry Hub (NG=F) when comparing with TTF on same chart.
                                      // EUR_MWh_to_USD_MWh: for TTF (TTF=F) when comparing with Henry Hub on same chart.
                                      // Conversion note is auto-appended to chart footer. Leave empty string or omit if not needed.
      }
```

- [ ] **Step 5.2: Add Type P instructions to SYSTEM_PROMPT chart types**

Find the chart type comment line:

```
        "type": "A",                  // A=time series, B=cross-country bar, D=table, E=before-after bar, F=100%-stacked bar (energy mix), G=horizontal bar (sector/country ranking)
```

Replace with:

```
        "type": "A",                  // A=time series, B=cross-country bar, D=table, E=before-after bar,
                                      // F=100%-stacked bar (energy mix / composition over years),
                                      // G=horizontal bar (sector/country ranking),
                                      // P=pie chart (single-year composition snapshot, sum=100%)
```

- [ ] **Step 5.3: Add gas unit conversion rule to SYSTEM_PROMPT**

Find the line that says:
```
- CRITICAL: NEVER put BZ=F (Brent, ~$80/barrel) and NG=F (Henry Hub, ~$2/MMBtu) on the same chart with absolute prices.
```

Add after it:

```
- CRITICAL — GAS UNIT CONVERSION: When comparing EU gas (TTF=F, EUR/MWh) and US gas (NG=F, USD/MMBtu)
  on the same chart, you MUST add "conversion" fields to harmonise units to USD/MWh:
    TTF=F  → "conversion": "EUR_MWh_to_USD_MWh"    (pipeline fetches live EUR/USD and multiplies)
    NG=F   → "conversion": "USD_MMBtu_to_USD_MWh"   (pipeline multiplies by 3.41214)
  Set y_label to "USD/MWh". The conversion note is auto-added to the chart footer — do NOT add it yourself.
  Do NOT set y_label to "Indekseret (basis=100)" for gas comparisons — use USD/MWh with conversions instead.
```

- [ ] **Step 5.4: Verify SYSTEM_PROMPT is valid Python (no syntax errors)**

```bash
python3 -c "from newsletter_agent.orchestrator import SYSTEM_PROMPT, build_task_manifest; print('OK, prompt length:', len(SYSTEM_PROMPT))"
```

Expected: `OK, prompt length: <some number>`

- [ ] **Step 5.5: Commit**

```bash
git add newsletter_agent/orchestrator.py
git commit -m "feat: update orchestrator prompt — Type P, conversion field, gas unit rules"
```

---

## Task 6: Flask `/rerender` Endpoint + preferred_types in `/run`

**Files:**
- Modify: `app.py`

- [ ] **Step 6.1: Update `/run` endpoint to accept `preferred_types`**

In `app.py`, replace:

```python
    brief = (request.json or {}).get("brief", "").strip()
    if not brief:
        return jsonify({"error": "Brief is required"}), 400
```

With:

```python
    body = request.json or {}
    brief = body.get("brief", "").strip()
    preferred_types = body.get("preferred_types", None)  # e.g. ["A", "G"]
    if not brief:
        return jsonify({"error": "Brief is required"}), 400
```

And in the `do_run` inner function, replace:

```python
            packages = run(brief, output_dir=OUTPUT_DIR)
```

With:

```python
            packages = run(brief, output_dir=OUTPUT_DIR, preferred_types=preferred_types)
```

- [ ] **Step 6.2: Add `POST /rerender` endpoint**

Add after the `/run` route in `app.py`:

```python
@app.route("/rerender", methods=["POST"])
def rerender_figure():
    """
    Re-render a single figure with a different chart type.
    Accepts JSON: {figure_id, chart_type, specialist, series_specs, chart_spec}
    Returns JSON: {path, title, note} or {error}.
    """
    data = request.json or {}
    figure_id    = data.get("figure_id", 0)
    chart_type   = data.get("chart_type", "A")
    specialist   = data.get("specialist")
    series_specs = data.get("series_specs", [])
    chart_spec   = data.get("chart_spec", {})

    if not specialist:
        return jsonify({"error": "specialist is required"}), 400

    # Override chart type in spec
    chart_spec = {**chart_spec, "type": chart_type}

    try:
        from newsletter_agent.pipeline import SPECIALIST_MAP, _render_figure
        from newsletter_agent.processors.converters import apply_conversions
        import tempfile, os as _os

        # Build mini task for this specialist
        mini_task = {"series": series_specs, "charts": [chart_spec]}

        # Re-fetch data
        if specialist not in SPECIALIST_MAP:
            return jsonify({"error": f"Unknown specialist: {specialist}"}), 400
        result = SPECIALIST_MAP[specialist](mini_task)
        result["chart_specs"] = [chart_spec]

        # Apply conversions
        period_days = chart_spec.get("period_days", 730)
        converted_dfs, conv_note = apply_conversions(result["dataframes"], series_specs, period_days)
        result["dataframes"] = converted_dfs
        if conv_note:
            existing = chart_spec.get("note", "").rstrip(". ")
            chart_spec = {**chart_spec, "note": f"{existing} {conv_note}".strip()}

        # Render to same output path as original (overwrites)
        output_path = _os.path.join(OUTPUT_DIR, f"figure_{figure_id:02d}.png")
        package = _render_figure(chart_spec, result, output_path)

        if package is None:
            return jsonify({"error": "No renderable data for this chart type"}), 422

        return jsonify({
            "path":  _os.path.basename(package["path"]),
            "title": package["metadata"]["title"],
            "note":  package["metadata"]["note"],
        })

    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "detail": traceback.format_exc()}), 500
```

- [ ] **Step 6.3: Test endpoints start without error**

```bash
python3 -c "
import app
client = app.app.test_client()
# Test /run rejects empty brief
r = client.post('/run', json={'brief': ''})
assert r.status_code == 400
# Test /rerender rejects missing specialist
r = client.post('/rerender', json={'chart_type': 'A'})
assert r.status_code == 400
print('Endpoint smoke tests passed')
"
```

Expected: `Endpoint smoke tests passed`

- [ ] **Step 6.4: Commit**

```bash
git add app.py
git commit -m "feat: add /rerender endpoint; pass preferred_types to run()"
```

---

## Task 7: Frontend — Visualization Panel + Per-Figure Re-render Buttons

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 7.1: Add CSS for the visualization panel and re-render buttons**

In `templates/index.html`, add the following inside the existing `<style>` block (before `</style>`):

```css
    /* ── Viz type panel ── */
    #topRow {
      display: grid;
      grid-template-columns: 210px 1fr;
      gap: 20px;
    }
    #vizPanel .card-header {
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: .05em;
    }
    .viz-section-label {
      font-size: 9px;
      color: #9ca3af;
      text-transform: uppercase;
      font-weight: 600;
      letter-spacing: .06em;
      margin-bottom: 6px;
    }
    .viz-opt {
      display: flex;
      align-items: flex-start;
      gap: 9px;
      padding: 7px 10px;
      border-radius: 5px;
      cursor: pointer;
      margin-bottom: 4px;
      border: 1.5px solid #d1d5db;
      background: #fff;
      transition: border-color .15s, background .15s;
    }
    .viz-opt.active {
      border: 2px solid #11716c;
      background: #f0faf9;
    }
    .viz-opt-labels { flex: 1; }
    .viz-opt-name { font-weight: 600; font-size: 11px; color: #374151; }
    .viz-opt.active .viz-opt-name { color: #11716c; }
    .viz-opt-desc { font-size: 9px; color: #6b7280; }
    .viz-check { color: #11716c; font-size: 12px; font-weight: 700; display: none; }
    .viz-opt.active .viz-check { display: block; }
    .viz-sub { margin: 4px 0 2px 23px; display: flex; flex-direction: column; gap: 3px; }
    .viz-sub-opt {
      display: flex; align-items: center; gap: 7px;
      padding: 5px 8px; border-radius: 4px; font-size: 10px; cursor: pointer;
      background: #f9fafb; border: 1.5px solid #e5e7eb; color: #6b7280;
    }
    .viz-sub-opt.active {
      background: #e8f7f6; border-color: #11716c; color: #11716c; font-weight: 600;
    }
    .viz-sub-dot { width: 6px; height: 6px; border-radius: 50%; background: #d1d5db; flex-shrink: 0; }
    .viz-sub-opt.active .viz-sub-dot { background: #11716c; }
    .viz-hint {
      margin-top: 8px; padding-top: 6px;
      border-top: 1px solid #f3f4f6;
      font-size: 9px; color: #9ca3af; line-height: 1.5;
    }

    /* ── Re-render buttons on figure cards ── */
    .rerender-row {
      padding: 8px 12px;
      background: #f8fafa;
      border-top: 1px solid #e4eaea;
    }
    .rerender-label {
      font-size: 10px; font-weight: 600; color: #374151; margin-bottom: 5px;
    }
    .rerender-btns { display: flex; gap: 4px; flex-wrap: wrap; }
    .rr-btn {
      border-radius: 4px; padding: 4px 8px; font-size: 10px; cursor: pointer;
      border: 1px solid #d1d5db; background: #f3f4f6; color: #374151;
      transition: background .1s;
    }
    .rr-btn.active { background: #11716c; color: #fff; border-color: #11716c; }
    .rr-btn:disabled { opacity: .5; cursor: not-allowed; }
    .fig-spinner {
      display: none;
      align-items: center; justify-content: center;
      height: 60px; color: #11716c; font-size: 12px; gap: 8px;
    }
    .fig-spinner.visible { display: flex; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .spinner-ring {
      width: 18px; height: 18px; border-radius: 50%;
      border: 2px solid #d1d5db; border-top-color: #11716c;
      animation: spin .7s linear infinite;
    }
```

- [ ] **Step 7.2: Replace the brief card section with the two-column top row**

In `templates/index.html`, replace:

```html
  <!-- ── Brief input ── -->
  <div class="card full-width">
    <div class="card-header">📝 Emne-brief</div>
    <div class="card-body">
```

With:

```html
  <!-- ── Top row: viz panel + brief ── -->
  <div class="full-width" id="topRow">

  <!-- Visualization type panel -->
  <div class="card" id="vizPanel">
    <div class="card-header">Visualiseringstype</div>
    <div class="card-body" style="padding:10px">
      <div class="viz-section-label">Vælg én eller flere</div>

      <!-- Figur -->
      <div class="viz-opt active" id="vopt-A" onclick="toggleVizOpt('A')">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="flex-shrink:0;margin-top:1px">
          <polyline points="1,11 4,7 7,9 10,4 13,6" stroke="#11716c" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <div class="viz-opt-labels">
          <div class="viz-opt-name">Figur</div>
          <div class="viz-opt-desc">Time series — linjegraf</div>
        </div>
        <span class="viz-check">✓</span>
      </div>

      <!-- Søjlediagram (parent) -->
      <div class="viz-opt" id="vopt-bar-parent" onclick="toggleVizOpt('bar')">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="flex-shrink:0;margin-top:1px">
          <rect x="1" y="5" width="3" height="8" rx=".5" fill="currentColor"/>
          <rect x="5.5" y="2" width="3" height="11" rx=".5" fill="currentColor"/>
          <rect x="10" y="7" width="3" height="6" rx=".5" fill="currentColor"/>
        </svg>
        <div class="viz-opt-labels">
          <div class="viz-opt-name">Søjlediagram</div>
          <div class="viz-opt-desc">Vælg type nedenfor</div>
        </div>
        <span class="viz-check">✓</span>
      </div>
      <div class="viz-sub" id="bar-subopts" style="display:none">
        <div class="viz-sub-opt active" id="vsub-B" onclick="selectBarSub('B')">
          <span class="viz-sub-dot"></span>Lodret — sammenligning
        </div>
        <div class="viz-sub-opt" id="vsub-G" onclick="selectBarSub('G')">
          <span class="viz-sub-dot"></span>Vandret — ranking
        </div>
        <div class="viz-sub-opt" id="vsub-F" onclick="selectBarSub('F')">
          <span class="viz-sub-dot"></span>Stablet — fordeling over tid
        </div>
      </div>

      <!-- Tabel -->
      <div class="viz-opt" id="vopt-D" onclick="toggleVizOpt('D')">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="flex-shrink:0;margin-top:1px">
          <rect x="1" y="1" width="12" height="12" rx="1" stroke="currentColor" stroke-width="1.2"/>
          <line x1="1" y1="5" x2="13" y2="5" stroke="currentColor" stroke-width="1"/>
          <line x1="1" y1="9" x2="13" y2="9" stroke="currentColor" stroke-width="1"/>
          <line x1="5" y1="1" x2="5" y2="13" stroke="currentColor" stroke-width="1"/>
        </svg>
        <div class="viz-opt-labels">
          <div class="viz-opt-name">Tabel</div>
          <div class="viz-opt-desc">Snapshot — nøgletal</div>
        </div>
        <span class="viz-check">✓</span>
      </div>

      <!-- Cirkeldiagram -->
      <div class="viz-opt" id="vopt-P" onclick="toggleVizOpt('P')">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="flex-shrink:0;margin-top:1px">
          <circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.2"/>
          <path d="M7 7 L7 1.5 A5.5 5.5 0 0 1 12.5 7 Z" fill="#d1d5db"/>
          <path d="M7 7 L12.5 7 A5.5 5.5 0 0 1 4 12 Z" fill="#e5e7eb"/>
        </svg>
        <div class="viz-opt-labels">
          <div class="viz-opt-name">Cirkeldiagram</div>
          <div class="viz-opt-desc">Snapshot — ét år, sum = 100%</div>
        </div>
        <span class="viz-check">✓</span>
      </div>

      <div class="viz-hint">Systemet respekterer dine valg som præference. Tilpasser automatisk til datans natur.</div>
    </div>
  </div>

  <!-- Brief card -->
  <div class="card">
    <div class="card-header">Emne-brief</div>
    <div class="card-body">
```

And after the closing `</div>` of the brief card-body and card, add a closing `</div>` for the `#topRow`:

```html
    </div><!-- end card-body -->
  </div><!-- end brief card -->
  </div><!-- end #topRow -->
```

- [ ] **Step 7.3: Update `renderFigures()` JS to include re-render buttons**

In `templates/index.html`, replace the entire `renderFigures` function:

```javascript
function renderFigures(figures) {
  const grid = document.getElementById('figuresGrid');
  grid.innerHTML = '';
  figures.forEach((fig, i) => {
    const flagHtml = fig.reviewer_flag
      ? `<div style="margin-top:6px;padding:6px 10px;background:#fff7ed;border:1px solid #fed7aa;border-radius:5px;font-size:11px;color:#92400e;">
           <strong>Reviewer flag:</strong> ${fig.reviewer_flag}
         </div>`
      : '';

    const activeType = fig.chart_type || 'A';
    const TYPES = [
      {code: 'A', label: 'Figur'},
      {code: 'B', label: 'Lodret'},
      {code: 'G', label: 'Vandret'},
      {code: 'F', label: 'Stablet'},
      {code: 'D', label: 'Tabel'},
      {code: 'P', label: 'Cirkel'},
    ];
    const btns = TYPES.map(t =>
      `<button class="rr-btn ${t.code === activeType ? 'active' : ''}"
         id="rrbtn-${i}-${t.code}"
         onclick="rerenderFigure(${i}, '${t.code}', this)">${t.label}</button>`
    ).join('');

    const card = document.createElement('div');
    card.className = 'fig-card';
    card.id = `figcard-${i}`;
    card.innerHTML = `
      <img src="/figures/${fig.path}?t=${Date.now()}" alt="${fig.title}"
           id="figimg-${i}" onclick="openLightbox(this.src)" />
      <div class="fig-spinner" id="figspinner-${i}">
        <div class="spinner-ring"></div> Genrenderer...
      </div>
      <div class="rerender-row">
        <div class="rerender-label">Genrender som:</div>
        <div class="rerender-btns">${btns}</div>
      </div>
      ${flagHtml ? `<div class="fig-meta">${flagHtml}</div>` : ''}`;

    card.dataset.ctx = JSON.stringify(fig.rerender_ctx || {});
    grid.appendChild(card);
  });
  document.getElementById('figuresPanel').style.display = 'block';
  document.getElementById('figuresPanel').scrollIntoView({ behavior: 'smooth' });
}
```

- [ ] **Step 7.4: Add `rerenderFigure()` and viz panel JS**

In `templates/index.html`, add the following JS functions before the closing `</script>` tag:

```javascript
// ── Visualization type panel ──
let activeVizTypes = new Set(['A']);
let activeBarSub = 'B';  // default Søjlediagram sub-type

function toggleVizOpt(key) {
  if (key === 'bar') {
    const el = document.getElementById('vopt-bar-parent');
    const subs = document.getElementById('bar-subopts');
    const isActive = el.classList.toggle('active');
    subs.style.display = isActive ? 'flex' : 'none';
    if (isActive) activeVizTypes.add(activeBarSub);
    else { ['B','G','F'].forEach(k => activeVizTypes.delete(k)); }
  } else {
    const el = document.getElementById(`vopt-${key}`);
    const isActive = el.classList.toggle('active');
    if (isActive) activeVizTypes.add(key);
    else activeVizTypes.delete(key);
  }
}

function selectBarSub(subKey) {
  ['B','G','F'].forEach(k => {
    document.getElementById(`vsub-${k}`)?.classList.remove('active');
    activeVizTypes.delete(k);
  });
  document.getElementById(`vsub-${subKey}`)?.classList.add('active');
  activeBarSub = subKey;
  activeVizTypes.add(subKey);
}

function getPreferredTypes() {
  return [...activeVizTypes];
}

// ── Per-figure re-render ──
async function rerenderFigure(figId, chartType, btn) {
  const card = document.getElementById(`figcard-${figId}`);
  const img  = document.getElementById(`figimg-${figId}`);
  const spinner = document.getElementById(`figspinner-${figId}`);
  const ctx  = JSON.parse(card.dataset.ctx || '{}');

  if (!ctx.specialist) {
    alert('Re-render context not available for this figure.');
    return;
  }

  // Disable all buttons for this card
  card.querySelectorAll('.rr-btn').forEach(b => { b.disabled = true; });
  img.style.display = 'none';
  spinner.classList.add('visible');

  try {
    const resp = await fetch('/rerender', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        figure_id:   figId,
        chart_type:  chartType,
        specialist:  ctx.specialist,
        series_specs: ctx.series_specs || [],
        chart_spec:  ctx.chart_spec   || {},
      }),
    });
    const data = await resp.json();
    if (resp.ok) {
      img.src = `/figures/${data.path}?t=${Date.now()}`;
      img.style.display = 'block';
      // Update active button
      card.querySelectorAll('.rr-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      card.dataset.ctx = JSON.stringify({...ctx, chart_spec: {...ctx.chart_spec, type: chartType}});
    } else {
      alert('Fejl ved genrendering: ' + (data.error || 'Ukendt fejl'));
      img.style.display = 'block';
    }
  } catch (err) {
    alert('Netværksfejl: ' + err);
    img.style.display = 'block';
  } finally {
    spinner.classList.remove('visible');
    card.querySelectorAll('.rr-btn').forEach(b => { b.disabled = false; });
  }
}
```

- [ ] **Step 7.5: Update `startRun()` to pass preferred types**

In `templates/index.html`, replace in `startRun()`:

```javascript
    body: JSON.stringify({ brief }),
```

With:

```javascript
    body: JSON.stringify({ brief, preferred_types: getPreferredTypes() }),
```

- [ ] **Step 7.6: Smoke test — start server and verify page loads**

```bash
python3 app.py &
sleep 2
curl -s http://localhost:5050/ | grep -o "vizPanel" | head -1
kill %1
```

Expected: `vizPanel`

- [ ] **Step 7.7: Commit**

```bash
git add templates/index.html
git commit -m "feat: add visualization type panel and per-figure re-render buttons"
```

---

## Self-Review

**Spec coverage check:**
- [x] §2.1 UI viz panel — Task 7
- [x] §2.2 Per-figure re-render with full re-run — Tasks 6 + 7
- [x] §2.3 Type F (already done), Type G (already done), Type P — Task 1
- [x] §2.4 EIA (already done), Eurostat (already done) — covered
- [x] §2.5 Unit conversion with date-matched FX + chart note — Task 2 + Task 4 step 4.4
- [x] §2.6 Hybrid routing — Task 3 + Task 4 step 4.3
- [x] preferred_types flow — Tasks 4.2, 4.3, 6.1, 7.5
- [x] Gas standard unit USD/MWh — Task 5.3

**Placeholder scan:** None found. All steps contain actual code.

**Type consistency:**
- `render_type_p` defined in Task 1, imported in Task 1.5 — consistent
- `apply_conversions(dfs, series_specs, period_days) -> tuple` defined in Task 2, called in Task 4 — consistent
- `get_routing_hint(brief) -> str` defined in Task 3, called in Task 4 — consistent
- `rerender_ctx` stored as dict per figure in Task 4.5, serialised to JSON in Task 4.6, read in Task 7 via `card.dataset.ctx` — consistent

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-18-visualization-type-selection.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints

**Which approach?**
