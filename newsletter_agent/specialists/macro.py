import time
import pandas as pd
import yfinance as yf
from fredapi import Fred
from datetime import date, timedelta
from newsletter_agent.config import API_KEYS, YF_LOCK


def _fred_get(fred: Fred, ticker: str, start: str, retries: int = 5) -> pd.Series:
    """Fetch a FRED series with exponential backoff retry on transient errors."""
    for attempt in range(retries):
        try:
            return fred.get_series(ticker, observation_start=start)
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s, 16s
                print(f"    [macro] FRED fetch failed for '{ticker}' (attempt {attempt+1}/{retries}): {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def fetch_macro(task: dict) -> dict:
    fred = Fred(api_key=API_KEYS["fred"])
    dataframes: dict[str, pd.DataFrame] = {}
    kilde: list[str] = []
    period_days = max(
        (c.get("period_days", 365 * 3) for c in task.get("charts", [])),
        default=365 * 3
    )
    start = str(date.today() - timedelta(days=period_days))

    for s in task["series"]:
        label = s["label"]
        ticker = s["ticker"]
        source = s.get("source", "fred")

        if source == "yfinance":
            try:
                with YF_LOCK:
                    raw = yf.download(ticker, start=start, end=str(date.today()),
                                      progress=False, auto_adjust=True)
                if isinstance(raw.columns, pd.MultiIndex):
                    close = raw["Close"]
                    if isinstance(close, pd.DataFrame):
                        close = close.iloc[:, 0]
                    df = close.to_frame(name=label)
                else:
                    df = raw[["Close"]].rename(columns={"Close": label})
                if not df.empty:
                    dataframes[label] = df
                    if "Yahoo Finance" not in kilde:
                        kilde.append("Yahoo Finance")
            except Exception as e:
                print(f"    [macro] yfinance failed for '{ticker}' ({label}): {e}")

        elif source == "eurostat_ts":
            # Delegate Eurostat time-series fetches directly — keeps the manifest in one
            # specialist so the LLM doesn't need to split a single chart across two.
            try:
                from newsletter_agent.specialists.eurostat import (
                    _eurostat_get, _parse_timeseries, KNOWN_DATASETS,
                )
                es_ticker = ticker
                es_params = s.get("params", {})
                if es_ticker in KNOWN_DATASETS:
                    known = KNOWN_DATASETS[es_ticker]
                    es_dataset = known["dataset"]
                    es_params = {**known["params"], **es_params}
                else:
                    es_dataset = es_ticker
                cutoff = pd.Timestamp(date.today()) - pd.Timedelta(days=period_days)
                raw = _eurostat_get(es_dataset, es_params)
                df = _parse_timeseries(raw, label)
                if df is not None:
                    df = df[df.index >= cutoff]
                    if not df.empty:
                        dataframes[label] = df
                        if "Eurostat" not in kilde:
                            kilde.append("Eurostat")
            except Exception as e:
                print(f"    [macro] Eurostat fetch failed for '{ticker}' ({label}): {e}")

        else:
            # FRED series IDs must be ≤25 alphanumeric chars
            if len(ticker) > 25 or not ticker.replace("_", "").isalnum():
                print(f"    [macro] Skipping invalid FRED series_id '{ticker}' for '{label}'")
                continue
            try:
                series = _fred_get(fred, ticker, start)
                df = series.to_frame(name=label)
                df.index = pd.to_datetime(df.index)
                dataframes[label] = df
                if "FRED" not in kilde:
                    kilde.append("FRED")
            except Exception as e:
                print(f"    [macro] Failed to fetch FRED '{ticker}' ({label}) after retries: {e}")

    return {"dataframes": dataframes, "kilde": kilde,
            "chart_specs": task.get("charts", [])}
