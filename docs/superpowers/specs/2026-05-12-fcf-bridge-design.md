# FCF Bridge — Financial Snapshot Enhancement
**Date:** 2026-05-12  
**Status:** Approved  

---

## Problem

Chart 2 (Financial Snapshot) shows `Cash FCF` as a single number. An investor cannot see where it comes from — whether a company generates cash through operations but destroys it through heavy capex, or whether working capital is a drag. FCF can mean many things; the components behind it are the signal.

---

## Goal

Add a full FCF bridge to Chart 2 so investors see:
```
EBIT (pre-tax)   ← profitability of the business
+ D&A            ← non-cash add-back
− CapEx          ← reinvestment requirement
± ΔNWC           ← working capital movement
= Cash FCF       ← the result
```
Shown as a time-series across all historical years (+ LTM where available), consistent with every other row in the table.

---

## Approach

**Approach A — Reformulator extension.** The reformulator owns all per-year financial data. The KPI builder only formats it. FMP fetcher provides the raw fields.

---

## Files Changed

### 1. `newsletter_agent/specialists/annual_report_fmp.py`

Add to `_LTM_CASHFLOW_FIELDS`:
```python
"depreciationAndAmortization",
"changeInWorkingCapital",
```
These are summed from the last 4 quarterly CF rows, identical to how `operatingCashFlow` and `capitalExpenditure` are handled. Without this, the LTM column would be blank for D&A and ΔNWC.

### 2. `newsletter_agent/specialists/annual_report_reformulator.py`

Inside the existing `for i in range(n)` loop, after `_ocf`/`_capex` extraction, add:
```python
_dna  = _safe(cf.get("depreciationAndAmortization"))
_dnwc = _safe(cf.get("changeInWorkingCapital"))
```
`ebit` is already extracted as `ebit = _safe(inc.get("operatingIncome"))` — no new extraction needed.

Four new per-year lists appended inside the loop:
- `ebit_l`  — EBIT (pre-tax), from income statement `operatingIncome`
- `dna_l`   — D&A, from cash flow statement `depreciationAndAmortization`
- `capex_l` — CapEx, from cash flow statement `capitalExpenditure` (already computed, re-expose)
- `dnwc_l`  — ΔNWC, from cash flow statement `changeInWorkingCapital`

Four new keys added to the returned dict:
```python
"ebit":  ebit_l,
"dna":   dna_l,
"capex": capex_l,
"dnwc":  dnwc_l,
```

**No change to existing keys.** Fully additive — nothing downstream breaks.

### 3. `newsletter_agent/specialists/annual_report_kpi.py`

#### Row reordering in Chart 2

Current order:
```
Revenue / NOPAT / Cash FCF / NOA / NFO / RNOA / NOPAT-margin / ATO / SPREAD
```

New order:
```
Revenue
NOPAT
━━ FCF (separator label row)
  EBIT
  + D&A
  − CapEx
  ± ΔNWC
  = Cash FCF
━━ Balance sheet (separator)
  NOA
  NFO
━━ Afkastnøgletal (separator)
  RNOA
  NOPAT-margin
  ATO
  SPREAD (RNOA − NBC)
```

Separator rows use the existing `{"indicator": "━━ Label", "col1": "", ...}` pattern already in Chart 1.

Bridge rows use the `_snap_row()` helper with the new lists from `reformulated`. LTM values:
- `ltm_ebit = float(ltm_inc.get("operatingIncome") or 0)` (already available via `ltm_inc`)
- `ltm_dna  = float(ltm_cf.get("depreciationAndAmortization") or 0)` (new LTM field)
- `ltm_capex = float(ltm_cf.get("capitalExpenditure") or 0)` (already available)
- `ltm_dnwc  = float(ltm_cf.get("changeInWorkingCapital") or 0)` (new LTM field)

#### Note update

`snap_note` gains one sentence:
> `Cash FCF = EBIT + D&A − CapEx ± ΔNWC (reported cash flow statement values).`

---

## Data availability

FMP's annual cash flow statement always includes `depreciationAndAmortization` and `changeInWorkingCapital` for US equities. For non-US or unusual structures, `_safe(..., default=0.0)` ensures no crash — the cell renders as `0` rather than `—`, which is still informative.

CapEx is sign-negative in FMP (cash outflow). Existing `cash_fcf` logic already accounts for this. The bridge row `− CapEx` will display the magnitude (absolute value shown with a minus label), consistent with standard waterfall presentation.

---

## What is NOT changing

- Chart 1 (Executive Summary) — unchanged
- Charts 3–7 (Trend, WACC, DCF, Sensitivity, Multiples) — unchanged
- Reformulator logic (averages, flags, exclusions) — unchanged
- FMP fetch (API calls, rate limits, scaling) — only `_LTM_CASHFLOW_FIELDS` list
- All existing `reformulated` dict keys — additive only

---

## Success criteria

1. Chart 2 shows EBIT, D&A, CapEx, ΔNWC, and Cash FCF as time-series rows for all historical years
2. LTM column populated for D&A and ΔNWC where quarterly data exists
3. EBIT (pre-tax) and NOPAT (post-tax) are both visible, showing the tax impact
4. No existing tests break
5. Bridge rows sum correctly: `EBIT + D&A + CapEx + ΔNWC ≈ Cash FCF` (within rounding)
