from unittest.mock import patch, MagicMock
from newsletter_agent.specialists.annual_report_fmp import fetch_all
import pytest

def _mock_response(data):
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status.return_value = None
    return m

FAKE_INCOME = [{"date": "2024-12-31", "revenue": 83000, "operatingIncome": 12000,
                "netIncome": 8500, "comprehensiveIncomePeriodChange": 8200,
                "interestExpense": 1200, "weightedAverageShsOutDil": 500}]
FAKE_BALANCE = [{"date": "2024-12-31", "totalAssets": 150000, "totalLiabilities": 90000,
                 "cashAndCashEquivalents": 8000, "shortTermInvestments": 2000,
                 "longTermInvestments": 1000, "shortTermDebt": 5000,
                 "longTermDebt": 25000, "capitalLeaseObligations": 3000,
                 "totalStockholdersEquity": 55000, "minorityInterest": 5000,
                 "goodwillAndIntangibleAssets": 20000}]
FAKE_CF = [{"date": "2024-12-31", "capitalExpenditure": -3000, "depreciationAndAmortization": 3500}]
FAKE_PROFILE = [{"beta": 0.85, "mktCap": 250000, "price": 500.0,
                 "country": "Denmark", "companyName": "TestCo A/S",
                 "currency": "DKK", "sharesOutstanding": 500}]
FAKE_RATING = [{"rating": "A2", "ratingAgency": "Moody's"}]
FAKE_METRICS = [{"date": "2024-12-31", "peRatio": 18.5}]
FAKE_ESTIMATES = [{"date": "2025-12-31", "estimatedRevenueLow": 85000}]


@patch("newsletter_agent.specialists.annual_report_fmp.requests.get")
def test_fetch_all_returns_expected_keys(mock_get):
    mock_get.side_effect = [
        _mock_response(FAKE_INCOME),
        _mock_response(FAKE_BALANCE),
        _mock_response(FAKE_CF),
        _mock_response(FAKE_PROFILE),
        _mock_response(FAKE_RATING),
        _mock_response(FAKE_METRICS),
        _mock_response(FAKE_ESTIMATES),
    ]
    result = fetch_all("CARL", "test_key")
    for key in ["income", "balance", "cashflow", "profile", "rating", "metrics", "estimates"]:
        assert key in result
    assert result["profile"]["country"] == "Denmark"
    assert result["income"][0]["revenue"] == 83000


@patch("newsletter_agent.specialists.annual_report_fmp.requests.get")
def test_fetch_all_raises_on_empty_income(mock_get):
    mock_get.side_effect = [
        _mock_response([]),   # income empty
        _mock_response(FAKE_BALANCE),
        _mock_response(FAKE_CF),
        _mock_response(FAKE_PROFILE),
        _mock_response(FAKE_RATING),
        _mock_response(FAKE_METRICS),
        _mock_response(FAKE_ESTIMATES),
    ]
    with pytest.raises(ValueError, match="No income statement"):
        fetch_all("INVALID", "test_key")


@patch("newsletter_agent.specialists.annual_report_fmp.requests.get")
def test_profile_unwrapped_from_list(mock_get):
    mock_get.side_effect = [
        _mock_response(FAKE_INCOME),
        _mock_response(FAKE_BALANCE),
        _mock_response(FAKE_CF),
        _mock_response(FAKE_PROFILE),   # profile is a list
        _mock_response(FAKE_RATING),
        _mock_response(FAKE_METRICS),
        _mock_response(FAKE_ESTIMATES),
    ]
    result = fetch_all("CARL", "test_key")
    # profile must be a dict (unwrapped from list), not a list
    assert isinstance(result["profile"], dict)
    assert result["profile"]["beta"] == 0.85
