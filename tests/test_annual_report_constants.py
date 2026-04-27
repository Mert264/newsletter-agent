from newsletter_agent.specialists.annual_report_constants import (
    RF_BY_COUNTRY, MSCI_WORLD_35YR_RETURN, MOODY_TO_SPREAD,
    ICR_TO_SPREAD, CRP_BY_COUNTRY, STATUTORY_TAX_RATE, normalize_country, icr_to_spread,
)

def test_rf_by_country_has_required_keys():
    for key in ["DNK", "USA", "DEU", "GBR", "SWE", "NOR", "_default"]:
        assert key in RF_BY_COUNTRY
        assert "rate" in RF_BY_COUNTRY[key]
        assert "maturity_yr" in RF_BY_COUNTRY[key]
        assert "bond_name" in RF_BY_COUNTRY[key]

def test_moody_spread_lookup():
    assert MOODY_TO_SPREAD["Aaa"] == 0.0063
    assert MOODY_TO_SPREAD["A2"] == 0.0125
    assert MOODY_TO_SPREAD["Baa2"] == 0.0175

def test_icr_spread_lookup():
    # ICR = 5.0 → between 4.25 and 5.50 → spread 0.0125
    assert icr_to_spread(5.0) == 0.0125
    # Boundary: ICR exactly 8.50 → highest band → spread 0.0063
    assert icr_to_spread(8.50) == 0.0063
    # Very high ICR
    assert icr_to_spread(100.0) == 0.0063
    # Low ICR < 0.20 → highest risk band → spread 0.0850
    assert icr_to_spread(0.10) == 0.0850
    # Negative ICR (distressed company)
    assert icr_to_spread(-5.0) == 0.1300

def test_normalize_country():
    assert normalize_country("Denmark") == "DNK"
    assert normalize_country("united states") == "USA"
    assert normalize_country("Unknownland") == "_default"

def test_statutory_tax_rate():
    assert STATUTORY_TAX_RATE["DNK"] == 0.22
    assert STATUTORY_TAX_RATE["USA"] == 0.21
    assert "_default" in STATUTORY_TAX_RATE
