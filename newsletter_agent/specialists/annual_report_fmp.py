from typing import Union
import time
import requests

_BASE = "https://financialmodelingprep.com/stable"
_MAX_RETRIES = 3

_NO_SCALE_INCOME = {"eps", "epsDiluted"}

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
        result["evToFCF"] = m["evToFreeCashFlow"]
    return result


_ESTIMATE_MONETARY_FIELDS = {
    # v3 API names
    "estimatedRevenueLow", "estimatedRevenueAvg", "estimatedRevenueHigh",
    "estimatedEpsLow", "estimatedEpsAvg", "estimatedEpsHigh",
    "estimatedNetIncomeLow", "estimatedNetIncomeAvg", "estimatedNetIncomeHigh",
    "estimatedEbitdaLow", "estimatedEbitdaAvg", "estimatedEbitdaHigh",
    "estimatedEbitLow", "estimatedEbitAvg", "estimatedEbitHigh",
    # stable API names (no "estimated" prefix)
    "revenueLow", "revenueAvg", "revenueHigh",
    "netIncomeLow", "netIncomeAvg", "netIncomeHigh",
    "ebitdaLow", "ebitdaAvg", "ebitdaHigh",
    "ebitLow", "ebitAvg", "ebitHigh",
    "sgaExpenseLow", "sgaExpenseAvg", "sgaExpenseHigh",
}


def _normalize_estimates(e: dict) -> dict:
    """Scale monetary estimate fields to millions; alias stable→v3 field names."""
    result = {}
    for k, v in e.items():
        if k in _ESTIMATE_MONETARY_FIELDS and isinstance(v, (int, float)):
            result[k] = v / 1_000_000
        else:
            result[k] = v
    # Alias stable API names → v3 names expected by _analyst_next_rev
    for prefix in ("revenue", "netIncome", "ebitda", "ebit"):
        for suffix in ("Low", "Avg", "High"):
            stable_k = f"{prefix}{suffix}"
            v3_k = f"estimated{prefix[0].upper()}{prefix[1:]}{suffix}"
            if stable_k in result and v3_k not in result:
                result[v3_k] = result[stable_k]
    # Also alias estimatedRevenue → estimatedRevenueAvg (some endpoints)
    if "estimatedRevenue" in result and "estimatedRevenueAvg" not in result:
        result["estimatedRevenueAvg"] = result["estimatedRevenue"]
    return result


def fetch_peer_comparison(ticker: str, api_key: str) -> dict:
    """Fetch TTM valuation multiples for the target ticker and up to 5 peers.

    Returns a dict with key 'companies', each entry having:
        ticker, name, pe, ev_ebitda, pb, ev_fcf, roe
    Returns empty dict on any failure.
    """
    try:
        # 1. Peer tickers — v3 endpoint (not on stable base)
        peers_url = f"https://financialmodelingprep.com/api/v3/stock_peers/{ticker}"
        peers_resp = requests.get(peers_url, params={"apikey": api_key}, timeout=15)
        peers_resp.raise_for_status()
        peers_data = peers_resp.json()
        raw_peers = []
        if isinstance(peers_data, list) and peers_data:
            raw_peers = peers_data[0].get("peersList", []) or []
        elif isinstance(peers_data, dict):
            raw_peers = peers_data.get("peersList", []) or []
        peer_tickers = raw_peers[:5]

        all_tickers = [ticker] + peer_tickers

        companies = []
        for t in all_tickers:
            try:
                # key-metrics-ttm — v3 endpoint
                km_url = f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{t}"
                km_resp = requests.get(km_url, params={"apikey": api_key}, timeout=15)
                km_resp.raise_for_status()
                km_data = km_resp.json()
                km = km_data[0] if isinstance(km_data, list) and km_data else {}

                # ratios-ttm — v3 endpoint
                rt_url = f"https://financialmodelingprep.com/api/v3/ratios-ttm/{t}"
                rt_resp = requests.get(rt_url, params={"apikey": api_key}, timeout=15)
                rt_resp.raise_for_status()
                rt_data = rt_resp.json()
                rt = rt_data[0] if isinstance(rt_data, list) and rt_data else {}

                # Company name from profile (best-effort)
                try:
                    prof_url = f"https://financialmodelingprep.com/stable/profile"
                    prof_resp = requests.get(prof_url, params={"apikey": api_key, "symbol": t}, timeout=10)
                    prof_resp.raise_for_status()
                    prof_data = prof_resp.json()
                    prof = prof_data[0] if isinstance(prof_data, list) and prof_data else {}
                    name = prof.get("companyName") or t
                except Exception:
                    name = t

                # Extract multiples — try both camelCase variants used across FMP responses
                pe      = km.get("peRatioTTM")       or rt.get("peRatioTTM")
                ev_eb   = km.get("evToEBITDATTM")    or km.get("enterpriseValueOverEBITDATTM") or rt.get("evToEbitdaTTM")
                pb      = km.get("pbRatioTTM")        or rt.get("priceToBookRatioTTM")
                ev_fcf  = km.get("evToFreeCashFlowTTM") or rt.get("evToFreeCashFlowTTM")
                roe     = km.get("roeTTM")             or rt.get("returnOnEquityTTM")

                companies.append({
                    "ticker":    t,
                    "name":      name,
                    "pe":        pe,
                    "ev_ebitda": ev_eb,
                    "pb":        pb,
                    "ev_fcf":    ev_fcf,
                    "roe":       roe,
                    "is_target": t == ticker,
                })
            except Exception:
                # Skip individual ticker failures silently
                continue

        if not companies:
            return {}
        return {"companies": companies}

    except Exception:
        return {}


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
        "income":        income,
        "balance":       balance,
        "cashflow":      cashflow,
        "profile":       profile_dict,
        "rating":        rating if isinstance(rating, list) else [],
        "metrics":       [_normalize_metrics(m) for m in metrics] if isinstance(metrics, list) else [],
        "estimates":     [_normalize_estimates(e) for e in estimates] if isinstance(estimates, list) else [],
        "ltm_income":    ltm_income,
        "ltm_cashflow":  ltm_cashflow,
        "ltm_balance":   ltm_balance,
    }
