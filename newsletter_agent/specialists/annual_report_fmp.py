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


# Sector-based peer candidates used when FMP peer endpoint is unavailable
_SECTOR_PEERS: dict = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "ORCL", "ADBE", "CRM"],
    "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "T", "VZ", "CMCSA"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW"],
    "Consumer Defensive": ["WMT", "COST", "PG", "KO", "PEP", "CL", "MDLZ", "GIS"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "ABT", "LLY"],
    "Financials": ["BRK-B", "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP"],
    "Industrials": ["HON", "UPS", "CAT", "DE", "MMM", "GE", "RTX", "LMT"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "PXD", "MPC", "VLO"],
    "Basic Materials": ["LIN", "APD", "ECL", "DD", "NEM", "FCX", "ALB", "CE"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA", "O", "DLR", "WELL"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL"],
}


def fetch_peer_comparison(ticker: str, api_key: str = "", peers: list = None) -> dict:
    """Fetch TTM valuation multiples for the target ticker and up to 5 peers.

    Uses yfinance — no FMP subscription required. If `peers` is provided those
    tickers are used directly; otherwise sector-based candidates are derived
    from the target ticker's sector.

    Returns a dict with key 'companies', each entry having:
        ticker, name, pe, ev_ebitda, pb, ev_fcf, roe
    Returns empty dict on any failure.
    """
    try:
        import yfinance as yf
        from newsletter_agent.config import YF_LOCK

        # 1. Determine peer tickers
        if peers is not None:
            peer_tickers = [t for t in peers if t != ticker][:5]
        else:
            try:
                with YF_LOCK:
                    target_info = yf.Ticker(ticker).info
                sector = target_info.get("sector", "")
            except Exception:
                sector = ""
            candidates = _SECTOR_PEERS.get(sector, [])
            peer_tickers = [t for t in candidates if t != ticker][:5]

        all_tickers = [ticker] + peer_tickers

        companies = []
        for t in all_tickers:
            try:
                with YF_LOCK:
                    info = yf.Ticker(t).info
                if not info:
                    continue

                name    = info.get("shortName") or info.get("longName") or t
                pe      = info.get("trailingPE")
                ev_eb   = info.get("enterpriseToEbitda")
                pb      = info.get("priceToBook")
                ev_fcf  = None  # yfinance does not expose EV/FCF directly
                roe     = info.get("returnOnEquity")
                # returnOnEquity in yfinance is a decimal (e.g. 0.35 = 35%)
                if roe is not None:
                    roe = roe * 100

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


_YF_INCOME_MAP = {
    "Total Revenue": "revenue",
    "Operating Income": "operatingIncome",
    "Net Income": "netIncome",
    "Net Income Common Stockholders": "netIncome",
    "Interest Expense": "interestExpense",
    "Gross Profit": "grossProfit",
    "EBITDA": "ebitda",
    "EBIT": "ebit",
    "Diluted Average Shares": "weightedAverageShsOutDil",
    "Basic Average Shares": "weightedAverageShsOut",
    "Diluted EPS": "epsDiluted",
    "Basic EPS": "eps",
    "Reconciled Depreciation": "depreciationAndAmortization",
    "Tax Provision": "incomeTaxExpense",
    "Pretax Income": "incomeBeforeTax",
    "Cost Of Revenue": "costOfRevenue",
    "Total Expenses": "totalExpenses",
}
_YF_BALANCE_MAP = {
    "Cash And Cash Equivalents": "cashAndCashEquivalents",
    "Other Short Term Investments": "shortTermInvestments",
    "Long Term Equity Investment": "longTermInvestments",
    "Current Debt": "shortTermDebt",
    "Long Term Debt": "longTermDebt",
    "Capital Lease Obligations": "capitalLeaseObligations",
    "Total Assets": "totalAssets",
    "Total Liabilities Net Minority Interest": "totalLiabilities",
    "Stockholders Equity": "totalStockholdersEquity",
    "Total Equity Gross Minority Interest": "totalEquity",
    "Goodwill And Other Intangible Assets": "goodwillAndIntangibleAssets",
    "Goodwill": "goodwill",
    "Common Stock Equity": "commonStockEquity",
    "Retained Earnings": "retainedEarnings",
    "Total Debt": "totalDebt",
    "Net Debt": "netDebt",
    "Invested Capital": "investedCapital",
    "Current Assets": "totalCurrentAssets",
    "Current Liabilities": "totalCurrentLiabilities",
    "Inventory": "inventory",
    "Accounts Receivable": "netReceivables",
    "Accounts Payable": "accountPayables",
    "Net PPE": "propertyPlantEquipmentNet",
}
_YF_CASHFLOW_MAP = {
    "Operating Cash Flow": "operatingCashFlow",
    "Capital Expenditure": "capitalExpenditure",
    "Free Cash Flow": "freeCashFlow",
    "Depreciation And Amortization": "depreciationAndAmortization",
    "Change In Working Capital": "changeInWorkingCapital",
    "Repurchase Of Capital Stock": "commonStockRepurchased",
    "Cash Dividends Paid": "dividendsPaid",
    "Stock Based Compensation": "stockBasedCompensation",
    "Deferred Income Tax": "deferredIncomeTax",
}


def _yf_df_to_fmp_rows(df, field_map: dict, scale: float = 1e-6,
                        no_scale: set = frozenset()) -> list[dict]:
    """Convert a yfinance DataFrame (fields×years) into FMP-style list of dicts (newest first)."""
    if df is None or df.empty:
        return []
    rows = []
    for col in df.columns:
        row = {"date": col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)}
        for yf_name, fmp_name in field_map.items():
            val = df.at[yf_name, col] if yf_name in df.index else None
            if val is not None and not (isinstance(val, float) and val != val):
                if fmp_name in no_scale:
                    row[fmp_name] = float(val)
                else:
                    row[fmp_name] = float(val) * scale
            else:
                row[fmp_name] = 0
        rows.append(row)
    return rows


def _yf_fetch_all(ticker: str) -> dict:
    """Fallback: build the same dict structure as fetch_all() using yfinance."""
    import yfinance as yf
    from newsletter_agent.config import YF_LOCK

    with YF_LOCK:
        t = yf.Ticker(ticker)
        info = t.info or {}
        fin_a = t.financials
        bs_a = t.balance_sheet
        cf_a = t.cashflow
        fin_q = t.quarterly_financials
        bs_q = t.quarterly_balance_sheet
        cf_q = t.quarterly_cashflow

    no_scale_income = {"eps", "epsDiluted"}
    income = _yf_df_to_fmp_rows(fin_a, _YF_INCOME_MAP, no_scale=no_scale_income)
    balance = _yf_df_to_fmp_rows(bs_a, _YF_BALANCE_MAP)
    cashflow = _yf_df_to_fmp_rows(cf_a, _YF_CASHFLOW_MAP)

    if not income:
        raise ValueError(f"No financial data from yfinance for '{ticker}'.")

    income_q = _yf_df_to_fmp_rows(fin_q, _YF_INCOME_MAP, no_scale=no_scale_income)
    cashflow_q = _yf_df_to_fmp_rows(cf_q, _YF_CASHFLOW_MAP)
    balance_q = _yf_df_to_fmp_rows(bs_q, _YF_BALANCE_MAP)

    ltm_income = _compute_ltm(income_q, _LTM_INCOME_FIELDS)
    ltm_cashflow = _compute_ltm(cashflow_q, _LTM_CASHFLOW_FIELDS)
    ltm_balance = balance_q[0] if balance_q else {}

    mkt_cap_raw = info.get("marketCap", 0) or 0
    shares_out = info.get("sharesOutstanding", 0) or 0
    implied_shares = info.get("impliedSharesOutstanding", 0) or 0
    diluted_shares = implied_shares if implied_shares > shares_out else shares_out * 1.02
    profile_dict = {
        "companyName": info.get("shortName") or info.get("longName") or ticker,
        "country": info.get("country", ""),
        "currency": info.get("currency", "USD"),
        "marketCap": mkt_cap_raw / 1_000_000,
        "mktCap": mkt_cap_raw / 1_000_000,
        "beta": info.get("beta", 1.0),
        "price": info.get("currentPrice") or info.get("regularMarketPrice") or 0,
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "sharesOutstanding": diluted_shares / 1_000_000,
    }

    for b in balance:
        if "minorityInterest" not in b:
            b["minorityInterest"] = (
                (b.get("totalEquity") or 0) - (b.get("totalStockholdersEquity") or 0)
            )

    return {
        "income": income,
        "balance": balance,
        "cashflow": cashflow,
        "profile": profile_dict,
        "rating": [],
        "metrics": [],
        "estimates": [],
        "ltm_income": ltm_income,
        "ltm_cashflow": ltm_cashflow,
        "ltm_balance": ltm_balance,
        "_source": "yfinance",
    }


def fetch_all(ticker: str, api_key: str) -> dict:
    try:
        income = _get("income-statement", api_key, symbol=ticker, period="annual")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (402, 403):
            print(f"  [annual_report] FMP returned {e.response.status_code} for {ticker} — falling back to yfinance")
            return _yf_fetch_all(ticker)
        raise

    try:
        balance = _get("balance-sheet-statement", api_key, symbol=ticker, period="annual")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (402, 403):
            print(f"  [annual_report] FMP balance-sheet {e.response.status_code} for {ticker} — falling back to yfinance")
            return _yf_fetch_all(ticker)
        raise
    try:
        cashflow = _get("cash-flow-statement", api_key, symbol=ticker, period="annual")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (402, 403):
            print(f"  [annual_report] FMP cashflow {e.response.status_code} for {ticker} — falling back to yfinance")
            return _yf_fetch_all(ticker)
        raise
    try:
        profile = _get("profile", api_key, symbol=ticker)
    except requests.HTTPError:
        print(f"  [annual_report] FMP profile failed for {ticker} — falling back to yfinance")
        return _yf_fetch_all(ticker)
    try:
        rating = _get("ratings-snapshot", api_key, symbol=ticker)
    except requests.HTTPError:
        rating = []
    try:
        metrics = _get("key-metrics", api_key, symbol=ticker, period="annual")
    except requests.HTTPError:
        metrics = []
    try:
        estimates = _get("analyst-estimates", api_key, symbol=ticker, period="annual")
    except requests.HTTPError:
        estimates = []

    income_q   = _get("income-statement",        api_key, symbol=ticker, period="quarter", limit=5)
    cashflow_q = _get("cash-flow-statement",     api_key, symbol=ticker, period="quarter", limit=5)
    balance_q  = _get("balance-sheet-statement", api_key, symbol=ticker, period="quarter", limit=2)

    if isinstance(income, dict) and "Error Message" in income:
        raise ValueError(f"FMP income statement error for '{ticker}': {income['Error Message']}")
    if not income:
        print(f"  [annual_report] FMP returned empty data for {ticker} — falling back to yfinance")
        return _yf_fetch_all(ticker)
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
