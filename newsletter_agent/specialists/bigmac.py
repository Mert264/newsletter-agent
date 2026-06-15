# newsletter_agent/specialists/bigmac.py
"""Big Mac Index specialist — The Economist's open dataset.
Fetches and caches the full CSV for 24 hours, then shapes it into SpecialistResult format.

Supports two output modes driven by task configuration:
  - Cross-country comparison (default): latest-date snapshot, bar chart (type B)
  - Single-country trend: time series of USD_raw and USD_adjusted, line chart (type A)
"""
from __future__ import annotations
import io
import requests
import pandas as pd
from newsletter_agent.cache import get as cache_get, put as cache_put

_CSV_URL = "https://raw.githubusercontent.com/TheEconomist/big-mac-data/master/output-data/big-mac-full-index.csv"
_TTL = 24 * 3600  # 24 hours
_CACHE_PREFIX = "bigmac"

# Danish country name overrides for common nations
_DA_NAMES: dict[str, str] = {
    "Argentina": "Argentina",
    "Australia": "Australien",
    "Brazil": "Brasilien",
    "Britain": "Storbritannien",
    "Canada": "Canada",
    "Chile": "Chile",
    "China": "Kina",
    "Colombia": "Colombia",
    "Czech Republic": "Tjekkiet",
    "Denmark": "Danmark",
    "Egypt": "Egypten",
    "Euro area": "Euroområdet",
    "Hong Kong": "Hong Kong",
    "Hungary": "Ungarn",
    "India": "Indien",
    "Indonesia": "Indonesien",
    "Israel": "Israel",
    "Japan": "Japan",
    "Malaysia": "Malaysia",
    "Mexico": "Mexico",
    "New Zealand": "New Zealand",
    "Norway": "Norge",
    "Pakistan": "Pakistan",
    "Peru": "Peru",
    "Philippines": "Filippinerne",
    "Poland": "Polen",
    "Russia": "Rusland",
    "Saudi Arabia": "Saudi-Arabien",
    "Singapore": "Singapore",
    "South Africa": "Sydafrika",
    "South Korea": "Sydkorea",
    "Sri Lanka": "Sri Lanka",
    "Sweden": "Sverige",
    "Switzerland": "Schweiz",
    "Taiwan": "Taiwan",
    "Thailand": "Thailand",
    "Turkey": "Tyrkiet",
    "UAE": "UAE",
    "Ukraine": "Ukraine",
    "United States": "USA",
    "Vietnam": "Vietnam",
}


def fetch_bigmac_data() -> pd.DataFrame:
    """Download and cache the Big Mac Index CSV. Returns full DataFrame."""
    cached = cache_get(_CACHE_PREFIX, _TTL, url=_CSV_URL)
    if cached is not None:
        try:
            df = pd.read_json(io.StringIO(cached), orient="split")
            print("    [bigmac] Cache hit.")
            return df
        except Exception:
            pass  # corrupt cache — fall through to live fetch

    print("    [bigmac] Fetching CSV from GitHub...")
    resp = requests.get(_CSV_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), parse_dates=["date"])
    df = df.dropna(subset=["USD_raw"])

    # Persist as JSON-serialisable split format
    cache_put(_CACHE_PREFIX, df.to_json(orient="split"), url=_CSV_URL)
    print(f"    [bigmac] Fetched {len(df)} rows, {df['iso_a3'].nunique()} countries.")
    return df


def fetch_bigmac(task: dict) -> dict:
    """Main pipeline entry point. Returns SpecialistResult dict.

    task keys consumed:
      - country (str, optional): ISO-3 code or country name for single-country mode
      - countries (list[str], optional): list of ISO-3 codes for comparison (defaults to all)
      - charts (list[dict]): chart_specs from orchestrator (passed through with additions)
    """
    try:
        df = fetch_bigmac_data()
    except Exception as e:
        print(f"    [bigmac] Failed to fetch data: {e}")
        return {"dataframes": {}, "kilde": ["The Economist"], "chart_specs": []}

    dataframes: dict[str, pd.DataFrame] = {}
    chart_specs: list[dict] = []

    country_arg = task.get("country", "")
    countries_arg = task.get("countries", [])

    # ── Resolve single-country mode ──────────────────────────────────────────
    single_iso: str | None = None
    if country_arg:
        # Match by ISO-3 or by name (case-insensitive)
        iso_upper = country_arg.strip().upper()
        if iso_upper in df["iso_a3"].str.upper().values:
            single_iso = iso_upper
        else:
            # Try name match
            name_match = df[df["name"].str.lower() == country_arg.strip().lower()]
            if not name_match.empty:
                single_iso = name_match.iloc[0]["iso_a3"]

    # ── Single-country: time series ──────────────────────────────────────────
    if single_iso:
        country_df = df[df["iso_a3"].str.upper() == single_iso].copy()
        country_df = country_df.sort_values("date").set_index("date")

        if not country_df.empty:
            country_name = _DA_NAMES.get(country_df.iloc[0]["name"], country_df.iloc[0]["name"])

            label_raw = f"{country_name} (råindeks)"
            label_adj = f"{country_name} (BNP-justeret)"
            label_price = f"{country_name} Big Mac-pris (USD)"

            s_raw = country_df[["USD_raw"]].rename(columns={"USD_raw": label_raw})
            s_adj = country_df[["USD_adjusted"]].rename(columns={"USD_adjusted": label_adj})
            s_price = country_df[["dollar_price"]].rename(columns={"dollar_price": label_price})

            dataframes[label_raw] = s_raw
            dataframes[label_adj] = s_adj
            dataframes[label_price] = s_price

            chart_specs.append({
                "type": "A",
                "title": f"Big Mac Index — {country_name}",
                "series_labels": [label_raw, label_adj],
                "x_label": "",
                "y_label": "Over-/undervurdering ift. USD (%)",
                "note": "Råindeks og BNP-justeret indeks. Positivt tal = overvurderet valuta.",
                "freq": "M",
            })
            chart_specs.append({
                "type": "A",
                "title": f"Big Mac-pris i USD — {country_name}",
                "series_labels": [label_price],
                "x_label": "",
                "y_label": "USD",
                "note": "Faktisk pris på en Big Mac i USD.",
                "freq": "M",
            })
        else:
            print(f"    [bigmac] No data for country '{single_iso}'.")

    # ── Cross-country comparison: latest snapshot ────────────────────────────
    else:
        latest_date = df["date"].max()
        snap = df[df["date"] == latest_date].copy()

        if countries_arg:
            iso_filter = [c.strip().upper() for c in countries_arg]
            snap = snap[snap["iso_a3"].str.upper().isin(iso_filter)]

        snap = snap.dropna(subset=["USD_raw"]).sort_values("USD_raw", ascending=False)

        if not snap.empty:
            label_raw = "USD_raw_snapshot"
            label_adj = "USD_adjusted_snapshot"
            label_price = "dollar_price_snapshot"

            # Country names as index (Danish where available)
            snap["display_name"] = snap["name"].map(lambda n: _DA_NAMES.get(n, n))
            snap_indexed = snap.set_index("display_name")

            dataframes[label_raw] = snap_indexed[["USD_raw"]].rename(columns={"USD_raw": label_raw})
            dataframes[label_adj] = snap_indexed[["USD_adjusted"]].rename(columns={"USD_adjusted": label_adj})
            dataframes[label_price] = snap_indexed[["dollar_price"]].rename(columns={"dollar_price": label_price})

            date_str = latest_date.strftime("%B %Y") if hasattr(latest_date, "strftime") else str(latest_date)

            chart_specs = []
            if True:
                chart_specs.append({
                    "type": "B",
                    "title": f"Big Mac Index — valutaer ift. USD ({date_str})",
                    "series_labels": [label_raw],
                    "x_label": "",
                    "y_label": "Over-/undervurdering ift. USD (%)",
                    "note": "Råindeks. Positivt tal = overvurderet valuta.",
                    "freq": "snapshot",
                })
                chart_specs.append({
                    "type": "B",
                    "title": f"Big Mac Index, BNP-justeret ({date_str})",
                    "series_labels": [label_adj],
                    "x_label": "",
                    "y_label": "Over-/undervurdering ift. USD, BNP-justeret (%)",
                    "note": "BNP-justeret indeks er mere præcist for rige vs. fattige lande.",
                    "freq": "snapshot",
                })
        else:
            print("    [bigmac] No snapshot data available.")

    print(f"    [bigmac] Done — {len(dataframes)} series prepared.")
    return {
        "dataframes": dataframes,
        "kilde": ["The Economist"],
        "chart_specs": chart_specs,
    }
