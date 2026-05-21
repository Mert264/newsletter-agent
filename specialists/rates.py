import time
import pandas as pd
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
                print(f"    [rates] FRED fetch failed for '{ticker}' (attempt {attempt+1}/{retries}): {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def fetch_rates(task: dict) -> dict:
    fred = Fred(api_key=API_KEYS["fred"])
    dataframes: dict[str, pd.DataFrame] = {}
    kilde: list[str] = []
    period_days = max(
        (c.get("period_days", 365) for c in task.get("charts", [])),
        default=365
    )
    start = str(date.today() - timedelta(days=period_days))

    for s in task["series"]:
        label = s["label"]
        source = s["source"]
        if source == "fred":
            ticker = s["ticker"]
            if len(ticker) > 25 or not ticker.replace("_", "").isalnum():
                print(f"    [rates] Skipping invalid FRED series_id '{ticker}'")
                continue
            try:
                series = _fred_get(fred, ticker, start)
                df = series.to_frame(name=label)
                df.index = pd.to_datetime(df.index)
                dataframes[label] = df
                if "FRED" not in kilde:
                    kilde.append("FRED")
            except Exception as e:
                print(f"    [rates] Failed to fetch '{ticker}' ({label}) after retries: {e}")
        elif source == "yfinance":
            import yfinance as yf
            end = date.today()
            with YF_LOCK:
                raw = yf.download(s["ticker"], start=start, end=str(end),
                                  progress=False, auto_adjust=True)
            if isinstance(raw.columns, pd.MultiIndex):
                close = raw["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                df = close.to_frame(name=label)
            else:
                df = raw[["Close"]].rename(columns={"Close": label})
            dataframes[label] = df
            if "Yahoo Finance" not in kilde:
                kilde.append("Yahoo Finance")

    return {"dataframes": dataframes, "kilde": kilde,
            "chart_specs": task.get("charts", [])}
