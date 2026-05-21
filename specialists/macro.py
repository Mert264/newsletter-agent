import re
import time
import requests
import pandas as pd
import yfinance as yf
from fredapi import Fred
from datetime import date, timedelta
from newsletter_agent.config import API_KEYS, YF_LOCK


def _fred_get(fred: Fred, ticker: str, start: str, retries: int = 5) -> pd.Series:
    """Fetch a FRED series with exponential backoff retry on transient errors."""
    for attempt in range(retries):
        try:
            return fred.get_series(ticker, observation_start=start)
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s, 16s
                print(f"    [macro] FRED fetch failed for '{ticker}' (attempt {attempt+1}/{retries}): {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


# Label → ISO-3 map used for FRED→IMF auto-redirect when LLM uses wrong source
_LABEL_TO_ISO3 = {
    "usa": "USA", "united states": "USA",
    "germany": "DEU", "deutschland": "DEU", "tyskland": "DEU",
    "china": "CHN", "kina": "CHN",
    "uk": "GBR", "united kingdom": "GBR",
    "japan": "JPN",
    "france": "FRA", "frankrig": "FRA",
    "italy": "ITA", "italien": "ITA",
    "spain": "ESP", "spanien": "ESP",
    "netherlands": "NLD", "holland": "NLD",
    "switzerland": "CHE", "schweiz": "CHE",
    "australia": "AUS",
    "canada": "CAN",
    "korea": "KOR",
    "brazil": "BRA", "brasilien": "BRA",
    "india": "IND", "indien": "IND",
}


def _imf_get(country_code: str, start: str) -> pd.Series:
    """
    Fetch Net International Investment Position from the IMF SDMX 2.1 API.
    country_code: ISO-3 (e.g. 'DEU', 'CHN', 'USA')
    start: 'YYYY-MM-DD' — observations before this date are dropped.
    Returns quarterly series in billions USD.
    Raw OBS_VALUE is actual USD; divide by 1e9 to get billions.
    """
    import xml.etree.ElementTree as ET
    url = (
        f"https://api.imf.org/external/sdmx/2.1/data/IIP/"
        f"{country_code}.NETAL_P.NIIP.USD.Q"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    start_ts = pd.Timestamp(start)
    records: dict = {}
    for obs in root.findall('.//{*}Obs'):
        period = obs.get('TIME_PERIOD')   # e.g. "2025-Q4"
        value  = obs.get('OBS_VALUE')
        if not period or value is None:
            continue
        try:
            year, q = period.split('-Q')
            month = (int(q) - 1) * 3 + 1
            ts = pd.Timestamp(f"{year}-{month:02d}-01")
            if ts >= start_ts:
                records[ts] = float(value) / 1e9  # actual USD → billions
        except Exception:
            continue

    if not records:
        raise RuntimeError(f"IMF IIP: no data returned for {country_code}")
    return pd.Series(records, name=country_code)


def _dst_get(table: str, variables: list, start: str,
             label: str, scale: float = 1.0) -> pd.DataFrame:
    """
    Fetch data from Danmarks Statistik (DST) free public API.
    table:     DST table code, e.g. "KN8M"
    variables: filter dicts like [{"code": "INDUD", "values": ["2"]}, ...]
               "Tid" is injected automatically — do NOT include it.
    start:     'YYYY-MM-DD' — drop observations before this date
    scale:     divide all values by this factor (e.g. 1e9 to convert DKK → Mia. DKK)
    Returns DataFrame with DatetimeIndex, one column named label.
    """
    from io import StringIO

    variables = [v for v in variables if v.get("code", "").upper() != "TID"]
    variables = list(variables) + [{"code": "Tid", "values": ["*"]}]

    url = f"https://api.statbank.dk/v1/data/{table}/CSV"
    payload = {
        "lang":               "en",
        "variables":          variables,
        "delimiter":          "Semicolon",
        "valuePresentation":  "Value",
        "allowCodeInValue":   False,
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()

    df_raw = pd.read_csv(StringIO(resp.text), sep=";", decimal=",", thousands=".")

    # Locate value and time columns (DST uses Danish header "INDHOLD" or English "VALUE")
    val_col = next((c for c in df_raw.columns if c.upper() in ("INDHOLD", "VALUE")), df_raw.columns[-1])
    tid_col = next((c for c in df_raw.columns if c.upper() in ("TID", "TIME")), None)
    if tid_col is None:
        raise RuntimeError(f"DST {table}: no time column found in response")

    df_raw[val_col] = pd.to_numeric(df_raw[val_col], errors="coerce")
    df_raw = df_raw.dropna(subset=[val_col])

    def _to_ts(p: str):
        p = str(p).strip()
        try:
            if "M" in p:
                y, m = p.split("M");  return pd.Timestamp(f"{y}-{m.zfill(2)}-01")
            if "Q" in p:
                y, q = p.split("Q");  return pd.Timestamp(f"{y}-{((int(q)-1)*3+1):02d}-01")
            if len(p) == 4 and p.isdigit():
                return pd.Timestamp(f"{p}-01-01")
            return pd.Timestamp(p)
        except Exception:
            return pd.NaT

    df_raw["_ts"] = df_raw[tid_col].map(_to_ts)
    df_raw = df_raw.dropna(subset=["_ts"])
    df_raw = df_raw[df_raw["_ts"] >= pd.Timestamp(start)]

    # Sum across all remaining dimension combinations per period
    result = df_raw.groupby("_ts")[val_col].sum()
    if scale != 1.0:
        result = result / scale
    result.index.name = None
    return result.rename(label).to_frame()


def fetch_macro(task: dict) -> dict:
    fred = Fred(api_key=API_KEYS["fred"])
    dataframes: dict[str, pd.DataFrame] = {}
    kilde: list[str] = []
    period_days = max(
        (c.get("period_days", 365 * 3) for c in task.get("charts", [])),
        default=365 * 3
    )
    start = str(date.today() - timedelta(days=period_days))

    for s in task["series"]:
        label = s["label"]
        ticker = s["ticker"]
        source = s.get("source", "fred")

        if source == "dst":
            # Danmarks Statistik free public API
            # ticker = DST table code, dst_variables = filter list, dst_scale = unit divisor
            try:
                dst_vars  = s.get("dst_variables", [])
                dst_scale = float(s.get("dst_scale", 1.0))
                df = _dst_get(ticker, dst_vars, start, label, scale=dst_scale)
                df.index = pd.to_datetime(df.index)
                dataframes[label] = df
                if "Danmarks Statistik" not in kilde:
                    kilde.append("Danmarks Statistik")
            except Exception as e:
                print(f"    [macro] DST fetch failed for '{ticker}' ({label}): {e}")

        elif source == "imf":
            # Net International Investment Position via IMF SDMX JSON API
            # ticker = ISO-3 country code, e.g. "DEU", "CHN", "USA"
            try:
                series = _imf_get(ticker, start)
                df = series.to_frame(name=label)
                df.index = pd.to_datetime(df.index)
                dataframes[label] = df
                if "IMF" not in kilde:
                    kilde.append("IMF")
            except Exception as e:
                print(f"    [macro] IMF fetch failed for '{ticker}' ({label}): {e}")

        elif source == "yfinance":
            try:
                with YF_LOCK:
                    raw = yf.download(ticker, start=start, end=str(date.today()),
                                      progress=False, auto_adjust=True)
                if isinstance(raw.columns, pd.MultiIndex):
                    close = raw["Close"]
                    if isinstance(close, pd.DataFrame):
                        close = close.iloc[:, 0]
                    df = close.to_frame(name=label)
                else:
                    df = raw[["Close"]].rename(columns={"Close": label})
                if not df.empty:
                    dataframes[label] = df
                    if "Yahoo Finance" not in kilde:
                        kilde.append("Yahoo Finance")
            except Exception as e:
                print(f"    [macro] yfinance failed for '{ticker}' ({label}): {e}")
        else:
            # FRED series IDs must be ≤25 alphanumeric chars
            if len(ticker) > 25 or not ticker.replace("_", "").isalnum():
                print(f"    [macro] Skipping invalid FRED series_id '{ticker}' for '{label}'")
                continue
            try:
                series = _fred_get(fred, ticker, start)
                df = series.to_frame(name=label)
                df.index = pd.to_datetime(df.index)
                dataframes[label] = df
                if "FRED" not in kilde:
                    kilde.append("FRED")
            except Exception as e:
                # Auto-redirect: if label is a country name, the LLM likely intended IMF (NIIP)
                # Strip any " — suffix" the LLM may have appended (e.g. "USA — NIIP" → "USA")
                base = re.split(r'\s*[—–-]\s*', label)[0].strip()
                iso3 = _LABEL_TO_ISO3.get(label.lower()) or _LABEL_TO_ISO3.get(base.lower())
                if iso3:
                    print(f"    [macro] FRED failed for '{label}' — auto-redirecting to IMF (NIIP fallback)...")
                    try:
                        series = _imf_get(iso3, start)
                        df = series.to_frame(name=label)
                        df.index = pd.to_datetime(df.index)
                        dataframes[label] = df
                        if "IMF" not in kilde:
                            kilde.append("IMF")
                        continue
                    except Exception as e2:
                        print(f"    [macro] IMF fallback also failed for '{label}' ({iso3}): {e2}")
                print(f"    [macro] Failed to fetch FRED '{ticker}' ({label}) after retries: {e}")

    return {"dataframes": dataframes, "kilde": kilde,
            "chart_specs": task.get("charts", [])}
