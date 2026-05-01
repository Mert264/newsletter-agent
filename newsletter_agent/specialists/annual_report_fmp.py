from typing import Union
import time
import requests

_BASE = "https://financialmodelingprep.com/stable"
_MAX_RETRIES = 3

_NO_SCALE_INCOME = {"eps", "epsDiluted"}

_LTM_INCOME_FIELDS = [
    "revenue", "operatingIncome", "netIncome", "interestExpense",
    "weightedAverageShsOutDil", "weightedAverageShsOut",
]
_LTM_CASHFLOW_FIELDS = [
    "operatingCashFlow", "capitalExpenditure", "freeCashFlow",
    "commonStockRepurchased", "dividendsPaid",
]


def _compute_ltm(quarterly_rows: list, fields: list) -> dict:
    """Sum the most recent 4 quarterly rows (newest-first) for flow-statement fields."""
    last4 = quarterly_rows[:4]
    if not last4:
        return {}
    ltm = {"date": last4[0].get("date", "")}
    for field in fields:
        ltm[field] = sum((r.get(field) or 0) for r in last4)
    return ltm


def _get(path: str, api_key: str, **params) -> Union[list, dict]:
    params["apikey"] = api_key
    url = f"{_BASE}/{path}"
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == _MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)
        except requests.HTTPError:
            if resp.status_code == 429 and attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def _scale(row: dict, no_scale: set = frozenset()) -> dict:
    """Divide all numeric fields by 1,000,000 to convert raw dollars → millions."""
    return {
        k: (v / 1_000_000 if isinstance(v, (int, float)) and k not in no_scale else v)
        for k, v in row.items()
    }


def _normalize_metrics(m: dict) -> dict:
    """Map stable API key-metric field names to the names the rest of the codebase expects."""
    result = dict(m)
    ey = m.get("earningsYield")
    if ey and ey != 0:
        result.setdefault("peRatio", 1.0 / ey)
    if "evToEBITDA" in m:
        result.setdefault("evToEbitda", m["evToEBITDA"])
    if "evToFreeCashFlow" in m:
        result.setdefault("pfcfRatio", m["evToFreeCashFlow"])
    return result


def fetch_all(ticker: str, api_key: str) -> dict:
    income    = _get("income-statement",        api_key, symbol=ticker, period="annual")
    balance   = _get("balance-sheet-statement", api_key, symbol=ticker, period="annual")
    cashflow  = _get("cash-flow-statement",     api_key, symbol=ticker, period="annual")
    profile   = _get("profile",                 api_key, symbol=ticker)
    rating    = _get("ratings-snapshot",        api_key, symbol=ticker)
    metrics   = _get("key-metrics",             api_key, symbol=ticker, period="annual")
    estimates = _get("analyst-estimates",       api_key, symbol=ticker, period="annual")

    # Quarterly data for LTM (Last Twelve Months) computation
    income_q   = _get("income-statement",        api_key, symbol=ticker, period="quarter", limit=5)
    cashflow_q = _get("cash-flow-statement",     api_key, symbol=ticker, period="quarter", limit=5)
    balance_q  = _get("balance-sheet-statement", api_key, symbol=ticker, period="quarter", limit=2)

    if isinstance(income, dict) and "Error Message" in income:
        raise ValueError(f"FMP income statement error for '{ticker}': {income['Error Message']}")
    if not income:
        raise ValueError(f"No income statement data for ticker '{ticker}' — check ticker symbol or FMP subscription.")
    if isinstance(balance, dict) and "Error Message" in balance:
        raise ValueError(f"FMP balance sheet error for '{ticker}': {balance['Error Message']}")
    if not balance:
        raise ValueError(f"No balance sheet data for ticker '{ticker}'.")

    # Scale annual statements
    income   = [_scale(r, no_scale=_NO_SCALE_INCOME) for r in income]
    balance  = [_scale(r) for r in balance]
    cashflow = [_scale(r) for r in cashflow]

    # Scale quarterly statements (guard against non-list responses)
    income_q   = [_scale(r, no_scale=_NO_SCALE_INCOME) for r in income_q]   if isinstance(income_q,   list) else []
    cashflow_q = [_scale(r) for r in cashflow_q]  if isinstance(cashflow_q, list) else []
    balance_q  = [_scale(r) for r in balance_q]   if isinstance(balance_q,  list) else []

    ltm_income   = _compute_ltm(income_q,   _LTM_INCOME_FIELDS)
    ltm_cashflow = _compute_ltm(cashflow_q, _LTM_CASHFLOW_FIELDS)
    ltm_balance  = balance_q[0] if balance_q else {}

    # Profile: stable API returns a list; normalize field names; scale monetary fields
    profile_dict = profile[0] if isinstance(profile, list) and profile else (profile or {})
    profile_dict = dict(profile_dict)
    mkt_cap_raw = profile_dict.get("marketCap", 0) or 0
    profile_dict["marketCap"]       = mkt_cap_raw / 1_000_000
    profile_dict["mktCap"]          = profile_dict["marketCap"]
    profile_dict["sharesOutstanding"] = income[0].get("weightedAverageShsOut")  # already scaled

    # Balance: stable API omits minorityInterest — derive it (already scaled)
    for b in balance:
        if "minorityInterest" not in b:
            b["minorityInterest"] = (
                (b.get("totalEquity") or 0) - (b.get("totalStockholdersEquity") or 0)
            )

    return {
        "income":    income,
        "balance":   balance,
        "cashflow":  cashflow,
        "profile":   profile_dict,
        "rating":    rating if isinstance(rating, list) else [],
        "metrics":   [_normalize_metrics(m) for m in metrics] if isinstance(metrics, list) else [],
        "estimates": estimates if isinstance(estimates, list) else [],
    }
