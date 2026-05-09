import pandas as pd
from newsletter_agent.specialists.annual_report_kpi import build_chart_specs

REFORMULATED = {
    "years": [2020, 2021, 2022, 2023, 2024],
    "revenue":       [100_000] * 5,
    "NOA":           [100_000] * 5,
    "NFO":           [40_000]  * 5,
    "OI":            [15_600]  * 5,
    "FCF":           [None, 15_600, 15_600, 15_600, 15_600],
    "cash_fcf":      [None, 14_000, 14_000, 14_000, 14_000],
    "RNOA":          [0.156] * 5,
    "OG":            [0.156] * 5,
    "ATO":           [1.0]   * 5,
    "FLEV":          [0.73]  * 5,
    "NBC":           [0.04]  * 5,
    "SPREAD":        [0.116] * 5,
    "ROCE":          [0.16]  * 5,
    "NCI":           [5_000] * 5,
    "common_equity": [55_000] * 5,
    "historical_avgs": {"OG": 0.156, "ATO": 1.0, "revenue_cagr": 0.03},
    "flags": [],
    "excluded_years": set(),
    "n_avg_years": 5,
}
WACC_DATA = {
    "rf": 0.028, "rf_entry": {"rate": 0.0384, "maturity_yr": 35,
                               "spot": 0.028, "bond_name": "Dansk statsobligation 35år avg"},
    "t": 0.22, "beta_raw": 0.90, "beta_adj": 0.933,
    "MRP": 0.0374, "CRP": 0.0, "rE": 0.073,
    "rating": "A2", "rs": 0.0125, "rs_moody": 0.0125, "rs_icr": 0.013,
    "rD": 0.0398, "D": 40_000, "E": 300_000, "V": 340_000,
    "wacc": 0.065, "iso3": "DNK",
}
_BASE_DETAIL = {
    "forecast_years": ["2025E", "2026E", "2027E", "2028E", "2029E"],
    "revenue_forecast": [103_000, 106_090, 109_273, 112_551, 115_927],
    "OI_forecast":      [16_068, 16_550, 17_046, 17_558, 18_085],
    "NOA_forecast":     [103_000, 106_090, 109_273, 112_551, 115_927],
    "dNOA_forecast":    [3_000, 3_090, 3_183, 3_278, 3_376],
    "FCF_forecast":     [13_068, 13_460, 13_863, 14_280, 14_709],
    "discount_factors": [1.065, 1.134, 1.208, 1.286, 1.370],
    "PV_FCF":           [12_269, 11_871, 11_477, 11_106, 10_738],
    "total_PV": 57_461, "TV": 324_098, "PV_TV": 236_567,
    "EV": 294_028, "NFO": 40_000, "NCI": 5_000,
    "equity_value": 249_028, "diluted_shares": 500,
    "price_per_share": 498.06, "g": 0.02, "n_years": 5,
}
DCF_SCENARIOS = {
    "bear": {"price": 375.0,  "detail": {**_BASE_DETAIL, "EV": 220_000, "equity_value": 175_000},
             "wacc": 0.075, "og": 0.136, "cagr": -0.01, "g": 0.015},
    "base": {"price": 498.06, "detail": _BASE_DETAIL,
             "wacc": 0.065, "og": 0.156, "cagr": 0.03,  "g": 0.02},
    "bull": {"price": 640.0,  "detail": {**_BASE_DETAIL, "EV": 380_000, "equity_value": 335_000},
             "wacc": 0.055, "og": 0.176, "cagr": 0.07,  "g": 0.025},
}
SENSITIVITY = {
    "wacc_axis": [0.054, 0.0565, 0.059, 0.0615, 0.065, 0.0665, 0.069, 0.0715, 0.074],
    "g_axis": [0.01, 0.015, 0.02, 0.025, 0.03],
    "grid": [[400.0, 420.0, 440.0, 460.0, 480.0, 500.0, 520.0, 540.0, 560.0]] * 5,
    "wacc_base": 0.065, "g_base": 0.02,
}
FAKE_FMP = {
    "profile": {"price": 550.0, "companyName": "TestCo A/S", "country": "Denmark",
                "mktCap": 275_000, "currency": "DKK", "sector": "Consumer Staples"},
    "estimates": [],
    "metrics": [{"peRatio": 18.5, "pbRatio": 3.2, "priceToSalesRatio": 2.8,
                 "pfcfRatio": 20.1, "evToEbitda": 12.3, "date": "2024-12-31"}],
    "income":  [{"weightedAverageShsOutDil": 500, "epsDiluted": 5.0,
                 "ebitda": 20_000, "operatingIncome": 20_000, "revenue": 100_000,
                 "date": "2024-12-31"}],
    "balance": [{"totalStockholdersEquity": 55_000, "date": "2024-12-31"}],
}


def test_returns_18_chart_specs():
    specs, dfs = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                   REFORMULATED, WACC_DATA, DCF_SCENARIOS, SENSITIVITY, FAKE_FMP)
    assert len(specs) == 8


def test_all_specs_have_title_note_kilde():
    specs, _ = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                  REFORMULATED, WACC_DATA, DCF_SCENARIOS, SENSITIVITY, FAKE_FMP)
    for i, s in enumerate(specs):
        assert s.get("title"),  f"Chart #{i+1} missing title"
        assert s.get("note"),   f"Chart #{i+1} missing note"
        assert s.get("kilde"),  f"Chart #{i+1} missing kilde"


def test_type_d_charts_have_table_data():
    specs, _ = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                  REFORMULATED, WACC_DATA, DCF_SCENARIOS, SENSITIVITY, FAKE_FMP)
    for s in specs:
        if s["type"] == "D":
            assert "table_data" in s, f"Type D chart '{s['title']}' missing table_data"
            assert "columns" in s["table_data"]
            assert "rows"    in s["table_data"]


def test_type_a_charts_have_series_labels():
    specs, dfs = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                    REFORMULATED, WACC_DATA, DCF_SCENARIOS, SENSITIVITY, FAKE_FMP)
    for s in specs:
        if s["type"] == "A":
            assert "series_labels" in s, f"Type A chart '{s['title']}' missing series_labels"
            for lbl in s["series_labels"]:
                assert lbl in dfs, f"series_labels ref '{lbl}' not in dataframes"


def test_type_a_dataframes_have_datetime_index():
    _, dfs = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                REFORMULATED, WACC_DATA, DCF_SCENARIOS, SENSITIVITY, FAKE_FMP)
    for label, df in dfs.items():
        assert isinstance(df.index, pd.DatetimeIndex), f"DataFrame '{label}' missing DatetimeIndex"


def test_dcf_table_has_transparency_labels():
    specs, _ = build_chart_specs("CARL", "TestCo A/S", "DNK",
                                  REFORMULATED, WACC_DATA, DCF_SCENARIOS, SENSITIVITY, FAKE_FMP)
    # DCF Prognose (Basis) table — find by type D + "dcf" in title + "prognose/forecast/tabel" in title
    dcf_spec = next(
        (s for s in specs if s["type"] == "D" and "dcf" in s.get("title", "").lower()
         and any(kw in s.get("title", "").lower() for kw in ["forecast", "prognose", "tabel"])),
        None
    )
    assert dcf_spec is not None, "DCF forecast table (chart 13) not found"
    rows = dcf_spec["table_data"]["rows"]
    labeled = [r["indicator"] for r in rows if any(
        tag in r.get("indicator", "") for tag in ["[EST]", "[CALC]", "[ASSUMED]", "[SOURCED]"]
    )]
    assert len(labeled) >= 5, f"DCF table must have at least 5 labeled rows, got {len(labeled)}: {labeled}"
