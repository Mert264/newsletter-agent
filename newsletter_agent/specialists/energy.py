import requests
import pandas as pd
import yfinance as yf
from datetime import date, timedelta
from newsletter_agent.config import YF_LOCK, API_KEYS


def _fetch_yfinance(ticker: str, period_days: int, label: str) -> pd.DataFrame:
    """Fetch OHLCV from yfinance, return Close column renamed to label."""
    end = date.today()
    start = end - timedelta(days=period_days)
    with YF_LOCK:
        raw = yf.download(ticker, start=str(start), end=str(end),
                          progress=False, auto_adjust=True)
    if raw.empty:
        raise ValueError(f"yfinance returned no data for {ticker}")
    # Handle MultiIndex (real yfinance ≥0.2) and flat columns (mocks / older versions)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        # raw["Close"] is a DataFrame when multiple tickers, Series when one
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        df = close.to_frame(name=label)
    else:
        df = raw[["Close"]].rename(columns={"Close": label})
    return df


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
        # EIA and GIE sources: placeholder for Phase 2
        # elif source == "eia": ...

    return {
        "dataframes": dataframes,
        "kilde": kilde,
        "chart_specs": task.get("charts", []),
    }
