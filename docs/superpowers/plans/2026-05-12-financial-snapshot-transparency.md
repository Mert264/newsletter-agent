# Financial Snapshot — Full Component Transparency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Chart 2 (Financial Snapshot) to show the underlying components behind every headline number — P&L bridge, FCF bridge, NOA bridge, and NFO bridge — as full time-series across all historical years and LTM.

**Architecture:** Three files change in sequence: (1) `annual_report_fmp.py` adds three LTM fields; (2) `annual_report_reformulator.py` exposes nine new keys derived from variables already computed inside the loop; (3) `annual_report_kpi.py` restructures Chart 2 into four sections using those keys. All changes are purely additive to existing interfaces.

**Tech Stack:** Python, pytest, FMP API data (already mocked in tests)

---

## File Map

| File | Change type | What changes |
|---|---|---|
| `newsletter_agent/specialists/annual_report_fmp.py` | Modify | Add 3 fields to LTM lists |
| `newsletter_agent/specialists/annual_report_reformulator.py` | Modify | Expose 9 new keys in returned dict |
| `newsletter_agent/specialists/annual_report_kpi.py` | Modify | Extend `_ltm_noa_nfo`, restructure Chart 2 |
| `tests/test_annual_report_fmp.py` | Modify | Add 2 LTM field tests |
| `tests/test_annual_report_reformulator.py` | Modify | Update fixture, add 5 new tests |
| `tests/test_annual_report_kpi.py` | Modify | Update REFORMULATED fixture, add 3 new tests |

---

## Task 1: FMP LTM field additions

**Files:**
- Modify: `newsletter_agent/specialists/annual_report_fmp.py:10-17`
- Modify: `tests/test_annual_report_fmp.py`

- [ ] **Step 1: Write two failing tests in `tests/test_annual_report_fmp.py`**

Add these two tests at the end of the file. The `_make_ltm_cf` / `_make_ltm_inc` helpers build quarterly rows from the existing `FAKE_CF` / `FAKE_INCOME` constants already in the file.

```python
@patch("newsletter_agent.specialists.annual_report_fmp.requests.get")
def test_ltm_cashflow_includes_dna_and_dnwc(mock_get):
    cf_row = {**FAKE_CF[0], "changeInWorkingCapital": -1_000}
    mock_get.side_effect = [
        _mock_response(FAKE_INCOME),
        _mock_response(FAKE_BALANCE),
        _mock_response(FAKE_CF),
        _mock_response(FAKE_PROFILE),
        _mock_response(FAKE_RATING),
        _mock_response(FAKE_METRICS),
        _mock_response(FAKE_ESTIMATES),
        _mock_response(FAKE_INCOME),          # income_q
        _mock_response([cf_row] * 4),         # cashflow_q — 4 identical quarters
        _mock_response(FAKE_BALANCE),         # balance_q
    ]
    result = fetch_all("CARL", "test_key")
    ltm_cf = result["ltm_cashflow"]
    assert "depreciationAndAmortization" in ltm_cf, "D&A missing from LTM cashflow"
    assert "changeInWorkingCapital" in ltm_cf, "ΔNWC missing from LTM cashflow"
    # 4 quarters summed
    assert abs(ltm_cf["depreciationAndAmortization"] - 4 * 3500 / 1e6) < 0.001
    assert abs(ltm_cf["changeInWorkingCapital"] - 4 * (-1_000) / 1e6) < 0.001


@patch("newsletter_agent.specialists.annual_report_fmp.requests.get")
def test_ltm_income_includes_gross_profit(mock_get):
    inc_row = {**FAKE_INCOME[0], "grossProfit": 35_000}
    mock_get.side_effect = [
        _mock_response(FAKE_INCOME),
        _mock_response(FAKE_BALANCE),
        _mock_response(FAKE_CF),
        _mock_response(FAKE_PROFILE),
        _mock_response(FAKE_RATING),
        _mock_response(FAKE_METRICS),
        _mock_response(FAKE_ESTIMATES),
        _mock_response([inc_row] * 4),        # income_q — 4 identical quarters
        _mock_response(FAKE_CF),              # cashflow_q
        _mock_response(FAKE_BALANCE),         # balance_q
    ]
    result = fetch_all("CARL", "test_key")
    assert "grossProfit" in result["ltm_income"], "grossProfit missing from LTM income"
    assert abs(result["ltm_income"]["grossProfit"] - 4 * 35_000 / 1e6) < 0.001
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/mertcandogusoy/newsletter-site
python -m pytest tests/test_annual_report_fmp.py::test_ltm_cashflow_includes_dna_and_dnwc tests/test_annual_report_fmp.py::test_ltm_income_includes_gross_profit -v
```

Expected: FAIL — `AssertionError: D&A missing from LTM cashflow`

- [ ] **Step 3: Implement — modify `annual_report_fmp.py` lines 10-17**

```python
_LTM_INCOME_FIELDS = [
    "revenue", "operatingIncome", "netIncome", "interestExpense",
    "weightedAverageShsOutDil", "weightedAverageShsOut",
    "grossProfit",
]
_LTM_CASHFLOW_FIELDS = [
    "operatingCashFlow", "capitalExpenditure", "freeCashFlow",
    "commonStockRepurchased", "dividendsPaid",
    "depreciationAndAmortization", "changeInWorkingCapital",
]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_annual_report_fmp.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git -C /Users/mertcandogusoy/newsletter-site add \
  newsletter_agent/specialists/annual_report_fmp.py \
  tests/test_annual_report_fmp.py
git -C /Users/mertcandogusoy/newsletter-site commit -m "feat: add grossProfit, D&A, ΔNWC to LTM field lists"
```

---

## Task 2: Reformulator — expose new component keys

**Files:**
- Modify: `newsletter_agent/specialists/annual_report_reformulator.py`
- Modify: `tests/test_annual_report_reformulator.py`

- [ ] **Step 1: Update `_make_fmp_data` fixture and add five failing tests**

In `tests/test_annual_report_reformulator.py`, modify `_make_fmp_data` to include `grossProfit` in income rows. Add `with_cf` parameter for cashflow data (existing tests pass `with_cf=False` by default and are unaffected):

```python
def _make_fmp_data(n_years=3, with_cf=False):
    """Produces n_years of identical synthetic FMP data (newest first)."""
    income = []
    balance = []
    cashflow = []
    for i in range(n_years):
        year = 2024 - i
        income.append({
            "date": f"{year}-12-31",
            "revenue": 100_000,
            "operatingIncome": 20_000,
            "grossProfit": 40_000,
            "netIncome": 12_000,
            "comprehensiveIncomePeriodChange": 11_500,
            "interestExpense": 2_000,
            "weightedAverageShsOutDil": 500,
        })
        balance.append({
            "date": f"{year}-12-31",
            "totalAssets": 200_000,
            "totalLiabilities": 120_000,
            "cashAndCashEquivalents": 10_000,
            "shortTermInvestments": 5_000,
            "longTermInvestments": 5_000,
            "shortTermDebt": 8_000,
            "longTermDebt": 30_000,
            "capitalLeaseObligations": 2_000,
            "totalStockholdersEquity": 75_000,
            "minorityInterest": 5_000,
            "goodwillAndIntangibleAssets": 20_000,
        })
        if with_cf:
            cashflow.append({
                "date": f"{year}-12-31",
                "operatingCashFlow": 16_000,
                "capitalExpenditure": -8_000,
                "freeCashFlow": 0,
                "depreciationAndAmortization": 5_000,
                "changeInWorkingCapital": -1_000,
            })
    return {
        "income": income,
        "balance": balance,
        "cashflow": cashflow if with_cf else [],
        "profile": {},
        "rating": [],
        "metrics": [],
        "estimates": [],
    }
```

Add five new tests at the end of the file:

```python
def test_returns_new_component_keys():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    for key in ["gross_profit", "ebit", "dna", "capex", "dnwc",
                "op_assets", "op_liabs", "gross_debt", "fin_assets"]:
        assert key in result, f"Missing new key: {key}"
        assert len(result[key]) == len(result["years"]), f"{key} length mismatch"


def test_ebit_matches_nopat_pretax():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    for i, ebit in enumerate(result["ebit"]):
        expected_oi = ebit * (1 - 0.22)
        assert abs(result["OI"][i] - expected_oi) < 0.01, \
            f"Year {result['years'][i]}: EBIT*{(1-0.22):.2f} != NOPAT"


def test_noa_equals_op_assets_minus_op_liabs():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    for i in range(len(result["years"])):
        expected = result["op_assets"][i] - result["op_liabs"][i]
        assert abs(result["NOA"][i] - expected) < 0.01, \
            f"Year {result['years'][i]}: NOA bridge mismatch"


def test_nfo_equals_gross_debt_minus_fin_assets():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    for i in range(len(result["years"])):
        expected = result["gross_debt"][i] - result["fin_assets"][i]
        assert abs(result["NFO"][i] - expected) < 0.01, \
            f"Year {result['years'][i]}: NFO bridge mismatch"


def test_dna_and_capex_populated_from_cashflow():
    data = _make_fmp_data(3, with_cf=True)
    result = reformulate(data, t=0.22)
    for i in range(len(result["years"])):
        assert abs(result["dna"][i] - 5_000) < 0.01,  f"D&A wrong year {i}"
        assert abs(result["capex"][i] - (-8_000)) < 0.01, f"CapEx wrong year {i}"
        assert abs(result["dnwc"][i] - (-1_000)) < 0.01, f"ΔNWC wrong year {i}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_annual_report_reformulator.py::test_returns_new_component_keys \
  tests/test_annual_report_reformulator.py::test_ebit_matches_nopat_pretax \
  tests/test_annual_report_reformulator.py::test_noa_equals_op_assets_minus_op_liabs \
  tests/test_annual_report_reformulator.py::test_nfo_equals_gross_debt_minus_fin_assets \
  tests/test_annual_report_reformulator.py::test_dna_and_capex_populated_from_cashflow -v
```

Expected: FAIL — `AssertionError: Missing new key: gross_profit`

- [ ] **Step 3: Implement — modify `annual_report_reformulator.py`**

**3a.** After the existing list declarations (after `NCI_l, equity_l, goodwill_l, avg_NOA_l, cash_fcf_l = [], [], [], [], []`), add:

```python
gross_profit_l, ebit_l, dna_l, capex_l, dnwc_l = [], [], [], [], []
op_assets_l, op_liabs_l, gross_debt_l, fin_assets_l = [], [], [], []
```

**3b.** Inside the loop, immediately after the existing `_ocf`/`_capex`/`_cfcf` lines, add:

```python
_dna  = _safe(cf.get("depreciationAndAmortization"))
_dnwc = _safe(cf.get("changeInWorkingCapital"))
```

**3c.** Inside the loop, at the end of the per-year append block (alongside the `ROCE_l.append`, `NCI_l.append`, etc. lines), add:

```python
gross_profit_l.append(_safe(inc.get("grossProfit")))
ebit_l.append(ebit)
dna_l.append(_dna)
capex_l.append(_capex)
dnwc_l.append(_dnwc)
op_assets_l.append(op_assets)
op_liabs_l.append(op_liabs)
gross_debt_l.append(fin_liabs)
fin_assets_l.append(fin_assets)
```

**3d.** In the returned dict, add the nine new keys alongside the existing ones:

```python
"gross_profit": gross_profit_l,
"ebit":         ebit_l,
"dna":          dna_l,
"capex":        capex_l,
"dnwc":         dnwc_l,
"op_assets":    op_assets_l,
"op_liabs":     op_liabs_l,
"gross_debt":   gross_debt_l,
"fin_assets":   fin_assets_l,
```

- [ ] **Step 4: Run all reformulator tests**

```bash
python -m pytest tests/test_annual_report_reformulator.py -v
```

Expected: all PASS (including existing tests — new keys are additive)

- [ ] **Step 5: Commit**

```bash
git -C /Users/mertcandogusoy/newsletter-site add \
  newsletter_agent/specialists/annual_report_reformulator.py \
  tests/test_annual_report_reformulator.py
git -C /Users/mertcandogusoy/newsletter-site commit -m "feat: expose component keys in reformulated dict (ebit, dna, capex, dnwc, op_assets, op_liabs, gross_debt, fin_assets, gross_profit)"
```

---

## Task 3: KPI — extend `_ltm_noa_nfo` return tuple

**Files:**
- Modify: `newsletter_agent/specialists/annual_report_kpi.py:100-120` (function), `277` (caller)

This task changes the return signature of `_ltm_noa_nfo` before Chart 2 is restructured. Running existing tests after this step verifies nothing breaks.

- [ ] **Step 1: Modify `_ltm_noa_nfo` in `annual_report_kpi.py`**

Current function (around line 100):

```python
def _ltm_noa_nfo(ltm_bal: dict, ltm_revenue: float = 0.0):
    if not ltm_bal:
        return None, None
    def s(k):
        return float(ltm_bal.get(k) or 0)
    cash_total    = s("cashAndCashEquivalents")
    op_cash_floor = 0.02 * ltm_revenue
    excess_cash   = max(0.0, cash_total - op_cash_floor)
    fin_assets = excess_cash + s("shortTermInvestments") + s("longTermInvestments")
    fin_liabs  = s("shortTermDebt") + s("longTermDebt") + s("capitalLeaseObligations")
    op_assets  = s("totalAssets") - fin_assets
    op_liabs   = s("totalLiabilities") - fin_liabs
    return op_assets - op_liabs, fin_liabs - fin_assets
```

Replace with:

```python
def _ltm_noa_nfo(ltm_bal: dict, ltm_revenue: float = 0.0):
    if not ltm_bal:
        return None, None, None, None, None, None
    def s(k):
        return float(ltm_bal.get(k) or 0)
    cash_total    = s("cashAndCashEquivalents")
    op_cash_floor = 0.02 * ltm_revenue
    excess_cash   = max(0.0, cash_total - op_cash_floor)
    fin_assets = excess_cash + s("shortTermInvestments") + s("longTermInvestments")
    fin_liabs  = s("shortTermDebt") + s("longTermDebt") + s("capitalLeaseObligations")
    op_assets  = s("totalAssets") - fin_assets
    op_liabs   = s("totalLiabilities") - fin_liabs
    return (op_assets - op_liabs, fin_liabs - fin_assets,
            op_assets, op_liabs, fin_liabs, fin_assets)
```

- [ ] **Step 2: Update the caller in `build_chart_specs` (around line 277)**

Current:
```python
ltm_noa, ltm_nfo = _ltm_noa_nfo(ltm_bal, ltm_rev or 0.0) if has_ltm else (None, None)
```

Replace with:
```python
(ltm_noa, ltm_nfo,
 ltm_op_assets, ltm_op_liabs,
 ltm_gross_debt, ltm_fin_assets) = (
    _ltm_noa_nfo(ltm_bal, ltm_rev or 0.0) if has_ltm
    else (None, None, None, None, None, None)
)
```

- [ ] **Step 3: Update `REFORMULATED` fixture in `tests/test_annual_report_kpi.py`**

Add the nine new keys to the `REFORMULATED` dict (the KPI builder will access them in Task 4 — add them now so the fixture is ready):

```python
REFORMULATED = {
    # --- existing keys (unchanged) ---
    "years": [2020, 2021, 2022, 2023, 2024],
    "revenue":       [100_000] * 5,
    "NOA":           [100_000] * 5,
    "NFO":           [40_000]  * 5,
    "OI":            [15_600]  * 5,
    "FCF":           [None, 15_600, 15_600, 15_600, 15_600],
    "cash_fcf":      [None, 14_000, 14_000, 14_000, 14_000],
    "RNOA":          [0.156] * 5,
    "OG":            [0.156] * 5,
    "ATO":           [1.0]   * 5,
    "FLEV":          [0.73]  * 5,
    "NBC":           [0.04]  * 5,
    "SPREAD":        [0.116] * 5,
    "ROCE":          [0.16]  * 5,
    "NCI":           [5_000] * 5,
    "common_equity": [55_000] * 5,
    "historical_avgs": {"OG": 0.156, "ATO": 1.0, "revenue_cagr": 0.03},
    "flags": [],
    "excluded_years": set(),
    "n_avg_years": 5,
    # --- new keys ---
    "gross_profit":  [40_000]  * 5,
    "ebit":          [20_000]  * 5,
    "dna":           [5_000]   * 5,
    "capex":         [-8_000]  * 5,
    "dnwc":          [-2_000]  * 5,
    "op_assets":     [150_000] * 5,
    "op_liabs":      [50_000]  * 5,
    "gross_debt":    [80_000]  * 5,
    "fin_assets":    [40_000]  * 5,
}
```

- [ ] **Step 4: Run all KPI tests to confirm nothing broke**

```bash
python -m pytest tests/test_annual_report_kpi.py -v
```

Expected: all PASS (Chart 2 rows unchanged yet — `_ltm_noa_nfo` callers updated correctly)

- [ ] **Step 5: Commit**

```bash
git -C /Users/mertcandogusoy/newsletter-site add \
  newsletter_agent/specialists/annual_report_kpi.py \
  tests/test_annual_report_kpi.py
git -C /Users/mertcandogusoy/newsletter-site commit -m "refactor: extend _ltm_noa_nfo to return op/fin components; update REFORMULATED fixture"
```

---

## Task 4: KPI — restructure Chart 2 into four sections

**Files:**
- Modify: `newsletter_agent/specialists/annual_report_kpi.py:265-370` (snap section)
- Modify: `tests/test_annual_report_kpi.py`

- [ ] **Step 1: Write three failing tests for the new Chart 2 rows**

Add these at the end of `tests/test_annual_report_kpi.py`. All three use the same `build_chart_specs` call pattern and a helper to find Chart 2.

```python
def _get_chart2_indicators(specs):
    chart2 = next(
        s for s in specs
        if s["type"] == "D" and "regnskab" in s.get("title", "").lower()
    )
    return [r.get("indicator", "") for r in chart2["table_data"]["rows"]]


def test_chart2_has_pl_bridge_rows():
    specs, _ = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                  REFORMULATED, WACC_DATA, DCF_SCENARIOS, SENSITIVITY, FAKE_FMP)
    inds = _get_chart2_indicators(specs)
    for expected in ["Bruttoavance", "EBIT", "NOPAT"]:
        assert any(expected in i for i in inds), f"P&L bridge missing: {expected}"


def test_chart2_has_fcf_bridge_rows():
    specs, _ = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                  REFORMULATED, WACC_DATA, DCF_SCENARIOS, SENSITIVITY, FAKE_FMP)
    inds = _get_chart2_indicators(specs)
    for expected in ["+ D&A", "− CapEx", "± ΔNWC", "= Cash FCF"]:
        assert any(expected in i for i in inds), f"FCF bridge missing: {expected}"


def test_chart2_has_capital_bridge_rows():
    specs, _ = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                  REFORMULATED, WACC_DATA, DCF_SCENARIOS, SENSITIVITY, FAKE_FMP)
    inds = _get_chart2_indicators(specs)
    for expected in ["Driftsaktiver", "Driftsforpligtelser", "= NOA",
                     "Bruttogæld", "Finansielle aktiver", "= NFO"]:
        assert any(expected in i for i in inds), f"Capital bridge missing: {expected}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest \
  tests/test_annual_report_kpi.py::test_chart2_has_pl_bridge_rows \
  tests/test_annual_report_kpi.py::test_chart2_has_fcf_bridge_rows \
  tests/test_annual_report_kpi.py::test_chart2_has_capital_bridge_rows -v
```

Expected: FAIL — indicator not found in current Chart 2 rows

- [ ] **Step 3: Implement — add `_sep` helper and new LTM scalars**

In `build_chart_specs`, immediately before the `snap_rows` assignment (around line 308), add:

**New LTM scalars** (after the existing `ltm_fcf`, `ltm_oi` etc. lines):

```python
ltm_gross_profit = float(ltm_inc.get("grossProfit") or 0) if has_ltm else None
ltm_ebit         = float(ltm_inc.get("operatingIncome") or 0) if has_ltm else None
ltm_dna          = float(ltm_cf.get("depreciationAndAmortization") or 0) if has_ltm else None
ltm_capex_raw    = float(ltm_cf.get("capitalExpenditure") or 0) if has_ltm else None
ltm_capex_abs    = abs(ltm_capex_raw) if ltm_capex_raw is not None else None
ltm_dnwc         = float(ltm_cf.get("changeInWorkingCapital") or 0) if has_ltm else None
```

**`_sep` helper** (add just before `snap_rows`):

```python
def _sep(label):
    row = {"indicator": f"━━ {label}"}
    for col in yr_cols:
        row[col] = ""
    return row
```

**CapEx display list** (CapEx is sign-negative in FMP; show magnitude with `−` label):

```python
capex_abs_hist = [abs(v) if v is not None else None
                  for v in reformulated.get("capex", [None] * len(years))]
```

- [ ] **Step 4: Replace `snap_rows` with the new four-section layout**

Find the existing `snap_rows = [...]` block (lines ~310–325) and replace it entirely with:

```python
snap_rows = [
    # ── P&L ──────────────────────────────────────────────────────────────────
    _sep("Resultatopgørelse"),
    _snap_row(f"Omsætning ({currency}m)",             reformulated["revenue"],      _num, ltm_rev),
    _snap_row(f"Bruttoavance ({currency}m)",          reformulated["gross_profit"], _num, ltm_gross_profit),
    _snap_row(f"EBIT ({currency}m)",                  reformulated["ebit"],         _num, ltm_ebit),
    _snap_row(f"NOPAT ({currency}m)",                 reformulated["OI"],           _num, ltm_oi),
    _snap_row("NOPAT-margin",                         reformulated["OG"],           _pct, ltm_og),

    # ── FCF bridge (fra NOPAT) ────────────────────────────────────────────────
    _sep("FCF (fra NOPAT)"),
    _snap_row(f"+ D&A ({currency}m)",                 reformulated["dna"],          _num, ltm_dna),
    _snap_row(f"− CapEx ({currency}m)",               capex_abs_hist,               _num, ltm_capex_abs),
    _snap_row(f"± ΔNWC ({currency}m)",                reformulated["dnwc"],         _num, ltm_dnwc),
    _snap_row(f"= Cash FCF ({currency}m)",            reformulated["cash_fcf"],     _num, ltm_fcf),

    # ── Kapitalstruktur ───────────────────────────────────────────────────────
    _sep("Kapitalstruktur"),
    _snap_row(f"Driftsaktiver ({currency}m)",         reformulated["op_assets"],    _num, ltm_op_assets),
    _snap_row(f"− Driftsforpligtelser ({currency}m)", reformulated["op_liabs"],     _num, ltm_op_liabs),
    _snap_row(f"= NOA ({currency}m)",                 reformulated["NOA"],          _num, ltm_noa),
    _snap_row(f"Bruttogæld ({currency}m)",            reformulated["gross_debt"],   _num, ltm_gross_debt),
    _snap_row(f"− Finansielle aktiver ({currency}m)", reformulated["fin_assets"],   _num, ltm_fin_assets),
    _snap_row(f"= NFO ({currency}m)",                 reformulated["NFO"],          _num, ltm_nfo),

    # ── Afkastnøgletal ────────────────────────────────────────────────────────
    _sep("Afkastnøgletal"),
    _snap_row("RNOA",                                 reformulated["RNOA"],         _pct, ltm_rnoa),
    _snap_row("Aktivomsætning (ATO)",                 reformulated["ATO"],          _x,   ltm_ato),
    _snap_row("SPREAD (RNOA − NBC)",                  reformulated["SPREAD"],       _pct, ltm_spread),
]
```

- [ ] **Step 5: Replace `snap_note` with the new structured version**

Find `snap_note = (...)` (around line 336) and replace:

```python
snap_note = (
    f"P&L: Bruttoavance = Omsætning − COGS. EBIT = driftsoeverskud før skat. "
    f"NOPAT = EBIT × (1−t = {_pct(t)} lovpligtig) — driftsoverskud efter skat, uafhæng af kapitalstruktur. "
    f"FCF: Cash FCF = NOPAT + D&A − CapEx ± ΔNWC (rapporterede pengestrømsopgørelsesværdier; "
    f"øvrige poster, fx udskudt skat og aktiebaseret vederlæggelse, indgår ikke i broen). "
    f"Kapital: NOA = Driftsaktiver − Driftsforpligtelser. "
    f"NFO = Bruttogæld − Finansielle aktiver; negativ = nettokasse. "
    f"Benchmarks: NOPAT-margin >10%, ATO >1×. SPREAD > 0 er værdiskabende finansiel gearing. "
    + (" ".join(_notes) if _notes else "")
)
```

Note: `_notes` is already built above this line (the existing dynamic flag/FCF-gap notes). Keep the entire `_notes` block above unchanged — only replace the final `snap_note` assignment.

- [ ] **Step 6: Run all KPI tests**

```bash
python -m pytest tests/test_annual_report_kpi.py -v
```

Expected: all PASS — including existing tests (8 specs still 8 specs; all type-D charts still have `table_data`; the title "Regnskabsoversigt" still matches the `_get_chart2_indicators` finder)

- [ ] **Step 7: Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git -C /Users/mertcandogusoy/newsletter-site add \
  newsletter_agent/specialists/annual_report_kpi.py \
  tests/test_annual_report_kpi.py
git -C /Users/mertcandogusoy/newsletter-site commit -m "feat: restructure Chart 2 into P&L / FCF / capital / returns sections with full component bridges"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task that implements it |
|---|---|
| Add grossProfit to LTM income | Task 1 |
| Add D&A, ΔNWC to LTM cashflow | Task 1 |
| Expose ebit, dna, capex, dnwc, op_assets, op_liabs, gross_debt, fin_assets, gross_profit in reformulated dict | Task 2 |
| Extend `_ltm_noa_nfo` return to 6-tuple | Task 3 |
| Update caller unpack | Task 3 |
| P&L bridge rows (Revenue, Gross Profit, EBIT, NOPAT, margin) | Task 4 |
| FCF bridge rows (D&A, CapEx, ΔNWC, Cash FCF) | Task 4 |
| NOA bridge rows (Op Assets, Op Liabs, NOA) | Task 4 |
| NFO bridge rows (Gross Debt, Fin Assets, NFO) | Task 4 |
| Update snap_note | Task 4 |
| No existing tests break | Verified in Task 3 Step 4 and Task 4 Step 6 |

No gaps found.

**CapEx sign note:** FMP stores `capitalExpenditure` as a negative number. `capex_abs_hist` takes `abs()` so the `− CapEx` row shows a positive magnitude. `ltm_capex_abs` does the same. ΔNWC uses FMP's sign directly (negative = cash outflow, positive = cash inflow), consistent with financial statement convention.

**`_notes` dependency:** The dynamic `_notes` list in Chart 2 is built above `snap_note` in the existing code. Task 4 Step 5 only replaces the `snap_note` string — do not touch the `_notes` building block above it.
