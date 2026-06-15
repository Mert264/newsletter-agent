from __future__ import annotations
"""OECD Data API v2 specialist — no authentication required.
Fetches all series in parallel (ThreadPoolExecutor) and caches results for 24 hours.
Uses SDMX-JSON format from https://sdmx.oecd.org/public/rest/data/
"""
import requests
import pandas as pd
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from newsletter_agent.cache import get as cache_get, put as cache_put

_OECD_BASE = "https://sdmx.oecd.org/public/rest/data/{agency_id},{dataset_id},{version}/{filter}"
_OECD_HEADERS = {"Accept": "application/vnd.sdmx.data+json;version=2"}
_TTL = 24 * 3600  # 24 hours — OECD publishes monthly, rarely updated intraday
_MAX_WORKERS = 8

# ── Known OECD dataset shortcuts ──────────────────────────────────────────────
# Maps a short task ticker to a full OECD API path + default filter params.
# Structured as: (agency_id, dataset_id, version, filter_expression, start_period)
KNOWN_DATASETS: dict[str, dict] = {
    # Composite Leading Indicator — monthly, OECD total
    "oecd_cli": {
        "agency":  "OECD.SDD.STES",
        "dataset": "DSD_KEI@DF_KEI",
        "version": "4.0",
        "filter":  "{country}.M.LI.LOLITOAA.IXOB....",
        "start":   "2000",
        "unit":    "Indeks (2015=100)",
        "kilde":   "OECD",
    },
    # Business Confidence Index — monthly
    "oecd_bci": {
        "agency":  "OECD.SDD.STES",
        "dataset": "DSD_KEI@DF_KEI",
        "version": "4.0",
        "filter":  "{country}.M.OE.LORSGPOR.IXOBSA....",
        "start":   "2000",
        "unit":    "Indeks",
        "kilde":   "OECD",
    },
    # Consumer Confidence Index — monthly
    "oecd_cci": {
        "agency":  "OECD.SDD.STES",
        "dataset": "DSD_KEI@DF_KEI",
        "version": "4.0",
        "filter":  "{country}.M.CS.LORSGCOR.IXOBSA....",
        "start":   "2000",
        "unit":    "Indeks",
        "kilde":   "OECD",
    },
    # GDP growth rate — quarterly, QNA
    "oecd_gdp": {
        "agency":  "OECD.SDD.NAD",
        "dataset": "DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_OECD",
        "version": "1.0",
        "filter":  "{country}.Q.S1.B1GQ.....G1",
        "start":   "2000",
        "unit":    "% kvartal/kvartal",
        "kilde":   "OECD",
    },
    # Unemployment rate — monthly, harmonised
    "oecd_unemployment": {
        "agency":  "OECD.SDD.STES",
        "dataset": "DSD_KEI@DF_KEI",
        "version": "4.0",
        "filter":  "{country}.M.UN.LMUNRRTT.STSA....",
        "start":   "2000",
        "unit":    "%",
        "kilde":   "OECD",
    },
    # CPI inflation — monthly, all items
    "oecd_cpi": {
        "agency":  "OECD.SDD.STES",
        "dataset": "DSD_PRICES@DF_PRICES_ALL",
        "version": "1.0",
        "filter":  "{country}.M.CPI.PA.IX._T.N",
        "start":   "2000",
        "unit":    "Indeks",
        "kilde":   "OECD",
    },
    # Multifactor Productivity — annual, STAN
    "oecd_mfp": {
        "agency":  "OECD.SDD.NAD",
        "dataset": "DSD_PDB@DF_PDB_GR",
        "version": "1.0",
        "filter":  "{country}.A.ULABF....",
        "start":   "1995",
        "unit":    "% p.a.",
        "kilde":   "OECD",
    },
}

# Country ISO2 → ISO2 pass-through (OECD uses ISO2 country codes in most endpoints)
_DEFAULT_COUNTRIES = ["USA", "DEU", "GBR", "FRA", "JPN"]


def _parse_sdmx_json(raw: dict, label: str) -> Optional[pd.DataFrame]:
    """Parse SDMX-JSON response into a DatetimeIndex DataFrame with a single 'value' column."""
    try:
        data_node = raw.get("data", {})
        datasets = data_node.get("dataSets", [])
        if not datasets:
            return None

        structure = data_node.get("structure", {})
        dimensions = structure.get("dimensions", {}).get("observation", [])

        # Find the TIME_PERIOD dimension index
        time_dim_idx = None
        time_periods: list[str] = []
        for i, dim in enumerate(dimensions):
            if dim.get("id") in ("TIME_PERIOD", "TIME"):
                time_dim_idx = i
                time_periods = [v.get("id", "") for v in dim.get("values", [])]
                break

        if time_dim_idx is None or not time_periods:
            return None

        observations = datasets[0].get("observations", {})
        records: list[tuple] = []
        for key_str, obs_vals in observations.items():
            keys = key_str.split(":")
            if int(keys[time_dim_idx]) >= len(time_periods):
                continue
            period_str = time_periods[int(keys[time_dim_idx])]
            val = obs_vals[0] if obs_vals else None
            if val is None:
                continue
            try:
                ts = pd.Period(period_str).to_timestamp()
                records.append((ts, float(val)))
            except Exception:
                continue

        if not records:
            return None

        records.sort(key=lambda r: r[0])
        dates, values = zip(*records)
        df = pd.DataFrame({"value": values}, index=pd.DatetimeIndex(dates))
        df = df[~df.index.duplicated(keep="last")]
        df.columns = [label]
        return df
    except Exception as e:
        print(f"    [oecd] Parse error for '{label}': {e}")
        return None


def fetch_oecd_dataset(
    agency_id: str,
    dataset_id: str,
    version: str,
    filter_expression: str,
    start_period: Optional[str] = None,
    label: str = "value",
) -> Optional[pd.DataFrame]:
    """Generic OECD SDMX-JSON fetcher. Caches for 24h. Returns DataFrame or None."""
    cache_key = dict(
        agency=agency_id, dataset=dataset_id, version=version,
        filter=filter_expression, start=start_period or "",
    )
    cached = cache_get("oecd", _TTL, **cache_key)
    if cached is not None:
        try:
            df = _parse_sdmx_json(cached, label)
            if df is not None:
                print(f"    [oecd] Cache hit: {dataset_id}/{filter_expression[:30]}")
                return df
        except Exception:
            pass

    url = _OECD_BASE.format(
        agency_id=agency_id,
        dataset_id=dataset_id,
        version=version,
        filter=filter_expression,
    )
    params: dict = {}
    if start_period:
        params["startPeriod"] = start_period

    for attempt in range(2):
        try:
            resp = requests.get(url, headers=_OECD_HEADERS, params=params, timeout=30)
            resp.raise_for_status()
            raw = resp.json()
            cache_put("oecd", raw, **cache_key)
            return _parse_sdmx_json(raw, label)
        except requests.exceptions.Timeout:
            if attempt == 0:
                print(f"    [oecd] Timeout for {dataset_id} — retrying...")
                continue
            print(f"    [oecd] Timeout after retry for {dataset_id} — skipping.")
            return None
        except Exception as e:
            print(f"    [oecd] Failed to fetch {dataset_id}: {e}")
            return None
    return None


def fetch_oecd(task: dict) -> dict:
    """Fetch OECD data series defined in task['series']. Returns SpecialistResult dict.
    All series are fetched in parallel; results are cached 24h per request parameters."""
    from datetime import date as _date

    dataframes: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []
    series_list = task.get("series", [])

    period_days = task.get("period_days", 730)
    _start_str = task.get("start_date")
    _end_str = task.get("end_date")
    _start_ts = pd.Timestamp(_start_str) if _start_str else None
    _end_ts = pd.Timestamp(_end_str) if _end_str else None

    # Derive start_period for OECD API from task date bounds
    if _start_ts:
        _api_start = _start_ts.strftime("%Y-%m")
    else:
        _api_start = (
            pd.Timestamp(_date.today()) - pd.Timedelta(days=period_days)
        ).strftime("%Y-%m")

    def _fetch_one(s: dict):
        label = s.get("label", s.get("ticker", ""))
        ticker = s.get("ticker", "")
        country = s.get("country", "USA")

        # Resolve known shortcuts
        if ticker in KNOWN_DATASETS:
            meta = KNOWN_DATASETS[ticker]
            agency = meta["agency"]
            dataset = meta["dataset"]
            version = meta["version"]
            # Substitute {country} placeholder
            filter_expr = meta["filter"].replace("{country}", country)
            start = s.get("start_period", meta.get("start", _api_start))
        else:
            # Raw OECD path: ticker = "AGENCY,DATASET@FLOW,VERSION/FILTER"
            # Support passing full path directly as ticker
            agency = s.get("agency", "OECD.SDD.STES")
            dataset = s.get("dataset", ticker)
            version = s.get("version", "1.0")
            filter_expr = s.get("filter", f"{country}....").replace("{country}", country)
            start = s.get("start_period", _api_start)

        df = fetch_oecd_dataset(agency, dataset, version, filter_expr, start, label=label)
        return label, df

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, s): s for s in series_list}
        for future in as_completed(futures):
            try:
                label, df = future.result()
            except Exception as e:
                s = futures[future]
                label = s.get("label", s.get("ticker", "?"))
                print(f"    [oecd] Exception for '{label}': {e}")
                skipped.append(label)
                continue

            if df is not None and not df.empty:
                if _start_ts is not None:
                    df = df[df.index >= _start_ts]
                if _end_ts is not None:
                    df = df[df.index <= _end_ts]
                if not df.empty:
                    dataframes[label] = df
                else:
                    print(f"    [oecd] No data in range — skipping '{label}'")
                    skipped.append(label)
            else:
                print(f"    [oecd] No data — skipping '{label}'")
                skipped.append(label)

    chart_specs = []
    for chart in task.get("charts", []):
        spec = dict(chart)
        required = spec.get("series_labels", [])
        available = [lbl for lbl in required if lbl in dataframes]
        missing_s = [lbl for lbl in required if lbl not in dataframes]

        if required and not available:
            print(f"    [oecd] Dropping chart '{spec.get('title')}' — no data for any required series.")
            continue

        if missing_s:
            print(f"    [oecd] Partial data for '{spec.get('title')}': missing {missing_s}")

        chart_specs.append(spec)

    if skipped:
        print(f"    [oecd] Skipped (no data): {', '.join(skipped)}")

    print(f"    [oecd] Done — {len(dataframes)} series fetched.")
    return {
        "dataframes":  dataframes,
        "kilde":       ["OECD"],
        "chart_specs": chart_specs,
    }
