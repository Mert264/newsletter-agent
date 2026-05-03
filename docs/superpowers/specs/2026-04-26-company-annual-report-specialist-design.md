# Company Annual Report Specialist — Design Spec
**Date:** 2026-04-26  
**Last updated:** 2026-05-03  
**Author:** Mert Can Doğusoy  
**Status:** Live — reflects current implementation

---

## 1. Purpose

A specialist for the newsletter agent pipeline that performs institutional-grade fundamental valuation of any publicly traded company. The specialist:

- Fetches up to 5 years of annual financial data + LTM (Last Twelve Months) via FMP
- Performs full Penman balance-sheet reformulation
- Computes WACC, Bear/Base/Bull DCF scenarios, and a sensitivity grid
- Surfaces 7 clean, investor-focused charts with all assumptions disclosed in figure notes

Works for any company on any exchange. All math is pure Python; LLM is used only for qualitative Devil's Advocate reviews.

---

## 2. Analytical Framework

### 2.1 Penman Reformulation

| Term | Formula | Notes |
|---|---|---|
| NOPAT | EBIT × (1 − t) | After-tax operating income. Label as **NOPAT**, not "Operating Income" |
| NOPAT Margin | NOPAT / Revenue | **Not** GAAP operating margin; labeled explicitly |
| FCF (Penman) | NOPAT − ΔNOA | Reinvestment-explicit free cash flow |
| Cash FCF | OCF − CapEx | Supplementary; from cash flow statement |
| NOA | Operating Assets − Operating Liabilities | See §3.2 for classification |
| NFO | Financial Liabilities − Financial Assets | See §3.2 for classification. Negative = net cash |
| RNOA | NOPAT / avg NOA | Decomposes as NOPAT Margin × ATO |
| ATO | Revenue / avg NOA | Asset turnover |
| NBC | After-tax interest expense / avg NFO | Net borrowing cost |
| SPREAD | RNOA − NBC | Positive = leverage creates value |
| FLEV | NFO / Common Equity | Financial leverage |
| ROCE | Comprehensive Net Income / avg Common Equity | Uses comprehensive income |

### 2.2 WACC

| Component | Formula / Source | Notes |
|---|---|---|
| rf | Country-matched government bond **spot yield** | Spot preferred over historical avg for forward-looking DCF |
| β_raw | FMP /profile | Raw market beta |
| β_adj | (2/3 × β_raw) + (1/3) | Blume (1975) mean-reversion adjustment; always applied |
| MRP | Damodaran US mature-market ERP ≈ 5.50% | **Flat across all countries.** Avoids double-counting with CRP |
| CRP | Damodaran country risk premium (by HQ country) | Added on top of MRP. Zero for USA, DNK, DEU, etc. |
| rE | rf + β_adj × (MRP + CRP) | CAPM with country risk |
| rs | Moody's rating → Damodaran spread table | ICR fallback if no rating available |
| rD | (rf + rs) × (1 − t) | After-tax cost of debt |
| D | max(NFO, 0) | Net debt used (Penman). Zero when company is net cash |
| E | Market cap from FMP /profile | |
| WACC | (D/V × rD) + (E/V × rE) | When D=0 (net cash), WACC = rE by design — not an error |

**Why MRP is flat (Damodaran standard) not MSCI World − rf:**  
Using MSCI_World_35yr_return − rf_local creates double-counting for non-US firms: the MSCI return already embeds country-specific equity returns, and then CRP is added again. Damodaran's recommended approach: use US mature-market ERP (~5.50%) for MRP everywhere and add CRP separately for non-mature markets.

**Why spot rf over historical:**  
The 35-year historical average embeds the 1990s high-rate environment. For a forward-looking DCF, the current market's opportunity cost of capital (spot) is more appropriate. Spot rates are stored per country in `RF_BY_COUNTRY["spot"]`.

### 2.3 DCF Scenarios

Three scenarios (Bear / Base / Bull) driven by:

| Parameter | Bear | Base | Bull |
|---|---|---|---|
| Revenue CAGR | max(base_cagr − 4%, −2%) | analyst consensus or hist. CAGR | min(base_cagr + 4%, 20%) |
| NOPAT Margin (Δ from avg) | −2% | 0% | +2% |
| WACC (Δ from base) | +1.0% | 0% | −1.0% |
| Terminal growth g | 1.5% | 2.0% | 2.5% |

Base CAGR source priority: analyst consensus → historical CAGR.

**DCF base revenue priority:**
1. LTM revenue (most current) if available and non-zero
2. Latest full FY revenue, unless that year was flagged as one-off
3. 3-year trailing average of non-flagged years if latest year was flagged

### 2.4 Historical Averages

Averages for NOPAT Margin and ATO exclude:
- Years with NOA ≤ 0 (RNOA/ATO undefined)
- Years where avg NOA ≤ 0 (transition year after negative-NOA year)
- Years where NOPAT changed >25% YoY (one-time item)
- Years where revenue jumped >20% with goodwill increase (M&A distortion)
- Years with anomalous NOA spike (>75% YoY NOA increase with ATO ratio drop <60%) 

The count of years actually averaged is surfaced in the label (e.g. "NOPAT Margin (4yr avg)").

Revenue CAGR is computed over the non-excluded years. Period shown explicitly (e.g. "FY2021–FY2025").

---

## 3. Data Layer

### 3.1 FMP Endpoints

All calls use the **FMP Stable API** (`/stable/` prefix).

| Endpoint | Data | Period/Limit |
|---|---|---|
| `income-statement` | Revenue, EBIT, interest expense, net income, comprehensive income, diluted shares | Annual, limit=10 |
| `balance-sheet-statement` | Total assets/liabilities, cash, investments, debt, lease obligations, equity, NCI | Annual, limit=10 |
| `cash-flow-statement` | OCF, CapEx, free cash flow | Annual, limit=10 |
| `income-statement` (quarterly) | Same as annual | Quarter, limit=5 |
| `cash-flow-statement` (quarterly) | OCF, CapEx, FCF | Quarter, limit=5 |
| `balance-sheet-statement` (quarterly) | Latest balance snapshot for LTM | Quarter, limit=2 |
| `profile` | Market cap, price, shares outstanding, HQ country, currency, beta | — |
| `ratings-snapshot` | Moody's / S&P / Fitch credit ratings | — |
| `key-metrics` | Pre-calculated ratios (P/E, EV/EBITDA, P/B, P/S, EV/FCF) | Annual |
| `analyst-estimates` | Consensus revenue/EPS forecasts | Annual |

All monetary fields scaled ÷ 1,000,000 → **USDm** (or local currency millions). Shares fields are NOT scaled (already in millions from FMP).

### 3.2 LTM Computation

LTM (Last Twelve Months) is computed by summing the 4 most recent quarterly rows for flow-statement fields (revenue, NOPAT, OCF, CapEx, interest expense). Balance sheet LTM uses the most recent quarterly snapshot.

LTM column label format: `LTM Mar'26` (abbreviated month + 2-digit year for narrow table columns).

LTM is displayed in the Financial Snapshot alongside annual data. LTM is used as the DCF base year when available (§2.3).

### 3.3 Balance Sheet Classification

```
excess_cash       = max(0, cashAndCashEquivalents − 2% × revenue)
Financial Assets  = excess_cash + shortTermInvestments + longTermInvestments
Financial Liabs   = shortTermDebt + longTermDebt + capitalLeaseObligations
Operating Assets  = totalAssets − Financial Assets
Operating Liabs   = totalLiabilities − Financial Liabs
NOA = Operating Assets − Operating Liabs
NFO = Financial Liabs − Financial Assets
```

**Operating cash floor (2% of revenue):** A fraction of cash is treated as operationally trapped (required for day-to-day operations). Only cash above this floor enters financial assets. Prevents understating NFO for cash-heavy companies.

**Capital lease obligations in financial liabilities:** Under IFRS 16 / ASC 842, lease liabilities are classified as financial (like debt) rather than operating. The corresponding ROU asset remains in operating assets. This treatment aligns with treating leases as debt-equivalent.

**Negative NFO = net cash.** When NFO < 0, the company holds more financial assets than financial obligations. In WACC: D = max(NFO, 0) = 0. WACC then equals rE entirely — this is correct, not an error.

NFO methodology is disclosed in every chart note.

### 3.4 Hardcoded Constants (updated annually)

| Constant | File | Notes |
|---|---|---|
| `RF_BY_COUNTRY` | `annual_report_constants.py` | spot + historical rate, bond name, maturity, per country |
| `US_MATURE_ERP = 0.055` | `annual_report_constants.py` | Damodaran mature-market ERP; flat MRP for all countries |
| `CRP_BY_COUNTRY` | `annual_report_constants.py` | Damodaran country risk premiums |
| `MOODY_TO_SPREAD` | `annual_report_constants.py` | Moody's rating → credit spread |
| `ICR_TO_SPREAD` | `annual_report_constants.py` | ICR brackets → credit spread (fallback) |
| `STATUTORY_TAX_RATE` | `annual_report_constants.py` | Normalized statutory rate per country |

Tax rate used = **statutory (normalized), not effective rate**. Disclosed explicitly in every WACC table.

---

## 4. Pipeline Architecture

```
User brief → Orchestrator → annual_report.py (lead specialist)
                                     │
                             fetch_all() — FMP
                        (annual + quarterly data)
                                     │
                          reformulate()
                    (NOA, NFO, NOPAT, FCF, ratios,
                     exclusion flags, n_avg_years)
                                     │
                           DA Review #1
                         (reformulation check)
                                     │
                           compute_wacc()
                    (rf spot, β_adj, MRP=US_ERP, CRP,
                     rE, Moody's/ICR → rs, rD, D/E/V)
                                     │
                           check() — 6 gates
                    (rf consistent, β_adj used,
                     diluted shares, statutory t, NCI)
                                     │
                      compute_dcf_scenarios()
                    (Bear/Base/Bull × 5yr forecast
                     + Gordon Growth TV; LTM base year)
                                     │
                        compute_sensitivity()
                     (WACC ± 1% × g 1–3% grid)
                                     │
                           DA Review #2
                         (valuation check, net-cash
                          aware capital structure)
                                     │
                        build_chart_specs()
                        (7 charts, all notes set)
                                     │
                           DA Review #3
                           (final gate check)
                                     │
                          → pipeline → renderer
```

**All heavy calculation is pure Python.** Claude is called only for three DA qualitative reviews (max 600 tokens each).

---

## 5. Module Specifications

### 5.1 `annual_report_fmp.py` — Data Fetcher

`fetch_all(ticker, api_key) → dict`

Returns: `income`, `balance`, `cashflow` (annual), `income_q`, `cashflow_q`, `balance_q` (quarterly), `ltm_income`, `ltm_cashflow`, `ltm_balance` (computed LTM), `profile`, `rating`, `metrics`, `estimates`.

All monetary fields scaled to millions. Shares fields unscaled. Profile normalised: `mktCap` in millions, `sharesOutstanding` from diluted shares.

Mapping fix: `evToFreeCashFlow` → stored as `evToFCF` (enterprise multiple, not P/FCF equity multiple).

---

### 5.2 `annual_report_reformulator.py` — Penman Reformulator

`reformulate(fmp_data, t, n_years_history=5) → dict`

- Slices to the most recent `n_years_history` annual years (default: 5)
- Computes NOA, NFO, NOPAT, FCF, RNOA, NOPAT Margin, ATO, FLEV, NBC, SPREAD, ROCE, cash FCF per year
- Applies exclusion logic (§2.4); builds `excluded_years` set
- Returns `historical_avgs` (NOPAT Margin avg, ATO avg, revenue CAGR) over non-excluded years only
- Returns `n_avg_years` (count of years actually averaged) for display labeling
- Returns `flags` list (human-readable) and `excluded_years` set

---

### 5.3 `annual_report_checker.py` — Consistency Checker

`check(wacc_inputs) → dict`

6 consistency gates. Returns `{"passed": bool, "issues": list}`. Issues are warned, not blocked (displayed in live log).

---

### 5.4 `annual_report_valuation.py` — WACC + DCF

`compute_wacc(fmp_data, reformulated, hq_country) → dict`

- rf = `RF_BY_COUNTRY[iso3]["spot"]`
- MRP = `US_MATURE_ERP` (flat)
- β_adj = (2/3 × β_raw) + 1/3
- rE = rf + β_adj × (MRP + CRP)
- rs: Moody's lookup → ICR fallback (ICR > 100 displayed as "Aaa equiv.")
- D = max(NFO, 0); WACC = D/V × rD + E/V × rE

`compute_dcf_scenarios(reformulated, wacc_base, NFO, NCI, diluted_shares, base_year, estimates, ltm_income) → dict`

- Base revenue priority: LTM → 3yr trailing avg (if latest year flagged) → latest FY
- Returns `{"bear": {...}, "base": {...}, "bull": {...}}` with price, detail, scenario params

`compute_sensitivity(reformulated, wacc_base, g_base, NFO, NCI, diluted_shares, base_year) → dict`

- WACC axis: base ± 1.0% in 0.25% steps (9 columns)
- g axis: 1.0% to 3.0% in 0.5% steps (5 rows)

---

### 5.5 `annual_report_da.py` — Devil's Advocate Reviews

Three DA reviews using Claude (REVIEWER_MODEL, max 600 tokens each).

| Review | Trigger | Key checks |
|---|---|---|
| DA #1 | After reformulation | NOA > 0, FCF vs cash FCF directional match, flagged years excluded, ATO plausible |
| DA #2 | After valuation | rf consistent, β_adj used, TV growth ≤ GDP, EV > 0, bear < base < bull ordering, net-cash WACC=rE is expected (not flagged) |
| DA #3 | After chart build | Bear < base < bull ordering, sensitivity grid midpoint consistency, all values plausible |

**Net-cash WACC awareness (DA #2):** When NFO < 0, D=0, so WACC = rE is mathematically correct. The DA prompt explicitly states this is expected for net-cash companies and must not be flagged as an error.

---

### 5.6 `annual_report_kpi.py` — Chart Builder

`build_chart_specs(ticker, company_name, hq_country, reformulated, wacc_data, dcf_scenarios, sensitivity, fmp_data) → (list[dict], dict[str, DataFrame])`

Produces 7 charts:

| # | Type | Title | Key content |
|---|---|---|---|
| 1 | D | Valuation Summary | Current price, fair value range (Bear/Base/Bull), WACC, terminal growth, NFO (net cash/debt), revenue, NOPAT margin (Xyr avg), CAGR with period, confidence, last updated |
| 2 | D | Financial Snapshot | FY columns + LTM column. Rows: Revenue, NOPAT, Cash FCF, NOA, NFO, RNOA, NOPAT Margin, ATO, SPREAD |
| 3 | A | Revenue & NOPAT | Line chart. Revenue CAGR labeled with exact period. NOPAT labeled as after-tax (not GAAP operating income) |
| 4 | D | WACC | rf (spot), β_raw, β_adj, MRP (Damodaran ERP), CRP, rE, rs (Moody's/ICR), t (statutory, not effective), rD, E/V, D/V (explains D=0 if net cash), WACC |
| 5 | D | DCF Scenarios | Bear/Base/Bull: CAGR, NOPAT Margin, WACC, g, EV, fair value/share, vs current price |
| 6 | D | Sensitivity | WACC × g grid, base case starred |
| 7 | D | Market Multiples | P/E, EV/EBITDA, P/B, P/S, EV/FCF (enterprise multiple, not P/FCF) |

**Labeling standards:**
- "NOPAT" not "Operating Income" (everywhere — snapshot, trend chart, scenarios)
- "NOPAT Margin (Xyr avg)" not "Operating Margin" — X reflects actual years averaged
- "NFO (Net Financial Obligations)" with methodology note in every snapshot
- "Revenue CAGR (FYxxxx–FYyyyy)" with explicit period
- Tax rate: "Statutory/normalized — not effective rate"
- Debt weight: "Net cash → D=0 (Penman net-debt treatment)" when D=0
- Last Updated: LTM date if available (more current), else annual filing date; annotated "(LTM)" or "(Annual)"
- EV displayed as "1.30T" not "1.3bn" for trillion-scale values

**Description duplication:** Notes are embedded inside each figure PNG via `_add_footer()`. The HTML frontend displays the figure only — no text description is repeated below the image.

---

### 5.7 `annual_report.py` — Lead Specialist

`fetch_annual_report(task) → dict`

Orchestrates the full pipeline. Returns `{"dataframes": ..., "chart_specs": ..., "kilde": ["FMP", "Damodaran"]}`.

Validates: ticker present, FMP key configured, NOA > 0 (raises if not).

---

## 6. Renderers

### `annual_report_kpi.py` → `newsletter_agent/renderers/tables.py`

Type D charts rendered by `render_type_d()`. Figure width scales with column count:
- ≤ 5 data columns: 7.0 inches (standard)
- 6 data columns (annual + LTM): 8.4 inches (scaled ×1.2)
- 7+ columns: scales proportionally at ×(n/5)

This prevents column header overflow for wide snapshot tables.

### Number formatting (`_num()`)

| Range (USDm) | Display | Example |
|---|---|---|
| ≥ 1,000,000 | XxxT | 1.30T (= $1.3 trillion) |
| < 1,000,000 | Plain with commas | 416,161 |

---

## 7. Devil's Advocate — Review Criteria Summary

| Review | Input | Passes when |
|---|---|---|
| DA #1 — Reformulation | reformulated dict | NOA > 0, ATO plausible, cash FCF directional match, flagged years excluded |
| DA #2 — Valuation | wacc_data, dcf_scenarios, market_price | rf consistent, β_adj used, TV ≤ GDP, EV > 0, bear < base < bull. WACC=rE accepted for net-cash |
| DA #3 — Final | chart_specs, price_range, market_price | Bear < base < bull ordering correct, sensitivity midpoint consistent |

DA issues are logged and displayed in the live pipeline output. They are informational (WARN) or advisory (BLOCK suggestion) — the pipeline always completes and renders charts.

---

## 8. Routing Integration

```python
# routing.py
_ANNUAL = re.compile(
    r"\b(annual report|årsrapport|årsregnskab|valuation|værdiansættelse|dcf|wacc|aktiekurs|fair value)\b",
    re.IGNORECASE
)
```

Routing hint injected: `"For selskabsanalyse: brug specialist='annual_report', source='fmp'. Type D/A."`

---

## 9. Error Handling

| Condition | Behaviour |
|---|---|
| Invalid ticker or FMP error | Raises ValueError immediately; pipeline surfaces to user |
| NOA ≤ 0 for latest year | Raises ValueError with explanation; likely data quality issue |
| Moody's rating unavailable | ICR fallback; labeled "ICR fallback (Aaa equiv.)" if ICR > 100 |
| Analyst consensus unavailable | Falls back to historical CAGR silently |
| LTM data incomplete / noisy | Falls back to latest full FY as DCF base |
| Latest year flagged as one-off | 3-year trailing average used as DCF base revenue |
| Net cash company (NFO < 0) | D=0, WACC=rE; labeled "Net cash → D=0"; DA informed to not flag |
| EV/share < 0 | Warning logged; charts still rendered; likely EV < NFO+NCI |

---

## 10. Out of Scope

- PDF parsing of annual report documents
- Real-time streaming prices (uses last close from FMP /profile)
- Options/derivatives valuation
- ESG scoring
- Multi-company comparison mode (charts 7–12 side-by-side) — planned, not built
- GAAP Operating Income separate from NOPAT in snapshot (pending user decision)
- Standard market net cash (gross cash − gross debt) alongside Penman NFO (pending user decision)
- Gross-debt WACC weighting alongside net-cash WACC (pending user decision)
- LTM periods included in historical averages (pending user decision)
