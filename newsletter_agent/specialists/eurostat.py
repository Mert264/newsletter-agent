from __future__ import annotations
"""
Eurostat specialist — fetches EU statistical data via the free Eurostat REST API.
No API key required. Returns SpecialistResult dict.

Supported source types:
  "eurostat_ts"   — time-series dataset (DatetimeIndex output, for Type A charts)
  "eurostat_mix"  — composition dataset:
                      • energy mix → wide DataFrame (time × product) via _parse_product_wide
                      • geo comparison → DataFrame with country index via _parse_cross_section
"""
import requests
import pandas as pd
from datetime import date

_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"


def _eurostat_get(dataset: str, params: dict):
    """Call Eurostat JSON API. Returns raw JSON response dict or None on failure."""
    try:
        resp = requests.get(
            f"{_BASE}/{dataset}",
            params={**params, "format": "JSON", "lang": "EN"},
            timeout=30,
        )
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
        # Use "id" for correct dimension order (JSON-stat spec)
        dim_keys_ts = raw.get("id", list(dims.keys()))
        dim_sizes_ts = raw.get("size", [1] * len(dim_keys_ts))
        time_dim = next((k for k in dim_keys_ts if k.lower() in ("time", "time_period")), None)
        if not time_dim:
            return None
        time_cats = list(dims[time_dim]["category"]["index"].keys())
        # Compute stride for the time dimension
        t_idx_ts = dim_keys_ts.index(time_dim)
        strides_ts = [1] * len(dim_keys_ts)
        for i in range(len(dim_keys_ts) - 2, -1, -1):
            strides_ts[i] = strides_ts[i + 1] * dim_sizes_ts[i + 1]
        time_stride = strides_ts[t_idx_ts]
        records = []
        for t_i, t in enumerate(time_cats):
            flat = t_i * time_stride  # all other dims fixed at 0
            val = values[flat] if isinstance(values, list) else values.get(str(flat))
            if val is not None:
                records.append((t, float(val)))
        if not records:
            return None
        df = pd.DataFrame(records, columns=["period", label])
        try:
            df["period"] = pd.to_datetime(df["period"])
        except Exception:
            try:
                df["period"] = pd.to_datetime(
                    df["period"].str.replace("M", "-"), errors="coerce"
                )
            except Exception:
                pass
        df = df.dropna(subset=["period"]).set_index("period").sort_index()
        return df
    except Exception as e:
        print(f"    [eurostat] Parse error: {e}")
        return None


def _parse_cross_section(raw: dict, country_filter=None):
    """
    Parse a Eurostat response into a DataFrame with countries as index.
    Used for Type F (stacked) and Type G (horizontal bar) geo-comparison charts.
    """
    if not raw:
        return None
    try:
        values = raw["value"]
        dims = raw["dimension"]
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


def _parse_product_wide(raw: dict, label_map: dict = None) -> "pd.DataFrame | None":
    """
    Parse a multi-dimensional Eurostat dataset into a wide DataFrame: time × product.

    Used for energy mix charts (siec dimension). Finds the time and siec/product
    dimensions, iterates over all combinations, and builds a year-indexed DataFrame
    where each column is an energy product. If label_map is provided, maps Eurostat
    English product labels to display names (keyword matching, case-insensitive);
    products whose labels match no keyword are excluded. When multiple products map
    to the same display name, their values are summed (aggregation).

    Returns DataFrame or None.
    """
    if not raw:
        return None
    try:
        values = raw.get("value", {})
        dims = raw.get("dimension", {})
        # CRITICAL: use the "id" array for dimension order — it is the authoritative
        # ordering for flat index arithmetic in JSON-stat. dims.keys() order is not reliable.
        dim_keys = raw.get("id", list(dims.keys()))
        dim_sizes = raw.get("size", [1] * len(dim_keys))

        time_key = next(
            (k for k in dim_keys if k.lower() in ("time", "time_period")), None
        )
        prod_key = next(
            (k for k in dim_keys if k.lower() in ("siec", "nrg_prod", "product", "products")),
            None,
        )

        if not time_key or not prod_key:
            print(f"    [eurostat] product_wide: no time/product dims found in {dim_keys}")
            return None

        time_cats = list(dims[time_key]["category"]["index"].keys())
        prod_index = dims[prod_key]["category"]["index"]   # {code: integer position}
        prod_labels_raw = dims[prod_key]["category"].get("label", {})

        t_idx = dim_keys.index(time_key)
        p_idx = dim_keys.index(prod_key)

        # Precompute strides: stride[i] = product of sizes of all dims after i
        strides = [1] * len(dim_keys)
        for i in range(len(dim_keys) - 2, -1, -1):
            strides[i] = strides[i + 1] * dim_sizes[i + 1]

        # Helper: handle both dict {"idx": val} and list [val, ...] value formats
        def _get_val(flat: int):
            if isinstance(values, list):
                return values[flat] if flat < len(values) else None
            return values.get(str(flat))

        # Map product codes → display labels (filter + aggregate duplicates by summing)
        prod_display: dict[str, str] = {}
        for p_code in prod_index:
            raw_label = prod_labels_raw.get(p_code, p_code)
            if label_map:
                display = None
                for keyword, name in label_map.items():
                    if keyword.lower() in raw_label.lower():
                        display = name
                        break
                if display:
                    prod_display[p_code] = display
            else:
                prod_display[p_code] = raw_label

        if not prod_display:
            print(f"    [eurostat] product_wide: no products matched label_map")
            return None

        # Build records: {time_str: {display_label: summed_value}}
        records: dict[str, dict[str, float]] = {}
        for p_code, display_label in prod_display.items():
            p_i = prod_index[p_code]
            for t_i, t_key in enumerate(time_cats):
                indices = [0] * len(dim_keys)
                indices[t_idx] = t_i
                indices[p_idx] = p_i
                flat = sum(indices[i] * strides[i] for i in range(len(dim_keys)))
                val = _get_val(flat)
                if val is not None:
                    row = records.setdefault(t_key, {})
                    row[display_label] = row.get(display_label, 0.0) + float(val)

        if not records:
            print(f"    [eurostat] product_wide: no values found — dim_keys={dim_keys}, sizes={dim_sizes}, n_values={len(values)}")
            return None

        df = pd.DataFrame(records).T          # rows=time, cols=products
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df[df.index.notna()].sort_index()
        df = df.dropna(axis=1, how="all")
        return df if not df.empty else None

    except Exception as e:
        print(f"    [eurostat] product_wide parse error: {e}")
        return None


# ── EU Energy Mix: keyword → Danish display name ──────────────────────────────
# Matches against Eurostat's English product labels (case-insensitive substring).
# Products matching the same keyword are summed (e.g. onshore + offshore wind).
_EU_ENERGY_LABEL_MAP = {
    "natural gas":            "Naturgas",
    "solid fossil":           "Kul",
    "coal":                   "Kul",
    "nuclear":                "Kerneenergi",
    "hydro":                  "Vandkraft",
    "wind":                   "Vindkraft",
    "solar":                  "Solenergi",
    "oil and petroleum":      "Olie",
    "bioenergy":              "Bioenergi",
    "biofuels":               "Bioenergi",
    "combustible renewables": "Bioenergi",
}

# ── Known Eurostat dataset shortcuts ──────────────────────────────────────────
KNOWN_DATASETS = {
    # EU27 energy consumption by product — annual, GIC2020 = Gross inland consumption
    # parse_mode="product_wide" → uses _parse_product_wide (time × product DataFrame)
    "eu_energy_mix": {
        "dataset":    "nrg_bal_c",
        "params":     {"freq": "A", "unit": "KTOE", "nrg_bal": "GIC2020", "geo": "EU27_2020"},
        "parse_mode": "product_wide",
        "label_map":  _EU_ENERGY_LABEL_MAP,
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
        label   = s["label"]
        source  = s.get("source", "eurostat_ts")
        dataset = s.get("ticker", "")
        params  = s.get("params", {})

        # Resolve known dataset shortcuts — keep extra metadata for parse routing
        known_meta: dict = {}
        if dataset in KNOWN_DATASETS:
            known = KNOWN_DATASETS[dataset]
            known_meta = known
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
            parse_mode = known_meta.get("parse_mode", "cross_section")

            if parse_mode == "product_wide":
                # Energy mix: returns wide DataFrame (time × product) — no cutoff filter
                # because energy data is annual and we want all available years for context
                df = _parse_product_wide(raw, label_map=known_meta.get("label_map"))
                if df is not None and not df.empty:
                    dataframes[label] = df
            else:
                countries = s.get("countries")
                df = _parse_cross_section(raw, countries)
                if df is not None:
                    dataframes[label] = df

    print(f"    [eurostat] Done — {len(dataframes)} series fetched.")
    return {
        "dataframes": dataframes,
        "kilde": kilde,
        "chart_specs": task.get("charts", []),
    }
