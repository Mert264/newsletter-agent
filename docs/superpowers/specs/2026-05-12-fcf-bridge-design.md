# Financial Snapshot — Full Component Transparency
**Date:** 2026-05-12  
**Status:** Approved  

---

## Problem

Chart 2 (Financial Snapshot) shows headline numbers — NOPAT, Cash FCF, NOA, NFO — but not the components behind them. An investor cannot tell:
- Whether margin comes from gross pricing power or lean OpEx
- Whether FCF reflects heavy CapEx, a D&A shield, or working capital dynamics
- Whether NOA is asset-heavy (PP&E/inventory) or working-capital-driven
- Whether NFO is low because the company is genuinely cash-rich or because short-term debt is offset by short-term cash

The components are as important as the headline number.

---

## Goal

Apply the same "bridge" principle to every leading factor in Chart 2:

```
P&L bridge:     Revenue → Gross Profit → EBIT → NOPAT
FCF bridge:     NOPAT + D&A − CapEx ± ΔNWC = Cash FCF
NOA bridge:     Operating Assets − Operating Liabilities = NOA
NFO bridge:     Gross Debt − Financial Assets = NFO
```

All shown as full time-series (all historical years + LTM where available).

Note: **WACC (Chart 4)** and **DCF detail (Charts 5–6)** are already fully decomposed — no change there.

---

## Approach

**Approach A — Reformulator extension.** The reformulator owns all per-year financial data; the KPI builder only formats it. This keeps financial parsing out of the display layer and makes all new fields reusable downstream.

Most of the required variables (`op_assets`, `op_liabs`, `fin_liabs`, `fin_assets`, `ebit`) are **already computed inside the reformulator loop** — they just aren't exposed in the returned dict. This makes the change almost purely additive.

---

## Files Changed

### 1. `newsletter_agent/specialists/annual_report_fmp.py`

**`_LTM_INCOME_FIELDS`** — add:
```python
"grossProfit",
```

**`_LTM_CASHFLOW_FIELDS`** — add:
```python
"depreciationAndAmortization",
"changeInWorkingCapital",
```

All three are standard FMP fields summed from the last 4 quarterly rows, identical to existing LTM logic. Without these, the LTM column would be blank for the new rows.

---

### 2. `newsletter_agent/specialists/annual_report_reformulator.py`

Inside the existing `for i in range(n)` loop, extract two new CF fields (alongside the existing `_ocf`/`_capex`):
```python
_dna  = _safe(cf.get("depreciationAndAmortization"))
_dnwc = _safe(cf.get("changeInWorkingCapital"))
```

All other required values are already computed in the loop:
- `ebit` = `_safe(inc.get("operatingIncome"))` — already computed as basis for `OI`
- `gross_profit` = `_safe(inc.get("grossProfit"))` — new income field to extract
- `op_assets` = `_safe(bal.get("totalAssets")) - fin_assets` — already computed for NOA
- `op_liabs` = `_safe(bal.get("totalLiabilities")) - fin_liabs` — already computed for NOA
- `fin_liabs` = short-term debt + long-term debt + leases — already computed for NFO
- `fin_assets` = excess cash + investments — already computed for NFO
- `_capex` = `_safe(cf.get("capitalExpenditure"))` — already computed for `cash_fcf`

**New lists to append per iteration** (append alongside existing ones):
- `gross_profit_l` — gross profit from income statement
- `ebit_l` — EBIT pre-tax (re-expose already-computed `ebit`)
- `dna_l` — D&A from cash flow statement
- `capex_l` — CapEx from cash flow statement (already used, re-expose)
- `dnwc_l` — ΔNWC from cash flow statement
- `op_assets_l` — gross operating assets (re-expose already-computed `op_assets`)
- `op_liabs_l` — gross operating liabilities (re-expose already-computed `op_liabs`)
- `gross_debt_l` — gross financial liabilities / debt (re-expose already-computed `fin_liabs`)
- `fin_assets_l` — financial assets / excess cash (re-expose already-computed `fin_assets`)

**New keys in the returned dict:**
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

**No change to existing keys.** Fully additive.

---

### 3. `newsletter_agent/specialists/annual_report_kpi.py`

#### Chart 2 — restructured into 4 sections

**Current layout (9 rows):**
```
Revenue / NOPAT / Cash FCF / NOA / NFO / RNOA / NOPAT-margin / ATO / SPREAD
```

**New layout (4 sections, ~22 rows including separators):**

```
━━ Resultatopgørelse (P&L)
  Revenue
  Gross Profit          [+ GM%]
  EBIT                  [pre-tax]
  NOPAT                 [= EBIT × (1−t), post-tax]
  NOPAT-margin

━━ FCF (fra NOPAT)
  + D&A
  − CapEx
  ± ΔNWC
  = Cash FCF

━━ Kapitalstruktur
  Operating Assets
  − Operating Liabilities
  = NOA
  Gross Debt
  − Financial Assets
  = NFO

━━ Afkastnøgletal
  RNOA
  ATO
  SPREAD (RNOA − NBC)
```

Separator rows follow the existing `{"indicator": "━━ Label", col: ""}` pattern used in Chart 1.
Bridge rows use the `_snap_row()` helper with new lists from `reformulated`.
NOPAT-margin moves into the P&L section (currently at the bottom) — same data, better position.

#### LTM values for new rows

**`_ltm_noa_nfo()` helper** — extend return to also yield `ltm_op_assets`, `ltm_op_liabs`, `ltm_gross_debt`, `ltm_fin_assets` (all computable from existing `ltm_bal` logic already in the helper):

```python
# Current return: (ltm_noa, ltm_nfo)
# New return:     (ltm_noa, ltm_nfo, ltm_op_assets, ltm_op_liabs, ltm_gross_debt, ltm_fin_assets)
```

**New LTM scalars** derived in `build_chart_specs`:
```python
ltm_gross_profit = float(ltm_inc.get("grossProfit") or 0)        # new LTM income field
ltm_ebit         = float(ltm_inc.get("operatingIncome") or 0)    # already available
ltm_dna          = float(ltm_cf.get("depreciationAndAmortization") or 0)  # new LTM CF field
ltm_capex        = float(ltm_cf.get("capitalExpenditure") or 0)  # already available
ltm_dnwc         = float(ltm_cf.get("changeInWorkingCapital") or 0)       # new LTM CF field
```

#### Note update

Replace current `snap_note` with a structured version covering all four sections:
```
P&L: Gross Profit = Revenue − COGS. NOPAT = EBIT × (1−t statutory).
FCF: Cash FCF = NOPAT + D&A − CapEx ± ΔNWC.
Capital: NOA = Operating Assets − Operating Liabilities. NFO = Gross Debt − Financial Assets; negative = net cash.
Returns: RNOA = NOPAT / avg NOA. Benchmarks: margin >10%, ATO >1×.
```

---

## Data availability

| Field | Source | Always present? |
|---|---|---|
| `grossProfit` | FMP income statement | Yes for US; `_safe` default 0 otherwise |
| `depreciationAndAmortization` | FMP cash flow statement | Yes for US; `_safe` default 0 |
| `changeInWorkingCapital` | FMP cash flow statement | Yes for US; `_safe` default 0 |
| `op_assets`, `op_liabs` | Already computed in reformulator | Yes — derived from `totalAssets`/`totalLiabilities` |
| `fin_liabs`, `fin_assets` | Already computed in reformulator | Yes — derived from debt/cash fields |
| `ebit` | Already computed in reformulator | Yes |

CapEx is sign-negative in FMP. The bridge label reads `− CapEx` and the displayed value is the magnitude.

---

## What is NOT changing

- Chart 1 (Executive Summary) — unchanged
- Charts 3–7 (Trend, WACC, DCF, Sensitivity, Multiples) — unchanged
- Reformulator computation logic (averages, flags, exclusions) — unchanged
- FMP fetch (API calls, rate limits, scaling) — only the two LTM field lists
- All existing `reformulated` dict keys — additive only
- All existing tests — additive changes cannot break existing assertions

---

## Success criteria

1. Chart 2 shows all four sections: P&L bridge, FCF bridge, NOA bridge, NFO bridge
2. All rows are full time-series (all historical years + LTM where available)
3. Bridge identities hold within rounding:
   - `Gross Profit + OpEx ≈ EBIT`  
   - `NOPAT + D&A − CapEx ± ΔNWC ≈ Cash FCF`  
   - `Operating Assets − Operating Liabilities ≈ NOA`  
   - `Gross Debt − Financial Assets ≈ NFO`
4. No existing tests break
5. `_ltm_noa_nfo` callers updated to unpack the extended return tuple
