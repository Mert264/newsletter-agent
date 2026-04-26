# Company Annual Report Specialist — Design Spec
**Date:** 2026-04-26
**Author:** Mert Can Doğusoy
**Status:** Approved for implementation

---

## 1. Purpose

A new specialist for the newsletter agent pipeline that performs institutional-grade fundamental valuation of public companies. Supports two modes:

- **Single-company deep dive**: Full Penman reformulation + DCF + sensitivity + KPIs
- **Multi-company comparison**: Parallel valuation runs, normalized KPI comparison charts

Output surfaces directly in the newsletter as type A/B/D/F/G/P charts with full transparency labeling on every figure. All heavy calculations run in background subagents; the user receives clean, investment-ready results.

---

## 2. Analytical Framework

### 2.1 Terminology & Formulas (Penman-consistent)

| Term | Formula | Notes |
|---|---|---|
| WACC | (D/V × rD) + (E/V × rE) | Market-value weights |
| rE | rf + β_adj × (MRP + CRP) | CAPM with country risk |
| rD | (rf + rs) × (1 − t) | After-tax cost of debt |
| rf | Country-matched govt bond historical avg | 35yr avg, see §3.2 |
| β_raw | Cov(Ri,Rm) / Var(Rm) | From FMP /beta |
| β_adj | (2/3 × β_raw) + (1/3 × 1) | Blume (1975) — always use β_adj |
| MRP | MSCI World 35yr arithmetic avg − rf | Same rf as CAPM |
| CRP | Revenue-weighted Damodaran country risk premiums | Per company geography |
| rs | Moody's rating → Damodaran credit spread table | ICR used as cross-check only |
| t | Statutory corporate tax rate | Default 22% (DK); configurable |
| NOA | Operating Assets − Operating Liabilities | Penman reformulated BS |
| NFO | Financial Obligations − Financial Assets | Penman reformulated BS |
| OI (NOPAT) | EBIT × (1 − t) | Operating income after tax |
| FCF | OI − ΔNOA | Penman definition — NOT NOPAT+D&A−CapEx−ΔNWC |
| RNOA | OI / avg NOA | Decomposes as OG × ATO |
| OG | OI / Revenue | After-tax operating margin (for RNOA decomposition) |
| ATO | Revenue / avg NOA | Asset turnover |
| ROCE | Comprehensive Net Income / avg Common Equity | Uses comprehensive income, not net income |
| FLEV | NFO / Common Equity | Financial leverage |
| NBC | Net Financial Expense (after tax) / avg NFO | Net borrowing cost |
| SPREAD | RNOA − NBC | Positive = leverage creates value |
| TV | FCF_{n+1} / (WACC − g) | Gordon Growth; g default = 2% |
| EV | Σ PV(FCF) + PV(TV) | Sum of discounted FCFs + terminal |
| Equity Value | EV − NFO_latest − NCI | Subtract net debt AND minority interest |
| Price/share | Equity Value / diluted shares | Always diluted, not basic |

### 2.2 Transparency Labels

Every figure, table cell, and assumption carries one of:
- `CALC` — derived from audited FMP financials
- `EST` — model projection (forecast year)
- `ASSUMED` — hardcoded input (rf, t, g)
- `SOURCED` — external reference table (Damodaran, Moody's, FMP /rating)

Intelligent investors can immediately distinguish hard data from judgment calls.

---

## 3. Data Layer

### 3.1 FMP Endpoints

| Endpoint | Data extracted |
|---|---|
| `/income-statement/{ticker}?limit=10&period=annual` | Revenue, EBIT, D&A, interest expense, tax, net income, comprehensive income |
| `/balance-sheet-statement/{ticker}?limit=10&period=annual` | Total assets/liabilities, cash, investments, debt, lease liabilities, equity, NCI |
| `/cash-flow-statement/{ticker}?limit=10&period=annual` | CapEx, D&A (cross-check), WC changes |
| `/profile/{ticker}` | Market cap, diluted shares, current price, HQ country, sector |
| `/key-metrics/{ticker}?limit=10&period=annual` | Pre-calculated ratios for sanity checking |
| `/rating/{ticker}` | Moody's / S&P / Fitch credit ratings |
| `/analyst-estimates/{ticker}` | Sell-side consensus revenue + EPS for forecast years |
| `/beta` (via profile) | β_raw |

All calls use `limit=10` for 10 years of history.

### 3.2 Balance Sheet Classification Rules (Python, deterministic)

```
Financial Assets  = cash + shortTermInvestments + longTermInvestments
Financial Liabs   = shortTermDebt + longTermDebt + leaseLiabilities
Operating Assets  = totalAssets − Financial Assets
Operating Liabs   = totalLiabilities − Financial Liabs
NOA = Operating Assets − Operating Liabs
NFO = Financial Liabs − Financial Assets
```

Applied consistently across all 10 years. Classification is deterministic Python — no LLM step.

### 3.3 WACC Input Sources (Hardcoded, Updated Annually)

| Input | Source | Update cadence |
|---|---|---|
| rf by country | Damodaran country risk-free rates | Annual |
| MRP | Damodaran MSCI World 35yr arithmetic avg − rf | Annual |
| CRP by country | Damodaran country risk premiums | Annual |
| ICR → credit spread table | Damodaran default spreads | Annual |
| Moody's → credit spread | Damodaran rating spreads | Annual |

**rf country matching**: The risk-free rate is always from the company's HQ country government bond (Danish company → Danish 35yr avg, US company → US 30yr Treasury avg, German → German Bund, etc.). rf used in rD and rE is the same number — no mismatch allowed.

---

## 4. Pipeline Architecture

```
User brief → Orchestrator → annual_report.py (lead specialist)
                                      │
                    ┌─────────────────┼──────────────────┐
                    │                 │                  │
              FMP Fetcher      One-time Item        Consistency
              (raw data)         Detector             Checker
                    │                 │                  │
                    └─────────────────┴──────────────────┘
                                      │
                              [DA Review #1]
                              Reformulator subagent
                         (NOA, NFO, OI, FCF, ratios)
                                      │
                              [DA Review #2]
                           Consistency Checker subagent
                      (rf match, β_adj used, Moody's vs ICR)
                                      │
                              [DA Review #3]
                            Valuation subagent
                     (WACC, 5yr forecast, DCF, sensitivity)
                                      │
                              [DA Review #4]
                            KPI Packager subagent
                        (chart specs: A/B/D/F/G/P types)
                                      │
                              [DA Review #5]
                           Final figures → pipeline
```

**Multi-company mode**: Reformulator + Valuation + KPI Packager run in parallel per company. A final comparison KPI Packager aggregates cross-company charts.

---

## 5. Subagent Specifications

### 5.1 Reformulator Subagent

**Input**: 10yr raw FMP financials (IS, BS, CF statements)

**Computes**:
- NOA, NFO per year (fixed classification rules)
- OI = EBIT × (1 − t) per year
- FCF = OI − ΔNOA per year
- RNOA, OG, ATO, FLEV, NBC, SPREAD per year
- ROCE = Comprehensive Net Income / avg Common Equity per year

**One-time item detection**: Any year where a single line item moves OI by >25% is flagged and excluded from historical averages used in forecasting. Flagged years are disclosed in note fields.

**Returns**:
```json
{
  "reformulated": [{"year": 2020, "NOA": ..., "NFO": ..., "OI": ..., "FCF": ..., ...}],
  "historical_avgs": {"OG": ..., "ATO": ..., "revenue_cagr": ...},
  "flags": ["2023: Russian write-down excluded from OG/ATO avg"],
  "assumptions": ["t=22% statutory", "IFRS 16 leases classified as financial"]
}
```

**DA Review #1 checks**: NOA > 0, FCF trend directionally consistent with operating CF, OG avg excludes flagged years, ROCE uses comprehensive income.

---

### 5.2 Consistency Checker Subagent

**Input**: Reformulated data + proposed WACC inputs

**Checks**:
1. rf used in rD formula = rf used in CAPM (identical value, no mismatch)
2. Moody's rating-implied rs within 0.5% of ICR-implied rs (flags if diverges)
3. β_adj was applied (not β_raw)
4. Shares outstanding = FMP period-end diluted shares
5. t = statutory rate (not effective rate)
6. NCI subtracted from equity bridge

**Gate**: If any check fails, Valuation subagent does NOT run. DA surfaces the specific issue to the user with the fix required.

**DA Review #2**: Reviews the issues list itself for completeness.

---

### 5.3 Valuation Subagent

**Input**: Reformulated data (passed Consistency Check) + WACC inputs

#### WACC Block
1. rf: country-matched from hardcoded dict [ASSUMED]
2. β_raw: from FMP [SOURCED]; β_adj = 2/3 × β_raw + 1/3 [CALC]
3. MRP = Damodaran MSCI World 35yr avg − rf (same rf) [SOURCED]
4. CRP = revenue-weighted Damodaran country premiums [SOURCED]
5. rE = rf + β_adj × (MRP + CRP) [CALC]
6. Moody's rating → rs from Damodaran table [SOURCED]; ICR cross-check [CALC]
7. rD = (rf + rs) × (1 − t) [CALC]
8. D/V = NFO / (NFO + market cap); E/V = market cap / (NFO + market cap) [CALC]
9. WACC = D/V × rD + E/V × rE [CALC]

#### 5-Year Forecast Block (matching Image #2 structure exactly)

Columns: Year_1E … Year_5E + Terminal year

| Row | Method | Label |
|---|---|---|
| Nettoomsætning | Prior year × (1 + revenue growth rate) | EST |
| Driftsoverskud (OI) | Revenue × OG_avg | EST |
| NOA | Revenue / ATO_avg | EST |
| ΔNOA | NOA_t − NOA_{t−1} | EST |
| Discount factor | (1 + WACC)^t | CALC |
| FCF (OI − ΔNOA) | OI − ΔNOA | EST |
| Nutidsværdi af FCF | FCF / Discount factor | CALC |

Revenue growth: historical CAGR (one-time items excluded). If analyst consensus available, shown alongside as reference.

#### DCF Bridge Block (matching Image #3 structure)
- Total nutidsværdi = Σ PV(FCF) [CALC]
- Terminalværdi = FCF_{n+1} / (WACC − g) [CALC, g=ASSUMED]
- Nutidsværdi af terminalværdi = TV / (1+WACC)^n [CALC]
- Virksomhedsværdi (EV) = Total PV + PV(TV) [CALC]
- NFO (latest year) [CALC]
- NCI (non-controlling interests, latest year) [CALC]
- Egenkapitalværdi = EV − NFO − NCI [CALC]
- Antal udestående aktier (diluted) [SOURCED]
- **Pris per aktie = Egenkapitalværdi / diluted shares** [CALC]

#### Sensitivity Grid
- WACC axis: base ± 1.0% in 0.25% steps (9 columns)
- g axis: 1.0% to 3.0% in 0.5% steps (5 rows)
- Each cell: implied price per share [CALC]
- Base case cell highlighted

**Returns**: All blocks with full `assumptions` and `flags` audit trail.

**DA Review #3 checks**: rf consistent throughout, β_adj used, Moody's rs matches assumed rs, terminal growth ≤ long-run GDP of HQ country, EV > 0, price/share within 0.2×–5× of market price (outside range = warning, not block), RNOA > WACC in terminal year is verified or flagged.

---

### 5.4 KPI Packager Subagent

Converts all outputs to chart specs. All notes include transparency labels.

**Output chart set (single-company):**

| # | Type | Content |
|---|---|---|
| 1 | D | Forecast assumptions table (rf, β_raw, β_adj, MRP, CRP, rE, rs, rD, WACC, OG, ATO, g, t — each row tagged CALC/EST/ASSUMED/SOURCED) |
| 2 | D | Avg. bond yield table (country, period, yield, rf used) |
| 3 | D | Moody's rating + rs table (rating, implied spread, ICR cross-check) |
| 4 | D | WACC component breakdown |
| 5 | D | Penman reformulated balance sheet summary (NOA, NFO, equity per year) |
| 6 | D | Key Penman ratios snapshot (RNOA, OG, ATO, FLEV, NBC, SPREAD — latest year) |
| 7 | A | Revenue trend (10yr historical + 5yr EST, consensus overlay if available) |
| 8 | A | Operating income trend (OI/NOPAT, 10yr + 5yr EST) |
| 9 | A | FCF trend (10yr historical + 5yr EST) |
| 10 | A | RNOA, ROCE, SPREAD over time (10yr) |
| 11 | A | RNOA vs. WACC spread (value creation signal, 10yr + forecast) |
| 12 | A | FLEV and net debt trend |
| 13 | D | DCF forecast table (Image #2 format: Revenue, OI, NOA, ΔNOA, Discount factor, FCF, PV of FCF — 5yr + Terminal) |
| 14 | D | DCF bridge summary (Image #3 format: Total PV + PV(TV) = EV − NFO − NCI = Equity ÷ shares = price/share) |
| 15 | D | Sensitivity grid (WACC × g → price/share, base case highlighted) |
| 16 | B | Fundamental price vs. market price (over/undervalued signal, % margin) |
| 17 | D | Multiples table (P/E, EV/EBITDA, P/B, P/S, P/FCF — trailing + forward if consensus available) |
| 18 | G | Regional revenue breakdown (if FMP segment data available) |

**Multi-company additions**: charts 7–12 and 16–17 rendered side-by-side per company for comparison.

**DA Review #5 checks**: all 18 charts have title, note, kilde; all EST/ASSUMED values labeled; price signal consistent with sensitivity grid midpoint; RNOA vs. WACC direction consistent with over/undervalued conclusion.

---

## 6. Devil's Advocate — Review Criteria Summary

| Review point | What is checked | Block or warn |
|---|---|---|
| #1 — Reformulator | NOA > 0, FCF vs. operating CF directional match, flagged years excluded | Block if NOA < 0 |
| #2 — Consistency | rf match, β_adj used, Moody's vs ICR within 0.5%, diluted shares, statutory t, NCI present | Block on any failure |
| #3 — Valuation | rf throughout, β_adj, rs match, TV growth ≤ country GDP, EV > 0, price sanity | Warn if price >5× or <0.2× market |
| #4 — KPI Packager | All 18 charts spec-complete, labels present | Block if any chart missing note or kilde |
| #5 — Final | EST/ASSUMED labeled everywhere, price vs. sensitivity consistency | Warn on inconsistency |

---

## 7. Routing Integration

New keyword rule added to `routing.py`:

```python
_ANNUAL = re.compile(r"\b(annual report|årsrapport|årsregnskab|valuation|værdiansættelse|dcf|wacc|aktiekurs|fair value)\b", re.IGNORECASE)
_COMPANY = re.compile(r"\b(carlsberg|novo|maersk|apple|microsoft|[A-Z]{2,5})\b")  # extend as needed
```

Routing hint: `"For selskabsanalyse: brug specialist='annual_report', source='fmp'. Type D/A/B/G."`

---

## 8. Error Handling

- FMP rate limit or missing ticker: surface error immediately, do not proceed with partial data
- Moody's rating unavailable: fall back to ICR-implied rs, label as `SOURCED (ICR fallback)`, flag in DA
- Analyst consensus unavailable: skip consensus overlay silently, note absence in chart note
- NCI not in FMP balance sheet: treat as 0, flag in DA review
- Segment data unavailable: skip chart #18, no error
- price/share outside 0.2×–5× market: DA issues warning in note field, does not block

---

## 9. Out of Scope

- PDF parsing of annual report documents
- Real-time streaming prices (valuation uses last close from FMP /profile)
- Options pricing or derivatives valuation
- ESG scoring
- Web scraping as fallback
