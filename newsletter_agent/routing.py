"""
Hybrid dataset routing: deterministic keyword rules produce a routing_hint string
that is injected into the orchestrator prompt. LLM can override if data contradicts.
"""
from __future__ import annotations
import re


def _re(pattern: str):
    return re.compile(pattern, re.IGNORECASE)


_EU   = _re(r"\b(eu|europe[an]*|eurozone|europ[aæ]|eu27)\b")
_US   = _re(r"\b(us|usa|american?|united states|amerikans?k)\b")
_NRG  = _re(r"\b(energy|energi|energimix|brændstofstype|fuel|forbrug)\b")
_GAS  = _re(r"\b(gas|naturgas|natural gas)\b")
_TTF  = _re(r"\bttf\b")
_HH   = _re(r"\b(henry hub|hh)\b")
_INFL = _re(r"\b(inflation|hicp|prisvækst)\b")
_UNEM = _re(r"\b(unemployment|ledighed|arbejdsløs)\b")
_GDP  = _re(r"\b(gdp|bnp|growth|vækst)\b")

ROUTING_RULES = [
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
