from __future__ import annotations
"""IMF REST API specialist — no authentication required.
Fetches all series in parallel (ThreadPoolExecutor) and caches results for 24 hours.

Supported datasets:
  IFS  — International Financial Statistics (GDP, CPI, exchange rates)
  WEO  — World Economic Outlook (growth/inflation forecasts)
  DOTS — Direction of Trade Statistics (trade flows)
  BOP  — Balance of Payments
  FSI  — Financial Soundness Indicators
"""
import requests
import pandas as pd
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from newsletter_agent.cache import get as cache_get, put as cache_put

_IMF_BASE  = "http://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData/{dataset}/{freq}.{country}.{indicator}"
_IMF_TTL   = 24 * 3600   # 24 hours — IMF data is monthly/quarterly
_MAX_WORKERS = 6
_LAG_NOTE  = "IMF-data publiceres typisk med 1–2 kvartals efterslæb."

# Common IFS indicator codes
IFS_INDICATORS = {
    "gdp_real":          "NGDP_R_XDC",
    "cpi":               "PCPI_IX",
    "current_account":   "BCA_BP6_USD",
    "unemployment":      "LUR_PT",
    "exchange_rate":     "ENDA_XDC_USD_RATE",
}

# WEO indicator codes (annual, uses different dataset path)
WEO_INDICATORS = {
    "gdp_growth_forecast":  "NGDP_RPCH",
    "inflation_forecast":   "PCPIPCH",
    "govt_debt_gdp":        "GGXWDG_NGDP",
    "current_account_gdp":  "BCA_NGDPD",
    "unemployment_rate":    "LUR",
}


def _parse_imf_response(raw: dict, label: str) -> Optional[pd.DataFrame]:
    """Extract time-series from IMF SDMX-JSON response into a DataFrame."""
    try:
        obs = (
            raw.get("CompactData", {})
               .get("DataSet", {})
               .get("Series", {})
               .get("Obs", [])
        )
        if not obs:
            return None
        # Obs can be a single dict (one observation) — normalise to list
        if isinstance(obs, dict):
            obs = [obs]
        records = []
        for o in obs:
            period = o.get("@TIME_PERIOD")
            value  = o.get("@OBS_VALUE")
            if period is None or value is None:
                continue
            try:
                ts = pd.Period(period).to_timestamp()
                records.append((ts, float(value)))
            except Exception:
                continue
        if not records:
            return None
        dates, values = zip(*sorted(records))
        df = pd.DataFrame({label: values}, index=pd.DatetimeIndex(dates))
        df = df[~df.index.duplicated(keep="last")]
        return df
    except Exception:
        return None


def fetch_imf_indicator(
    indicator_code: str,
    country_iso2: str,
    dataset: str = "IFS",
    freq: str = "Q",
    start_year: Optional[int] = None,
    label: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """Fetch one IMF indicator for one country. Cache for 24h.

    Args:
        indicator_code: IMF series code, e.g. 'NGDP_R_XDC'
        country_iso2:   ISO-2 country code, e.g. 'US', 'DE'
        dataset:        IMF dataset id, e.g. 'IFS', 'WEO'
        freq:           Frequency — 'Q' (quarterly), 'M' (monthly), 'A' (annual)
        start_year:     Optional: only return data from this year onwards
        label:          Column name in the returned DataFrame (defaults to indicator_code)
    """
    col_label = label or indicator_code
    cache_key_kwargs = dict(dataset=dataset, freq=freq, country=country_iso2, indicator=indicator_code)
    cached = cache_get("imf", _IMF_TTL, **cache_key_kwargs)
    if cached is not None:
        try:
            df = _parse_imf_response(cached, col_label)
            if df is not None:
                print(f"    [imf] Cache hit: {dataset}/{freq}.{country_iso2}.{indicator_code}")
                if start_year:
                    df = df[df.index.year >= start_year]
                return df
        except Exception:
            pass  # corrupt cache — fall through to live fetch

    url = _IMF_BASE.format(
        dataset=dataset, freq=freq, country=country_iso2, indicator=indicator_code
    )
    if start_year:
        url += f"?startPeriod={start_year}"

    for attempt in range(2):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            raw = resp.json()
            # Cache the raw response
            cache_put("imf", raw, **cache_key_kwargs)
            df = _parse_imf_response(raw, col_label)
            if df is not None and start_year:
                df = df[df.index.year >= start_year]
            return df
        except requests.exceptions.Timeout:
            if attempt == 0:
                print(f"    [imf] Timeout for {dataset}/{freq}.{country_iso2}.{indicator_code} — retrying...")
                continue
            print(f"    [imf] Timeout after retry — skipping.")
            return None
        except requests.exceptions.HTTPError as e:
            # 404 means the series doesn't exist for this country/freq combination
            if e.response is not None and e.response.status_code == 404:
                print(f"    [imf] No data (404): {dataset}/{freq}.{country_iso2}.{indicator_code}")
            else:
                print(f"    [imf] HTTP error for {dataset}/{freq}.{country_iso2}.{indicator_code}: {e}")
            return None
        except Exception as e:
            print(f"    [imf] Failed to fetch {dataset}/{freq}.{country_iso2}.{indicator_code}: {e}")
            return None
    return None


def fetch_imf(task: dict) -> dict:
    """Fetch IMF data series defined in task['series']. Returns SpecialistResult dict.

    Series dict keys:
      label         — display name / DataFrame column name
      ticker        — IMF indicator code (e.g. 'NGDP_R_XDC')
      country       — ISO-2 country code (e.g. 'US')
      dataset       — IMF dataset (default 'IFS')
      freq          — 'Q' | 'M' | 'A' (default 'Q')
      start_year    — optional int, e.g. 2000

    All series are fetched in parallel; results are cached 24 hours.
    """
    import pandas as _pd

    dataframes: dict[str, _pd.DataFrame] = {}
    skipped: list[str] = []
    series_list = task.get("series", [])

    # Derive date bounds from explicit task dates
    _start_str = task.get("start_date")
    _end_str   = task.get("end_date")
    _start_ts  = _pd.Timestamp(_start_str) if _start_str else None
    _end_ts    = _pd.Timestamp(_end_str)   if _end_str   else None

    def _fetch_one(s: dict):
        lbl       = s.get("label", s.get("ticker", ""))
        indicator = s.get("ticker", "")
        country   = s.get("country", "US")
        dataset   = s.get("dataset", "IFS")
        freq      = s.get("freq", "Q")
        start_yr  = s.get("start_year")
        if start_yr is None and _start_str:
            try:
                start_yr = _pd.Timestamp(_start_str).year
            except Exception:
                pass
        return lbl, fetch_imf_indicator(
            indicator_code=indicator,
            country_iso2=country,
            dataset=dataset,
            freq=freq,
            start_year=start_yr,
            label=lbl,
        )

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(series_list) or 1)) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in series_list}
        for future in as_completed(futures):
            try:
                label, df = future.result()
            except Exception as e:
                label = futures[future].get("label", "?")
                print(f"    [imf] Unexpected error for '{label}': {e}")
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
                    print(f"    [imf] No data in date range — skipping '{label}'")
                    skipped.append(label)
            else:
                print(f"    [imf] No data — skipping '{label}'")
                skipped.append(label)

    chart_specs = []
    for chart in task.get("charts", []):
        spec     = dict(chart)
        required  = spec.get("series_labels", [])
        available = [lbl for lbl in required if lbl in dataframes]
        missing_s = [lbl for lbl in required if lbl not in dataframes]

        if required and not available:
            print(f"    [imf] Dropping chart '{spec.get('title')}' — no data for any required series.")
            continue

        if missing_s:
            print(f"    [imf] Partial data for '{spec.get('title')}': missing {missing_s}")

        existing = spec.get("note", "")
        if _LAG_NOTE not in existing:
            spec["note"] = (existing + " " + _LAG_NOTE).strip()
        chart_specs.append(spec)

    if skipped:
        print(f"    [imf] Skipped (no data): {', '.join(skipped)}")

    print(f"    [imf] Done — {len(dataframes)} series fetched.")
    return {
        "dataframes":  dataframes,
        "kilde":       ["IMF"],
        "chart_specs": chart_specs,
    }
