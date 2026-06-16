"""Country and region group definitions for macro specialists.

Usage:
    from newsletter_agent.regions import resolve_countries
    codes = resolve_countries("Eurozone")  # ["AT", "BE", "CY", ...]
    codes = resolve_countries("DK")        # ["DK"]  (pass-through)
"""

GROUPS: dict[str, list[str]] = {
    # ── European Union (27) ──
    "EU": [
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
        "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
        "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    ],
    # ── Eurozone (20) ──
    "EUROZONE": [
        "AT", "BE", "CY", "EE", "FI", "FR", "DE", "GR", "IE", "IT",
        "LV", "LT", "LU", "MT", "NL", "PT", "SK", "SI", "ES", "HR",
    ],
    # ── Nordic ──
    "NORDIC": ["DK", "FI", "IS", "NO", "SE"],
    # ── G7 ──
    "G7": ["US", "GB", "FR", "DE", "IT", "JP", "CA"],
    # ── G20 ──
    "G20": [
        "US", "GB", "FR", "DE", "IT", "JP", "CA", "AU", "BR", "CN",
        "IN", "ID", "KR", "MX", "RU", "SA", "ZA", "TR", "AR",
    ],
    # ── BRICS ──
    "BRICS": ["BR", "RU", "IN", "CN", "ZA"],
    # ── Emerging Markets (major) ──
    "EM": [
        "BR", "CN", "IN", "ID", "KR", "MX", "RU", "ZA", "TR", "TH",
        "PL", "CL", "CO", "PH", "MY", "HU", "CZ", "EG", "SA", "AE",
    ],
    # ── Developed Markets ──
    "DM": [
        "US", "GB", "FR", "DE", "IT", "JP", "CA", "AU", "NZ", "CH",
        "SE", "NO", "DK", "FI", "NL", "BE", "AT", "IE", "ES", "PT",
        "SG", "HK", "IL",
    ],
    # ── Scandinavia ──
    "SCANDINAVIA": ["DK", "NO", "SE"],
}

_ALIASES: dict[str, str] = {
    "EURO AREA": "EUROZONE",
    "EURO": "EUROZONE",
    "EZ": "EUROZONE",
    "EUROPEAN UNION": "EU",
    "NORDICS": "NORDIC",
    "SKANDINAVIEN": "SCANDINAVIA",
    "EMERGING": "EM",
    "EMERGING MARKETS": "EM",
    "DEVELOPED": "DM",
    "DEVELOPED MARKETS": "DM",
}

# ISO-2 → ISO-3 for specialists that need 3-letter codes (World Bank, some IMF)
ISO2_TO_ISO3: dict[str, str] = {
    "AT": "AUT", "AU": "AUS", "BE": "BEL", "BG": "BGR", "BR": "BRA",
    "CA": "CAN", "CH": "CHE", "CL": "CHL", "CN": "CHN", "CO": "COL",
    "CY": "CYP", "CZ": "CZE", "DE": "DEU", "DK": "DNK", "EE": "EST",
    "EG": "EGY", "ES": "ESP", "FI": "FIN", "FR": "FRA", "GB": "GBR",
    "GR": "GRC", "HK": "HKG", "HR": "HRV", "HU": "HUN", "ID": "IDN",
    "IE": "IRL", "IL": "ISR", "IN": "IND", "IS": "ISL", "IT": "ITA",
    "JP": "JPN", "KR": "KOR", "LT": "LTU", "LU": "LUX", "LV": "LVA",
    "MT": "MLT", "MX": "MEX", "MY": "MYS", "NL": "NLD", "NO": "NOR",
    "NZ": "NZL", "PH": "PHL", "PL": "POL", "PT": "PRT", "RO": "ROU",
    "RU": "RUS", "SA": "SAU", "SE": "SWE", "SG": "SGP", "SI": "SVN",
    "SK": "SVK", "TH": "THA", "TR": "TUR", "AE": "ARE", "US": "USA",
    "ZA": "ZAF", "AR": "ARG",
}


def resolve_countries(name_or_code: str, iso3: bool = False) -> list[str]:
    """Resolve a group name or single country code to a list of ISO-2 codes.

    If iso3=True, returns ISO-3 codes instead (for World Bank etc.).
    Pass-through: if name_or_code is already a 2-3 letter country code, returns [code].
    """
    key = name_or_code.strip().upper()
    resolved = key
    if key in _ALIASES:
        resolved = _ALIASES[key]
    codes = GROUPS.get(resolved)
    if codes is None:
        codes = [key]
    if iso3:
        return [ISO2_TO_ISO3.get(c, c) for c in codes]
    return list(codes)


def available_groups() -> list[str]:
    """Return sorted list of all group names (for LLM prompt hints)."""
    return sorted(GROUPS.keys())
