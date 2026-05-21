from __future__ import annotations

import requests
import pandas as pd
import yfinance as yf
from datetime import date, timedelta
from newsletter_agent.config import API_KEYS, YF_LOCK


def _fetch_yfinance(ticker: str, period_days: int, label: str) -> pd.DataFrame:
    """Fetch OHLCV from yfinance, return Close column renamed to label."""
    end = date.today()
    start = end - timedelta(days=period_days)
    with YF_LOCK:
        raw = yf.download(ticker, start=str(start), end=str(end),
                          progress=False, auto_adjust=True)
    if raw.empty:
        raise ValueError(f"yfinance returned no data for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        df = close.to_frame(name=label)
    else:
        df = raw[["Close"]].rename(columns={"Close": label})
    return df


def _fetch_eia(ticker: str, route: str | None, frequency: str,
               period_days: int, label: str,
               facet_key: str = "series", value_col: str = "value") -> pd.DataFrame:
    """
    Fetch a time series from the EIA API.
    Uses v2 if route is provided; falls back to v1 (legacy) otherwise.

    ticker:    EIA series ID
    route:     EIA v2 route path, e.g. "petroleum/pri/spt" (None → use v1)
    frequency: "daily" | "weekly" | "monthly" | "annual"
    facet_key: EIA v2 facet dimension name (default "series"; some routes differ)
    value_col: column name in EIA v2 response rows (default "value"; some routes use "price" etc.)
    """
    api_key = API_KEYS.get("eia", "")
    if not api_key:
        raise ValueError("EIA_API_KEY is not set in environment")

    end = date.today()
    start = end - timedelta(days=period_days)

    if route:
        # ── EIA API v2 ──────────────────────────────────────────────────────
        if frequency == "daily":
            start_str = start.strftime("%Y-%m-%d")
        elif frequency == "annual":
            start_str = str(start.year)
        else:
            start_str = start.strftime("%Y-%m")

        url = f"https://api.eia.gov/v2/{route}/data/"
        params = {
            "api_key": api_key,
            "frequency": frequency,
            f"data[0]": value_col,
            f"facets[{facet_key}][]": ticker,
            "start": start_str,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": 5000,
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json().get("response", {}).get("data", [])

        records = {}
        for row in rows:
            period = row.get("period", "")
            # Try the requested value_col, then "value" as universal fallback
            value = row.get(value_col) if row.get(value_col) is not None else row.get("value")
            if not period or value is None:
                continue
            try:
                records[pd.Timestamp(period)] = float(value)
            except Exception:
                continue

        # If v2 returned nothing, try without facet filter as a diagnostic fallback
        if not records:
            print(f"    [energy] EIA v2 returned 0 rows for facet[{facet_key}]={ticker}. "
                  f"Check route and facet_key in the task manifest.")

    else:
        # ── EIA API v1 (legacy fallback) ────────────────────────────────────
        url = "https://api.eia.gov/series/"
        params = {
            "api_key": api_key,
            "series_id": ticker,
            "start": start.strftime("%Y%m%d"),
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        series_list = resp.json().get("series", [{}])
        raw_obs = series_list[0].get("data", []) if series_list else []

        records = {}
        for obs in raw_obs:
            period_str, value = str(obs[0]), obs[1]
            if value is None:
                continue
            try:
                if len(period_str) == 8:
                    ts = pd.Timestamp(period_str)
                elif len(period_str) == 6:
                    ts = pd.Timestamp(f"{period_str[:4]}-{period_str[4:]}-01")
                else:
                    ts = pd.Timestamp(period_str)
                records[ts] = float(value)
            except Exception:
                continue

    s = pd.Series(records, name=label).sort_index()
    return s.to_frame()


def fetch_energy(task: dict) -> dict:
    """
    Fetch all energy series defined in task["series"].
    Returns SpecialistResult dict.
    """
    dataframes: dict[str, pd.DataFrame] = {}
    kilde: list[str] = []
    period_days = max(
        (c.get("period_days", 365) for c in task.get("charts", [])),
        default=365
    )

    for s in task["series"]:
        label = s["label"]
        source = s["source"]

        if source == "yfinance":
            df = _fetch_yfinance(s["ticker"], period_days, label)
            dataframes[label] = df
            if "Yahoo Finance" not in kilde:
                kilde.append("Yahoo Finance")

        elif source == "eia":
            route      = s.get("eia_route")           # optional v2 route
            frequency  = s.get("eia_frequency", "monthly")
            facet_key  = s.get("eia_facet_key", "series")   # override if route uses a different facet dimension
            value_col  = s.get("eia_value_col", "value")    # override if route returns a differently-named value column
            try:
                df = _fetch_eia(s["ticker"], route, frequency, period_days, label,
                                facet_key=facet_key, value_col=value_col)
                dataframes[label] = df
                if "EIA" not in kilde:
                    kilde.append("EIA")
            except Exception as e:
                print(f"    [energy] EIA fetch failed for '{label}' ({s['ticker']}): {e}")

    return {
        "dataframes": dataframes,
        "kilde": kilde,
        "chart_specs": task.get("charts", []),
    }
