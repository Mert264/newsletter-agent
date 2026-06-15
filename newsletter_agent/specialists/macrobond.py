# newsletter_agent/specialists/macrobond.py
"""
Macrobond specialist — REQUIRES a Macrobond Data Feed (Web API) license.

────────────────────────────────────────────────────────────────────────────
SETUP (one-time, when license is obtained):
1. pip install macrobond-data-api
2. Add to .env:
     MACROBOND_CLIENT_ID=<your_client_id>
     MACROBOND_CLIENT_SECRET=<your_client_secret>
3. Add "macrobond" to API_KEYS in config.py:
     "macrobond_client_id":     os.getenv("MACROBOND_CLIENT_ID", ""),
     "macrobond_client_secret": os.getenv("MACROBOND_CLIENT_SECRET", ""),
4. Wire into pipeline.py SPECIALIST_MAP:
     "macrobond": fetch_macrobond,
5. Then the orchestrator can use source: "macrobond" for any Macrobond series ID.

HOW TO GET CREDENTIALS:
- Contact your Macrobond account manager and ask for "Data Feed" or "Web API" access.
- If your organisation has a Data+ desktop subscription, request the Web API add-on.
- Macrobond will provision a client_id + client_secret via their OAuth2 portal.

COM CLIENT ALTERNATIVE (if Data+ desktop is installed on this machine):
- Replace WebClient with ComClient — no credentials needed.
- from macrobond_data_api.com import ComClient
- ComClient only works on the same Windows machine as the installed desktop app.
────────────────────────────────────────────────────────────────────────────
"""

import pandas as pd
from datetime import date, timedelta


def fetch_macrobond(task: dict) -> dict:
    """
    Fetch series from Macrobond using the official Python client.
    Returns SpecialistResult dict compatible with the newsletter pipeline.

    Series spec format in the task manifest:
      {
        "source": "macrobond",
        "ticker": "dkgdp",          // Macrobond series name (not case-sensitive)
        "label":  "Denmark GDP",
        "region": "Denmark"
      }
    """
    try:
        from macrobond_data_api.web import WebClient
        from newsletter_agent.config import API_KEYS
    except ImportError:
        raise RuntimeError(
            "macrobond-data-api is not installed. Run: pip install macrobond-data-api\n"
            "See newsletter_agent/specialists/macrobond.py for full setup instructions."
        )

    client_id     = API_KEYS.get("macrobond_client_id", "")
    client_secret = API_KEYS.get("macrobond_client_secret", "")
    if not client_id or not client_secret:
        raise RuntimeError(
            "MACROBOND_CLIENT_ID / MACROBOND_CLIENT_SECRET not set in .env\n"
            "See newsletter_agent/specialists/macrobond.py for setup instructions."
        )

    period_days = max(
        (c.get("period_days", 1825) for c in task.get("charts", [])),
        default=1825
    )
    start = str(date.today() - timedelta(days=period_days))

    dataframes: dict[str, pd.DataFrame] = {}
    kilde: list[str] = []

    with WebClient(client_id, client_secret) as api:
        for s in task["series"]:
            label  = s["label"]
            ticker = s["ticker"]
            try:
                series = api.get_one_series(ticker)
                sr = series.values_to_pd_series()
                sr.name = label
                # Filter to requested start date
                sr.index = pd.to_datetime(sr.index)
                sr = sr[sr.index >= pd.Timestamp(start)]
                dataframes[label] = sr.to_frame()
                if "Macrobond" not in kilde:
                    kilde.append("Macrobond")
            except Exception as e:
                print(f"    [macrobond] Failed to fetch '{ticker}' ({label}): {e}")

    return {
        "dataframes": dataframes,
        "kilde":      kilde,
        "chart_specs": task.get("charts", []),
    }
