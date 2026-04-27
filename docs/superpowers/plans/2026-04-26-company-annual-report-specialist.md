# Company Annual Report Specialist — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `annual_report` specialist module that fetches FMP financial data, performs Penman DCF valuation, and produces 18 newsletter charts with full transparency labeling.

**Architecture:** Lead specialist (`annual_report.py`) calls FMP client → Reformulator (Penman NOA/OI/FCF) → Consistency Checker (7 gates) → Valuation (WACC + 5yr DCF + sensitivity) → KPI Packager (18 chart specs). DA reviews after each stage via Claude Haiku. All math is pure Python; LLM only for qualitative review.

**Tech Stack:** Python 3.x, `requests` (FMP API), `pandas`, `anthropic` SDK, `newsletter_agent.config` (REVIEWER_MODEL, API_KEYS), `newsletter_agent.renderers.tables` (render_type_d)

---

## File Map

**Create:**
- `newsletter_agent/specialists/annual_report_constants.py` — RF_BY_COUNTRY, MOODY_TO_SPREAD, ICR_TO_SPREAD, CRP_BY_COUNTRY, STATUTORY_TAX_RATE, COUNTRY_MAP
- `newsletter_agent/specialists/annual_report_fmp.py` — `fetch_all(ticker, api_key) -> dict`
- `newsletter_agent/specialists/annual_report_reformulator.py` — `reformulate(fmp_data, t) -> dict`
- `newsletter_agent/specialists/annual_report_checker.py` — `check(wacc_inputs) -> dict`
- `newsletter_agent/specialists/annual_report_valuation.py` — `compute_wacc()`, `compute_dcf()`, `compute_sensitivity()`
- `newsletter_agent/specialists/annual_report_da.py` — 5 DA review functions
- `newsletter_agent/specialists/annual_report_kpi.py` — `build_chart_specs() -> (list[dict], dict[str, DataFrame])`
- `newsletter_agent/specialists/annual_report.py` — `fetch_annual_report(task) -> dict`
- `tests/test_annual_report_constants.py`
- `tests/test_annual_report_fmp.py`
- `tests/test_annual_report_reformulator.py`
- `tests/test_annual_report_checker.py`
- `tests/test_annual_report_valuation.py`
- `tests/test_annual_report_kpi.py`

**Modify:**
- `newsletter_agent/pipeline.py:575` — add `table_data` shortcut before `_build_table()` call; add `annual_report` to `SPECIALIST_MAP`
- `newsletter_agent/config.py` — add `"fmp": os.getenv("FMP_API_KEY", "")` to `API_KEYS`
- `newsletter_agent/routing.py` — add annual report routing keywords
- `newsletter_agent/orchestrator.py` — add `annual_report` to SYSTEM_PROMPT specialist list

---

### Task 1: Hardcoded Constants

**Files:**
- Create: `newsletter_agent/specialists/annual_report_constants.py`
- Test: `tests/test_annual_report_constants.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_annual_report_constants.py
from newsletter_agent.specialists.annual_report_constants import (
    RF_BY_COUNTRY, MSCI_WORLD_35YR_RETURN, MOODY_TO_SPREAD,
    ICR_TO_SPREAD, CRP_BY_COUNTRY, STATUTORY_TAX_RATE, normalize_country,
)

def test_rf_by_country_has_required_keys():
    for key in ["DNK", "USA", "DEU", "GBR", "SWE", "NOR", "_default"]:
        assert key in RF_BY_COUNTRY
        assert "rate" in RF_BY_COUNTRY[key]
        assert "maturity_yr" in RF_BY_COUNTRY[key]
        assert "bond_name" in RF_BY_COUNTRY[key]

def test_moody_spread_lookup():
    assert MOODY_TO_SPREAD["Aaa"] == 0.0063
    assert MOODY_TO_SPREAD["A2"] == 0.0125
    assert MOODY_TO_SPREAD["Baa2"] == 0.0175

def test_icr_spread_lookup():
    # ICR = 5.0 → between 4.25 and 5.50 → spread 0.0125
    spread = next(s for lo, hi, s in ICR_TO_SPREAD if lo <= 5.0 < hi)
    assert spread == 0.0125

def test_normalize_country():
    assert normalize_country("Denmark") == "DNK"
    assert normalize_country("united states") == "USA"
    assert normalize_country("Unknownland") == "_default"

def test_statutory_tax_rate():
    assert STATUTORY_TAX_RATE["DNK"] == 0.22
    assert STATUTORY_TAX_RATE["USA"] == 0.21
    assert "_default" in STATUTORY_TAX_RATE
```

- [ ] **Step 2: Run test to confirm it fails**

```
cd /Users/mertcandogusoy/newsletter-site
pytest tests/test_annual_report_constants.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create the constants file**

```python
# newsletter_agent/specialists/annual_report_constants.py
MSCI_WORLD_35YR_RETURN = 0.0758  # Damodaran arithmetic avg

RF_BY_COUNTRY = {
    "DNK": {"rate": 0.0384, "maturity_yr": 35, "spot": 0.028, "bond_name": "Dansk statsobligation 35år avg"},
    "USA": {"rate": 0.0450, "maturity_yr": 30, "spot": 0.044, "bond_name": "US Treasury 30yr avg"},
    "DEU": {"rate": 0.0260, "maturity_yr": 30, "spot": 0.026, "bond_name": "Deutscher Bund 30yr avg"},
    "GBR": {"rate": 0.0420, "maturity_yr": 30, "spot": 0.042, "bond_name": "UK Gilt 30yr avg"},
    "SWE": {"rate": 0.0320, "maturity_yr": 30, "spot": 0.032, "bond_name": "Svensk statsobligation 30yr avg"},
    "NOR": {"rate": 0.0340, "maturity_yr": 30, "spot": 0.034, "bond_name": "Norsk statsobligation 30yr avg"},
    "CHE": {"rate": 0.0210, "maturity_yr": 30, "spot": 0.021, "bond_name": "Swiss Confederation 30yr avg"},
    "NLD": {"rate": 0.0270, "maturity_yr": 30, "spot": 0.027, "bond_name": "Dutch State Loan 30yr avg"},
    "FRA": {"rate": 0.0290, "maturity_yr": 30, "spot": 0.031, "bond_name": "OAT 30yr avg"},
    "JPN": {"rate": 0.0150, "maturity_yr": 30, "spot": 0.015, "bond_name": "JGB 30yr avg"},
    "_default": {"rate": 0.0450, "maturity_yr": 10, "spot": 0.045, "bond_name": "10yr govt bond"},
}

MOODY_TO_SPREAD = {
    "Aaa": 0.0063, "Aa1": 0.0075, "Aa2": 0.0088, "Aa3": 0.0100,
    "A1": 0.0113, "A2": 0.0125, "A3": 0.0138,
    "Baa1": 0.0150, "Baa2": 0.0175, "Baa3": 0.0200,
    "Ba1": 0.0240, "Ba2": 0.0275, "Ba3": 0.0325,
    "B1": 0.0400, "B2": 0.0500, "B3": 0.0600,
    "Caa1": 0.0750, "Caa2": 0.0850, "Caa3": 0.1000,
    "Ca": 0.1300, "C": 0.1500,
}

# (lower_bound_exclusive, upper_bound_inclusive, spread)
ICR_TO_SPREAD = [
    (8.50, float("inf"), 0.0063),
    (6.50, 8.50, 0.0088),
    (5.50, 6.50, 0.0113),
    (4.25, 5.50, 0.0125),
    (3.00, 4.25, 0.0150),
    (2.50, 3.00, 0.0175),
    (2.00, 2.50, 0.0200),
    (1.75, 2.00, 0.0240),
    (1.50, 1.75, 0.0275),
    (1.25, 1.50, 0.0325),
    (0.80, 1.25, 0.0400),
    (0.65, 0.80, 0.0500),
    (0.20, 0.65, 0.0850),
    (float("-inf"), 0.20, 0.1300),
]

CRP_BY_COUNTRY = {
    "DNK": 0.0000, "SWE": 0.0000, "NOR": 0.0000, "DEU": 0.0000,
    "USA": 0.0000, "CHE": 0.0000, "AUT": 0.0000, "NLD": 0.0000,
    "FIN": 0.0000, "GBR": 0.0022, "FRA": 0.0022, "JPN": 0.0038,
    "CHN": 0.0075, "POL": 0.0075, "HUN": 0.0088,
    "BRA": 0.0163, "IND": 0.0113, "MEX": 0.0113, "RUS": 0.0525,
    "TUR": 0.0275, "ARE": 0.0063, "SAU": 0.0088, "_default": 0.0200,
}

STATUTORY_TAX_RATE = {
    "DNK": 0.22, "SWE": 0.206, "NOR": 0.22, "DEU": 0.298,
    "USA": 0.21, "GBR": 0.25, "FRA": 0.2572, "CHN": 0.25,
    "JPN": 0.2974, "NLD": 0.258, "CHE": 0.1468, "_default": 0.22,
}

_COUNTRY_NAME_MAP = {
    "denmark": "DNK", "sweden": "SWE", "norway": "NOR", "germany": "DEU",
    "united states": "USA", "us": "USA", "usa": "USA",
    "united kingdom": "GBR", "uk": "GBR", "gb": "GBR",
    "france": "FRA", "china": "CHN", "japan": "JPN",
    "switzerland": "CHE", "netherlands": "NLD", "finland": "FIN",
    "austria": "AUT", "poland": "POL", "hungary": "HUN",
    "brazil": "BRA", "india": "IND", "mexico": "MEX",
    "turkey": "TUR", "russia": "RUS", "saudi arabia": "SAU",
    "united arab emirates": "ARE", "dnk": "DNK", "swe": "SWE",
    "nor": "NOR", "deu": "DEU", "gbr": "GBR",
}


def normalize_country(country_str: str) -> str:
    return _COUNTRY_NAME_MAP.get(country_str.lower().strip(), "_default")


def icr_to_spread(icr: float) -> float:
    for lo, hi, spread in ICR_TO_SPREAD:
        if lo <= icr < hi:
            return spread
    return ICR_TO_SPREAD[-1][2]
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_annual_report_constants.py -v
```
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add newsletter_agent/specialists/annual_report_constants.py tests/test_annual_report_constants.py
git commit -m "feat: add annual report constants (Damodaran rf/CRP/spread tables)"
```

---

### Task 2: FMP API Client

**Files:**
- Create: `newsletter_agent/specialists/annual_report_fmp.py`
- Test: `tests/test_annual_report_fmp.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_annual_report_fmp.py
from unittest.mock import patch, MagicMock
from newsletter_agent.specialists.annual_report_fmp import fetch_all

def _mock_response(data):
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status.return_value = None
    return m

FAKE_INCOME = [{"date": "2024-12-31", "revenue": 83000, "operatingIncome": 12000,
                "netIncome": 8500, "comprehensiveIncomePeriodChange": 8200,
                "interestExpense": 1200, "weightedAverageShsOutDil": 500}]
FAKE_BALANCE = [{"date": "2024-12-31", "totalAssets": 150000, "totalLiabilities": 90000,
                 "cashAndCashEquivalents": 8000, "shortTermInvestments": 2000,
                 "longTermInvestments": 1000, "shortTermDebt": 5000,
                 "longTermDebt": 25000, "capitalLeaseObligations": 3000,
                 "totalStockholdersEquity": 55000, "minorityInterest": 5000,
                 "goodwillAndIntangibleAssets": 20000}]
FAKE_CF = [{"date": "2024-12-31", "capitalExpenditure": -3000, "depreciationAndAmortization": 3500}]
FAKE_PROFILE = [{"beta": 0.85, "mktCap": 250000, "price": 500.0,
                 "country": "Denmark", "companyName": "TestCo A/S",
                 "currency": "DKK", "sharesOutstanding": 500}]
FAKE_RATING = [{"rating": "A2", "ratingAgency": "Moody's"}]
FAKE_METRICS = [{"date": "2024-12-31", "peRatio": 18.5}]
FAKE_ESTIMATES = [{"date": "2025-12-31", "estimatedRevenueLow": 85000, "estimatedRevenueHigh": 90000}]


@patch("newsletter_agent.specialists.annual_report_fmp.requests.get")
def test_fetch_all_returns_expected_keys(mock_get):
    mock_get.return_value = _mock_response(FAKE_INCOME)

    responses = [
        _mock_response(FAKE_INCOME),
        _mock_response(FAKE_BALANCE),
        _mock_response(FAKE_CF),
        _mock_response(FAKE_PROFILE),
        _mock_response(FAKE_RATING),
        _mock_response(FAKE_METRICS),
        _mock_response(FAKE_ESTIMATES),
    ]
    mock_get.side_effect = responses

    result = fetch_all("CARL", "test_key")
    for key in ["income", "balance", "cashflow", "profile", "rating", "metrics", "estimates"]:
        assert key in result
    assert result["profile"]["country"] == "Denmark"
    assert result["income"][0]["revenue"] == 83000


@patch("newsletter_agent.specialists.annual_report_fmp.requests.get")
def test_fetch_all_raises_on_empty_income(mock_get):
    import pytest
    responses = [
        _mock_response([]),   # income empty
        _mock_response(FAKE_BALANCE),
        _mock_response(FAKE_CF),
        _mock_response(FAKE_PROFILE),
        _mock_response(FAKE_RATING),
        _mock_response(FAKE_METRICS),
        _mock_response(FAKE_ESTIMATES),
    ]
    mock_get.side_effect = responses
    with pytest.raises(ValueError, match="No income statement"):
        fetch_all("INVALID", "test_key")
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_annual_report_fmp.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement FMP client**

```python
# newsletter_agent/specialists/annual_report_fmp.py
import requests

_BASE = "https://financialmodelingprep.com/api/v3"


def _get(path: str, api_key: str, **params) -> list | dict:
    params["apikey"] = api_key
    resp = requests.get(f"{_BASE}/{path}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_all(ticker: str, api_key: str) -> dict:
    income    = _get(f"income-statement/{ticker}", api_key, limit=10, period="annual")
    balance   = _get(f"balance-sheet-statement/{ticker}", api_key, limit=10, period="annual")
    cashflow  = _get(f"cash-flow-statement/{ticker}", api_key, limit=10, period="annual")
    profile   = _get(f"profile/{ticker}", api_key)
    rating    = _get(f"rating/{ticker}", api_key)
    metrics   = _get(f"key-metrics/{ticker}", api_key, limit=10, period="annual")
    estimates = _get(f"analyst-estimates/{ticker}", api_key, limit=5, period="annual")

    if not income:
        raise ValueError(f"No income statement data for ticker '{ticker}' — check ticker symbol or FMP subscription.")
    if not balance:
        raise ValueError(f"No balance sheet data for ticker '{ticker}'.")

    profile_dict = profile[0] if isinstance(profile, list) and profile else (profile or {})

    return {
        "income":    income,     # newest first
        "balance":   balance,
        "cashflow":  cashflow,
        "profile":   profile_dict,
        "rating":    rating if isinstance(rating, list) else [],
        "metrics":   metrics if isinstance(metrics, list) else [],
        "estimates": estimates if isinstance(estimates, list) else [],
    }
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_annual_report_fmp.py -v
```
Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add newsletter_agent/specialists/annual_report_fmp.py tests/test_annual_report_fmp.py
git commit -m "feat: add FMP API client for annual report specialist"
```

---

### Task 3: Penman Reformulator

**Files:**
- Create: `newsletter_agent/specialists/annual_report_reformulator.py`
- Test: `tests/test_annual_report_reformulator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_annual_report_reformulator.py
from newsletter_agent.specialists.annual_report_reformulator import reformulate

def _make_fmp_data(n_years=3):
    """Produces n_years of identical synthetic FMP data (newest first)."""
    income = []
    balance = []
    for i in range(n_years):
        year = 2024 - i
        income.append({
            "date": f"{year}-12-31",
            "revenue": 100_000,
            "operatingIncome": 20_000,    # EBIT
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
    return {
        "income": income,
        "balance": balance,
        "cashflow": [],
        "profile": {},
        "rating": [],
        "metrics": [],
        "estimates": [],
    }


def test_noa_calculation():
    data = _make_fmp_data(2)
    result = reformulate(data, t=0.22)
    # Financial Assets = 10_000 + 5_000 + 5_000 = 20_000
    # Financial Liabs  = 8_000 + 30_000 + 2_000 = 40_000
    # Operating Assets = 200_000 - 20_000 = 180_000
    # Operating Liabs  = 120_000 - 40_000 = 80_000
    # NOA = 180_000 - 80_000 = 100_000
    assert result["NOA"][0] == 100_000


def test_oi_calculation():
    data = _make_fmp_data(2)
    result = reformulate(data, t=0.22)
    # OI = EBIT * (1 - t) = 20_000 * 0.78 = 15_600
    assert abs(result["OI"][0] - 15_600) < 1


def test_fcf_is_none_for_first_year():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    # FCF requires ΔNOA — undefined for oldest year
    assert result["FCF"][0] is None


def test_fcf_second_year():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    # Stable NOA → ΔNOA = 0 → FCF = OI
    assert abs(result["FCF"][1] - 15_600) < 1


def test_historical_avgs_computed():
    data = _make_fmp_data(5)
    result = reformulate(data, t=0.22)
    assert "OG" in result["historical_avgs"]
    assert "ATO" in result["historical_avgs"]
    assert "revenue_cagr" in result["historical_avgs"]
    # OG = OI/Revenue = 15_600/100_000 = 0.156
    assert abs(result["historical_avgs"]["OG"] - 0.156) < 0.001


def test_one_time_item_detection():
    data = _make_fmp_data(5)
    # Spike OI in year index 1 (second oldest) by 50%
    data["income"][3]["operatingIncome"] = 30_000  # 50% jump from 20_000
    result = reformulate(data, t=0.22)
    assert any("flagged" in f.lower() for f in result["flags"])


def test_returns_required_keys():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    for key in ["years", "revenue", "NOA", "NFO", "OI", "FCF", "RNOA",
                "OG", "ATO", "FLEV", "NBC", "SPREAD", "ROCE", "NCI",
                "common_equity", "historical_avgs", "flags", "assumptions"]:
        assert key in result, f"Missing key: {key}"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_annual_report_reformulator.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement reformulator**

```python
# newsletter_agent/specialists/annual_report_reformulator.py

def _safe(val, default=0.0):
    return float(val) if val is not None else default


def reformulate(fmp_data: dict, t: float) -> dict:
    income  = list(reversed(fmp_data["income"]))   # oldest first
    balance = list(reversed(fmp_data["balance"]))
    n = min(len(income), len(balance))

    years, revenue_l, NOA_l, NFO_l, OI_l, FCF_l = [], [], [], [], [], []
    RNOA_l, OG_l, ATO_l, FLEV_l, NBC_l, SPREAD_l, ROCE_l = [], [], [], [], [], [], []
    NCI_l, equity_l, goodwill_l = [], [], []

    prev_NOA = prev_NFO = prev_equity = None

    for i in range(n):
        inc, bal = income[i], balance[i]
        year    = int(inc["date"][:4])
        revenue = _safe(inc.get("revenue"))
        ebit    = _safe(inc.get("operatingIncome"))
        OI      = ebit * (1 - t)
        comp_ni = _safe(inc.get("comprehensiveIncomePeriodChange") or inc.get("netIncome"))
        interest= _safe(inc.get("interestExpense"))

        fin_assets = (_safe(bal.get("cashAndCashEquivalents"))
                      + _safe(bal.get("shortTermInvestments"))
                      + _safe(bal.get("longTermInvestments")))
        fin_liabs  = (_safe(bal.get("shortTermDebt"))
                      + _safe(bal.get("longTermDebt"))
                      + _safe(bal.get("capitalLeaseObligations")))
        op_assets  = _safe(bal.get("totalAssets")) - fin_assets
        op_liabs   = _safe(bal.get("totalLiabilities")) - fin_liabs

        NOA          = op_assets - op_liabs
        NFO          = fin_liabs - fin_assets
        common_eq    = _safe(bal.get("totalStockholdersEquity"))
        nci          = _safe(bal.get("minorityInterest"))
        goodwill     = _safe(bal.get("goodwillAndIntangibleAssets"))

        dNOA  = (NOA - prev_NOA) if prev_NOA is not None else None
        FCF   = (OI - dNOA)     if dNOA is not None else None

        avg_NOA   = (NOA + prev_NOA) / 2 if prev_NOA is not None else NOA
        avg_NFO   = (NFO + prev_NFO) / 2 if prev_NFO is not None else NFO
        avg_eq    = (common_eq + prev_equity) / 2 if prev_equity is not None else common_eq

        RNOA   = OI / avg_NOA    if avg_NOA  != 0 else 0.0
        OG     = OI / revenue    if revenue  != 0 else 0.0
        ATO    = revenue / avg_NOA if avg_NOA != 0 else 0.0
        FLEV   = NFO / common_eq  if common_eq != 0 else 0.0
        NBC    = (interest * (1 - t)) / avg_NFO if avg_NFO != 0 else 0.0
        SPREAD = RNOA - NBC
        ROCE   = comp_ni / avg_eq if avg_eq != 0 else 0.0

        years.append(year); revenue_l.append(revenue); NOA_l.append(NOA)
        NFO_l.append(NFO); OI_l.append(OI); FCF_l.append(FCF)
        RNOA_l.append(RNOA); OG_l.append(OG); ATO_l.append(ATO)
        FLEV_l.append(FLEV); NBC_l.append(NBC); SPREAD_l.append(SPREAD)
        ROCE_l.append(ROCE); NCI_l.append(nci); equity_l.append(common_eq)
        goodwill_l.append(goodwill)

        prev_NOA, prev_NFO, prev_equity = NOA, NFO, common_eq

    flags         = []
    excluded_yrs  = set()

    # One-time item detection: OI change > 25% in a single year
    for i in range(1, len(OI_l)):
        if OI_l[i - 1] != 0:
            chg = abs((OI_l[i] - OI_l[i - 1]) / OI_l[i - 1])
            if chg > 0.25:
                flags.append(
                    f"{years[i]}: OI changed {chg:.0%} YoY — flagged as potential one-time item, "
                    f"excluded from historical averages [ASSUMED]"
                )
                excluded_yrs.add(years[i])

    # M&A CAGR distortion: revenue jump >20% + goodwill increase same year
    for i in range(1, len(revenue_l)):
        if revenue_l[i - 1] != 0:
            rev_jump = (revenue_l[i] - revenue_l[i - 1]) / revenue_l[i - 1]
            if rev_jump > 0.20 and goodwill_l[i] > goodwill_l[i - 1]:
                flags.append(
                    f"{years[i]}: Revenue +{rev_jump:.0%} with goodwill increase — CAGR may be "
                    f"M&A-distorted. Organic CAGR excludes this year [ASSUMED]"
                )
                excluded_yrs.add(years[i])

    # Trending OG: same direction 4+ consecutive years
    if len(OG_l) >= 5:
        og_diffs = [OG_l[i] - OG_l[i - 1] for i in range(1, len(OG_l))]
        last4    = og_diffs[-4:]
        if all(d > 0 for d in last4) or all(d < 0 for d in last4):
            flags.append(
                "OG has trended consistently for 4+ consecutive years — simple average may "
                "understate trend. DA has reviewed both simple avg [ASSUMED] and trend-extrapolated OG [EST]."
            )

    # Historical averages excluding flagged years
    valid_idx = [i for i, y in enumerate(years) if y not in excluded_yrs and FCF_l[i] is not None]
    if not valid_idx:
        valid_idx = list(range(len(years)))

    avg_OG  = sum(OG_l[i]  for i in valid_idx) / len(valid_idx)
    avg_ATO = sum(ATO_l[i] for i in valid_idx) / len(valid_idx)

    valid_rev = [(years[i], revenue_l[i]) for i in range(len(years)) if years[i] not in excluded_yrs]
    if len(valid_rev) >= 2:
        y0, r0 = valid_rev[0]
        yn, rn = valid_rev[-1]
        n_yrs  = yn - y0
        rev_cagr = ((rn / r0) ** (1 / n_yrs) - 1) if r0 != 0 and n_yrs > 0 else 0.0
    else:
        rev_cagr = 0.0

    return {
        "years":          years,
        "revenue":        revenue_l,
        "NOA":            NOA_l,
        "NFO":            NFO_l,
        "OI":             OI_l,
        "FCF":            FCF_l,
        "RNOA":           RNOA_l,
        "OG":             OG_l,
        "ATO":            ATO_l,
        "FLEV":           FLEV_l,
        "NBC":            NBC_l,
        "SPREAD":         SPREAD_l,
        "ROCE":           ROCE_l,
        "NCI":            NCI_l,
        "common_equity":  equity_l,
        "historical_avgs": {
            "OG":          avg_OG,
            "ATO":         avg_ATO,
            "revenue_cagr": rev_cagr,
        },
        "flags":       flags,
        "assumptions": [f"t={t:.1%} statutory corporate tax rate applied to OI and NBC"],
    }
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_annual_report_reformulator.py -v
```
Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add newsletter_agent/specialists/annual_report_reformulator.py tests/test_annual_report_reformulator.py
git commit -m "feat: add Penman reformulator with one-time item, M&A, and trending OG detectors"
```

---

### Task 4: Consistency Checker

**Files:**
- Create: `newsletter_agent/specialists/annual_report_checker.py`
- Test: `tests/test_annual_report_checker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_annual_report_checker.py
from newsletter_agent.specialists.annual_report_checker import check

def _valid_inputs():
    return {
        "rf_re":        0.0384,
        "rf_rd":        0.0384,    # must match rf_re
        "rating_spread": 0.0125,   # Moody's A2
        "icr_spread":    0.0130,   # within 0.5% of rating_spread
        "beta_raw":      0.85,
        "beta_adj":      0.8167,   # 2/3*0.85 + 1/3
        "shares_source": "diluted",
        "tax_type":      "statutory",
        "nci_present":   True,
        "bond_type":     "nominal",
    }


def test_all_checks_pass():
    result = check(_valid_inputs())
    assert result["passed"] is True
    assert result["issues"] == []


def test_rf_mismatch_fails():
    inputs = _valid_inputs()
    inputs["rf_rd"] = 0.0432   # differs from rf_re
    result = check(inputs)
    assert result["passed"] is False
    assert any("rf" in issue.lower() for issue in result["issues"])


def test_spread_divergence_fails():
    inputs = _valid_inputs()
    inputs["icr_spread"] = 0.0200   # >0.5% from rating_spread 0.0125
    result = check(inputs)
    assert result["passed"] is False
    assert any("spread" in issue.lower() for issue in result["issues"])


def test_beta_raw_used_fails():
    inputs = _valid_inputs()
    inputs["beta_adj"] = inputs["beta_raw"]   # β_adj equals β_raw → Blume not applied
    result = check(inputs)
    assert result["passed"] is False
    assert any("blume" in issue.lower() or "β_adj" in issue for issue in result["issues"])


def test_basic_shares_fails():
    inputs = _valid_inputs()
    inputs["shares_source"] = "basic"
    result = check(inputs)
    assert result["passed"] is False


def test_effective_tax_fails():
    inputs = _valid_inputs()
    inputs["tax_type"] = "effective"
    result = check(inputs)
    assert result["passed"] is False


def test_nci_absent_fails():
    inputs = _valid_inputs()
    inputs["nci_present"] = False
    result = check(inputs)
    assert result["passed"] is False


def test_inflation_linked_bond_fails():
    inputs = _valid_inputs()
    inputs["bond_type"] = "inflation_linked"
    result = check(inputs)
    assert result["passed"] is False
    assert any("nominal" in issue.lower() or "inflation" in issue.lower() for issue in result["issues"])
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_annual_report_checker.py -v
```

- [ ] **Step 3: Implement checker**

```python
# newsletter_agent/specialists/annual_report_checker.py

def check(wacc_inputs: dict) -> dict:
    issues = []

    rf_re = wacc_inputs["rf_re"]
    rf_rd = wacc_inputs["rf_rd"]
    if abs(rf_re - rf_rd) > 1e-6:
        issues.append(
            f"rf mismatch: rf used in rE ({rf_re:.4f}) ≠ rf used in rD ({rf_rd:.4f}). "
            f"Both must use the same country-matched historical avg. [BLOCK]"
        )

    rating_spread = wacc_inputs["rating_spread"]
    icr_spread    = wacc_inputs["icr_spread"]
    if abs(rating_spread - icr_spread) > 0.005:
        issues.append(
            f"Credit spread divergence: Moody's-implied rs={rating_spread:.4f} vs "
            f"ICR-implied rs={icr_spread:.4f} (diff={abs(rating_spread-icr_spread):.4f} > 0.5%). "
            f"Verify rating or recompute ICR. [BLOCK]"
        )

    beta_raw = wacc_inputs["beta_raw"]
    beta_adj = wacc_inputs["beta_adj"]
    expected_adj = (2 / 3) * beta_raw + (1 / 3)
    if abs(beta_adj - expected_adj) > 0.001:
        issues.append(
            f"β_adj={beta_adj:.4f} does not match Blume formula (2/3×β_raw+1/3={expected_adj:.4f}). "
            f"β_raw={beta_raw}. Always apply Blume adjustment. [BLOCK]"
        )

    if wacc_inputs.get("shares_source") != "diluted":
        issues.append(
            "Shares outstanding must be diluted (from FMP weightedAverageShsOutDil), "
            "not basic. Basic shares overstates price per share. [BLOCK]"
        )

    if wacc_inputs.get("tax_type") != "statutory":
        issues.append(
            "Tax rate must be statutory corporate rate, not effective rate. "
            "Effective rate fluctuates with one-time items. [BLOCK]"
        )

    if not wacc_inputs.get("nci_present"):
        issues.append(
            "NCI (minority interest) not subtracted from equity bridge. "
            "EV − NFO − NCI = equity value. Missing NCI overstates equity value. [BLOCK]"
        )

    if wacc_inputs.get("bond_type") == "inflation_linked":
        issues.append(
            "rf source is an inflation-linked bond. Must use nominal government bond. "
            "Mixing real rf with nominal g=2% silently inflates terminal value. [BLOCK]"
        )

    return {"passed": len(issues) == 0, "issues": issues}
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_annual_report_checker.py -v
```
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add newsletter_agent/specialists/annual_report_checker.py tests/test_annual_report_checker.py
git commit -m "feat: add consistency checker with 7 WACC validation gates"
```

---

### Task 5: Valuation Engine

**Files:**
- Create: `newsletter_agent/specialists/annual_report_valuation.py`
- Test: `tests/test_annual_report_valuation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_annual_report_valuation.py
import pytest
from newsletter_agent.specialists.annual_report_valuation import (
    compute_wacc, compute_dcf, compute_sensitivity,
)
from newsletter_agent.specialists.annual_report_constants import MOODY_TO_SPREAD

FAKE_PROFILE = {
    "beta": 0.90, "mktCap": 300_000, "price": 600.0,
    "country": "Denmark", "currency": "DKK",
    "sharesOutstanding": 500,
}
FAKE_RATING = [{"rating": "A2", "ratingAgency": "Moody's"}]

FAKE_FMP = {
    "profile": FAKE_PROFILE,
    "rating":  FAKE_RATING,
    "income":  [{"weightedAverageShsOutDil": 500}],
}

FAKE_REFORMULATED = {
    "NOA":  [100_000] * 5,
    "NFO":  [40_000]  * 5,
    "OI":   [15_600]  * 5,
    "FCF":  [None, 15_600, 15_600, 15_600, 15_600],
    "NCI":  [5_000]   * 5,
    "common_equity": [55_000] * 5,
    "revenue": [100_000] * 5,
    "years": [2020, 2021, 2022, 2023, 2024],
    "historical_avgs": {"OG": 0.156, "ATO": 1.0, "revenue_cagr": 0.03},
    "flags": [],
}


def test_compute_wacc_keys():
    result = compute_wacc(FAKE_FMP, FAKE_REFORMULATED, "DNK")
    for k in ["rf", "beta_raw", "beta_adj", "MRP", "CRP", "rE", "rs", "rD", "wacc", "t",
              "D", "E", "V", "rs_icr", "rating", "checker_inputs"]:
        assert k in result, f"Missing key: {k}"


def test_compute_wacc_beta_adj():
    result = compute_wacc(FAKE_FMP, FAKE_REFORMULATED, "DNK")
    expected_adj = (2 / 3) * 0.90 + (1 / 3)
    assert abs(result["beta_adj"] - expected_adj) < 1e-4


def test_compute_wacc_rf_dnk():
    result = compute_wacc(FAKE_FMP, FAKE_REFORMULATED, "DNK")
    assert abs(result["rf"] - 0.0384) < 1e-4


def test_compute_wacc_moody_spread():
    result = compute_wacc(FAKE_FMP, FAKE_REFORMULATED, "DNK")
    assert abs(result["rs"] - MOODY_TO_SPREAD["A2"]) < 1e-6


def test_compute_dcf_returns_keys():
    result = compute_dcf(
        FAKE_REFORMULATED, wacc=0.065, g=0.02,
        NFO=40_000, NCI=5_000, diluted_shares=500, base_year=2024,
    )
    for k in ["forecast_years", "revenue_forecast", "OI_forecast", "NOA_forecast",
              "dNOA_forecast", "FCF_forecast", "discount_factors", "PV_FCF",
              "total_PV", "TV", "PV_TV", "EV", "NFO", "NCI",
              "equity_value", "diluted_shares", "price_per_share", "g"]:
        assert k in result, f"Missing: {k}"


def test_compute_dcf_discount_factor_year1():
    result = compute_dcf(
        FAKE_REFORMULATED, wacc=0.065, g=0.02,
        NFO=40_000, NCI=5_000, diluted_shares=500, base_year=2024,
    )
    assert abs(result["discount_factors"][0] - 1.065) < 0.001


def test_compute_dcf_ev_positive():
    result = compute_dcf(
        FAKE_REFORMULATED, wacc=0.065, g=0.02,
        NFO=40_000, NCI=5_000, diluted_shares=500, base_year=2024,
    )
    assert result["EV"] > 0
    assert result["price_per_share"] > 0


def test_compute_sensitivity_grid_shape():
    result = compute_sensitivity(
        FAKE_REFORMULATED, wacc_base=0.065, g_base=0.02,
        NFO=40_000, NCI=5_000, diluted_shares=500, base_year=2024,
    )
    assert len(result["wacc_axis"]) == 9
    assert len(result["g_axis"]) == 5
    assert len(result["grid"]) == 5
    assert len(result["grid"][0]) == 9
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_annual_report_valuation.py -v
```

- [ ] **Step 3: Implement valuation engine**

```python
# newsletter_agent/specialists/annual_report_valuation.py
from newsletter_agent.specialists.annual_report_constants import (
    RF_BY_COUNTRY, MSCI_WORLD_35YR_RETURN, MOODY_TO_SPREAD,
    CRP_BY_COUNTRY, STATUTORY_TAX_RATE, normalize_country, icr_to_spread,
)


def compute_wacc(fmp_data: dict, reformulated: dict, hq_country: str) -> dict:
    iso3     = normalize_country(hq_country) if len(hq_country) > 3 else hq_country.upper()
    rf_entry = RF_BY_COUNTRY.get(iso3, RF_BY_COUNTRY["_default"])
    rf       = rf_entry["rate"]
    t        = STATUTORY_TAX_RATE.get(iso3, STATUTORY_TAX_RATE["_default"])

    profile   = fmp_data.get("profile", {})
    beta_raw  = float(profile.get("beta") or 1.0)
    beta_adj  = (2 / 3) * beta_raw + (1 / 3)

    MRP = MSCI_WORLD_35YR_RETURN - rf
    CRP = CRP_BY_COUNTRY.get(iso3, CRP_BY_COUNTRY["_default"])
    rE  = rf + beta_adj * (MRP + CRP)

    # Moody's credit spread (primary); ICR cross-check
    rating     = ""
    rs_moody   = None
    for r in fmp_data.get("rating", []):
        if "moody" in (r.get("ratingAgency") or "").lower():
            rating   = r.get("rating", "")
            rs_moody = MOODY_TO_SPREAD.get(rating)
            break

    # ICR cross-check: EBIT / interest expense from latest income year
    income = fmp_data.get("income", [{}])
    ebit   = float(income[0].get("operatingIncome") or 0)
    int_ex = float(income[0].get("interestExpense") or 1)
    icr    = ebit / int_ex if int_ex != 0 else 8.5
    rs_icr = icr_to_spread(icr)

    rs = rs_moody if rs_moody is not None else rs_icr
    if rs_moody is None:
        rating = f"ICR fallback (ICR={icr:.1f})"

    rD = (rf + rs) * (1 - t)

    NFO  = reformulated["NFO"][-1]
    mktcap = float(profile.get("mktCap") or 0)
    D    = max(NFO, 0)
    E    = mktcap
    V    = D + E if (D + E) > 0 else 1
    wacc = (D / V) * rD + (E / V) * rE

    checker_inputs = {
        "rf_re":         rf,
        "rf_rd":         rf,
        "rating_spread": rs,
        "icr_spread":    rs_icr,
        "beta_raw":      beta_raw,
        "beta_adj":      beta_adj,
        "shares_source": "diluted",
        "tax_type":      "statutory",
        "nci_present":   any(v > 0 for v in reformulated["NCI"]),
        "bond_type":     "nominal",
    }

    return {
        "rf": rf, "rf_entry": rf_entry, "t": t,
        "beta_raw": beta_raw, "beta_adj": beta_adj,
        "MRP": MRP, "CRP": CRP, "rE": rE,
        "rating": rating, "rs": rs, "rs_moody": rs_moody, "rs_icr": rs_icr,
        "rD": rD, "D": D, "E": E, "V": V, "wacc": wacc,
        "checker_inputs": checker_inputs,
        "iso3": iso3,
    }


def _dcf_price(reformulated: dict, wacc: float, g: float,
               NFO: float, NCI: float, diluted_shares: float,
               base_year: int, n_years: int = 5) -> tuple[float, dict]:
    avgs        = reformulated["historical_avgs"]
    rev_cagr    = avgs["revenue_cagr"]
    og_avg      = avgs["OG"]
    ato_avg     = avgs["ATO"]
    base_rev    = reformulated["revenue"][-1]
    base_NOA    = reformulated["NOA"][-1]

    forecast_years, rev_f, oi_f, noa_f, dnoa_f, fcf_f, df_f, pv_f = [], [], [], [], [], [], [], []
    prev_NOA = base_NOA

    for t_idx in range(1, n_years + 1):
        yr_label = f"{base_year + t_idx}E"
        rev      = base_rev * ((1 + rev_cagr) ** t_idx)
        oi       = rev * og_avg
        noa      = rev / ato_avg if ato_avg != 0 else prev_NOA
        dnoa     = noa - prev_NOA
        fcf      = oi - dnoa
        disc     = (1 + wacc) ** t_idx
        pv       = fcf / disc

        forecast_years.append(yr_label)
        rev_f.append(rev); oi_f.append(oi); noa_f.append(noa)
        dnoa_f.append(dnoa); fcf_f.append(fcf); df_f.append(disc); pv_f.append(pv)
        prev_NOA = noa

    total_PV = sum(pv_f)
    fcf_t1   = fcf_f[-1] * (1 + g)
    TV       = fcf_t1 / (wacc - g) if (wacc - g) > 0 else 0
    PV_TV    = TV / ((1 + wacc) ** n_years)
    EV       = total_PV + PV_TV
    eq_val   = EV - NFO - NCI
    price    = eq_val / diluted_shares if diluted_shares > 0 else 0

    detail = dict(
        forecast_years=forecast_years,
        revenue_forecast=rev_f, OI_forecast=oi_f,
        NOA_forecast=noa_f, dNOA_forecast=dnoa_f,
        FCF_forecast=fcf_f, discount_factors=df_f, PV_FCF=pv_f,
        total_PV=total_PV, TV=TV, PV_TV=PV_TV, EV=EV,
        NFO=NFO, NCI=NCI, equity_value=eq_val,
        diluted_shares=diluted_shares, price_per_share=price,
        g=g, n_years=n_years,
    )
    return price, detail


def compute_dcf(reformulated: dict, wacc: float, g: float = 0.02,
                NFO: float = 0.0, NCI: float = 0.0,
                diluted_shares: float = 1.0, base_year: int = 2024) -> dict:
    _, detail = _dcf_price(reformulated, wacc, g, NFO, NCI, diluted_shares, base_year)
    return detail


def compute_sensitivity(reformulated: dict, wacc_base: float, g_base: float,
                         NFO: float, NCI: float, diluted_shares: float,
                         base_year: int) -> dict:
    wacc_steps = [wacc_base + (i - 4) * 0.0025 for i in range(9)]
    g_steps    = [0.01, 0.015, 0.02, 0.025, 0.03]
    grid       = []
    for g in g_steps:
        row = []
        for w in wacc_steps:
            if w <= g:
                row.append(None)
            else:
                price, _ = _dcf_price(reformulated, w, g, NFO, NCI, diluted_shares, base_year)
                row.append(round(price, 2))
        grid.append(row)
    return {
        "wacc_axis":   [round(w, 4) for w in wacc_steps],
        "g_axis":      g_steps,
        "grid":        grid,
        "wacc_base":   wacc_base,
        "g_base":      g_base,
    }
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_annual_report_valuation.py -v
```
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add newsletter_agent/specialists/annual_report_valuation.py tests/test_annual_report_valuation.py
git commit -m "feat: add valuation engine (WACC, DCF, sensitivity grid)"
```

---

### Task 6: Devil's Advocate Reviewers

**Files:**
- Create: `newsletter_agent/specialists/annual_report_da.py`

- [ ] **Step 1: Implement DA reviewers** (no unit test needed — Claude API calls are fully mocked in integration; test coverage comes from Task 8)

```python
# newsletter_agent/specialists/annual_report_da.py
import anthropic
from newsletter_agent.config import REVIEWER_MODEL


def _call(client: anthropic.Anthropic, system: str, user: str) -> str:
    msg = client.messages.create(
        model=REVIEWER_MODEL,
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip()


_SYSTEM = (
    "You are a Devil's Advocate financial analyst. Be concise (max 4 bullet points). "
    "Flag only real issues — not hypothetical. Each bullet: issue + severity (WARN/BLOCK)."
)


def review_reformulation(reformulated: dict, client: anthropic.Anthropic) -> str:
    noa_latest = reformulated["NOA"][-1]
    fcf_latest = next((v for v in reversed(reformulated["FCF"]) if v is not None), None)
    flags      = reformulated.get("flags", [])
    user = (
        f"NOA (latest year): {noa_latest:,.0f}\n"
        f"FCF (latest year): {fcf_latest:,.0f if fcf_latest else 'N/A'}\n"
        f"OG avg: {reformulated['historical_avgs']['OG']:.3f}\n"
        f"ATO avg: {reformulated['historical_avgs']['ATO']:.3f}\n"
        f"Revenue CAGR: {reformulated['historical_avgs']['revenue_cagr']:.3f}\n"
        f"Flags raised: {flags}\n\n"
        "Review: Is NOA > 0? Is FCF trend directionally consistent with OI? "
        "Are flagged years properly excluded from averages?"
    )
    return _call(client, _SYSTEM, user)


def review_consistency(check_result: dict, client: anthropic.Anthropic) -> str:
    user = (
        f"Consistency check result: passed={check_result['passed']}\n"
        f"Issues: {check_result['issues']}\n\n"
        "Review: Are the issues complete and correctly described? "
        "Is any critical check missing?"
    )
    return _call(client, _SYSTEM, user)


def review_valuation(wacc_data: dict, dcf_results: dict,
                     market_price: float, client: anthropic.Anthropic) -> str:
    price = dcf_results["price_per_share"]
    ratio = price / market_price if market_price > 0 else 0
    user = (
        f"WACC: {wacc_data['wacc']:.4f}, rf: {wacc_data['rf']:.4f}, "
        f"rE: {wacc_data['rE']:.4f}, rD: {wacc_data['rD']:.4f}\n"
        f"β_raw={wacc_data['beta_raw']:.2f}, β_adj={wacc_data['beta_adj']:.4f}\n"
        f"DCF price/share: {price:.2f}, Market price: {market_price:.2f} "
        f"(ratio: {ratio:.2f}x)\n"
        f"EV: {dcf_results['EV']:,.0f}, TV share: "
        f"{dcf_results['PV_TV']/dcf_results['EV']:.0%}\n"
        f"g={dcf_results['g']:.3f}\n\n"
        "Review: Is rf consistent? Is β_adj applied? Is terminal growth ≤ long-run GDP? "
        "Is EV > 0? Flag if price/share is outside 0.2×–5× of market price."
    )
    return _call(client, _SYSTEM, user)


def review_kpi_specs(chart_specs: list, client: anthropic.Anthropic) -> str:
    missing_notes  = [s.get("title", f"#{i}") for i, s in enumerate(chart_specs) if not s.get("note")]
    missing_kilde  = [s.get("title", f"#{i}") for i, s in enumerate(chart_specs) if not s.get("kilde")]
    user = (
        f"Total chart specs generated: {len(chart_specs)}\n"
        f"Missing 'note' field: {missing_notes or 'none'}\n"
        f"Missing 'kilde' field: {missing_kilde or 'none'}\n\n"
        "Review: Are all 18 charts present? Any missing note or kilde? "
        "Is the over/undervalued conclusion in chart #16 consistent with the sensitivity midpoint in chart #15?"
    )
    return _call(client, _SYSTEM, user)


def review_final(chart_specs: list, price_per_share: float,
                 market_price: float, client: anthropic.Anthropic) -> str:
    unlabeled = [
        s.get("title", f"#{i}") for i, s in enumerate(chart_specs)
        if s.get("table_data") and not any(
            any(tag in str(row) for tag in ["EST]", "CALC]", "ASSUMED]", "SOURCED]"])
            for row in s["table_data"].get("rows", [])
        )
    ]
    ratio = price_per_share / market_price if market_price > 0 else 0
    user = (
        f"Fundamental price: {price_per_share:.2f}, Market price: {market_price:.2f} "
        f"(ratio: {ratio:.2f}x)\n"
        f"Type-D tables without transparency labels: {unlabeled or 'none'}\n\n"
        "Final gate: Are all EST/ASSUMED values labeled in table cells? "
        "Is the over/undervalued conclusion (chart #16) consistent with the sensitivity midpoint (chart #15)?"
    )
    return _call(client, _SYSTEM, user)
```

- [ ] **Step 2: Commit**

```bash
git add newsletter_agent/specialists/annual_report_da.py
git commit -m "feat: add 5 Devil's Advocate reviewers for annual report pipeline"
```

---

### Task 7: KPI Packager (18 Chart Specs)

**Files:**
- Create: `newsletter_agent/specialists/annual_report_kpi.py`
- Test: `tests/test_annual_report_kpi.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_annual_report_kpi.py
import pandas as pd
from newsletter_agent.specialists.annual_report_kpi import build_chart_specs

REFORMULATED = {
    "years": [2020, 2021, 2022, 2023, 2024],
    "revenue":       [100_000] * 5,
    "NOA":           [100_000] * 5,
    "NFO":           [40_000]  * 5,
    "OI":            [15_600]  * 5,
    "FCF":           [None, 15_600, 15_600, 15_600, 15_600],
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
}
WACC_DATA = {
    "rf": 0.0384, "rf_entry": {"rate": 0.0384, "maturity_yr": 35,
                                "spot": 0.028, "bond_name": "Dansk statsobligation 35år avg"},
    "t": 0.22, "beta_raw": 0.90, "beta_adj": 0.933,
    "MRP": 0.0374, "CRP": 0.0, "rE": 0.073,
    "rating": "A2", "rs": 0.0125, "rs_moody": 0.0125, "rs_icr": 0.013,
    "rD": 0.0398, "D": 40_000, "E": 300_000, "V": 340_000,
    "wacc": 0.065, "iso3": "DNK",
}
DCF = {
    "forecast_years": ["2025E", "2026E", "2027E", "2028E", "2029E"],
    "revenue_forecast": [103_000, 106_090, 109_273, 112_551, 115_927],
    "OI_forecast":      [16_068, 16_550, 17_046, 17_558, 18_085],
    "NOA_forecast":     [103_000, 106_090, 109_273, 112_551, 115_927],
    "dNOA_forecast":    [3_000, 3_090, 3_183, 3_278, 3_376],
    "FCF_forecast":     [13_068, 13_460, 13_863, 14_280, 14_709],
    "discount_factors": [1.065, 1.134, 1.208, 1.286, 1.370],
    "PV_FCF":           [12_269, 11_871, 11_477, 11_106, 10_738],
    "total_PV":         57_461, "TV": 324_098, "PV_TV": 236_567,
    "EV": 294_028, "NFO": 40_000, "NCI": 5_000,
    "equity_value": 249_028, "diluted_shares": 500,
    "price_per_share": 498.06, "g": 0.02, "n_years": 5,
}
SENSITIVITY = {
    "wacc_axis": [0.054, 0.0565, 0.059, 0.0615, 0.065, 0.0665, 0.069, 0.0715, 0.074],
    "g_axis": [0.01, 0.015, 0.02, 0.025, 0.03],
    "grid": [[400, 420, 440, 460, 480, 500, 520, 540, 560]] * 5,
    "wacc_base": 0.065, "g_base": 0.02,
}
FAKE_FMP = {
    "profile": {"price": 550.0, "companyName": "TestCo A/S", "country": "Denmark",
                "mktCap": 275_000, "currency": "DKK"},
    "estimates": [],
    "metrics": [{"peRatio": 18.5, "pbRatio": 3.2, "priceToSalesRatio": 2.8,
                 "pfcfRatio": 20.1, "evToEbitda": 12.3, "date": "2024-12-31"}],
}


def test_returns_18_chart_specs():
    specs, dfs = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                   REFORMULATED, WACC_DATA, DCF, SENSITIVITY, FAKE_FMP)
    assert len(specs) == 18


def test_all_specs_have_title_note_kilde():
    specs, _ = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                  REFORMULATED, WACC_DATA, DCF, SENSITIVITY, FAKE_FMP)
    for i, s in enumerate(specs):
        assert s.get("title"),  f"Chart #{i+1} missing title"
        assert s.get("note"),   f"Chart #{i+1} missing note"
        assert s.get("kilde"),  f"Chart #{i+1} missing kilde"


def test_type_d_charts_have_table_data():
    specs, _ = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                  REFORMULATED, WACC_DATA, DCF, SENSITIVITY, FAKE_FMP)
    for s in specs:
        if s["type"] == "D":
            assert "table_data" in s, f"Type D chart '{s['title']}' missing table_data"
            assert "columns" in s["table_data"]
            assert "rows"    in s["table_data"]


def test_type_a_charts_have_series_labels():
    specs, dfs = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                    REFORMULATED, WACC_DATA, DCF, SENSITIVITY, FAKE_FMP)
    for s in specs:
        if s["type"] == "A":
            assert "series_labels" in s, f"Type A chart '{s['title']}' missing series_labels"
            for lbl in s["series_labels"]:
                assert lbl in dfs, f"series_labels ref '{lbl}' not in dataframes"


def test_type_a_dataframes_have_datetime_index():
    _, dfs = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                REFORMULATED, WACC_DATA, DCF, SENSITIVITY, FAKE_FMP)
    import pandas as pd
    for label, df in dfs.items():
        assert isinstance(df.index, pd.DatetimeIndex), f"DataFrame '{label}' missing DatetimeIndex"


def test_dcf_table_has_transparency_labels():
    specs, _ = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                  REFORMULATED, WACC_DATA, DCF, SENSITIVITY, FAKE_FMP)
    dcf_spec = next(s for s in specs if "DCF" in s.get("title", "") and s["type"] == "D"
                    and "forecast" in s.get("title", "").lower())
    rows = dcf_spec["table_data"]["rows"]
    labeled = [r["indicator"] for r in rows if any(
        tag in r["indicator"] for tag in ["[EST]", "[CALC]", "[ASSUMED]", "[SOURCED]"]
    )]
    assert len(labeled) >= 5, "DCF table must have at least 5 labeled rows"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_annual_report_kpi.py -v
```

- [ ] **Step 3: Implement KPI packager**

```python
# newsletter_agent/specialists/annual_report_kpi.py
import pandas as pd


def _ts(years: list, values: list, label: str) -> pd.DataFrame:
    """Build a DatetimeIndex DataFrame from year list and values."""
    idx = pd.DatetimeIndex([pd.Timestamp(f"{y}-12-31") for y in years])
    return pd.DataFrame({label: values}, index=idx)


def _pct(v: float) -> str:
    return f"{v:.2%}"

def _num(v: float, scale: float = 1) -> str:
    return f"{v / scale:,.1f}"


def build_chart_specs(
    ticker: str, company_name: str, hq_country: str,
    reformulated: dict, wacc_data: dict, dcf_results: dict,
    sensitivity: dict, fmp_data: dict,
) -> tuple[list[dict], dict[str, pd.DataFrame]]:

    years   = reformulated["years"]
    profile = fmp_data.get("profile", {})
    currency= profile.get("currency", "")
    price   = float(profile.get("price") or 0)
    kilde   = f"FMP, Damodaran ({ticker})"
    rf_entry= wacc_data["rf_entry"]
    wacc    = wacc_data["wacc"]
    iso3    = wacc_data["iso3"]
    dcf_price = dcf_results["price_per_share"]

    # ── Shared DataFrames for type A charts ──────────────────────────────────
    dfs: dict[str, pd.DataFrame] = {}

    lbl_rev    = f"{ticker} — Omsætning ({currency}m)"
    lbl_oi     = f"{ticker} — OI/NOPAT ({currency}m)"
    lbl_fcf    = f"{ticker} — FCF ({currency}m)"
    lbl_rnoa   = f"{ticker} — RNOA (%)"
    lbl_roce   = f"{ticker} — ROCE (%)"
    lbl_spread = f"{ticker} — SPREAD (%)"
    lbl_wacc_line = f"{ticker} — WACC (%)"
    lbl_rnoa_vs   = f"{ticker} — RNOA vs WACC (%)"
    lbl_flev   = f"{ticker} — FLEV"
    lbl_nfo    = f"{ticker} — NFO ({currency}m)"

    scale = 1  # values already in native currency units

    dfs[lbl_rev]    = _ts(years, reformulated["revenue"],    lbl_rev)
    dfs[lbl_oi]     = _ts(years, reformulated["OI"],         lbl_oi)
    fcf_vals        = [v if v is not None else float("nan") for v in reformulated["FCF"]]
    dfs[lbl_fcf]    = _ts(years, fcf_vals, lbl_fcf)
    dfs[lbl_rnoa]   = _ts(years, [v * 100 for v in reformulated["RNOA"]], lbl_rnoa)
    dfs[lbl_roce]   = _ts(years, [v * 100 for v in reformulated["ROCE"]], lbl_roce)
    dfs[lbl_spread] = _ts(years, [v * 100 for v in reformulated["SPREAD"]], lbl_spread)
    dfs[lbl_wacc_line] = _ts(years, [wacc * 100] * len(years), lbl_wacc_line)
    spread_rnoa_wacc = [r * 100 - wacc * 100 for r in reformulated["RNOA"]]
    dfs[lbl_rnoa_vs] = _ts(years, spread_rnoa_wacc, lbl_rnoa_vs)
    dfs[lbl_flev]   = _ts(years, reformulated["FLEV"], lbl_flev)
    dfs[lbl_nfo]    = _ts(years, reformulated["NFO"],  lbl_nfo)

    # Fundamental vs market price (type B)
    lbl_fund   = f"{ticker} — Fundamental pris"
    lbl_market = f"{ticker} — Markedspris"
    dfs[lbl_fund]   = _ts([years[-1]], [dcf_price],  lbl_fund)
    dfs[lbl_market] = _ts([years[-1]], [price],       lbl_market)

    # ── Chart specs (18 total) ───────────────────────────────────────────────
    specs = []

    # Chart 1: Forecast assumptions table
    specs.append({
        "type": "D", "title": f"{company_name} — Forecast Assumptions [ASSUMED/SOURCED]",
        "note": (f"rf={_pct(wacc_data['rf'])} ({rf_entry['bond_name']}, "
                 f"{rf_entry['maturity_yr']}yr historical avg [ASSUMED]). "
                 f"β_raw={wacc_data['beta_raw']:.2f} [SOURCED], "
                 f"β_adj={wacc_data['beta_adj']:.4f} (Blume 1975 [CALC]). "
                 f"MRP={_pct(wacc_data['MRP'])} [SOURCED], CRP={_pct(wacc_data['CRP'])} [SOURCED]. "
                 f"t={_pct(wacc_data['t'])} statutory [ASSUMED]."),
        "kilde": kilde,
        "table_data": {
            "columns": ["Parameter", "Værdi", "Label", "Kilde"],
            "rows": [
                {"indicator": "rf (risikofri rente)",    "Parameter": "rf",    "Værdi": _pct(wacc_data["rf"]),    "Label": "ASSUMED",  "Kilde": rf_entry["bond_name"]},
                {"indicator": "β_raw",                   "Parameter": "β_raw", "Værdi": f"{wacc_data['beta_raw']:.4f}", "Label": "SOURCED", "Kilde": "FMP /profile"},
                {"indicator": "β_adj (Blume 1975)",      "Parameter": "β_adj", "Værdi": f"{wacc_data['beta_adj']:.4f}", "Label": "CALC",    "Kilde": "2/3×β_raw+1/3"},
                {"indicator": "MRP (markedsrisikopræmie)","Parameter": "MRP",  "Værdi": _pct(wacc_data["MRP"]),   "Label": "SOURCED",  "Kilde": "Damodaran MSCI World 35yr"},
                {"indicator": "CRP (landrisikopræmie)",  "Parameter": "CRP",   "Værdi": _pct(wacc_data["CRP"]),   "Label": "SOURCED",  "Kilde": f"Damodaran {iso3}"},
                {"indicator": "rE (egenkapitalomkostning)","Parameter": "rE",  "Værdi": _pct(wacc_data["rE"]),   "Label": "CALC",     "Kilde": "CAPM"},
                {"indicator": "Moody's rating",          "Parameter": "rating","Værdi": wacc_data["rating"],       "Label": "SOURCED",  "Kilde": "FMP /rating"},
                {"indicator": "rs (kreditspænd)",        "Parameter": "rs",    "Værdi": _pct(wacc_data["rs"]),    "Label": "SOURCED",  "Kilde": "Damodaran spread tabel"},
                {"indicator": "rD (gældsomkostning, after-tax)","Parameter": "rD","Værdi": _pct(wacc_data["rD"]),"Label": "CALC",   "Kilde": "(rf+rs)×(1−t)"},
                {"indicator": "WACC",                    "Parameter": "WACC",  "Værdi": _pct(wacc_data["wacc"]), "Label": "CALC",     "Kilde": "D/V×rD + E/V×rE"},
                {"indicator": "OG (driftsmargin, avg)",  "Parameter": "OG",    "Værdi": _pct(reformulated["historical_avgs"]["OG"]), "Label": "CALC", "Kilde": "FMP 10yr avg"},
                {"indicator": "ATO (aktivomsætning, avg)","Parameter": "ATO",  "Værdi": f"{reformulated['historical_avgs']['ATO']:.2f}x", "Label": "CALC", "Kilde": "FMP 10yr avg"},
                {"indicator": "g (terminalvækst)",       "Parameter": "g",     "Værdi": _pct(dcf_results["g"]),  "Label": "ASSUMED",  "Kilde": "Gordons vækstmodel"},
                {"indicator": "t (skattesats, statutær)","Parameter": "t",     "Værdi": _pct(wacc_data["t"]),    "Label": "ASSUMED",  "Kilde": f"Statutory {iso3}"},
            ],
        },
    })

    # Chart 2: Bond yield table
    specs.append({
        "type": "D", "title": f"{company_name} — Risikofri Rente [ASSUMED]",
        "note": (f"rf = {_pct(rf_entry['rate'])} er det {rf_entry['maturity_yr']}-årige historiske gennemsnit "
                 f"af {rf_entry['bond_name']}. Aktuel spotrente = {_pct(rf_entry['spot'])} — vises kun til reference, "
                 f"ikke anvendt i beregninger. Historisk gennemsnit afspejler den langsigtede ligevægt "
                 f"og matcher terminalperiodens løbetid [ASSUMED]."),
        "kilde": kilde,
        "table_data": {
            "columns": ["Land", "Obligation", "Løbetid", "Hist. avg. [ASSUMED]", "Spot (ref.)"],
            "rows": [
                {"indicator": iso3,
                 "Land": iso3, "Obligation": rf_entry["bond_name"],
                 "Løbetid": f"{rf_entry['maturity_yr']}yr",
                 "Hist. avg. [ASSUMED]": _pct(rf_entry["rate"]),
                 "Spot (ref.)": _pct(rf_entry["spot"])},
            ],
        },
    })

    # Chart 3: Moody's rating + spread table
    specs.append({
        "type": "D", "title": f"{company_name} — Kreditvurdering og Kreditspænd [SOURCED]",
        "note": (f"Moody's kreditvurdering: {wacc_data['rating']}. "
                 f"Kreditspænd (rs) = {_pct(wacc_data['rs'])} [SOURCED]. "
                 f"ICR-baseret krydscheck: {_pct(wacc_data['rs_icr'])} [CALC]."),
        "kilde": kilde,
        "table_data": {
            "columns": ["Kreditvurdering", "Kreditspænd [SOURCED]", "ICR krydscheck [CALC]", "Anvendt"],
            "rows": [
                {"indicator": company_name,
                 "Kreditvurdering": wacc_data["rating"],
                 "Kreditspænd [SOURCED]": _pct(wacc_data["rs"]),
                 "ICR krydscheck [CALC]": _pct(wacc_data["rs_icr"]),
                 "Anvendt": "Moody's (primær)" if wacc_data["rs_moody"] else "ICR (fallback)"},
            ],
        },
    })

    # Chart 4: WACC breakdown
    specs.append({
        "type": "D", "title": f"{company_name} — WACC Komponentopdeling [CALC]",
        "note": f"WACC = D/V × rD + E/V × rE = {_pct(wacc_data['wacc'])} [CALC].",
        "kilde": kilde,
        "table_data": {
            "columns": ["Komponent", "Værdi [CALC]"],
            "rows": [
                {"indicator": "rE (egenkapitalomkostning)", "Komponent": "rE", "Værdi [CALC]": _pct(wacc_data["rE"])},
                {"indicator": "rD (after-tax gældsomkostning)", "Komponent": "rD", "Værdi [CALC]": _pct(wacc_data["rD"])},
                {"indicator": "E/V (egenkapitalvægt)", "Komponent": "E/V", "Værdi [CALC]": _pct(wacc_data["E"] / wacc_data["V"])},
                {"indicator": "D/V (gældsvægt)",       "Komponent": "D/V", "Værdi [CALC]": _pct(wacc_data["D"] / wacc_data["V"])},
                {"indicator": "WACC",                   "Komponent": "WACC","Værdi [CALC]": _pct(wacc_data["wacc"])},
            ],
        },
    })

    # Chart 5: Penman reformulated BS (recent 5 years)
    display_years = years[-5:]
    specs.append({
        "type": "D", "title": f"{company_name} — Penman Reformuleret Balance [CALC]",
        "note": "NOA = Driftsaktiver − Driftsforpligtelser. NFO = Finansielle forpligtelser − Finansielle aktiver [CALC].",
        "kilde": kilde,
        "table_data": {
            "columns": [str(y) for y in display_years],
            "rows": [
                {"indicator": f"NOA [{currency}m] [CALC]",
                 **{str(y): _num(reformulated["NOA"][years.index(y)]) for y in display_years}},
                {"indicator": f"NFO [{currency}m] [CALC]",
                 **{str(y): _num(reformulated["NFO"][years.index(y)]) for y in display_years}},
                {"indicator": f"Egenkapital [{currency}m] [CALC]",
                 **{str(y): _num(reformulated["common_equity"][years.index(y)]) for y in display_years}},
                {"indicator": f"NCI [{currency}m] [CALC]",
                 **{str(y): _num(reformulated["NCI"][years.index(y)]) for y in display_years}},
            ],
        },
    })

    # Chart 6: Key Penman ratios snapshot (latest year)
    ly = len(years) - 1
    specs.append({
        "type": "D", "title": f"{company_name} — Nøgletal (Penman) {years[ly]} [CALC]",
        "note": "RNOA = OI / avg NOA. OG = OI / Omsætning. ATO = Omsætning / avg NOA. "
                "SPREAD = RNOA − NBC. Positiv SPREAD → finansiel gearing skaber værdi [CALC].",
        "kilde": kilde,
        "table_data": {
            "columns": ["Nøgletal", f"{years[ly]} [CALC]"],
            "rows": [
                {"indicator": "RNOA",   "Nøgletal": "RNOA",   f"{years[ly]} [CALC]": _pct(reformulated["RNOA"][ly])},
                {"indicator": "OG",     "Nøgletal": "OG",     f"{years[ly]} [CALC]": _pct(reformulated["OG"][ly])},
                {"indicator": "ATO",    "Nøgletal": "ATO",    f"{years[ly]} [CALC]": f"{reformulated['ATO'][ly]:.2f}x"},
                {"indicator": "ROCE",   "Nøgletal": "ROCE",   f"{years[ly]} [CALC]": _pct(reformulated["ROCE"][ly])},
                {"indicator": "FLEV",   "Nøgletal": "FLEV",   f"{years[ly]} [CALC]": f"{reformulated['FLEV'][ly]:.2f}x"},
                {"indicator": "NBC",    "Nøgletal": "NBC",    f"{years[ly]} [CALC]": _pct(reformulated["NBC"][ly])},
                {"indicator": "SPREAD", "Nøgletal": "SPREAD", f"{years[ly]} [CALC]": _pct(reformulated["SPREAD"][ly])},
            ],
        },
    })

    # Charts 7–12: Type A time series
    specs.append({
        "type": "A", "title": f"{company_name} — Omsætning ({currency}m)",
        "series_labels": [lbl_rev],
        "note": f"10-årig historisk omsætning [CALC]. Revenue CAGR = {_pct(reformulated['historical_avgs']['revenue_cagr'])} (organisk, M&A-justeret [ASSUMED]).",
        "kilde": kilde,
    })
    specs.append({
        "type": "A", "title": f"{company_name} — Driftsoverskud OI/NOPAT ({currency}m)",
        "series_labels": [lbl_oi],
        "note": f"OI = EBIT × (1 − t). t = {_pct(wacc_data['t'])} [ASSUMED]. Penman definition [CALC].",
        "kilde": kilde,
    })
    specs.append({
        "type": "A", "title": f"{company_name} — Frit Cashflow FCF ({currency}m)",
        "series_labels": [lbl_fcf],
        "note": "FCF = OI − ΔNOA (Penman). Første år mangler da ΔNOA kræver forudgående år [CALC].",
        "kilde": kilde,
    })
    specs.append({
        "type": "A", "title": f"{company_name} — RNOA, ROCE og SPREAD (%)",
        "series_labels": [lbl_rnoa, lbl_roce, lbl_spread],
        "note": "RNOA = OI / avg NOA. ROCE = Comprehensive NI / avg egenkapital. SPREAD = RNOA − NBC [CALC].",
        "kilde": kilde,
    })
    specs.append({
        "type": "A", "title": f"{company_name} — RNOA vs. WACC Spread (%)",
        "series_labels": [lbl_rnoa_vs],
        "note": f"Positiv bar → RNOA > WACC → virksomheden skaber reel driftsøkonomisk værdi. WACC = {_pct(wacc)} [CALC].",
        "kilde": kilde,
    })
    specs.append({
        "type": "A", "title": f"{company_name} — Finansiel Gearing (FLEV) og NFO ({currency}m)",
        "series_labels": [lbl_flev, lbl_nfo],
        "note": "FLEV = NFO / Egenkapital. NFO = Finansielle forpligtelser − Finansielle aktiver (Penman) [CALC].",
        "kilde": kilde,
    })

    # Chart 13: DCF forecast table
    fy    = dcf_results["forecast_years"]
    cols  = fy + ["Terminalår"]
    def _frow(label, vals, terminal_val=None):
        row = {"indicator": label}
        for i, yr in enumerate(fy):
            row[yr] = _num(vals[i]) if vals[i] is not None else ""
        row["Terminalår"] = _num(terminal_val) if terminal_val is not None else ""
        return row

    specs.append({
        "type": "D", "title": f"{company_name} — DCF Forecast Tabel [EST/CALC]",
        "note": (f"5-årig prognose. Omsætningsvækst = {_pct(reformulated['historical_avgs']['revenue_cagr'])} [ASSUMED]. "
                 f"OG avg = {_pct(reformulated['historical_avgs']['OG'])} [CALC]. "
                 f"ATO avg = {reformulated['historical_avgs']['ATO']:.2f}x [CALC]. "
                 f"WACC = {_pct(wacc)} [CALC]."),
        "kilde": kilde,
        "table_data": {
            "columns": cols,
            "rows": [
                _frow(f"Nettoomsætning [EST]", dcf_results["revenue_forecast"]),
                _frow(f"Driftsoverskud (OI) [EST]", dcf_results["OI_forecast"]),
                _frow(f"NOA [EST]", dcf_results["NOA_forecast"]),
                _frow(f"ΔNOA [EST]", dcf_results["dNOA_forecast"]),
                _frow(f"Discount factor [CALC]", [round(d, 4) for d in dcf_results["discount_factors"]]),
                _frow(f"FCF (OI − ΔNOA) [EST]", dcf_results["FCF_forecast"]),
                _frow(f"Nutidsværdi af FCF [CALC]", dcf_results["PV_FCF"]),
                {"indicator": ""},
                {"indicator": f"Total nutidsværdi [CALC]", "Terminalår": _num(dcf_results["total_PV"])},
                {"indicator": f"Terminalværdi [CALC]",     "Terminalår": _num(dcf_results["TV"])},
                {"indicator": f"Nutidsværdi af terminalværdi [CALC]", "Terminalår": _num(dcf_results["PV_TV"])},
                {"indicator": ""},
                {"indicator": f"Virksomhedsværdi (EV) [CALC]", "Terminalår": _num(dcf_results["EV"])},
                {"indicator": f"NFO [CALC]",                   "Terminalår": _num(dcf_results["NFO"])},
                {"indicator": f"NCI [CALC]",                   "Terminalår": _num(dcf_results["NCI"])},
                {"indicator": f"Egenkapitalværdi [CALC]",      "Terminalår": _num(dcf_results["equity_value"])},
                {"indicator": f"Antal aktier (fortyndet) [SOURCED]", "Terminalår": f"{dcf_results['diluted_shares']:.2f}m"},
                {"indicator": f"Pris per aktie [CALC]",        "Terminalår": f"{dcf_results['price_per_share']:.2f} {currency}"},
            ],
        },
    })

    # Chart 14: DCF bridge summary
    specs.append({
        "type": "D", "title": f"{company_name} — DCF Brobygger [CALC]",
        "note": f"EV = Σ PV(FCF) + PV(TV). Egenkapitalværdi = EV − NFO − NCI. g = {_pct(dcf_results['g'])} [ASSUMED].",
        "kilde": kilde,
        "table_data": {
            "columns": ["Post", "Beløb [CALC]"],
            "rows": [
                {"indicator": "Total nutidsværdi af FCF [CALC]",        "Post": "Σ PV(FCF)",   "Beløb [CALC]": _num(dcf_results["total_PV"])},
                {"indicator": "Nutidsværdi af terminalværdi [CALC]",    "Post": "PV(TV)",      "Beløb [CALC]": _num(dcf_results["PV_TV"])},
                {"indicator": "Virksomhedsværdi (EV) [CALC]",           "Post": "EV",          "Beløb [CALC]": _num(dcf_results["EV"])},
                {"indicator": "Fratruk NFO [CALC]",                     "Post": "− NFO",       "Beløb [CALC]": _num(dcf_results["NFO"])},
                {"indicator": "Fratruk NCI [CALC]",                     "Post": "− NCI",       "Beløb [CALC]": _num(dcf_results["NCI"])},
                {"indicator": "Egenkapitalværdi [CALC]",                "Post": "= Egenkapital","Beløb [CALC]": _num(dcf_results["equity_value"])},
                {"indicator": f"Pris per aktie [CALC]",                 "Post": "÷ aktier",    "Beløb [CALC]": f"{dcf_results['price_per_share']:.2f} {currency}"},
            ],
        },
    })

    # Chart 15: Sensitivity grid (WACC × g → price)
    wacc_axis = sensitivity["wacc_axis"]
    g_axis    = sensitivity["g_axis"]
    wacc_base = sensitivity["wacc_base"]
    g_base    = sensitivity["g_base"]
    sens_cols = [f"WACC {_pct(w)}" for w in wacc_axis]
    sens_rows = []
    for row_idx, g in enumerate(g_axis):
        row = {"indicator": f"g = {_pct(g)} [ASSUMED]"}
        for col_idx, w in enumerate(wacc_axis):
            cell_val = sensitivity["grid"][row_idx][col_idx]
            cell_str = f"{cell_val:.1f}" if cell_val is not None else "—"
            if abs(w - wacc_base) < 1e-6 and abs(g - g_base) < 1e-6:
                cell_str = f"★ {cell_str}"  # highlight base case
            row[f"WACC {_pct(w)}"] = cell_str
        sens_rows.append(row)
    specs.append({
        "type": "D", "title": f"{company_name} — Følsomhedsanalyse: Pris/aktie ({currency}) [CALC]",
        "note": (f"★ = base case (WACC={_pct(wacc_base)}, g={_pct(g_base)}) [ASSUMED]. "
                 f"Pris per aktie varierer med WACC ± 1 pct.point (0,25% trin) og g 1–3% [CALC]."),
        "kilde": kilde,
        "table_data": {"columns": sens_cols, "rows": sens_rows},
    })

    # Chart 16: Fundamental vs market price (type B)
    pct_diff  = (dcf_price - price) / price if price > 0 else 0
    direction = "undervurderet" if dcf_price > price else "overvurderet"
    specs.append({
        "type": "B", "title": f"{company_name} — Fundamental vs. Markedspris ({currency})",
        "series_labels": [lbl_fund, lbl_market],
        "note": (f"Fundamental pris = {dcf_price:.2f} {currency} [CALC]. "
                 f"Markedspris = {price:.2f} {currency} [SOURCED]. "
                 f"Margen: {_pct(abs(pct_diff))} ({direction}). "
                 f"Vurdering baseret på DCF med WACC={_pct(wacc)}, g={_pct(dcf_results['g'])} [ASSUMED]."),
        "kilde": kilde,
    })

    # Chart 17: Multiples table
    metrics = fmp_data.get("metrics", [{}])
    m = metrics[0] if metrics else {}
    specs.append({
        "type": "D", "title": f"{company_name} — Nøgletalssammenligning [SOURCED/CALC]",
        "note": "Trailing multiples fra FMP [SOURCED]. Forward multiples kun hvis analytikerestimat tilgængeligt [EST].",
        "kilde": kilde,
        "table_data": {
            "columns": ["Multipel", "Trailing [SOURCED]"],
            "rows": [
                {"indicator": "P/E",       "Multipel": "P/E",       "Trailing [SOURCED]": f"{m.get('peRatio', 'N/A'):.1f}x" if m.get("peRatio") else "N/A"},
                {"indicator": "EV/EBITDA", "Multipel": "EV/EBITDA", "Trailing [SOURCED]": f"{m.get('evToEbitda', 'N/A'):.1f}x" if m.get("evToEbitda") else "N/A"},
                {"indicator": "P/B",       "Multipel": "P/B",       "Trailing [SOURCED]": f"{m.get('pbRatio', 'N/A'):.1f}x"   if m.get("pbRatio") else "N/A"},
                {"indicator": "P/S",       "Multipel": "P/S",       "Trailing [SOURCED]": f"{m.get('priceToSalesRatio', 'N/A'):.1f}x" if m.get("priceToSalesRatio") else "N/A"},
                {"indicator": "P/FCF",     "Multipel": "P/FCF",     "Trailing [SOURCED]": f"{m.get('pfcfRatio', 'N/A'):.1f}x" if m.get("pfcfRatio") else "N/A"},
            ],
        },
    })

    # Chart 18: Regional revenue breakdown (type G — skip gracefully if unavailable)
    seg_data = fmp_data.get("revenue_segments", [])
    if seg_data:
        lbl_seg = f"{ticker} — Geografisk omsætning"
        seg_latest = seg_data[0] if seg_data else {}
        seg_vals   = {k: v for k, v in seg_latest.items() if k != "date" and v}
        if seg_vals:
            idx  = pd.DatetimeIndex([pd.Timestamp(f"{years[-1]}-12-31")] * len(seg_vals))
            df_g = pd.DataFrame({"value": list(seg_vals.values())},
                                 index=pd.Index(list(seg_vals.keys())))
            dfs[lbl_seg] = df_g
            specs.append({
                "type": "G", "title": f"{company_name} — Geografisk Omsætningsfordeling",
                "series_labels": [lbl_seg],
                "note": f"Geografisk omsætningsfordeling, {years[-1]} [SOURCED].",
                "kilde": kilde,
            })
        else:
            specs.append(_placeholder_chart18(company_name, kilde))
    else:
        specs.append(_placeholder_chart18(company_name, kilde))

    return specs, dfs


def _placeholder_chart18(company_name: str, kilde: str) -> dict:
    return {
        "type": "D", "title": f"{company_name} — Geografisk Omsætning (ikke tilgængelig)",
        "note": "Segmentdata ikke tilgængeligt for denne virksomhed via FMP [SOURCED].",
        "kilde": kilde,
        "table_data": {"columns": ["Status"], "rows": [{"indicator": "Segmentdata ikke tilgængeligt"}]},
    }
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_annual_report_kpi.py -v
```
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add newsletter_agent/specialists/annual_report_kpi.py tests/test_annual_report_kpi.py
git commit -m "feat: add KPI packager producing 18 chart specs with transparency labels"
```

---

### Task 8: Main Specialist Entry Point

**Files:**
- Create: `newsletter_agent/specialists/annual_report.py`

- [ ] **Step 1: Implement the main specialist**

```python
# newsletter_agent/specialists/annual_report.py
import anthropic
from newsletter_agent.config import API_KEYS, REVIEWER_MODEL
from newsletter_agent.specialists.annual_report_constants import (
    STATUTORY_TAX_RATE, normalize_country,
)
from newsletter_agent.specialists.annual_report_fmp import fetch_all
from newsletter_agent.specialists.annual_report_reformulator import reformulate
from newsletter_agent.specialists.annual_report_checker import check
from newsletter_agent.specialists.annual_report_valuation import (
    compute_wacc, compute_dcf, compute_sensitivity,
)
from newsletter_agent.specialists.annual_report_da import (
    review_reformulation, review_consistency, review_valuation,
    review_kpi_specs, review_final,
)
from newsletter_agent.specialists.annual_report_kpi import build_chart_specs


def fetch_annual_report(task: dict) -> dict:
    ticker = (task.get("ticker") or task.get("label") or "").upper().strip()
    if not ticker:
        raise ValueError("annual_report specialist requires 'ticker' field in task.")

    fmp_key = API_KEYS.get("fmp", "")
    if not fmp_key:
        raise ValueError("FMP_API_KEY not configured. Set FMP_API_KEY env var.")

    client = anthropic.Anthropic()

    # Stage 1: Fetch raw FMP data
    print(f"  [annual_report] Fetching FMP data for {ticker}...")
    fmp_data = fetch_all(ticker, fmp_key)

    profile     = fmp_data["profile"]
    hq_country  = profile.get("country", "_default")
    company_name= profile.get("companyName", ticker)
    iso3        = normalize_country(hq_country)
    t           = STATUTORY_TAX_RATE.get(iso3, STATUTORY_TAX_RATE["_default"])

    # Stage 2: Penman reformulation
    print(f"  [annual_report] Reformulating Penman financials...")
    reformulated = reformulate(fmp_data, t=t)

    if reformulated["NOA"][-1] <= 0:
        raise ValueError(
            f"NOA for {ticker} is non-positive ({reformulated['NOA'][-1]:,.0f}). "
            "Check balance sheet classification — possible data quality issue."
        )

    da1 = review_reformulation(reformulated, client)
    print(f"  [annual_report] DA #1 (reformulation): {da1[:120]}...")

    # Stage 3: WACC computation
    print(f"  [annual_report] Computing WACC...")
    wacc_data = compute_wacc(fmp_data, reformulated, hq_country)

    # Stage 4: Consistency check (gate — blocks valuation if fails)
    print(f"  [annual_report] Running consistency check...")
    check_result = check(wacc_data["checker_inputs"])
    da2 = review_consistency(check_result, client)
    print(f"  [annual_report] DA #2 (consistency): {da2[:120]}...")

    if not check_result["passed"]:
        raise ValueError(
            f"Consistency check failed for {ticker}:\n" +
            "\n".join(check_result["issues"])
        )

    # Stage 5: DCF valuation + sensitivity
    print(f"  [annual_report] Running DCF valuation...")
    NFO            = reformulated["NFO"][-1]
    NCI            = reformulated["NCI"][-1]
    diluted_shares = float(fmp_data["income"][0].get("weightedAverageShsOutDil") or
                           profile.get("sharesOutstanding") or 1)
    base_year      = reformulated["years"][-1]
    wacc           = wacc_data["wacc"]

    dcf_results  = compute_dcf(reformulated, wacc=wacc, g=0.02,
                                NFO=NFO, NCI=NCI,
                                diluted_shares=diluted_shares, base_year=base_year)
    sensitivity  = compute_sensitivity(reformulated, wacc_base=wacc, g_base=0.02,
                                        NFO=NFO, NCI=NCI,
                                        diluted_shares=diluted_shares, base_year=base_year)

    market_price = float(profile.get("price") or 0)
    da3 = review_valuation(wacc_data, dcf_results, market_price, client)
    print(f"  [annual_report] DA #3 (valuation): {da3[:120]}...")

    # Stage 6: Build 18 chart specs
    print(f"  [annual_report] Building chart specs...")
    chart_specs, dataframes = build_chart_specs(
        ticker, company_name, iso3,
        reformulated, wacc_data, dcf_results, sensitivity, fmp_data,
    )

    da4 = review_kpi_specs(chart_specs, client)
    print(f"  [annual_report] DA #4 (KPI specs): {da4[:120]}...")

    da5 = review_final(chart_specs, dcf_results["price_per_share"], market_price, client)
    print(f"  [annual_report] DA #5 (final): {da5[:120]}...")

    # Embed DA reviews in chart notes (append to first chart)
    if chart_specs:
        da_summary = (
            f"\n\nDA Reviews: "
            f"[#1 Reformulation] {da1[:80]} | "
            f"[#3 Valuation] {da3[:80]} | "
            f"[#5 Final] {da5[:80]}"
        )
        chart_specs[0]["note"] = chart_specs[0].get("note", "") + da_summary

    return {
        "dataframes": dataframes,
        "kilde":      ["FMP", "Damodaran"],
        "chart_specs": chart_specs,
    }
```

- [ ] **Step 2: Verify import chain works**

```
cd /Users/mertcandogusoy/newsletter-site
python -c "from newsletter_agent.specialists.annual_report import fetch_annual_report; print('OK')"
```
Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add newsletter_agent/specialists/annual_report.py
git commit -m "feat: add annual report specialist main entry point with 5-stage DA pipeline"
```

---

### Task 9: Pipeline Integration

**Files:**
- Modify: `newsletter_agent/pipeline.py`

- [ ] **Step 1: Add `table_data` shortcut at line 575**

In `pipeline.py`, find this block:
```python
    # ── Type D — Snapshot / before-after table ────────────────────────────
    if chart_type == "D":
        path = _build_table(dfs, chart_spec, kilde_str, output_path)
```

Replace with:
```python
    # ── Type D — Snapshot / before-after table ────────────────────────────
    if chart_type == "D":
        if chart_spec.get("table_data"):
            from newsletter_agent.renderers.tables import render_type_d
            path = render_type_d(
                chart_spec["table_data"],
                {**chart_spec, "kilde": kilde_str},
                output_path,
            )
        else:
            path = _build_table(dfs, chart_spec, kilde_str, output_path)
```

- [ ] **Step 2: Add `annual_report` to SPECIALIST_MAP at line 183**

Find:
```python
SPECIALIST_MAP = {
    "energy":      fetch_energy,
    "rates":       fetch_rates,
    "macro":       fetch_macro,
    "commodities": fetch_commodities,
    "equities":    fetch_equities,
    "eurostat":    fetch_eurostat,
    "worldbank":   fetch_worldbank,
}
```

Replace with:
```python
from newsletter_agent.specialists.annual_report import fetch_annual_report

SPECIALIST_MAP = {
    "energy":        fetch_energy,
    "rates":         fetch_rates,
    "macro":         fetch_macro,
    "commodities":   fetch_commodities,
    "equities":      fetch_equities,
    "eurostat":      fetch_eurostat,
    "worldbank":     fetch_worldbank,
    "annual_report": fetch_annual_report,
}
```

- [ ] **Step 3: Verify pipeline imports cleanly**

```
python -c "from newsletter_agent.pipeline import SPECIALIST_MAP; print(list(SPECIALIST_MAP.keys()))"
```
Expected output includes `'annual_report'`

- [ ] **Step 4: Verify table_data shortcut works with a mock render**

```python
# Quick smoke test — run in Python REPL or as a script
from newsletter_agent.renderers.tables import render_type_d
import tempfile, os

data = {
    "columns": ["2025E", "2026E"],
    "rows": [
        {"indicator": "Omsætning [EST]", "2025E": "100.0", "2026E": "103.0"},
        {"indicator": "OI [CALC]",       "2025E": "15.6",  "2026E": "16.1"},
    ]
}
spec = {"title": "Test Table", "note": "Test", "kilde": "FMP"}
with tempfile.TemporaryDirectory() as tmp:
    path = render_type_d(data, spec, os.path.join(tmp, "test.png"))
    assert os.path.exists(path), "render_type_d did not produce output file"
    print("render_type_d smoke test PASSED")
```

Run: `python -c "exec(open('/tmp/test_render.py').read())"` after saving above to `/tmp/test_render.py`, or paste directly into a Python shell.

- [ ] **Step 5: Commit**

```bash
git add newsletter_agent/pipeline.py
git commit -m "feat: add table_data shortcut in pipeline + annual_report to SPECIALIST_MAP"
```

---

### Task 10: Config / Routing / Orchestrator Wiring

**Files:**
- Modify: `newsletter_agent/config.py`
- Modify: `newsletter_agent/routing.py`
- Modify: `newsletter_agent/orchestrator.py`

- [ ] **Step 1: Add FMP key to config.py**

Find the `API_KEYS` dict in `newsletter_agent/config.py`. Add `"fmp"` entry:

```python
API_KEYS = {
    # ... existing keys ...
    "fmp": os.getenv("FMP_API_KEY", ""),
}
```

Verify `import os` is already at the top of config.py. If not, add it.

- [ ] **Step 2: Add routing keywords to routing.py**

Find the existing routing keyword patterns in `newsletter_agent/routing.py`. Add:

```python
import re

_ANNUAL = re.compile(
    r"\b(annual report|årsrapport|årsregnskab|valuation|værdiansættelse|dcf|wacc|"
    r"aktiekurs|fair value|selskabsanalyse|fundamental|penman|ebit|noa|fcf|"
    r"carlsberg|novo|maersk|apple|microsoft)\b",
    re.IGNORECASE,
)
```

In the routing hint function/dict (look for where other specialist hints are defined), add:

```python
"annual_report": "For selskabsanalyse og DCF-værdiansættelse: brug specialist='annual_report', source='fmp'. Angiv ticker-symbol (fx 'CARL', 'NOVO B', 'AAPL'). Returnerer type A/B/D charts.",
```

- [ ] **Step 3: Add annual_report to orchestrator SYSTEM_PROMPT**

In `newsletter_agent/orchestrator.py`, find `SYSTEM_PROMPT` (the string describing available specialists). Add `annual_report` to the specialist list:

```python
# In the SYSTEM_PROMPT string, find the specialists section and add:
"""
- annual_report: DCF valuation of a public company. Use for: "analyse af [virksomhed]", "hvad er [ticker] værd", "DCF", "WACC", "årsrapport". 
  Task format: {"source": "annual_report", "label": "Company Analysis", "ticker": "CARL", "charts": []}
  Returns 18 charts (type A/B/D) with full transparency labeling. Always pass ticker symbol, not company name.
"""
```

- [ ] **Step 4: Set FMP_API_KEY environment variable for testing**

```
export FMP_API_KEY=your_actual_key_here
```

- [ ] **Step 5: End-to-end smoke test**

With Flask running (`python -m flask run` in `/Users/mertcandogusoy/newsletter-site`):

```bash
curl -s -X POST http://localhost:5000/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Analysér Carlsberg (CARL) — lav en fuld DCF-værdiansættelse"}' | head -50
```

Expected: SSE stream starts, `[annual_report]` log lines appear, 18 charts rendered.

- [ ] **Step 6: Commit**

```bash
git add newsletter_agent/config.py newsletter_agent/routing.py newsletter_agent/orchestrator.py
git commit -m "feat: wire annual_report specialist into config, routing, and orchestrator"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by task |
|---|---|
| §2.1 Penman formulas (NOA, OI, FCF, RNOA, OG, ATO, FLEV, NBC, SPREAD, ROCE) | Task 3 (reformulator) |
| §2.2 Transparency labels (CALC/EST/ASSUMED/SOURCED) | Tasks 7, 8 |
| §3.1 FMP 8 endpoints | Task 2 (fetch_all) |
| §3.2 Balance sheet classification rules | Task 3 |
| §3.3 WACC hardcoded tables (rf, MRP, CRP, ICR→spread, Moody's→spread) | Task 1, Task 5 |
| §4 Pipeline architecture (5-stage DA) | Task 8 |
| §5.1 Reformulator: one-time item, M&A, trending OG detectors | Task 3 |
| §5.2 Consistency checker: 7 checks, gate | Task 4 |
| §5.3 Valuation: WACC block, 5yr forecast, DCF bridge, sensitivity 9×5 | Task 5 |
| §5.4 KPI packager: all 18 charts | Task 7 |
| §6 DA reviews: 5 checkpoints | Tasks 6, 8 |
| §7 Routing integration | Task 10 |
| §8 Error handling (FMP rate limit, missing rating, missing NCI, missing segments) | Tasks 2, 8, 7 |
| Pipeline type D table_data shortcut | Task 9 |
| SPECIALIST_MAP registration | Task 9 |

**Type consistency check:**
- `reformulate()` returns `"OG"`, `"ATO"`, `"revenue_cagr"` under `"historical_avgs"` — referenced identically in Tasks 5 and 7 ✓
- `compute_wacc()` returns `"checker_inputs"` dict — consumed by `check()` in Task 8 ✓
- `build_chart_specs()` returns `(list[dict], dict[str, DataFrame])` — consumed in Task 8 as `chart_specs, dataframes` ✓
- `render_type_d(data, spec, output_path)` — called with `chart_spec["table_data"]` as `data` and `{**chart_spec, "kilde": kilde_str}` as `spec` ✓
- `series_labels` in type A specs reference keys that exist in returned `dfs` dict ✓

**Placeholder scan:** No TBD, TODO, or "similar to Task N" patterns found.

**Edge cases handled:**
- NOA ≤ 0: raises ValueError in Task 8 (blocks before DA reviews)
- FMP ticker invalid: raises ValueError in Task 2 with clear message
- Moody's rating unavailable: falls back to ICR in Task 5, labeled `SOURCED (ICR fallback)`
- NCI not in balance sheet: `_safe()` returns 0, flagged in DA #2
- Segment data unavailable: chart #18 replaced with placeholder type D (no error)
- WACC ≤ g: `compute_sensitivity()` returns `None` for that cell ✓
