import pandas as pd
import yfinance as yf
from datetime import date, timedelta
from newsletter_agent.config import YF_LOCK


def fetch_commodities(task: dict) -> dict:
    dataframes: dict[str, pd.DataFrame] = {}
    kilde: list[str] = []
    period_days = max(
        (c.get("period_days", 365) for c in task.get("charts", [])),
        default=365
    )
    start = str(date.today() - timedelta(days=period_days))

    for s in task["series"]:
        label = s["label"]
        with YF_LOCK:
            raw = yf.download(s["ticker"], start=start, end=str(date.today()),
                              progress=False, auto_adjust=True)
        if raw.empty:
            print(f"    [commodities] WARNING: ticker '{s['ticker']}' (label='{label}') returned no data — check ticker symbol")
            continue
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            df = close.to_frame(name=label)
        else:
            df = raw[["Close"]].rename(columns={"Close": label})
        if df.index.duplicated().any():
            df = df[~df.index.duplicated(keep="last")]
        dataframes[label] = df
        if "Yahoo Finance" not in kilde:
            kilde.append("Yahoo Finance")

    return {"dataframes": dataframes, "kilde": kilde,
            "chart_specs": task.get("charts", [])}
