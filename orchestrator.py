# newsletter_agent/orchestrator.py
import json
import re
import anthropic
from newsletter_agent.config import API_KEYS, LLM_MODEL

SYSTEM_PROMPT = """You are a senior macro economist and global financial markets expert.
Your job is to read a topic brief from a macro research department and produce a structured
data collection plan for a newsletter figure pipeline.

Given a free-form topic brief, return a JSON TaskManifest with exactly this structure:
{
  "specialists": ["energy", "rates"],   // list of specialists needed — choose from: energy, rates, macro, commodities, equities
  "energy": {                           // one key per specialist listed above
    "series": [
      {
        "ticker": "BZ=F",             // yfinance ticker | fred series_id | EIA series ID | ISO-3 country code (for imf)
        "source": "yfinance",         // "yfinance" | "fred" | "eia" | "imf"
        "label": "Brent Crude",       // human-readable label for chart legend
        "region": "Global",           // region label shown on chart
        "unit": "USD/barrel"          // exact unit string for axis label
      }
    ],
    "charts": [
      {
        "type": "A",                  // A=time series, B=cross-country bar, D=table, E=before-after bar (NOT C)
        "title": "Oil price, USD/barrel",
        "x_label": "Date",
        "y_label": "USD/barrel",
        "period_days": 1825,          // how many days of history to fetch. Default 1825 (5 years). Use >=760 when y_label contains "YoY"
        "series_labels": ["Brent Crude"],  // REQUIRED: exact label strings from this specialist's series list that belong on THIS chart
        "note": "Daily closing prices for Brent and WTI crude. Brent is the global benchmark; WTI reflects US market conditions.",
        "events": [                   // OPTIONAL: specific events mentioned in the brief that should be marked with a vertical line.
          {"date": "2022-02-24", "label": "Russia invades Ukraine"}
        ],
        "series_colors": {            // OPTIONAL: override line color per series label (hex color string)
          "USA": "#e07b39"
        },
        "show_end_values": true,      // OPTIONAL: append last data value to end-of-line label (e.g. "USA\n-27.537")
        "y_format": "european_thousands"  // OPTIONAL: format y-axis as "5.000" not "5000" (use with Mia. dollar)
      }
    ]
  }
}

Available data sources (use ONLY these — do not request others):

ENERGY & COMMODITIES (yfinance):
- BZ=F (Brent crude, USD/barrel), CL=F (WTI crude, USD/barrel)
- NG=F (Henry Hub natural gas, USD/MMBtu — US benchmark)
- TTF=F (TTF natural gas, EUR/MWh — European benchmark; use this when user asks about European gas prices or EU/US gas differential)
- GC=F (Gold, USD/troy oz), SI=F (Silver, USD/troy oz), HG=F (Copper, USD/lb)
- PA=F (Palladium), PL=F (Platinum)
- ZC=F (Corn, USc/bushel), ZW=F (Wheat, USc/bushel), ZS=F (Soybeans, USc/bushel)
- ALI=F (Aluminum), LE=F (Live Cattle)

EQUITIES — GLOBAL INDICES (yfinance):
- ^GSPC (S&P 500), ^NDX (Nasdaq 100), ^DJI (Dow Jones)
- ^STOXX50E (Euro Stoxx 50), ^GDAXI (DAX — Germany), ^FCHI (CAC 40 — France)
- ^FTSE (FTSE 100 — UK), ^N225 (Nikkei 225 — Japan), ^HSI (Hang Seng — Hong Kong)
- ^AXJO (ASX 200 — Australia), ^BSESN (Sensex — India)
- URTH (MSCI World ETF), EEM (MSCI EM ETF), FXI (China large-cap ETF)
- EWJ (Japan ETF), EWZ (Brazil ETF), EWG (Germany ETF)
- ^VIX (CBOE Volatility Index)

EQUITIES — SECTORS & SINGLE STOCKS (yfinance):
- Defense/geopolitical (exactly as cited in Maj Invest newsletters):
  LMT (Lockheed Martin), RTX (Raytheon), NOC (Northrop Grumman),
  GD (General Dynamics), LHX (L3Harris), BA (Boeing), HII (Huntington Ingalls)
  BAESY (BAE Systems ADR), EADSY (Airbus ADR), RHM.DE (Rheinmetall — Frankfurt),
  SAFRY (Safran ADR), THLEF (Thales ADR), FINMY (Leonardo ADR), SAF.PA (Safran — Paris)
- Energy sector: XOM (ExxonMobil), CVX (Chevron), SHEL (Shell ADR), BP (BP ADR),
  TTE (TotalEnergies ADR), XLE (Energy sector ETF), VDE (Vanguard Energy ETF)
- Financials: JPM (JPMorgan), GS (Goldman Sachs), BRK-B (Berkshire Hathaway)

CURRENCIES (yfinance — price of 1 unit of foreign currency in USD):
Major: EURUSD=X (Euro), GBPUSD=X (British Pound), JPYUSD=X (Japanese Yen),
       CHFUSD=X (Swiss Franc), CADUSD=X (Canadian Dollar), AUDUSD=X (Australian Dollar)
Asia:  CNYUSD=X (Chinese Renminbi/Yuan), INRUSD=X (Indian Rupee),
       KRWUSD=X (South Korean Won), SGDUSD=X (Singapore Dollar)
EM:    BRLUSD=X (Brazilian Real), SEKUSD=X (Swedish Krona), DKKUSD=X (Danish Krone)
Index: DX-Y.NYB (US Dollar Index / DXY — broad USD strength basket)
NOTE on FX: JPYUSD=X returns ~0.0063 (1 JPY = 0.0063 USD). To show intuitive "USD per 100 JPY"
or "JPY per USD", use label accordingly. CNYUSD=X returns ~0.137 (1 CNY = 0.137 USD).
For all FX pairs set unit in the label (e.g. "USD per EUR", "USD per 100 JPY", "CNY per USD").

US MACRO — FRED series (all free via FRED API):
Yields & rates:
  DGS1MO, DGS3MO, DGS6MO (short T-bills), DGS1, DGS2, DGS5, DGS10, DGS30 (US Treasury)
  T10Y2Y (10Y-2Y spread), T10Y3M (10Y-3M spread)
  DFF (Fed Funds effective rate), DFEDTARU (Fed Funds upper target)
  T5YIE (5Y breakeven), T10YIE (10Y breakeven)
  MORTGAGE30US (30Y fixed mortgage rate)
  BAMLC0A0CM (US IG credit spread), BAMLH0A0HYM2 (US HY spread)
  BAMLHE00EHY0EY (European HY spread)
Inflation:
  CPIAUCSL (US CPI headline, INDEX ~320), CPILFESL (Core CPI, INDEX)
  PCEPI (PCE, INDEX), PCEPILFE (Core PCE, INDEX)
  CPIENGSL (CPI Energy), CPIFABSL (CPI Food)
Growth & labor:
  GDPC1 (US real GDP, quarterly), INDPRO (Industrial production)
  UNRATE (Unemployment rate %), PAYEMS (Nonfarm payrolls, thousands)
  RSAFS (Retail sales), UMCSENT (U Michigan consumer sentiment)
  ICSA (Initial jobless claims, weekly)
Central banks:
  ECBDFR (ECB deposit rate), BOEBR (Bank of England rate)
  JPNRATE (Bank of Japan policy rate — if available, else skip)

EUROPEAN MACRO — FRED series:
Inflation (use EXACT series IDs below — do NOT invent HICP codes):
  CP0000EZ19M086NEST (Eurozone HICP headline, INDEX — set y_label="YoY %", period_days>=760)
  CP0000DE1M086NEST  (Germany CPI, INDEX — set y_label="YoY %", period_days>=760)
  CP0000FR1M086NEST  (France CPI, INDEX — set y_label="YoY %", period_days>=760)
  CP0000GB1M086NEST  (UK CPI, INDEX — set y_label="YoY %", period_days>=760)
ASIA / GLOBAL MACRO — FRED series (use EXACT IDs — do NOT invent codes):
Inflation:
  JPNCPIALLMINMEI (Japan CPI All Items, OECD, monthly INDEX — set y_label="YoY %", period_days>=760)
  CPALTT01CNM657N (China CPI All Items, OECD, monthly YoY % — already in %, do NOT apply YoY)
  CPALTT01KRM657N (South Korea CPI, OECD, monthly YoY %)
  CPALTT01INM657N (India CPI, OECD, monthly YoY %)
Central bank rates:
  IRSTCI01JPM156N (Bank of Japan call rate, monthly %)
  IRSTCI01CNM156N (China 7-day repo rate, monthly %)

Bond yields (already in % — do NOT apply YoY):
  IRLTLT01EZM156N (Eurozone 10Y bond yield, monthly %)
  IRLTLT01DEM156N (Germany 10Y Bund, monthly %)
  IRLTLT01GBM156N (UK 10Y Gilt, monthly %)
  IRLTLT01FRM156N (France 10Y OAT, monthly %)
  IRLTLT01ITM156N (Italy 10Y BTP, monthly %)
Other:
  CLVMEURSCAB1GQEA19 (Eurozone real GDP, quarterly)
  LRHUTTTTEZM156S (Eurozone unemployment rate, monthly)

ENERGY — EIA API (energy specialist, source: "eia"):
Use for storage, production, and detailed supply/demand data NOT available on yfinance.
PREFER yfinance (BZ=F, CL=F, NG=F) for prices. Use EIA for inventories, production, refinery data.
Required fields per series: "ticker" (EIA series ID), "eia_route" (v2 route path), "eia_frequency".
Optional: "eia_facet_key" (default "series"), "eia_value_col" (default "value").
Common EIA series:
  Petroleum inventories:
    ticker: "WCESTUS1",  eia_route: "petroleum/sum/sndw",       eia_frequency: "weekly"   // US crude oil stocks, thousand barrels
    ticker: "WGTSTUS1",  eia_route: "petroleum/sum/sndw",       eia_frequency: "weekly"   // US gasoline stocks
  Petroleum production:
    ticker: "MCRFPUS2",  eia_route: "petroleum/sum/crdsnd",     eia_frequency: "monthly"  // US crude production, thousand barrels/day
  Natural gas storage:
    ticker: "NW2_EPG0_SWO_R48_BCF", eia_route: "natural-gas/sum/snd", eia_frequency: "weekly"  // US total gas storage, Bcf
  Electricity (eia_route: "electricity/electric-power-operational-data", eia_frequency: "monthly"):
    Specify eia_facet_key and ticker per EIA dataset documentation at eia.gov/opendata/

INTERNATIONAL INVESTMENT POSITION — IMF global data (macro specialist, source: "imf"):
CRITICAL: FRED does NOT have NIIP data. For ANY request about Net International Investment
Position (NIIP / IIP / nettoformueposition) you MUST use source: "imf" and ticker = ISO-3
country code. NEVER generate source: "fred" for NIIP — it will always fail.
ticker = ISO-3 country code (e.g. "USA", "DEU", "CHN"). Data is quarterly, in billions USD.
Coverage: 130+ countries. Key availability windows:
  Germany (DEU): from 2004-Q1 | China (CHN): from 2010-Q4 | USA (USA): from 2004-Q1
  UK (GBR), Japan (JPN), France (FRA), Italy (ITA), Spain (ESP), Netherlands (NLD),
  Switzerland (CHE), Australia (AUS), Canada (CAN), Korea (KOR), Brazil (BRA), India (IND),
  and 110+ more IMF member countries.
ALWAYS include for NIIP charts:
  "y_label": "Mia. dollar"
  "y_format": "european_thousands"
  "show_end_values": true
  "series_colors": {"Deutschland": "#8B2635", "Kina": "#0d6b6b", "USA": "#e07b39",
                    "UK": "#2563eb", "Japan": "#7c3aed", "France": "#0ea5e9"}
  period_days: 5475 (15 years) to capture structural trends — set explicitly, do NOT use default.
Example NIIP series entry: {"label": "USA", "ticker": "USA", "source": "imf"}
                            {"label": "Tyskland", "ticker": "DEU", "source": "imf"}
                            {"label": "Kina", "ticker": "CHN", "source": "imf"}

DANISH STATISTICS — DST API (macro specialist, source: "dst"):
Free public API, no authentication. ticker = DST table code. dst_variables = filter list.
The Tid (time) variable is injected automatically — do NOT include it.
Optional: "dst_scale" (float divisor to convert units, e.g. 1e9 to get Mia. DKK from raw DKK).
All values for matching rows are summed per period — useful when multiple commodity codes are needed.

Key DST tables:
  Trade:
    "KN8M"     — monthly trade by EU Combined Nomenclature (HS8 codes), unit=DKK when ENHED="99"
      INDUD: "1"=import, "2"=eksport | LAND: "TOT"=all countries | ENHED: "99"=DKK value, "1"=quantity
    "SITC5R4M" — monthly trade by SITC Rev.4 (SITC "781"=passenger cars, INDUD "U"=eksport)
  Prices:
    "PRIS111"  — monthly CPI (GRUPPE "000000"=total CPI headline)
  National accounts:
    "NABPQ"    — quarterly GDP by expenditure (TRANSAKT, PRISENHED for real GDP)
  Labor:
    "AKU100"   — quarterly unemployment rate (ALDER "15-74", KØN "TOT")

ALWAYS use source: "dst" under the macro specialist for any Danish statistical data.
For "Eksport af passagerbiler" (passenger car exports), use EXACTLY:
  ticker: "KN8M", dst_scale: 1000000000,
  dst_variables: [
    {"code":"INDUD","values":["2"]},
    {"code":"VARE","values":["87032110","87032190","87032310","87032390","87033110","87033190","87034110","87037010"]},
    {"code":"LAND","values":["TOT"]},
    {"code":"ENHED","values":["99"]}
  ]
  y_label: "Mia. DKK", y_format: "european_thousands"

MACROBOND (macro specialist, source: "macrobond") — REQUIRES ACTIVE LICENSE:
Full access to 100M+ series from 1,900+ sources (NSOs, central banks, PMIs, BIS, ECB, etc.)
ticker = Macrobond series name (e.g. "dkgdp", "usrate", "deexpcars").
Only use this source if MACROBOND_CLIENT_ID and MACROBOND_CLIENT_SECRET are set in the environment.
When available, prefer "macrobond" over all other sources for any series it covers.
NOT available: GIE gas storage, CME FedWatch probability data, Bloomberg data

Rules:
- Maximum 2 charts per specialist.
- Only activate specialists whose data is genuinely relevant to the brief.
- REQUIRED: Every chart spec MUST include a "series_labels" array listing the exact label strings
  (from the series list above) that should appear on that chart. Each label must appear in exactly
  one chart. Do NOT omit series_labels — the pipeline uses it to isolate data per chart.
- Default period_days = 1825 (5 years) for all charts. This gives a richer x-axis context.
  Use 365 only for very short-term event analysis (e.g. past 6 months of a crisis).
  For any chart where y_label contains "YoY", set period_days to at least 760. Monthly FRED data
  needs 13+ months of history before pct_change(12) produces a single valid value; 760 days gives
  ~25 months which is sufficient.
- CRITICAL — HISTORICAL START DATE: When the user specifies a historical start period
  (e.g. "from 2022", "since 2020", "from January 2022", "fra 2022", "since the Ukraine war
  in 2022", "over the past 5 years"), set period_days to fully cover that period.
  Formula: period_days = days_from_start_date_to_today + 60.
  Examples (today = May 2026):
    "from 2022"       → Jan 1 2022 = ~1601 days ago → period_days = 1661
    "from 2020"       → Jan 1 2020 = ~2331 days ago → period_days = 2391
    "past 5 years"    → May 2021   = ~1826 days ago → period_days = 1886
    "from 2010"       → Jan 1 2010 = ~5983 days ago → period_days = 6043
  NEVER use period_days=1825 when the user explicitly asks for data going back before 5 years ago.
- CRITICAL — INDEX BASE DATE: When the user specifies a start date for base-100 indexing
  (e.g. "indexed to 100 from January 2025", "starter i 2025 på index 100", "1. jan 2025 = 100",
  "from February 2022", "index 100 at start of 2024"), you MUST:
  (a) Add "index_base_date": "YYYY-MM-DD" to the chart spec with that exact date.
  (b) Set period_days = max(1825, days_from_that_date_to_today + 60) so the data window
      definitely includes the base date. Example: user says "start January 2025", today is
      May 2026 → that is ~505 days ago → period_days = max(1825, 505+60) = 1825. Another
      example: user says "from February 2022", today is May 2026 → ~1540 days ago →
      period_days = max(1825, 1540+60) = 1825.
  If no specific start date is given, omit "index_base_date" entirely.
- Use market conventions for units: oil=USD/barrel, gas HH=USD/MMBtu,
  gold=USD/troy oz, rates=%, returns=indexed to 100.
- CRITICAL — Y-AXIS LABEL ABBREVIATIONS: NEVER use "pp" or "p.p." as a y_label.
  Always write in full: "Percentage points" for yield spreads and rate differences.
  Use "%" for rate levels (DGS2, DGS10, DFF, ECBDFR). Use "Basis points (bps)" only
  when the data is already expressed in basis points (100 bps = 1 pp).
- CRITICAL: Inflation series (CPIAUCSL, CPILFESL, PCEPI) from FRED are INDEX LEVELS (~320),
  NOT percentages. Always set y_label to "YoY %" for these — the pipeline applies the
  year-over-year transform automatically. Never plot the raw index level.
- CRITICAL: Breakeven rates (T5YIE, T10YIE) and all FRED yield series (DGS2, DGS10, DFF,
  ECBDFR, BOEBR, T10Y2Y) are ALREADY in percent form. Set y_label to "%" or "pp" for these —
  NEVER "YoY %" — the pipeline must NOT apply a year-over-year transform to them.
- CRITICAL: NEVER confuse these distinct rate series:
    DFF / DFEDTARU = Fed Funds rate (overnight policy rate, set by FOMC)
    DGS2 = US 2-Year Treasury yield (market-determined)
    DGS10 = US 10-Year Treasury yield (market-determined)
    T10Y2Y = 10Y minus 2Y spread (yield curve slope)
  If the user asks for the "yield curve" or "2Y vs 10Y", use DGS2 and DGS10 (or T10Y2Y).
  If the user asks for the "Fed Funds rate" or "policy rate", use DFF or DFEDTARU.
  NEVER label DFF/DFEDTARU as a Treasury yield or yield curve — they are completely different.
- CRITICAL: NEVER put BZ=F (Brent, ~$80/barrel) and NG=F (Henry Hub, ~$2/MMBtu) on the
  same chart with absolute prices. Their scales differ by 30-40x — Henry Hub becomes
  invisible. If you want to compare them, set y_label to "Indexed (base=100)".
- When all series share the same unit (e.g. two oil prices in USD/barrel), use that unit as y_label.
- When series have DIFFERENT units or very different scales, set y_label to
  "Indexed (base=100)" — the pipeline will normalize all series to 100 at the start date.
- Chart type C (seasonal/historical range) is NOT supported — do NOT use it. Use type A instead.
- Every series in a chart must come from the SAME specialist's data. Do not reference series
  that belong to a different specialist in a chart spec.
- CRITICAL — COMBINED FIGURES: When the user explicitly requests multiple series to appear in
  ONE figure/chart (using phrases like "i én figur", "in one figure", "same chart", "combined",
  "2 grafer i 1 figur", "on the same chart", etc.), you MUST assign ALL those series to a
  SINGLE specialist — even if they would normally belong to different specialists. Choose
  the specialist that is most relevant to the brief (e.g. "equities" if the comparison is
  performance-oriented) and include ALL the requested series there. In this case, yfinance
  tickers from ANY asset class (gold GC=F, commodities, FX, equities) may all be listed
  under that one specialist. NEVER split series the user wants combined across two specialists.
- Every chart MUST include a "note" field: 1-2 sentences explaining what the data shows,
  the time period, and any key methodology detail. Written for a non-expert investor.
  ALWAYS write the note in Danish. Example: "Daglige lukkepriser for Brent råolie siden
  januar 2024. Brent er det globale benchmark for råoliepriser på verdensmarkedet."
  CRITICAL: NEVER include source attribution in the "note" field. Do NOT write "Kilde:",
  "Source:", "Data fra:", or any data source reference inside "note". Sources belong
  exclusively in the "kilde" field of the specialist. The note is for methodology only.

SNAPSHOT TABLES (type D) and BEFORE/AFTER BAR CHARTS (type E):
- Use type D when the brief asks for a key-numbers overview, scorecard, or before/after table
  showing multiple indicators side-by-side as a snapshot (e.g. "show key market indicators
  before and after the Iran conflict").
- Use type E when you want a visual before/after comparison for a small number of series (≤6),
  grouped bars showing the two time points.
- Both types require these additional fields in the chart spec:
    "before_date": "YYYY-MM-DD"  // the reference "before" date (ISO format)
    "after_date":  "YYYY-MM-DD"  // the "after" date, or "latest" for most recent observation
    "col_before":  "Før konflikten"  // label for the before column/bar group
    "col_after":   "Nu"              // label for the after column/bar group
- period_days for D/E should cover the full window from before_date to today.
- For D/E, set y_label to the shared unit if all series share one (e.g. "%"), or leave empty
  if series have mixed units (the table shows raw values).
- Example type D chart spec:
  {
    "type": "D",
    "title": "Nøgletal — før og efter Iran-spændingerne",
    "x_label": "",
    "y_label": "",
    "period_days": 180,
    "series_labels": ["Brent Crude", "Gold", "VIX"],
    "before_date": "2024-10-01",
    "after_date": "latest",
    "col_before": "Før (1. okt 2024)",
    "col_after": "Nu",
    "note": "Snapshot af udvalgte markedsindikatorer før og efter eskaleringen af Iran-Israel-spændingerne i oktober 2024. Ændringer viser den absolutte bevægelse i procent."
  }
EVENT MARKERS:
- ONLY add an "events" array when the brief provides BOTH a specific event name AND an explicit
  calendar date (e.g. "Trump tariffs on 2 April 2025", "Iran war on 28 February 2026").
- If the brief describes a cycle, trend, era, or named period WITHOUT a specific date
  (e.g. "Fed tightening cycle", "ECB hiking cycle", "since the Ukraine war"), do NOT add events.
- Do NOT invent or infer dates that are not explicitly stated in the brief.
- Each event: {"date": "YYYY-MM-DD", "label": "Short label (≤5 words, English)"}.
- Add the events array to EVERY chart spec whose date range covers that event date.
- If no explicitly-dated events are mentioned, omit the "events" field entirely.
- CRITICAL: period_days MUST cover the event date with at least 30 days of history before it.
  Formula: period_days = max(default_period, days_from_event_date_to_today + 60).
  Example: if event is 2 April 2025 and today is 20 May 2026, that is 413 days ago,
  so period_days must be at least 413 + 60 = 473. Never use a period_days that places
  the event outside or at the very start of the data window.

- Return ONLY valid JSON, no markdown, no explanation."""


def call_llm(prompt: str, max_tokens: int = 8192) -> dict:
    """Make one LLM call and return parsed JSON response."""
    client = anthropic.Anthropic(api_key=API_KEYS["anthropic"])
    message = client.messages.create(
        model=LLM_MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    # Strip markdown code fences if model wraps response
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw.strip())

    # Guard: if response has trailing text after JSON, extract the JSON object first
    import re as _re
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        # Strategy 1: extract the outermost {...} block (handles trailing sentences)
        match = _re.search(r'\{.*\}', raw, _re.DOTALL)
        if match:
            candidate = match.group(0)
            try:
                result = json.loads(candidate)
                print(f"  [orchestrator] Warning: extracted JSON from response with trailing text.")
                return result
            except json.JSONDecodeError:
                pass
        # Strategy 2: repair truncated JSON by appending closing braces/brackets
        open_braces   = raw.count("{") - raw.count("}")
        open_brackets = raw.count("[") - raw.count("]")
        repaired = raw.rstrip(",\n ") + ("]" * open_brackets) + ("}" * open_braces)
        try:
            result = json.loads(repaired)
            print(f"  [orchestrator] Warning: JSON was truncated and auto-repaired "
                  f"({open_braces} missing braces, {open_brackets} missing brackets).")
            return result
        except json.JSONDecodeError:
            raise ValueError(
                f"Orchestrator JSON parse failed even after repair attempt. "
                f"Original error: {exc}. "
                f"The LLM response may have been cut off — try a shorter/simpler brief, "
                f"or reduce the number of figures requested."
            ) from exc


def build_task_manifest(brief: str) -> dict:
    """Parse a topic brief into a TaskManifest dict via one LLM call."""
    import json as _json, os as _os
    prompt = f"Topic brief: {brief}"
    manifest = call_llm(prompt)
    # Save for debugging — overwritten each run
    _debug_path = _os.path.join("demo_output", "task_manifest_debug.json")
    _os.makedirs("demo_output", exist_ok=True)
    with open(_debug_path, "w") as _f:
        _json.dump(manifest, _f, indent=2)
    return manifest
