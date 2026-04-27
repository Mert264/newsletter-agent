from typing import Union
import requests

_BASE = "https://financialmodelingprep.com/api/v3"


def _get(path: str, api_key: str, **params) -> Union[list, dict]:
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
        "income":    income,
        "balance":   balance,
        "cashflow":  cashflow,
        "profile":   profile_dict,
        "rating":    rating if isinstance(rating, list) else [],
        "metrics":   metrics if isinstance(metrics, list) else [],
        "estimates": estimates if isinstance(estimates, list) else [],
    }
