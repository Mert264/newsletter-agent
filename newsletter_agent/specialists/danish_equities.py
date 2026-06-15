# danish_equities.py
"""
Danish equities specialist — fetches C25 price history and key fundamentals
entirely via yfinance (ticker.info + ticker.history).

Entry point: fetch_danish_equity(task) → SpecialistResult dict
  {"dataframes": {...}, "kilde": [...], "chart_specs": [...]}

Routing:
  - task["series"] list → single-company or multi-company fetch
  - task["mode"] == "overview" → parallel fetch of all C25_TOP names
"""
from __future__ import annotations

import pandas as pd
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from newsletter_agent.config import YF_LOCK

# ---------------------------------------------------------------------------
# C25 top constituents  (display name → yfinance / FMP ticker)
# FMP uses the same .CO suffix as yfinance for Copenhagen-listed stocks.
# ---------------------------------------------------------------------------
C25_TOP: dict[str, str] = {
    "Novo Nordisk":  "NOVO-B.CO",
    "DSV":           "DSV.CO",
    "Vestas":        "VWS.CO",
    "Mærsk":         "MAERSK-B.CO",
    "Danske Bank":   "DANSKE.CO",
    "Carlsberg":     "CARL-B.CO",
    "Pandora":       "PNDORA.CO",
    "Coloplast":     "COLO-B.CO",
    "Ørsted":        "ORSTED.CO",
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _yf_price_history(ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """Fetch daily close prices for *ticker* via yfinance. Returns None on failure."""
    try:
        import yfinance as yf
        with YF_LOCK:
            raw = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            df = close.to_frame(name=ticker)
        else:
            df = raw[["Close"]].rename(columns={"Close": ticker})
        if df.index.duplicated().any():
            df = df[~df.index.duplicated(keep="last")]
        return df
    except Exception as exc:
        print(f"    [danish_equities] yfinance failed for {ticker}: {exc}")
        return None


def _yf_fundamentals(ticker: str) -> dict:
    """Fetch key fundamentals from yfinance ticker.info for *ticker*. Returns {} on failure."""
    try:
        import yfinance as yf
        with YF_LOCK:
            info = yf.Ticker(ticker).info
        return info if isinstance(info, dict) else {}
    except Exception as exc:
        print(f"    [danish_equities] yfinance info failed for {ticker}: {exc}")
        return {}


def _fetch_single(name: str, ticker: str, start: str, end: str) -> tuple[str, Optional[pd.DataFrame], dict]:
    """Fetch price history + fundamentals for one company. Thread-safe."""
    df = _yf_price_history(ticker, start, end)
    if df is not None:
        df = df.rename(columns={ticker: name})
    info = _yf_fundamentals(ticker)
    return name, df, info


def _build_fundamentals_df(name: str, info: dict) -> Optional[pd.DataFrame]:
    """Convert yfinance info dict into a single-row snapshot DataFrame for type-D tables."""
    if not info:
        return None

    def _pct(val: Optional[float]) -> Optional[float]:
        return round(val * 100, 2) if val is not None else None

    def _round2(val: Optional[float]) -> Optional[float]:
        return round(val, 2) if val is not None else None

    selected = {
        "P/E (TTM)":   _round2(info.get("trailingPE")),
        "P/B (TTM)":   _round2(info.get("priceToBook")),
        "EV/EBITDA":   _round2(info.get("enterpriseToEbitda")),
        "ROE (%)":     _pct(info.get("returnOnEquity")),
        "Udbytte (%)": _pct(info.get("dividendYield")),
        "Margin (%)":  _pct(info.get("profitMargins")),
    }
    row = {k: v for k, v in selected.items() if v is not None}
    if not row:
        return None
    df = pd.DataFrame([row], index=[name])
    df.index.name = "Selskab"
    return df


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_danish_equity(task: dict) -> dict:
    """
    Fetch Danish equity data as specified in *task*.

    task["series"] list items: {"label": str, "ticker": str}
      - ticker should be a .CO ticker (or a C25_TOP display name)
    task["mode"] (optional): "overview" → fetch all C25_TOP names in parallel
    task["start_date"] / task["end_date"] / task["period_days"] for date range.
    """
    dataframes: dict[str, pd.DataFrame] = {}
    kilde: list[str] = []

    # --- Date range --------------------------------------------------------
    period_days = max(
        (c.get("period_days", 365) for c in task.get("charts", [])),
        default=365,
    )
    start = task.get("start_date") or str(date.today() - timedelta(days=period_days))
    end   = task.get("end_date")   or str(date.today())
    _start_ts = pd.Timestamp(start)
    _end_ts   = pd.Timestamp(end)

    # --- Resolve series list -----------------------------------------------
    mode = task.get("mode", "single")

    if mode == "overview":
        # Fetch all C25_TOP names in parallel
        series_list = [{"label": name, "ticker": ticker} for name, ticker in C25_TOP.items()]
    else:
        series_list = task.get("series", [])
        # Allow passing a display name from C25_TOP as the ticker
        for s in series_list:
            if s.get("ticker") in C25_TOP:
                s["ticker"] = C25_TOP[s["ticker"]]
            elif s.get("label") in C25_TOP and not s.get("ticker", "").endswith(".CO"):
                s["ticker"] = C25_TOP[s["label"]]

    if not series_list:
        return {"dataframes": dataframes, "kilde": kilde, "chart_specs": task.get("charts", [])}

    # --- Parallel fetch -----------------------------------------------------
    max_workers = min(len(series_list), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_single, s["label"], s["ticker"], start, end): s
            for s in series_list
        }
        for future in as_completed(futures):
            try:
                name, df, info = future.result()
            except Exception as exc:
                print(f"    [danish_equities] Worker failed: {exc}")
                continue

            # Price series
            if df is not None and not df.empty:
                df = df[(df.index >= _start_ts) & (df.index <= _end_ts)]
                if not df.empty:
                    dataframes[name] = df
                    if "Yahoo Finance" not in kilde:
                        kilde.append("Yahoo Finance")

            # Fundamentals snapshot (keyed as "<name> — Nøgletal")
            fund_df = _build_fundamentals_df(name, info)
            if fund_df is not None:
                dataframes[f"{name} — Nøgletal"] = fund_df
                if "Yahoo Finance" not in kilde:
                    kilde.append("Yahoo Finance")

    return {
        "dataframes":  dataframes,
        "kilde":       kilde,
        "chart_specs": task.get("charts", []),
    }
