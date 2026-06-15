"""
Hybrid dataset routing: deterministic keyword rules produce a routing_hint string
that is injected into the orchestrator prompt. LLM can override if data contradicts.
"""
from __future__ import annotations
import re


def _re(pattern: str):
    return re.compile(pattern, re.IGNORECASE)


_EU   = _re(r"\b(eu|europe[an]*|eurozone|europ[aæ]|eu27)\b")
_ANNUAL = re.compile(
    r"\b(annual report|årsrapport|årsregnskab|valuation|værdiansættelse|dcf|wacc|"
    r"aktiekurs|fair value|selskabsanalyse|fundamental|penman)\b",
    re.IGNORECASE,
)
_US   = _re(r"\b(us|usa|american?|united states|amerikans?k)\b")
_NRG  = _re(r"\b(energy|energi|energimix|brændstofstype|fuel|forbrug)\b")
_GAS  = _re(r"\b(gas|naturgas|natural gas)\b")
_TTF  = _re(r"\bttf\b")
_HH   = _re(r"\b(henry hub|hh)\b")
_INFL = _re(r"\b(inflation|hicp|prisvækst)\b")
_UNEM = _re(r"\b(unemployment|ledighed|arbejdsløs)\b")
_GDP  = _re(r"\b(gdp|bnp|growth|vækst)\b")
_EMPL = re.compile(
    r"beskæftigelse|jobvækst|jobrapport|lønmodtager"
    r"|\bpayroll\b|\bnonfarm\b|\bjobs added\b|\barbejdspladser\b|\bemployment report\b",
    re.IGNORECASE,
)
# Country economy keyword — fires only with an economy keyword AND a non-EU/US context
_COUNTRY_ECON_KW = _re(r"\b(økonomi|makroprofil|makroøkonomisk|landeprofil|bnp|inflation i|gæld|betalingsbalance|arbejdsløshed i|ledighed i)\b")
_IMF   = _re(r"\b(imf|international monetary fund|weo|world economic outlook|ifs|balance of payments|betalingsbalance|gæld til bnp|statsgæld|government debt|financial soundness|fsi)\b")
_TRADE = _re(r"\b(trade balance|handelsbalance|eksport|import|current account|løbende konto|dots|direction of trade)\b")
# Scorecard / multi-asset dashboard — enforces FRED-in-macro rule
_SCORECARD = _re(r"\b(scorecard|dashboard|markedsscorecard|overblik|markedsoverblik|oversigt)\b")
_OECD      = _re(r"\b(oecd|leading indicator|cli|composite leading|forretningsklima|business confidence|bci|consumer confidence|cci|forbrugertillid|erhvervstillid|oecd outlook|multifactor productivity|mfp|total factor productivity|tfp)\b")
_BIGMAC    = _re(
    r"\b(big mac|bigmac|big-mac|hamburger index|ppp|purchasing power parity|"
    r"købekraftparitet|købekraft|valutavurdering|valutaværdi|"
    r"overvurderet valuta|undervurderet valuta|currency valuation|"
    r"overvalued|undervalued currency|the economist index)\b"
)

ROUTING_RULES = [
    # Annual report / company valuation → annual_report specialist (FMP)
    (
        lambda b: _ANNUAL.search(b),
        "For selskabsanalyse og DCF-værdiansættelse: brug specialist='annual_report', source='fmp'. "
        "Angiv ticker-symbol (fx 'CARL', 'NOVO B', 'AAPL'). Returnerer type A/B/D charts.",
    ),
    # EU energy mix → Eurostat
    (
        lambda b: _EU.search(b) and _NRG.search(b),
        "For EU-energidata: brug specialist='eurostat', ticker='eu_energy_mix', "
        "source='eurostat_mix'. Brug type='P' (cirkeldiagram) for snapshot ét år, "
        "type='F' (stablet søjle) for fordeling over flere år.",
    ),
    # EU inflation → Eurostat HICP
    (
        lambda b: _EU.search(b) and _INFL.search(b),
        "For EU-inflation: brug specialist='eurostat', ticker='eu_hicp', "
        "source='eurostat_ts'. Type='A'.",
    ),
    # EU unemployment → Eurostat
    (
        lambda b: _EU.search(b) and _UNEM.search(b),
        "For EU-ledighed: brug specialist='eurostat', ticker='eu_unemployment', "
        "source='eurostat_ts'. Type='A'.",
    ),
    # EU GDP → Eurostat
    (
        lambda b: _EU.search(b) and _GDP.search(b),
        "For EU-BNP/vækst: brug specialist='eurostat', ticker='eu_gdp_growth', "
        "source='eurostat_ts'. Type='A'.",
    ),
    # US energy mix → EIA
    (
        lambda b: _US.search(b) and _NRG.search(b),
        "For US-energimix: brug specialist='energy', source='eia_mix', "
        "label='Energimix USA'. Type='F' (stablet søjle).",
    ),
    # Cross-region gas → conversion required
    (
        lambda b: _GAS.search(b) and (_TTF.search(b) or _EU.search(b)) and (_HH.search(b) or _US.search(b)),
        "For EU/US-gassammenligning: brug TTF=F (EUR/MWh, conversion='EUR_MWh_to_USD_MWh') "
        "og NG=F (USD/MMBtu, conversion='USD_MMBtu_to_USD_MWh'). Fælles y-akse: USD/MWh. Type='A'.",
    ),
    # US labor market / employment → PAYEMS with diff transform
    (
        lambda b: _EMPL.search(b),
        "For beskæftigelsesdata (USA og globalt): brug specialist='macro', source='fred'. "
        "PAYEMS = månedlig jobvækst (nonfarm payrolls): "
        "{\"ticker\": \"PAYEMS\", \"transform\": \"diff\", \"label\": \"Månedlig jobvækst (tusinder)\"}. "
        "KRITISK: brug transform='diff' — uden det viser PAYEMS niveauet ~155.000, IKKE månedlig ændring. "
        "Søjlediagram (type B): PAYEMS-diff, y_label='Tusinder', x_label=''. "
        "Linjegraf (type A): brug UNRATE (arbejdsløshedsprocent) eller PAYEMS-diff som tidsserie — "
        "giver god kontekst ved siden af søjlediagrammet. "
        "Producér én chart per requested type: B hvis 'B' er i preferred_types, A hvis 'A' er i preferred_types. "
        "period_days: brug brugerens valgte Tidsperiode præcist — standardværdi 1825 KUN når ingen Tidsperiode er valgt.",
    ),
    # Scorecard / multi-asset dashboard → enforce FRED in macro, rest in domain specialists
    (
        lambda b: _SCORECARD.search(b),
        "For scorecards og markedsoverblik med blandede aktivklasser: "
        "ALLE FRED-serier (DGS10, DGS2, DFF, T10Y2Y, T10YIE, osv.) → specialist='macro', source='fred'. "
        "yfinance-tickers (BZ=F, GC=F, ^GSPC, EURUSD=X, DX-Y.NYB) → domain specialist (energy/commodities/equities/rates). "
        "DGS10 MÅ ALDRIG placeres under specialist='equities' eller 'rates' — FRED serier går KUN i 'macro'. "
        "For Type A oversigtsgraf med blandede enheder: sæt y_label='Indekseret (basis=100)'. "
        "Brug specialist='macro' for ALLE rente- og obligationsserier uanset context.",
    ),
    # IMF explicit mention → IMF specialist
    (
        lambda b: _IMF.search(b),
        "For IMF-data: brug specialist='imf'. "
        "Angiv ISO-2 landekode (fx 'US', 'DE', 'CN'). "
        "Vigtige indikatorer: BNP-vækst (ticker='NGDP_RPCH', dataset='WEO', freq='A'), "
        "CPI-inflation (ticker='PCPI_IX', dataset='IFS', freq='Q'), "
        "statsgæld/BNP (ticker='GGXWDG_NGDP', dataset='WEO', freq='A'), "
        "betalingsbalance i USD (ticker='BCA_BP6_USD', dataset='IFS', freq='Q'), "
        "ledighed (ticker='LUR_PT', dataset='IFS', freq='Q'). "
        "Kilde='IMF'. Type='A' for tidsserie, type='D' for tabels.",
    ),
    # Trade balance / current account (non-EU) → IMF DOTS or IFS
    (
        lambda b: _TRADE.search(b) and not _EU.search(b),
        "For handelsbalance og betalingsbalance (ikke-EU): brug specialist='imf', "
        "dataset='IFS', ticker='BCA_BP6_USD' (løbende konto i USD). "
        "For handelsstrømme mellem lande: dataset='DOTS'. "
        "Angiv ISO-2 landekode. Type='A'.",
    ),
    # OECD leading indicators, confidence indices, productivity → OECD specialist
    (
        lambda b: _OECD.search(b),
        "For OECD-ledende indikatorer, tillidsindekser og produktivitet: brug specialist='oecd'. "
        "Tilgængelige tickers: 'oecd_cli' (Composite Leading Indicator), 'oecd_bci' (Business Confidence), "
        "'oecd_cci' (Consumer Confidence), 'oecd_gdp' (BNP-vækst, kvartalsvis), "
        "'oecd_unemployment' (harmoniseret ledighed), 'oecd_cpi' (forbrugerprisindeks), "
        "'oecd_mfp' (multifaktorproduktivitet, årlig). "
        "Angiv landet med 'country'-felt (ISO2-kode, fx 'USA', 'DEU', 'GBR', 'FRA', 'JPN'). "
        "Type='A' for tidsserie. y_label fra units i KNOWN_DATASETS.",
    ),
    # Big Mac Index / PPP / currency valuation → bigmac specialist
    (
        lambda b: _BIGMAC.search(b),
        "For Big Mac Index, PPP og valutavurdering: brug specialist='bigmac', source='the_economist'. "
        "Enkelt-land: angiv 'country' som ISO-3-kode (fx 'DNK', 'CHN', 'USA') — returnerer tidsserie (type A) "
        "med USD_raw og USD_adjusted over/undervurdering. "
        "Lande-sammenligning (standard): udelad 'country' — returnerer snapshot søjlediagram (type B) "
        "med alle lande rangeret efter over/undervurdering. "
        "For specifikt udvalg af lande: angiv 'countries' liste med ISO-3-koder. "
        "y_label='Over-/undervurdering ift. USD (%)'. Kilde='The Economist'.",
    ),
    # Country economy → World Bank (fires when country-specific economy keyword present, not EU/US)
    (
        lambda b: _COUNTRY_ECON_KW.search(b) and not _EU.search(b) and not _US.search(b),
        "For landets økonomi: brug specialist='worldbank'. "
        "Oversæt landets navn til ISO-3-kode. Brug y_label='%', years=20. "
        "ENKELT-LAND OBLIGATORISK LAYOUT (10 charts, eller 8 for CHN/JPN/SAU/LBY/ARE/KWT/QAT): "
        "Producér ALLE fem indikatorer som SEPARATE charts — kombiner ALDRIG to indikatorer på én Type A. "
        "Rækkefølge: (1) BNP-vækst A, (2) Kombineret nøgletal D (alle indikatorer), "
        "(3) Inflation A, (4) Inflation D companion, (5) Arbejdsløshed A, (6) Arbejdsløshed D companion, "
        "(7) Offentlig gæld A, (8) Offentlig gæld D companion (skip for data-gap lande), "
        "(9) Betalingsbalance A, (10) Betalingsbalance D companion. "
        "TIMELINE-reglen ændrer KUN years og before_date — IKKE antallet af charts. "
        "Antallet er altid 10 (eller 8) uanset period_days.",
    ),
]


def get_routing_hint(brief: str) -> str:
    """
    Match brief against keyword rules.
    Returns a routing hint string for injection into the orchestrator prompt,
    or empty string if no rules match.
    """
    matched = []
    for predicate, hint in ROUTING_RULES:
        try:
            if predicate(brief):
                matched.append(hint)
        except Exception:
            pass
    if not matched:
        return ""
    lines = "\n".join(f"- {h}" for h in matched)
    return f"\nROUTING HINTS (følg disse medmindre data klart modsiger dem):\n{lines}\n"
