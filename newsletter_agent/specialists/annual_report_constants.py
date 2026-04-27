MSCI_WORLD_35YR_RETURN = 0.0758

RF_BY_COUNTRY = {
    "DNK": {"rate": 0.0384, "maturity_yr": 35, "spot": 0.028, "bond_name": "Dansk statsobligation 35år avg"},
    "USA": {"rate": 0.0450, "maturity_yr": 30, "spot": 0.044, "bond_name": "US Treasury 30yr avg"},
    "DEU": {"rate": 0.0260, "maturity_yr": 30, "spot": 0.026, "bond_name": "Deutscher Bund 30yr avg"},
    "GBR": {"rate": 0.0420, "maturity_yr": 30, "spot": 0.042, "bond_name": "UK Gilt 30yr avg"},
    "SWE": {"rate": 0.0320, "maturity_yr": 30, "spot": 0.032, "bond_name": "Svensk statsobligation 30yr avg"},
    "NOR": {"rate": 0.0340, "maturity_yr": 30, "spot": 0.034, "bond_name": "Norsk statsobligation 30yr avg"},
    "CHE": {"rate": 0.0210, "maturity_yr": 30, "spot": 0.021, "bond_name": "Swiss Confederation 30yr avg"},
    "NLD": {"rate": 0.0270, "maturity_yr": 30, "spot": 0.027, "bond_name": "Dutch State Loan 30yr avg"},
    "FRA": {"rate": 0.0290, "maturity_yr": 30, "spot": 0.031, "bond_name": "OAT 30yr avg"},
    "JPN": {"rate": 0.0150, "maturity_yr": 30, "spot": 0.015, "bond_name": "JGB 30yr avg"},
    "_default": {"rate": 0.0450, "maturity_yr": 10, "spot": 0.045, "bond_name": "10yr govt bond"},
}

MOODY_TO_SPREAD = {
    "Aaa": 0.0063, "Aa1": 0.0075, "Aa2": 0.0088, "Aa3": 0.0100,
    "A1": 0.0113, "A2": 0.0125, "A3": 0.0138,
    "Baa1": 0.0150, "Baa2": 0.0175, "Baa3": 0.0200,
    "Ba1": 0.0240, "Ba2": 0.0275, "Ba3": 0.0325,
    "B1": 0.0400, "B2": 0.0500, "B3": 0.0600,
    "Caa1": 0.0750, "Caa2": 0.0850, "Caa3": 0.1000,
    "Ca": 0.1300, "C": 0.1500,
}

ICR_TO_SPREAD = [
    (8.50, float("inf"), 0.0063),
    (6.50, 8.50, 0.0088),
    (5.50, 6.50, 0.0113),
    (4.25, 5.50, 0.0125),
    (3.00, 4.25, 0.0150),
    (2.50, 3.00, 0.0175),
    (2.00, 2.50, 0.0200),
    (1.75, 2.00, 0.0240),
    (1.50, 1.75, 0.0275),
    (1.25, 1.50, 0.0325),
    (0.80, 1.25, 0.0400),
    (0.65, 0.80, 0.0500),
    (0.20, 0.65, 0.0850),
    (float("-inf"), 0.20, 0.1300),
]

CRP_BY_COUNTRY = {
    "DNK": 0.0000, "SWE": 0.0000, "NOR": 0.0000, "DEU": 0.0000,
    "USA": 0.0000, "CHE": 0.0000, "AUT": 0.0000, "NLD": 0.0000,
    "FIN": 0.0000, "GBR": 0.0022, "FRA": 0.0022, "JPN": 0.0038,
    "CHN": 0.0075, "POL": 0.0075, "HUN": 0.0088,
    "BRA": 0.0163, "IND": 0.0113, "MEX": 0.0113, "RUS": 0.0525,
    "TUR": 0.0275, "ARE": 0.0063, "SAU": 0.0088, "_default": 0.0200,
}

STATUTORY_TAX_RATE = {
    "DNK": 0.22, "SWE": 0.206, "NOR": 0.22, "DEU": 0.298,
    "USA": 0.21, "GBR": 0.25, "FRA": 0.2572, "CHN": 0.25,
    "JPN": 0.2974, "NLD": 0.258, "CHE": 0.1468, "_default": 0.22,
}

_COUNTRY_NAME_MAP = {
    "denmark": "DNK", "sweden": "SWE", "norway": "NOR", "germany": "DEU",
    "united states": "USA", "us": "USA", "usa": "USA",
    "united kingdom": "GBR", "uk": "GBR", "gb": "GBR",
    "france": "FRA", "china": "CHN", "japan": "JPN",
    "switzerland": "CHE", "netherlands": "NLD", "finland": "FIN",
    "austria": "AUT", "poland": "POL", "hungary": "HUN",
    "brazil": "BRA", "india": "IND", "mexico": "MEX",
    "turkey": "TUR", "russia": "RUS", "saudi arabia": "SAU",
    "united arab emirates": "ARE", "dnk": "DNK", "swe": "SWE",
    "nor": "NOR", "deu": "DEU", "gbr": "GBR",
}


def normalize_country(country_str: str) -> str:
    return _COUNTRY_NAME_MAP.get(country_str.lower().strip(), "_default")


def icr_to_spread(icr: float) -> float:
    for lo, hi, spread in ICR_TO_SPREAD:
        if lo <= icr < hi:
            return spread
    return ICR_TO_SPREAD[-1][2]
