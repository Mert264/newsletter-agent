"""
Unit conversion for cross-source series.
Applies named conversions (physical constants + date-matched FX) before rendering.
"""
from __future__ import annotations
import pandas as pd
import yfinance as yf
from datetime import date, timedelta
from newsletter_agent.config import YF_LOCK

# Fixed physical conversion factors
_PHYSICAL = {
    "USD_MMBtu_to_USD_MWh": 3.41214,  # 1 MWh = 3.41214 MMBtu
}


def _fetch_fx(ticker: str, period_days: int) -> pd.Series:
    """Fetch daily FX close prices for the given period."""
    end = date.today()
    start = end - timedelta(days=period_days)
    try:
        with YF_LOCK:
            raw = yf.download(ticker, start=str(start), end=str(end),
                              progress=False, auto_adjust=True)
        if raw.empty:
            return pd.Series(dtype=float)
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"].iloc[:, 0]
        else:
            close = raw["Close"]
        return close.squeeze()
    except Exception as e:
        print(f"    [converters] FX fetch failed for {ticker}: {e}")
        return pd.Series(dtype=float)


def apply_conversions(dfs: dict, series_specs: list, period_days: int) -> tuple:
    """
    Apply unit conversions specified in series_specs[i]["conversion"].

    Supported conversion names:
      "USD_MMBtu_to_USD_MWh"  — multiply by 3.41214 (physical constant)
      "EUR_MWh_to_USD_MWh"    — multiply by date-matched EUR/USD rate from yfinance

    Returns:
      (converted_dfs: dict, note: str)
      converted_dfs is a shallow copy of dfs with converted DataFrames replaced.
      note is a Danish-language explanation of all conversions applied, for chart footer.
    """
    converted = dict(dfs)
    notes = []

    # Pre-fetch EUR/USD only if any series needs it (avoid unnecessary API call)
    eur_usd = None
    if any(s.get("conversion") == "EUR_MWh_to_USD_MWh" for s in series_specs):
        eur_usd = _fetch_fx("EURUSD=X", period_days)

    for spec in series_specs:
        label = spec.get("label", "")
        conversion = spec.get("conversion", "")
        if not conversion or label not in converted:
            continue

        df = converted[label]
        series = df.iloc[:, 0].copy()

        if conversion == "USD_MMBtu_to_USD_MWh":
            factor = _PHYSICAL["USD_MMBtu_to_USD_MWh"]
            converted[label] = (series * factor).to_frame(name=label)
            notes.append(
                f"{label} omregnet fra USD/MMBtu til USD/MWh (faktor: {factor})"
            )

        elif conversion == "EUR_MWh_to_USD_MWh":
            if eur_usd is not None and not eur_usd.empty:
                # Outer join + forward-fill for date alignment
                aligned = (
                    series.to_frame("v")
                    .join(eur_usd.rename("fx"), how="outer")
                    .ffill()
                    .dropna()
                )
                converted[label] = (aligned["v"] * aligned["fx"]).to_frame(name=label)
                latest_rate = float(eur_usd.iloc[-1])
                latest_date = eur_usd.index[-1].strftime("%-d %b %Y")
                notes.append(
                    f"{label} omregnet fra EUR/MWh til USD/MWh "
                    f"(EUR/USD dato-matchet, seneste: {latest_rate:.3f}, {latest_date})"
                )
            else:
                print(f"    [converters] WARNING: EUR/USD fetch failed — '{label}' is in EUR/MWh, NOT USD/MWh. Chart y-axis will be misleading.")
                notes.append(
                    f"⚠ {label}: EUR/USD ikke tilgængelig — værdier vises i EUR/MWh (ikke USD/MWh)"
                )

    note = ". ".join(notes) + "." if notes else ""
    return converted, note
