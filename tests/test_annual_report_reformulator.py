from newsletter_agent.specialists.annual_report_reformulator import reformulate


def _make_fmp_data(n_years=3, with_cf=False):
    """Produces n_years of identical synthetic FMP data (newest first)."""
    income = []
    balance = []
    cashflow = []
    for i in range(n_years):
        year = 2024 - i
        income.append({
            "date": f"{year}-12-31",
            "revenue": 100_000,
            "operatingIncome": 20_000,
            "grossProfit": 40_000,
            "netIncome": 12_000,
            "comprehensiveIncomePeriodChange": 11_500,
            "interestExpense": 2_000,
            "weightedAverageShsOutDil": 500,
        })
        balance.append({
            "date": f"{year}-12-31",
            "totalAssets": 200_000,
            "totalLiabilities": 120_000,
            "cashAndCashEquivalents": 10_000,
            "shortTermInvestments": 5_000,
            "longTermInvestments": 5_000,
            "shortTermDebt": 8_000,
            "longTermDebt": 30_000,
            "capitalLeaseObligations": 2_000,
            "totalStockholdersEquity": 75_000,
            "minorityInterest": 5_000,
            "goodwillAndIntangibleAssets": 20_000,
        })
        if with_cf:
            cashflow.append({
                "date": f"{year}-12-31",
                "operatingCashFlow": 16_000,
                "capitalExpenditure": -8_000,
                "freeCashFlow": 0,
                "depreciationAndAmortization": 5_000,
                "changeInWorkingCapital": -1_000,
            })
    return {
        "income": income,
        "balance": balance,
        "cashflow": cashflow if with_cf else [],
        "profile": {},
        "rating": [],
        "metrics": [],
        "estimates": [],
    }


def test_noa_calculation():
    data = _make_fmp_data(2)
    result = reformulate(data, t=0.22)
    assert result["NOA"][0] == 102_000


def test_oi_calculation():
    data = _make_fmp_data(2)
    result = reformulate(data, t=0.22)
    assert abs(result["OI"][0] - 15_600) < 1


def test_fcf_is_none_for_first_year():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    assert result["FCF"][0] is None


def test_fcf_second_year():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    assert abs(result["FCF"][1] - 15_600) < 1


def test_historical_avgs_computed():
    data = _make_fmp_data(5)
    result = reformulate(data, t=0.22)
    assert "OG" in result["historical_avgs"]
    assert "ATO" in result["historical_avgs"]
    assert "revenue_cagr" in result["historical_avgs"]
    assert abs(result["historical_avgs"]["OG"] - 0.156) < 0.001


def test_one_time_item_detection():
    data = _make_fmp_data(5)
    data["income"][3]["operatingIncome"] = 30_000
    result = reformulate(data, t=0.22)
    assert any("flagged" in f.lower() for f in result["flags"])


def test_returns_required_keys():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    for key in ["years", "revenue", "NOA", "NFO", "OI", "FCF", "RNOA",
                "OG", "ATO", "FLEV", "NBC", "SPREAD", "ROCE", "NCI",
                "common_equity", "historical_avgs", "flags", "assumptions"]:
        assert key in result, f"Missing key: {key}"


def test_revenue_cagr_stable_data():
    data = _make_fmp_data(5)
    result = reformulate(data, t=0.22)
    assert abs(result["historical_avgs"]["revenue_cagr"]) < 0.001


def test_returns_new_component_keys():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    for key in ["gross_profit", "ebit", "dna", "capex", "dnwc",
                "op_assets", "op_liabs", "gross_debt", "fin_assets"]:
        assert key in result, f"Missing new key: {key}"
        assert len(result[key]) == len(result["years"]), f"{key} length mismatch"


def test_ebit_matches_nopat_pretax():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    for i, ebit in enumerate(result["ebit"]):
        expected_oi = ebit * (1 - 0.22)
        assert abs(result["OI"][i] - expected_oi) < 0.01, \
            f"Year {result['years'][i]}: EBIT*(1-t) != NOPAT"


def test_noa_equals_op_assets_minus_op_liabs():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    for i in range(len(result["years"])):
        expected = result["op_assets"][i] - result["op_liabs"][i]
        assert abs(result["NOA"][i] - expected) < 0.01, \
            f"Year {result['years'][i]}: NOA bridge mismatch"


def test_nfo_equals_gross_debt_minus_fin_assets():
    data = _make_fmp_data(3)
    result = reformulate(data, t=0.22)
    for i in range(len(result["years"])):
        expected = result["gross_debt"][i] - result["fin_assets"][i]
        assert abs(result["NFO"][i] - expected) < 0.01, \
            f"Year {result['years'][i]}: NFO bridge mismatch"


def test_dna_and_capex_populated_from_cashflow():
    data = _make_fmp_data(3, with_cf=True)
    result = reformulate(data, t=0.22)
    for i in range(len(result["years"])):
        assert abs(result["dna"][i] - 5_000) < 0.01, f"D&A wrong year {i}"
        assert abs(result["capex"][i] - (-8_000)) < 0.01, f"CapEx wrong year {i}"
        assert abs(result["dnwc"][i] - (-1_000)) < 0.01, f"ΔNWC wrong year {i}"
