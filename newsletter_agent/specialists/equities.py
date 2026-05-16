import pandas as pd
import yfinance as yf
from datetime import date, timedelta
from newsletter_agent.config import YF_LOCK


def fetch_equities(task: dict) -> dict:
    dataframes: dict[str, pd.DataFrame] = {}
    kilde: list[str] = []
    period_days = max(
        (c.get("period_days", 365) for c in task.get("charts", [])),
        default=365
    )
    start = task.get("start_date") or str(date.today() - timedelta(days=period_days))
    end = task.get("end_date") or str(date.today())
    _start_ts = pd.Timestamp(start)
    _end_ts   = pd.Timestamp(end)

    for s in task["series"]:
        label = s["label"]
        with YF_LOCK:
            raw = yf.download(s["ticker"], start=start, end=end,
                              progress=False, auto_adjust=True)
        if raw.empty:
            print(f"    [equities] WARNING: ticker '{s['ticker']}' (label='{label}') returned no data — check ticker symbol")
            continue
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            df = close.to_frame(name=label)
        else:
            df = raw[["Close"]].rename(columns={"Close": label})
        # Deduplicate index — yfinance occasionally returns duplicate timestamps
        if df.index.duplicated().any():
            df = df[~df.index.duplicated(keep="last")]
        df = df[(df.index >= _start_ts) & (df.index <= _end_ts)]
        dataframes[label] = df
        if "Yahoo Finance" not in kilde:
            kilde.append("Yahoo Finance")

    return {"dataframes": dataframes, "kilde": kilde,
            "chart_specs": task.get("charts", [])}
