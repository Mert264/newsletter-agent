from __future__ import annotations
"""
Eurostat specialist — fetches EU statistical data via the free Eurostat REST API.
No API key required. Returns SpecialistResult dict.

Supported source types:
  "eurostat_ts"   — time-series dataset (DatetimeIndex output, for Type A charts)
  "eurostat_mix"  — cross-sectional/composition dataset (string index, for Type F/G charts)
"""
import requests
import pandas as pd
from datetime import date

_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"


def _eurostat_get(dataset: str, params: dict):
    """Call Eurostat JSON API. Returns raw JSON response dict or None on failure."""
    try:
        resp = requests.get(f"{_BASE}/{dataset}", params={**params, "format": "JSON", "lang": "EN"}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"    [eurostat] Failed to fetch dataset '{dataset}': {e}")
        return None


def _parse_timeseries(raw: dict, label: str):
    """Extract a time-series from Eurostat JSON-stat response."""
    if not raw:
        return None
    try:
        values = raw["value"]
        dims = raw["dimension"]
        # Find the time dimension (usually "time" or "TIME_PERIOD")
        time_dim = next((k for k in dims if k.lower() in ("time", "time_period")), None)
        if not time_dim:
            return None
        time_cats = list(dims[time_dim]["category"]["index"].keys())
        # values is a sparse dict: str(flat_index) → float
        n_time = len(time_cats)
        # Single dimension → direct mapping
        records = []
        for i, t in enumerate(time_cats):
            val = values.get(str(i))
            if val is not None:
                records.append((t, float(val)))
        if not records:
            return None
        df = pd.DataFrame(records, columns=["period", label])
        # Parse periods: "2024-Q1", "2024-01", "2024", "2024M01"
        try:
            df["period"] = pd.to_datetime(df["period"])
        except Exception:
            try:
                df["period"] = pd.to_datetime(df["period"].str.replace("M", "-"), errors="coerce")
            except Exception:
                pass
        df = df.dropna(subset=["period"]).set_index("period").sort_index()
        return df
    except Exception as e:
        print(f"    [eurostat] Parse error: {e}")
        return None


def _parse_cross_section(raw: dict, country_filter=None):
    """
    Parse a Eurostat response into a wide DataFrame with countries/categories as index.
    Used for Type F (stacked) and Type G (horizontal bar) charts.
    Returns DataFrame with string index.
    """
    if not raw:
        return None
    try:
        values = raw["value"]
        dims = raw["dimension"]
        # Find geo dimension
        geo_dim = next((k for k in dims if k.lower() in ("geo", "geo\\time")), None)
        if not geo_dim:
            return None
        geo_cats = {v: k for k, v in dims[geo_dim]["category"]["index"].items()}
        records = {}
        for flat_idx_str, val in values.items():
            flat_idx = int(flat_idx_str)
            geo_key = geo_cats.get(flat_idx % len(geo_cats), "?")
            geo_label = dims[geo_dim]["category"]["label"].get(geo_key, geo_key)
            if country_filter and geo_key not in country_filter:
                continue
            records[geo_label] = float(val)
        if not records:
            return None
        return pd.DataFrame.from_dict(records, orient="index", columns=["value"])
    except Exception as e:
        print(f"    [eurostat] Cross-section parse error: {e}")
        return None


# ── Known Eurostat dataset shortcuts ──────────────────────────────────────────
# These are reliable dataset IDs + default params for common macro queries.
KNOWN_DATASETS = {
    # EU energy consumption by product (for stacked chart) — annual
    "eu_energy_mix": {
        "dataset": "nrg_bal_c",
        "params":  {"freq": "A", "unit": "KTOE", "nrg_bal": "FC", "geo": "EU27_2020"},
    },
    # EU GDP growth (annual % change)
    "eu_gdp_growth": {
        "dataset": "tec00115",
        "params":  {"freq": "A", "unit": "PC_GDP_EU", "geo": "EU27_2020"},
    },
    # EU unemployment rate
    "eu_unemployment": {
        "dataset": "une_rt_m",
        "params":  {"freq": "M", "age": "TOTAL", "sex": "T", "unit": "PC_ACT", "s_adj": "SA"},
    },
    # EU HICP inflation (monthly)
    "eu_hicp": {
        "dataset": "prc_hicp_mmor",
        "params":  {"freq": "M", "unit": "PCH_M1", "coicop": "CP00"},
    },
}


def fetch_eurostat(task: dict) -> dict:
    """Fetch Eurostat data series defined in task['series']. Returns SpecialistResult dict."""
    dataframes: dict[str, pd.DataFrame] = {}
    kilde: list[str] = ["Eurostat"]
    period_days = max(
        (c.get("period_days", 730) for c in task.get("charts", [])),
        default=730,
    )
    cutoff = pd.Timestamp(date.today()) - pd.Timedelta(days=period_days)

    for s in task["series"]:
        label  = s["label"]
        source = s.get("source", "eurostat_ts")
        dataset = s.get("ticker", "")     # re-use "ticker" field for dataset ID
        params  = s.get("params", {})

        # Allow shorthand names to map to known datasets
        if dataset in KNOWN_DATASETS:
            known = KNOWN_DATASETS[dataset]
            dataset = known["dataset"]
            params  = {**known["params"], **params}

        raw = _eurostat_get(dataset, params)

        if source == "eurostat_ts":
            df = _parse_timeseries(raw, label)
            if df is not None:
                df = df[df.index >= cutoff]
                if not df.empty:
                    dataframes[label] = df

        elif source in ("eurostat_mix", "eurostat_cross"):
            countries = s.get("countries")
            df = _parse_cross_section(raw, countries)
            if df is not None:
                dataframes[label] = df

    return {
        "dataframes": dataframes,
        "kilde": kilde,
        "chart_specs": task.get("charts", []),
    }
