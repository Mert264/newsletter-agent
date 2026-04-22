# newsletter_agent/processors/normalize.py
import pandas as pd
import numpy as np


def drop_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows where all values are NaN; forward-fill single missing values."""
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]
    return df.dropna(how="all").ffill().dropna()


def align_dates(dataframes: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Trim all DataFrames to their shared start date; drop stale series.

    End-date handling: use max(ends) so a single discontinued series (e.g. a
    CPALTT OECD-MEI series that stopped publishing in 2022) does not clip every
    other series to that stale cutoff. Instead, any series whose last observation
    is more than 400 days before the most recent data available is dropped with a
    warning. The remaining series are trimmed to a common start and the full
    max-end window (NaN tails are forward-filled downstream in the pipeline).
    """
    if not dataframes:
        return dataframes
    # Deduplicate index first — Yahoo Finance occasionally returns duplicate timestamps
    deduped = {
        label: df[~df.index.duplicated(keep="last")]
        for label, df in dataframes.items()
    }
    ends = {label: df.index.max() for label, df in deduped.items()}
    global_end = max(ends.values())

    # Drop any series whose last obs is >400 days stale relative to the freshest series
    stale_threshold_days = 400
    stale = [
        label for label, end in ends.items()
        if (global_end - end).days > stale_threshold_days
    ]
    if stale:
        for label in stale:
            print(f"    [align_dates] Dropping stale series '{label}' "
                  f"(last obs {ends[label].date()}, freshest {global_end.date()} "
                  f"— gap {(global_end - ends[label]).days} days > 400-day threshold)")
        deduped = {k: v for k, v in deduped.items() if k not in stale}
    if not deduped:
        return deduped

    starts = [df.index.min() for df in deduped.values()]
    common_start = max(starts)
    common_end = max(df.index.max() for df in deduped.values())
    return {
        label: df.loc[common_start:common_end]
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
