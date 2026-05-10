# newsletter_agent/specialists/annual_report_market_researcher.py
"""
Market Researcher — fetches recent company news via FMP, filters for valuation-material
events using Claude, and returns a D-type chart spec. Cached for 30 days.
"""
from __future__ import annotations
import requests
from datetime import datetime, timedelta
import anthropic
from newsletter_agent.config import API_KEYS, REVIEWER_MODEL
from newsletter_agent.cache import get as cache_get, put as cache_put

_TTL = 30 * 24 * 3600   # 30-day cache
_FMP_V3 = "https://financialmodelingprep.com/api/v3"


def _fetch_news(ticker: str, api_key: str) -> list:
    cached = cache_get("market_news", _TTL, ticker=ticker)
    if cached is not None:
        print(f"  [market_researcher] Cache hit: {ticker}")
        return cached

    try:
        resp = requests.get(
            f"{_FMP_V3}/stock_news",
            params={"tickers": ticker, "limit": 50, "apikey": api_key},
            timeout=15,
        )
        if resp.status_code in (402, 403):
            print(f"  [market_researcher] FMP news requires a higher plan (HTTP {resp.status_code}) — skipping.")
            return []
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [market_researcher] News fetch failed: {e}")
        return []

    news = [n for n in (data if isinstance(data, list) else [])
            if ticker.upper() in (n.get("symbol", "") or "").upper()]
    print(f"  [market_researcher] Fetched {len(news)} ticker-matched items for {ticker}")
    if news:
        cache_put("market_news", news, ticker=ticker)
    return news


def fetch_market_researcher(
    ticker: str,
    company_name: str,
    client: anthropic.Anthropic,
) -> dict | None:
    """
    Returns a D-type chart spec with material news for the last 30 days,
    or None if no material news is found.
    """
    fmp_key = API_KEYS.get("fmp", "")
    if not fmp_key:
        print("  [market_researcher] No FMP key — skipping.")
        return None

    news = _fetch_news(ticker, fmp_key)
    if not news:
        print(f"  [market_researcher] No news returned for {ticker}.")
        return None

    # Filter to last 30 days client-side
    cutoff = datetime.now() - timedelta(days=30)
    recent = []
    for n in news:
        date_str = (n.get("publishedDate") or n.get("date") or "")[:10]
        try:
            if datetime.strptime(date_str, "%Y-%m-%d") >= cutoff:
                recent.append(n)
        except ValueError:
            pass

    if not recent:
        print(f"  [market_researcher] No news in last 30 days for {ticker}.")
        return None

    # Build headlines list for Claude
    news_text = "\n".join(
        f"- [{n.get('publishedDate', n.get('date', ''))[:10]}] {n.get('title', '')}"
        for n in recent[:40]
    )

    prompt = (
        f"Her er nyhedsoverskrifter for {company_name} ({ticker}) fra de seneste 30 dage:\n\n"
        f"{news_text}\n\n"
        f"Identificér max 5 nyheder der er materielt relevante for DCF-værdiansættelse. "
        f"Materielle nyheder inkluderer: resultatoverraskelser, guidancejusteringer, M&A-aktivitet, "
        f"kapitalallokering (tilbagekøb, udbytte, udstedelse), regulering eller ledelsesændringer. "
        f"Ignorer generelle markedskommentarer og irrelevante omtaler af virksomheden.\n\n"
        f"VIGTIGT: Oversæt ALTID overskrift og implikation til dansk — uanset originalsprog.\n\n"
        f"For hver materiel nyhed, returner præcis én linje:\n"
        f"DATO | KATEGORI | OVERSKRIFT (maks 6 ord — OVERSÆT TIL DANSK) | IMPLIKATION (maks 5 ord — OVERSÆT TIL DANSK)\n\n"
        f"Gyldige kategorier: Resultater | Guidance | M&A | Kapital | Regulering | Ledelse\n"
        f"Svar kun med linjerne. Hvis ingen materielle nyheder: skriv kun INGEN."
    )

    try:
        msg = client.messages.create(
            model=REVIEWER_MODEL,
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
    except Exception as e:
        print(f"  [market_researcher] Claude filtering failed: {e}")
        return None

    if not text or text.upper().startswith("INGEN"):
        print(f"  [market_researcher] No material news after filtering for {ticker}.")
        return None

    rows = []
    for line in text.splitlines():
        line = line.strip("- •").strip()
        if not line or line.upper() == "INGEN":
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4:
            rows.append({
                "indicator": parts[0],    # date as row label
                "Kategori":  parts[1],
                "Overskrift": parts[2],
                "Implikation": parts[3],
            })

    if not rows:
        print(f"  [market_researcher] Parsing produced no rows for {ticker}.")
        return None

    print(f"  [market_researcher] {len(rows)} material news item(s) for {ticker}.")
    return {
        "type": "D",
        "title": f"{company_name} — Markedsupdate (seneste 30 dage)",
        "note": (
            "Kun begivenheder med materiel relevans for DCF-værdiansættelse er inkluderet. "
            "Filtreret og oversat af AI. Kilde: FMP nyheder."
        ),
        "kilde": "FMP",
        "table_data": {"columns": ["Kategori", "Overskrift", "Implikation"], "rows": rows},
    }
