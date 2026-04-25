from __future__ import annotations
"""World Bank REST API specialist — no authentication required.
Fetches all series in parallel (ThreadPoolExecutor) and caches results for 48 hours.
"""
import requests
import pandas as pd
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from newsletter_agent.cache import get as cache_get, put as cache_put

_WB_BASE = "https://api.worldbank.org/v2/country/{iso3}/indicator/{code}?format=json&mrv={years}&per_page=100"
_LAG_NOTE = "Verdensbank-data publiceres typisk med 1–2 års efterslæb."
_TTL = 48 * 3600  # 48 hours — WB data is annual, rarely updated mid-day
_MAX_WORKERS = 8  # parallel HTTP connections


def _records_to_df(records: list) -> pd.DataFrame:
    dates, values = zip(*sorted(records))
    df = pd.DataFrame({"value": values}, index=pd.DatetimeIndex(dates))
    df = df[~df.index.duplicated(keep="last")]
    df = df.ffill(limit=1)
    return df


def _fetch_indicator(iso3: str, code: str, years: int) -> Optional[pd.DataFrame]:
    """Fetch one World Bank indicator for one country. Cache for 48h."""
    cached = cache_get("wb", _TTL, iso3=iso3, code=code, years=years)
    if cached is not None:
        try:
            df = _records_to_df([(pd.Timestamp(r[0]), r[1]) for r in cached])
            print(f"    [worldbank] Cache hit: {iso3}/{code}")
            return df
        except Exception:
            pass  # corrupt cache entry — fall through to live fetch

    url = _WB_BASE.format(iso3=iso3, code=code, years=years)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        if not payload or len(payload) < 2 or not payload[1]:
            return None
        records = [
            (pd.Timestamp(f"{row['date']}-01-01"), row["value"])
            for row in payload[1]
            if row.get("value") is not None
        ]
        if not records:
            return None
        # Persist to cache as ISO-format strings (JSON-serialisable)
        cache_put("wb", [[str(d), v] for d, v in records], iso3=iso3, code=code, years=years)
        return _records_to_df(records)
    except Exception as e:
        print(f"    [worldbank] Failed to fetch {iso3}/{code}: {e}")
        return None


def fetch_worldbank(task: dict) -> dict:
    """Fetch World Bank data series defined in task['series']. Returns SpecialistResult dict.
    All series are fetched in parallel; results are cached 48 hours per (iso3, code, years)."""
    dataframes: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []
    series_list = task.get("series", [])

    def _fetch_one(s: dict):
        label = s.get("label", s.get("ticker", ""))
        iso3  = s.get("country", "WLD")
        code  = s.get("ticker", "")
        years = int(s.get("years", 20))
        return label, _fetch_indicator(iso3, code, years)

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(series_list) or 1)) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in series_list}
        for future in as_completed(futures):
            try:
                label, df = future.result()
            except Exception as e:
                label = futures[future].get("label", "?")
                print(f"    [worldbank] Unexpected error for '{label}': {e}")
                skipped.append(label)
                continue

            if df is not None and not df.empty:
                df.columns = [label]
                dataframes[label] = df
            else:
                print(f"    [worldbank] No data — skipping '{label}'")
                skipped.append(label)

    chart_specs = []
    for chart in task.get("charts", []):
        spec = dict(chart)
        existing = spec.get("note", "")
        if _LAG_NOTE not in existing:
            spec["note"] = (existing + " " + _LAG_NOTE).strip()
        spec["freq"] = "A"
        chart_specs.append(spec)

    if skipped:
        print(f"    [worldbank] Skipped (no data): {', '.join(skipped)}")

    print(f"    [worldbank] Done — {len(dataframes)} series fetched.")
    return {
        "dataframes":  dataframes,
        "kilde":       ["Verdensbanken"],
        "chart_specs": chart_specs,
    }
