# newsletter_agent/orchestrator.py
import json
import re
import anthropic
from newsletter_agent.config import API_KEYS, LLM_MODEL

SYSTEM_PROMPT = """Du er en erfaren makroøkonom og ekspert i globale finansmarkeder.
Dit arbejde er at læse et emne-brief fra en makroresearchafdeling og producere en struktureret
dataindsamlingsplan til en newsletter-figur-pipeline.

SPROG: Dansk er det primære sprog. Engelsk er det sekundære sprog.
- Alle brugervendte tekstfelter i JSON-outputtet (title, note, col_before, col_after, event labels, y_label-tekster som "Indekseret (basis=100)") SKAL skrives på dansk.
- Tekniske identifikatorer (ticker, source, type, series_labels, specialist-navne) forbliver på engelsk — de er kodestrenge, ikke brugervendt tekst.
- Hvis briefen er skrevet på dansk, svar på dansk. Hvis briefen er på engelsk, producér stadig alle brugervendte tekstfelter på dansk.

Given a free-form topic brief, return a JSON TaskManifest with exactly this structure:
{
  "specialists": ["energy", "rates"],   // list of specialists needed — choose from: energy, rates, macro, commodities, equities, eurostat
  "energy": {                           // one key per specialist listed above
    "series": [
      {
        "ticker": "BZ=F",             // yfinance ticker OR fred series_id OR "eia" OR "gie"
        "source": "yfinance",         // "yfinance" | "fred" | "eia" | "gie"
        "label": "Brent Crude",       // human-readable label for chart legend
        "region": "Global",           // region label shown on chart
        "unit": "USD/barrel"          // exact unit string for axis label
      }
    ],
    "charts": [
      {
        "type": "A",                  // A=time series, B=cross-country bar, D=table, E=before-after bar, F=100%-stacked bar (energy mix), G=horizontal bar (sector/country ranking)
        "title": "Oil price, USD/barrel",
        "x_label": "Date",
        "y_label": "USD/barrel",
        "period_days": 365,           // how many days of history to fetch. Use >=760 when y_label contains "YoY"
        "series_labels": ["Brent Crude"],  // REQUIRED: exact label strings from this specialist's series list that belong on THIS chart
        "note": "Daily closing prices for Brent and WTI crude. Brent is the global benchmark; WTI reflects US market conditions.",
        "events": [                   // OPTIONAL: specific events mentioned in the brief that should be marked with a vertical line.
          {"date": "2022-02-24", "label": "Russia invades Ukraine"}
        ]
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
Bond yields (already in % — do NOT apply YoY):
  IRLTLT01EZM156N (Eurozone 10Y bond yield, monthly %)
  IRLTLT01DEM156N (Germany 10Y Bund, monthly %)
  IRLTLT01GBM156N (UK 10Y Gilt, monthly %)
  IRLTLT01FRM156N (France 10Y OAT, monthly %)
  IRLTLT01ITM156N (Italy 10Y BTP, monthly %)
Other:
  CLVMEURSCAB1GQEA19 (Eurozone real GDP, quarterly)
  LRHUTTTTEZM156S (Eurozone unemployment rate, monthly)

US ENERGY MIX — EIA (US Energy Information Administration, free API):
Use specialist "energy" with source="eia" to fetch individual US energy series by MSN code:
  - PATOBUS  (Petroleum — total US consumption, Quadrillion BTU, annual)
  - NNTCBUS  (Natural gas — total US consumption, Quadrillion BTU, annual)
  - CLTCBUS  (Coal — total US consumption, Quadrillion BTU, annual)
  - NUETBUS  (Nuclear — total US electricity consumption, Quadrillion BTU, annual)
  - RETCBUS  (Renewables — total US consumption, Quadrillion BTU, annual)
Use source="eia_mix" with a single series entry (label="Energimix USA") to auto-fetch ALL five
sources above as a single wide DataFrame ready for a Type F stacked chart. No msn_codes needed.
Example eia_mix series entry:
  {"ticker": "eia_mix", "source": "eia_mix", "label": "Energimix USA", "unit": "Quadrillion BTU"}
Example Type F chart spec for energy mix:
  {"type": "F", "title": "Sammensætning af USA's energiforbrug", "x_label": "År",
   "y_label": "Pct. af total", "period_days": 3650, "series_labels": ["Energimix USA"],
   "note": "USA's samlede energiforbrug opdelt på brændstofstype. Kilde: EIA."}

EU STATISTICAL DATA — Eurostat (free, no API key):
Use specialist "eurostat" with the following dataset shortcuts (set "ticker" to the shortcut name):
  "eu_energy_mix"   → EU27 energy consumption by product (stacked/composition, Type F)
  "eu_gdp_growth"   → EU27 real GDP growth (annual %, Type A or B)
  "eu_unemployment" → EU27 unemployment rate (monthly %, Type A)
  "eu_hicp"         → EU27 HICP inflation (monthly % change, Type A)
Or provide a raw Eurostat dataset ID in "ticker" with custom "params" dict.
Source type: "eurostat_ts" for time series, "eurostat_mix" for cross-sectional (Type F/G).
Example eurostat entry:
  {"ticker": "eu_unemployment", "source": "eurostat_ts", "label": "EU27 ledighed (%)", "unit": "%"}

NOT available: GIE gas storage, CME FedWatch probability data, Bloomberg data, BlackRock, JPMorgan, ICE real-time data

Rules:
- Maximum 2 charts per specialist.
- Only activate specialists whose data is genuinely relevant to the brief.
- REQUIRED: Every chart spec MUST include a "series_labels" array listing the exact label strings
  (from the series list above) that should appear on that chart. Each label must appear in exactly
  one chart. Do NOT omit series_labels — the pipeline uses it to isolate data per chart.
- Default period_days = 730 (2 years) for all charts. This gives a richer x-axis context.
  Use 365 only for very short-term event analysis (e.g. past 6 months of a crisis).
  For any chart where y_label contains "YoY", set period_days to at least 760. Monthly FRED data
  needs 13+ months of history before pct_change(12) produces a single valid value; 760 days gives
  ~25 months which is sufficient.
- CRITICAL — HISTORICAL START DATE: When the user specifies a historical start period
  (e.g. "from 2022", "since 2020", "from January 2022", "fra 2022", "since the Ukraine war
  in 2022", "over the past 5 years"), set period_days to fully cover that period.
  Formula: period_days = days_from_start_date_to_today + 60.
  Examples (today = April 2026):
    "from 2022"       → Jan 1 2022 = ~1566 days ago → period_days = 1626
    "from 2020"       → Jan 1 2020 = ~2297 days ago → period_days = 2357
    "past 5 years"    → Apr 2021   = ~1826 days ago → period_days = 1886
  NEVER use period_days=730 when the user explicitly asks for data going back before 2 years ago.
- CRITICAL — INDEX BASE DATE: When the user specifies a start date for base-100 indexing
  (e.g. "indexed to 100 from January 2025", "starter i 2025 på index 100", "1. jan 2025 = 100",
  "from February 2022", "index 100 at start of 2024"), you MUST:
  (a) Add "index_base_date": "YYYY-MM-DD" to the chart spec with that exact date.
  (b) Set period_days = max(730, days_from_that_date_to_today + 60) so the data window
      definitely includes the base date. Example: user says "start January 2025", today is
      April 2026 → that is ~470 days ago → period_days = max(730, 470+60) = 730. Another
      example: user says "from February 2022", today is April 2026 → ~1510 days ago →
      period_days = max(730, 1510+60) = 1570.
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
  "Indekseret (basis=100)" — the pipeline will normalize all series to 100 at the start date.
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
- Each event: {"date": "YYYY-MM-DD", "label": "Kort dansk label (maks. 5 ord)"}.
- Add the events array to EVERY chart spec whose date range covers that event date.
- If no explicitly-dated events are mentioned, omit the "events" field entirely.
- CRITICAL: period_days MUST cover the event date with at least 30 days of history before it.
  Formula: period_days = max(default_period, days_from_event_date_to_today + 60).
  Example: if event is 2 April 2025 and today is 16 April 2026, that is 379 days ago,
  so period_days must be at least 379 + 60 = 439. Never use a period_days that places
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
