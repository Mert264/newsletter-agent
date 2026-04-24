from __future__ import annotations
"""World Bank REST API specialist — no authentication required."""
import requests
import pandas as pd
from typing import Optional

_WB_BASE = "https://api.worldbank.org/v2/country/{iso3}/indicator/{code}?format=json&mrv={years}&per_page=100"
_LAG_NOTE = "Verdensbank-data publiceres typisk med 1–2 års efterslæb."


def _fetch_indicator(iso3: str, code: str, years: int) -> Optional[pd.DataFrame]:
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
        dates, values = zip(*sorted(records))
        df = pd.DataFrame({"value": values}, index=pd.DatetimeIndex(dates))
        df = df[~df.index.duplicated(keep="last")]
        df = df.ffill(limit=1)
        return df
    except Exception as e:
        print(f"    [worldbank] Failed to fetch {iso3}/{code}: {e}")
        return None


def fetch_worldbank(task: dict) -> dict:
    """Fetch World Bank data series defined in task['series']. Returns SpecialistResult dict."""
    dataframes: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []

    for s in task.get("series", []):
        label = s.get("label", s.get("ticker", ""))
        iso3  = s.get("country", "WLD")
        code  = s.get("ticker", "")
        years = int(s.get("years", 20))

        df = _fetch_indicator(iso3, code, years)
        if df is not None and not df.empty:
            df.columns = [label]
            dataframes[label] = df
        else:
            print(f"    [worldbank] No data for {iso3}/{code} — skipping '{label}'")
            skipped.append(label)

    for chart in task.get("charts", []):
        existing = chart.get("note", "")
        if _LAG_NOTE not in existing:
            chart["note"] = (existing + " " + _LAG_NOTE).strip()
        chart["freq"] = "A"

    if skipped:
        print(f"    [worldbank] Skipped indicators (no data): {', '.join(skipped)}")

    return {
        "dataframes": dataframes,
        "kilde":      ["Verdensbanken"],
    }
