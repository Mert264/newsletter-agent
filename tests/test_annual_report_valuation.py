from newsletter_agent.specialists.annual_report_valuation import (
    compute_wacc, compute_dcf, compute_sensitivity,
)
from newsletter_agent.specialists.annual_report_constants import MOODY_TO_SPREAD

FAKE_FMP = {
    "profile": {
        "beta": 0.90, "mktCap": 300_000, "price": 600.0,
        "country": "Denmark", "currency": "DKK",
        "sharesOutstanding": 500,
    },
    "rating": [{"rating": "A2", "ratingAgency": "Moody's"}],
    "income": [{"operatingIncome": 20_000, "interestExpense": 2_000,
                "weightedAverageShsOutDil": 500}],
}

FAKE_REFORMULATED = {
    "NOA":  [100_000] * 5,
    "NFO":  [40_000]  * 5,
    "OI":   [15_600]  * 5,
    "FCF":  [None, 15_600, 15_600, 15_600, 15_600],
    "NCI":  [5_000]   * 5,
    "common_equity": [55_000] * 5,
    "revenue": [100_000] * 5,
    "years": [2020, 2021, 2022, 2023, 2024],
    "historical_avgs": {"OG": 0.156, "ATO": 1.0, "revenue_cagr": 0.03},
    "flags": [],
}


def test_compute_wacc_returns_required_keys():
    result = compute_wacc(FAKE_FMP, FAKE_REFORMULATED, "DNK")
    for k in ["rf", "beta_raw", "beta_adj", "MRP", "CRP", "rE", "rs", "rD", "wacc", "t",
              "D", "E", "V", "rs_icr", "rating", "checker_inputs", "iso3", "rf_entry"]:
        assert k in result, f"Missing key: {k}"


def test_compute_wacc_beta_adj():
    result = compute_wacc(FAKE_FMP, FAKE_REFORMULATED, "DNK")
    expected_adj = (2 / 3) * 0.90 + (1 / 3)
    assert abs(result["beta_adj"] - expected_adj) < 1e-4


def test_compute_wacc_rf_dnk():
    result = compute_wacc(FAKE_FMP, FAKE_REFORMULATED, "DNK")
    assert abs(result["rf"] - 0.0384) < 1e-4


def test_compute_wacc_moody_spread():
    result = compute_wacc(FAKE_FMP, FAKE_REFORMULATED, "DNK")
    assert abs(result["rs"] - MOODY_TO_SPREAD["A2"]) < 1e-6


def test_compute_wacc_checker_inputs_structure():
    result = compute_wacc(FAKE_FMP, FAKE_REFORMULATED, "DNK")
    ci = result["checker_inputs"]
    assert ci["rf_re"] == ci["rf_rd"]   # same rf used everywhere
    assert ci["shares_source"] == "diluted"
    assert ci["tax_type"] == "statutory"
    assert ci["bond_type"] == "nominal"


def test_compute_dcf_returns_required_keys():
    result = compute_dcf(
        FAKE_REFORMULATED, wacc=0.065, g=0.02,
        NFO=40_000, NCI=5_000, diluted_shares=500, base_year=2024,
    )
    for k in ["forecast_years", "revenue_forecast", "OI_forecast", "NOA_forecast",
              "dNOA_forecast", "FCF_forecast", "discount_factors", "PV_FCF",
              "total_PV", "TV", "PV_TV", "EV", "NFO", "NCI",
              "equity_value", "diluted_shares", "price_per_share", "g"]:
        assert k in result, f"Missing: {k}"


def test_compute_dcf_discount_factor_year1():
    result = compute_dcf(
        FAKE_REFORMULATED, wacc=0.065, g=0.02,
        NFO=40_000, NCI=5_000, diluted_shares=500, base_year=2024,
    )
    assert abs(result["discount_factors"][0] - 1.065) < 0.001


def test_compute_dcf_ev_and_price_positive():
    result = compute_dcf(
        FAKE_REFORMULATED, wacc=0.065, g=0.02,
        NFO=40_000, NCI=5_000, diluted_shares=500, base_year=2024,
    )
    assert result["EV"] > 0
    assert result["price_per_share"] > 0


def test_compute_dcf_5_forecast_years():
    result = compute_dcf(
        FAKE_REFORMULATED, wacc=0.065, g=0.02,
        NFO=40_000, NCI=5_000, diluted_shares=500, base_year=2024,
    )
    assert len(result["forecast_years"]) == 5
    assert result["forecast_years"][0] == "2025E"
    assert result["forecast_years"][-1] == "2029E"


def test_compute_sensitivity_grid_shape():
    result = compute_sensitivity(
        FAKE_REFORMULATED, wacc_base=0.065, g_base=0.02,
        NFO=40_000, NCI=5_000, diluted_shares=500, base_year=2024,
    )
    assert len(result["wacc_axis"]) == 9
    assert len(result["g_axis"]) == 5
    assert len(result["grid"]) == 5
    assert len(result["grid"][0]) == 9


def test_compute_sensitivity_base_case_in_grid():
    result = compute_sensitivity(
        FAKE_REFORMULATED, wacc_base=0.065, g_base=0.02,
        NFO=40_000, NCI=5_000, diluted_shares=500, base_year=2024,
    )
    # g=0.02 is row index 2 (0.01, 0.015, 0.02, ...), wacc_base=0.065 is index 4 (center)
    g_idx   = result["g_axis"].index(0.02)
    wacc_idx = result["wacc_axis"].index(round(0.065, 4))
    assert result["grid"][g_idx][wacc_idx] is not None
    assert result["grid"][g_idx][wacc_idx] > 0
