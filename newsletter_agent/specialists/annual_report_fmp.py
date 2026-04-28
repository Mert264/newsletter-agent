from typing import Union
import time
import requests

_BASE = "https://financialmodelingprep.com/stable"
_MAX_RETRIES = 3


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


def _normalize_metrics(m: dict) -> dict:
    """Map stable API key-metric field names to the names the rest of the codebase expects."""
    result = dict(m)
    # PE ratio: new API exposes earningsYield = 1/PE
    ey = m.get("earningsYield")
    if ey and ey != 0:
        result.setdefault("peRatio", 1.0 / ey)
    # EV/EBITDA: capitalization changed
    if "evToEBITDA" in m:
        result.setdefault("evToEbitda", m["evToEBITDA"])
    # P/FCF: approximate via EV/FCF
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

    if isinstance(income, dict) and "Error Message" in income:
        raise ValueError(f"FMP income statement error for '{ticker}': {income['Error Message']}")
    if not income:
        raise ValueError(f"No income statement data for ticker '{ticker}' — check ticker symbol or FMP subscription.")
    if isinstance(balance, dict) and "Error Message" in balance:
        raise ValueError(f"FMP balance sheet error for '{ticker}': {balance['Error Message']}")
    if not balance:
        raise ValueError(f"No balance sheet data for ticker '{ticker}'.")

    # Profile: stable API returns a list; also normalize field names
    profile_dict = profile[0] if isinstance(profile, list) and profile else (profile or {})
    profile_dict = dict(profile_dict)
    profile_dict.setdefault("mktCap", profile_dict.get("marketCap", 0))
    profile_dict.setdefault("sharesOutstanding", income[0].get("weightedAverageShsOut"))

    # Balance: stable API omits minorityInterest — derive it
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
