"""
Magnificent 7 comparison specialist.

Produces two outputs for any Mag 7 / Big Tech / FAANG request:
  1. Price performance line chart (type A) — all 7 indexed to 100 from start date.
  2. Valuation & fundamentals comparison table (type D).

Cache: 4 hours (intraday data changes; heavier than macro but lighter than tick data).
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import yfinance as yf

from newsletter_agent.config import YF_LOCK
from newsletter_agent.cache import get as cache_get, put as cache_put

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAG7: dict[str, str] = {
    "Apple":     "AAPL",
    "Microsoft": "MSFT",
    "Alphabet":  "GOOGL",
    "Amazon":    "AMZN",
    "NVIDIA":    "NVDA",
    "Meta":      "META",
    "Tesla":     "TSLA",
}

_TTL = 4 * 3600          # 4-hour cache
_MAX_WORKERS = 7         # one thread per company

# ---------------------------------------------------------------------------
# Price history (yfinance)
# ---------------------------------------------------------------------------

def _fetch_price_history(name: str, ticker: str, period_days: int) -> tuple[str, Optional[pd.DataFrame]]:
    """Download Close prices for one ticker; returns (name, DataFrame or None)."""
    cache_key = f"mag7_price_{ticker}_{period_days}"
    cached = cache_get("mag7", _TTL, ticker=ticker, period_days=period_days, kind="price")
    if cached is not None:
        try:
            df = pd.DataFrame(cached)
            df.index = pd.DatetimeIndex(df.index)
            print(f"    [mag7] Cache hit price: {ticker}")
            return name, df
        except Exception:
            pass

    end = date.today()
    start = end - timedelta(days=period_days)
    try:
        with YF_LOCK:
            raw = yf.download(ticker, start=str(start), end=str(end),
                              progress=False, auto_adjust=True)
        if raw.empty:
            print(f"    [mag7] No price data for {ticker}")
            return name, None

        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
        else:
            close = raw["Close"]

        df = close.to_frame(name=name)
        df.index = pd.DatetimeIndex(df.index)

        # Cache as records (index → value)
        cache_put("mag7", {i.isoformat(): float(v) for i, v in df[name].items()},
                  ticker=ticker, period_days=period_days, kind="price")
        return name, df
    except Exception as e:
        print(f"    [mag7] Price fetch error {ticker}: {e}")
        return name, None


def _build_price_chart(period_days: int) -> tuple[dict[str, pd.DataFrame], list[str], dict]:
    """Fetch prices for all 7, index to 100, return (dataframes, kilde, chart_spec)."""
    dataframes: dict[str, pd.DataFrame] = {}

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_price_history, name, ticker, period_days): name
            for name, ticker in MAG7.items()
        }
        for fut in as_completed(futures):
            name, df = fut.result()
            if df is not None:
                dataframes[name] = df

    if not dataframes:
        return {}, [], {}

    # Index all series to 100 from common start date
    indexed: dict[str, pd.DataFrame] = {}
    for name, df in dataframes.items():
        series = df[name].dropna()
        if series.empty:
            continue
        base = series.iloc[0]
        if base == 0:
            continue
        indexed_series = (series / base) * 100
        indexed[name] = indexed_series.to_frame(name=name)

    years = round(period_days / 365, 1)
    chart_spec = {
        "type": "A",
        "title": f"Magnificent 7 — Kursudvikling ({years}Y, indekseret 100)",
        "x_label": "Dato",
        "y_label": "Indekseret kurs (basis = 100)",
        "period_days": period_days,
        "series_labels": list(indexed.keys()),
        "note": "Alle kurser indekseret til 100 ved startdato. Kilde: Yahoo Finance.",
    }

    return indexed, ["Yahoo Finance"], chart_spec


# ---------------------------------------------------------------------------
# FMP fundamentals
# ---------------------------------------------------------------------------

def _safe_float(val, default: float = float("nan")) -> float:
    try:
        return float(val) if val not in (None, "", "None") else default
    except (TypeError, ValueError):
        return default


def _fmt_market_cap(val: float) -> str:
    if np.isnan(val):
        return "N/A"
    if val >= 1e12:
        return f"${val/1e12:.1f}T"
    if val >= 1e9:
        return f"${val/1e9:.1f}B"
    return f"${val/1e6:.1f}M"


def _fmt_pct(val: float, decimals: int = 1) -> str:
    return "N/A" if np.isnan(val) else f"{val * 100:.{decimals}f}%"


def _fmt_x(val: float, decimals: int = 1) -> str:
    return "N/A" if np.isnan(val) else f"{val:.{decimals}f}x"


def _fetch_yf_metrics(name: str, ticker: str) -> tuple[str, Optional[dict]]:
    """Fetch fundamentals for one ticker via yfinance ticker.info."""
    cache_key_kwargs = dict(ticker=ticker, kind="yf_info")
    cached = cache_get("mag7", _TTL, **cache_key_kwargs)
    if cached is not None:
        try:
            print(f"    [mag7] Cache hit yf_info: {ticker}")
            return name, cached
        except Exception:
            pass

    try:
        with YF_LOCK:
            info = yf.Ticker(ticker).info

        market_cap = _safe_float(info.get("marketCap"))
        fcf        = _safe_float(info.get("freeCashflow"))

        # P/FCF = marketCap / freeCashflow
        if not np.isnan(market_cap) and not np.isnan(fcf) and fcf != 0:
            p_fcf = market_cap / fcf
        else:
            p_fcf = float("nan")

        # FCF Yield = freeCashflow / marketCap
        if not np.isnan(fcf) and not np.isnan(market_cap) and market_cap != 0:
            fcf_yield = fcf / market_cap
        else:
            fcf_yield = float("nan")

        result = {
            "market_cap":   market_cap,
            "pe":           _safe_float(info.get("trailingPE")),
            "ev_ebitda":    _safe_float(info.get("enterpriseToEbitda")),
            "ps":           _safe_float(info.get("priceToSalesTrailing12Months")),
            "p_fcf":        p_fcf,
            "rev_growth":   _safe_float(info.get("revenueGrowth")),
            "nopat_margin": _safe_float(info.get("profitMargins")),
            "roe":          _safe_float(info.get("returnOnEquity")),
            "fcf_yield":    fcf_yield,
        }

        cache_put("mag7", result, **cache_key_kwargs)
        return name, result
    except Exception as e:
        print(f"    [mag7] yfinance metrics error {ticker}: {e}")
        return name, None


def _ytd_return(name: str, ticker: str) -> tuple[str, Optional[float]]:
    """Fetch YTD return via yfinance."""
    try:
        year_start = date(date.today().year, 1, 1)
        days = (date.today() - year_start).days + 5  # buffer for non-trading days
        with YF_LOCK:
            raw = yf.download(ticker, start=str(year_start - timedelta(days=5)),
                              end=str(date.today()), progress=False, auto_adjust=True)
        if raw.empty:
            return name, None
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
        else:
            close = raw["Close"]
        close = close.dropna()
        if len(close) < 2:
            return name, None
        ret = (close.iloc[-1] / close.iloc[0]) - 1
        return name, float(ret)
    except Exception as e:
        print(f"    [mag7] YTD return error {ticker}: {e}")
        return name, None


def _one_year_return(name: str, ticker: str) -> tuple[str, Optional[float]]:
    """Fetch 1Y trailing return via yfinance."""
    try:
        end = date.today()
        start = end - timedelta(days=370)
        with YF_LOCK:
            raw = yf.download(ticker, start=str(start), end=str(end),
                              progress=False, auto_adjust=True)
        if raw.empty:
            return name, None
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
        else:
            close = raw["Close"]
        close = close.dropna()
        if len(close) < 2:
            return name, None
        ret = (close.iloc[-1] / close.iloc[0]) - 1
        return name, float(ret)
    except Exception as e:
        print(f"    [mag7] 1Y return error {ticker}: {e}")
        return name, None


def _build_table() -> tuple[dict, list[str], dict]:
    """Build the type-D comparison table for all 7 companies."""
    yf_results: dict[str, dict] = {}
    ytd_results: dict[str, float] = {}
    one_y_results: dict[str, float] = {}

    # Parallel: yfinance fundamentals + YTD + 1Y returns for all 7
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        yf_futures = {
            pool.submit(_fetch_yf_metrics, name, ticker): ("yf", name)
            for name, ticker in MAG7.items()
        }
        ytd_futures = {
            pool.submit(_ytd_return, name, ticker): ("ytd", name)
            for name, ticker in MAG7.items()
        }
        one_y_futures = {
            pool.submit(_one_year_return, name, ticker): ("1y", name)
            for name, ticker in MAG7.items()
        }

        for fut in as_completed({**yf_futures, **ytd_futures, **one_y_futures}):
            try:
                result = fut.result()
                if fut in yf_futures:
                    kind, name = yf_futures[fut]
                    name2, data = result
                    if data:
                        yf_results[name2] = data
                elif fut in ytd_futures:
                    name2, val = result
                    if val is not None:
                        ytd_results[name2] = val
                else:
                    name2, val = result
                    if val is not None:
                        one_y_results[name2] = val
            except Exception as e:
                print(f"    [mag7] Future error: {e}")

    # Build rows — sort by market cap descending
    rows = []
    for name in MAG7:
        metrics = yf_results.get(name, {})
        row = {
            "indicator":   name,
            "Market Cap":  _fmt_market_cap(metrics.get("market_cap", float("nan"))),
            "YTD":         _fmt_pct(ytd_results.get(name, float("nan"))),
            "1Y Afkast":   _fmt_pct(one_y_results.get(name, float("nan"))),
            "P/E":         _fmt_x(metrics.get("pe", float("nan"))),
            "EV/EBITDA":   _fmt_x(metrics.get("ev_ebitda", float("nan"))),
            "P/S":         _fmt_x(metrics.get("ps", float("nan"))),
            "P/FCF":       _fmt_x(metrics.get("p_fcf", float("nan"))),
            "Omsætningsvækst": _fmt_pct(metrics.get("rev_growth", float("nan"))),
            "NOPAT Margin":    _fmt_pct(metrics.get("nopat_margin", float("nan"))),
            "ROE":         _fmt_pct(metrics.get("roe", float("nan"))),
            "FCF Yield":   _fmt_pct(metrics.get("fcf_yield", float("nan"))),
            "_sort_key":   metrics.get("market_cap", 0) or 0,
        }
        rows.append(row)

    rows.sort(key=lambda r: r["_sort_key"], reverse=True)
    for r in rows:
        del r["_sort_key"]

    # Median row
    def _med_x(key: str) -> str:
        vals = sorted([yf_results[n][key] for n in yf_results if not np.isnan(yf_results[n].get(key, float("nan")))])
        if not vals:
            return "N/A"
        m = vals[len(vals)//2] if len(vals) % 2 == 1 else (vals[len(vals)//2 - 1] + vals[len(vals)//2]) / 2
        return _fmt_x(m)

    def _med_pct(key: str) -> str:
        vals = sorted([yf_results[n][key] for n in yf_results if not np.isnan(yf_results[n].get(key, float("nan")))])
        if not vals:
            return "N/A"
        m = vals[len(vals)//2] if len(vals) % 2 == 1 else (vals[len(vals)//2 - 1] + vals[len(vals)//2]) / 2
        return _fmt_pct(m)

    ytd_sorted = sorted([v for v in ytd_results.values()])
    oney_sorted = sorted([v for v in one_y_results.values()])
    med_ytd = (ytd_sorted[len(ytd_sorted)//2] if len(ytd_sorted) % 2 == 1
               else (ytd_sorted[len(ytd_sorted)//2 - 1] + ytd_sorted[len(ytd_sorted)//2]) / 2) if ytd_sorted else float("nan")
    med_oney = (oney_sorted[len(oney_sorted)//2] if len(oney_sorted) % 2 == 1
                else (oney_sorted[len(oney_sorted)//2 - 1] + oney_sorted[len(oney_sorted)//2]) / 2) if oney_sorted else float("nan")

    median_row = {
        "indicator":       "Median",
        "Market Cap":      "—",
        "YTD":             _fmt_pct(med_ytd),
        "1Y Afkast":       _fmt_pct(med_oney),
        "P/E":             _med_x("pe"),
        "EV/EBITDA":       _med_x("ev_ebitda"),
        "P/S":             _med_x("ps"),
        "P/FCF":           _med_x("p_fcf"),
        "Omsætningsvækst": _med_pct("rev_growth"),
        "NOPAT Margin":    _med_pct("nopat_margin"),
        "ROE":             _med_pct("roe"),
        "FCF Yield":       _med_pct("fcf_yield"),
    }
    rows.append(median_row)

    columns = ["Market Cap", "YTD", "1Y Afkast", "P/E", "EV/EBITDA", "P/S", "P/FCF",
               "Omsætningsvækst", "NOPAT Margin", "ROE", "FCF Yield"]

    table_data = {"columns": columns, "rows": rows}

    chart_spec = {
        "type": "D",
        "title": "Magnificent 7 — Nøgletal (TTM)",
        "x_label": "",
        "y_label": "",
        "note": "TTM = Trailing Twelve Months. Kilde: FMP, Yahoo Finance.",
        "table_data": table_data,
    }

    return table_data, ["FMP", "Yahoo Finance"], chart_spec


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fetch_mag7(task: dict) -> dict:
    """
    Main entry point for the mag7 specialist.

    Returns SpecialistResult:
        {
            "dataframes":  {series_label: pd.DataFrame, ...},
            "kilde":       [str, ...],
            "chart_specs": [chart_spec, ...],
        }
    """
    api_key = API_KEYS.get("fmp", "")

    # Determine period from task charts — default 2 years (730 days)
    period_days = max(
        (c.get("period_days", 730) for c in task.get("charts", [])),
        default=730,
    )

    dataframes: dict[str, pd.DataFrame] = {}
    all_kilde: list[str] = []
    chart_specs: list[dict] = []

    # --- Chart 1: Price performance line chart ---
    try:
        price_dfs, price_kilde, price_spec = _build_price_chart(period_days)
        dataframes.update(price_dfs)
        for k in price_kilde:
            if k not in all_kilde:
                all_kilde.append(k)
        if price_spec:
            chart_specs.append(price_spec)
    except Exception as e:
        print(f"  [mag7] Price chart error: {e}")

    # --- Chart 2: Fundamentals comparison table ---
    if api_key:
        try:
            table_data, tbl_kilde, tbl_spec = _build_table(api_key)
            for k in tbl_kilde:
                if k not in all_kilde:
                    all_kilde.append(k)
            chart_specs.append(tbl_spec)
        except Exception as e:
            print(f"  [mag7] Table build error: {e}")
    else:
        print("  [mag7] No FMP API key — skipping fundamentals table.")

    # Dataframes dict must contain an entry for every series_label referenced
    # in chart_specs (non-table charts). Table charts are self-contained via table_data.

    return {
        "dataframes":  dataframes,
        "kilde":       all_kilde if all_kilde else ["Yahoo Finance"],
        "chart_specs": chart_specs,
    }
