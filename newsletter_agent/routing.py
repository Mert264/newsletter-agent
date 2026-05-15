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
