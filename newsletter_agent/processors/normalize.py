# newsletter_agent/processors/normalize.py
import pandas as pd
import numpy as np


def drop_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows where all values are NaN; forward-fill single missing values."""
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]
    return df.dropna(how="all").ffill().dropna()


def align_dates(dataframes: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Trim all DataFrames to their shared date range, deduplicating any duplicate timestamps."""
    if not dataframes:
        return dataframes
    # Deduplicate index first — Yahoo Finance occasionally returns duplicate timestamps
    deduped = {
        label: df[~df.index.duplicated(keep="last")]
        for label, df in dataframes.items()
    }
    starts = [df.index.min() for df in deduped.values()]
    ends = [df.index.max() for df in deduped.values()]
    common_start = max(starts)
    common_end = min(ends)
    return {
        label: df.loc[common_start:common_end]
        for label, df in deduped.items()
    }


def resample_to_freq(df: pd.DataFrame, freq: str = "W") -> pd.DataFrame:
    """Resample DataFrame to given frequency using last observation."""
    return df.resample(freq).last().dropna()


def index_to_100(df: pd.DataFrame, base_date: pd.Timestamp = None) -> pd.DataFrame:
    """Re-index all columns so the first row (or base_date row) = 100."""
    if base_date is not None:
        base = df.loc[base_date]
    else:
        base = df.iloc[0]
    return (df / base) * 100


def compute_yoy(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Compute year-over-year % change for a column. Auto-detects frequency."""
    if len(df) >= 2:
        avg_delta = (df.index[-1] - df.index[0]).days / (len(df) - 1)
    else:
        avg_delta = 1
    if avg_delta >= 60:    # quarterly data (FRED GDP, CLVMEURSCAB1GQEA19, etc.)
        periods = 4
    elif avg_delta >= 25:  # monthly data (FRED CPI, PCE, etc.)
        periods = 12
    elif avg_delta >= 6:   # weekly
        periods = 52
    else:                  # daily (yfinance)
        periods = 252
    result = df[[column]].pct_change(periods=periods) * 100
    result.columns = [f"{column} YoY (%)"]
    return result


def convert_eur_to_usd(df: pd.DataFrame, column: str, rate: float) -> pd.DataFrame:
    """Multiply column by EUR/USD rate. rate = EURUSD (e.g. 1.08)."""
    out = df.copy()
    out[column] = out[column] * rate
    return out
