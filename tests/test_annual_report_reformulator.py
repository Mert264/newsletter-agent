from newsletter_agent.specialists.annual_report_reformulator import reformulate


def _make_fmp_data(n_years=3):
    """Produces n_years of identical synthetic FMP data (newest first)."""
    income = []
    balance = []
    for i in range(n_years):
        year = 2024 - i
        income.append({
            "date": f"{year}-12-31",
            "revenue": 100_000,
            "operatingIncome": 20_000,
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
    return {
        "income": income,
        "balance": balance,
        "cashflow": [],
        "profile": {},
        "rating": [],
        "metrics": [],
        "estimates": [],
    }


def test_noa_calculation():
    data = _make_fmp_data(2)
    result = reformulate(data, t=0.22)
    assert result["NOA"][0] == 100_000


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
