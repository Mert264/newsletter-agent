# newsletter_agent/processors/normalize.py
import pandas as pd
import numpy as np


def drop_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows where all values are NaN; forward-fill single missing values."""
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]
    return df.dropna(how="all").ffill().dropna()


def align_dates(dataframes: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Align DataFrames to a common start date; each series keeps its own last observation.

    Only the START date uses intersection (so no series extends before the others have data).
    End dates are NOT clipped — series with less history (e.g. OECD-lagged Japan CPI) end
    at their own last data point. The pipeline's outer-join + limited ffill handles the gaps.
    """
    if not dataframes:
        return dataframes
    # Deduplicate index first — Yahoo Finance occasionally returns duplicate timestamps
    deduped = {
        label: df[~df.index.duplicated(keep="last")]
        for label, df in dataframes.items()
    }
    starts = [df.index.min() for df in deduped.values()]
    common_start = max(starts)
    return {
        label: df.loc[common_start:]
        for label, df in deduped.items()
    }


def resample_to_freq(df: pd.DataFrame, freq: str = "W") -> pd.DataFrame:
    """Resample DataFrame to given frequency using last observation."""
    return df.resample(freq).last().dropna()


def index_to_100(df: pd.DataFrame, base_date: pd.Timestamp = None) -> pd.DataFrame:
    """Re-index all columns so the first row (or base_date row) = 100."""
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]
    if base_date is not None:
        base_row = df.loc[base_date]
        base = base_row.iloc[0] if isinstance(base_row, pd.DataFrame) else base_row
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
