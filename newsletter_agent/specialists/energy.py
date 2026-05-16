import requests
import pandas as pd
import yfinance as yf
from datetime import date, timedelta
from newsletter_agent.config import YF_LOCK, API_KEYS


def _fetch_yfinance(ticker: str, period_days: int, label: str,
                    start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """Fetch OHLCV from yfinance, return Close column renamed to label."""
    end_str = end_date or str(date.today())
    start_str = start_date or str(date.today() - timedelta(days=period_days))
    with YF_LOCK:
        raw = yf.download(ticker, start=start_str, end=end_str,
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


_EIA_BASE = "https://api.eia.gov/v2"

# MSN codes for US total energy consumption by source (annual, Quadrillion BTU)
EIA_ENERGY_MIX_CODES = {
    "Olie & petroleum": "PATOBUS",
    "Naturgas":         "NNTCBUS",
    "Kul":              "CLTCBUS",
    "Kerneenergi":      "NUETBUS",
    "Vedvarende energi": "RETCBUS",
}


def _fetch_eia(msn: str, label: str, api_key: str, frequency: str = "annual"):
    """Fetch one EIA total-energy series by MSN code. Returns DataFrame with DatetimeIndex."""
    if not api_key:
        print(f"    [eia] No EIA_API_KEY set — skipping '{label}'")
        return None
    try:
        resp = requests.get(
            f"{_EIA_BASE}/total-energy/data/",
            params={
                "api_key":           api_key,
                "frequency":         frequency,
                "data[0]":           "value",
                "facets[msn][]":     msn,
                "sort[0][column]":   "period",
                "sort[0][direction]": "asc",
                "length":            60,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json().get("response", {}).get("data", [])
        records = [(str(d["period"]), d["value"]) for d in data if d.get("value") is not None]
        if not records:
            return None
        df = pd.DataFrame(records, columns=["period", label])
        df["period"] = pd.to_datetime(df["period"].astype(str), format="%Y")
        return df.set_index("period").sort_index()
    except Exception as e:
        print(f"    [eia] Failed to fetch '{label}' ({msn}): {e}")
        return None


def _fetch_eia_mix(msn_codes: dict, api_key: str):
    """
    Fetch multiple EIA MSN codes and return a wide DataFrame suitable for Type F stacked chart.
    msn_codes: {label: msn_code} dict, e.g. {"Olie": "PATOBUS", ...}
    Index = year (string), columns = label names.
    """
    if not msn_codes:
        msn_codes = EIA_ENERGY_MIX_CODES
    frames = {}
    for lbl, msn in msn_codes.items():
        df = _fetch_eia(msn, lbl, api_key)
        if df is not None:
            frames[lbl] = df[lbl]
    if not frames:
        return None
    wide = pd.DataFrame(frames).dropna(how="all")
    wide.index = wide.index.year.astype(str)  # "2020", "2021", ...
    return wide.tail(10)  # last 10 years


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
    start_date = task.get("start_date")
    end_date = task.get("end_date")
    _start_ts = pd.Timestamp(start_date) if start_date else None
    _end_ts   = pd.Timestamp(end_date)   if end_date   else None

    for s in task["series"]:
        label = s["label"]
        source = s["source"]
        if source == "yfinance":
            df = _fetch_yfinance(s["ticker"], period_days, label, start_date, end_date)
            if _start_ts is not None:
                df = df[df.index >= _start_ts]
            if _end_ts is not None:
                df = df[df.index <= _end_ts]
            dataframes[label] = df
            if "Yahoo Finance" not in kilde:
                kilde.append("Yahoo Finance")
        elif source == "eia":
            df = _fetch_eia(s["ticker"], label, API_KEYS.get("eia", ""))
            if df is not None:
                if _start_ts is not None:
                    df = df[df.index >= _start_ts]
                if _end_ts is not None:
                    df = df[df.index <= _end_ts]
                if not df.empty:
                    dataframes[label] = df
                if "EIA" not in kilde:
                    kilde.append("EIA")
        elif source == "eia_mix":
            # Special: fetch a full energy-mix snapshot (multiple MSN codes → one wide DataFrame)
            # EIA mix uses string-year index — filter by start/end year if provided
            mix_df = _fetch_eia_mix(s.get("msn_codes", {}), API_KEYS.get("eia", ""))
            if mix_df is not None:
                if _start_ts is not None:
                    mix_df = mix_df[mix_df.index.astype(int) >= _start_ts.year]
                if _end_ts is not None:
                    mix_df = mix_df[mix_df.index.astype(int) <= _end_ts.year]
                if not mix_df.empty:
                    dataframes[label] = mix_df
                if "EIA" not in kilde:
                    kilde.append("EIA")

    return {
        "dataframes": dataframes,
        "kilde": kilde,
        "chart_specs": task.get("charts", []),
    }
