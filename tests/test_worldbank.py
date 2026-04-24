import pandas as pd
import pytest
from unittest.mock import patch


MOCK_WB_RESPONSE = [
    {"page": 1, "total": 2},
    [
        {"date": "2023", "value": 2.4},
        {"date": "2022", "value": 3.1},
        {"date": "2021", "value": 5.0},
        {"date": "2020", "value": None},
        {"date": "2019", "value": 4.2},
    ]
]


def _mock_fetch(url, timeout=10):
    class R:
        def raise_for_status(self): pass
        def json(self): return MOCK_WB_RESPONSE
    return R()


def test_fetch_worldbank_returns_specialist_result():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get", side_effect=_mock_fetch):
        result = fetch_worldbank(task)
    assert "dataframes" in result
    assert "kilde" in result
    assert "chart_specs" in result
    assert "BNP-vækst" in result["dataframes"]


def test_chart_specs_freq_and_note_injected():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get", side_effect=_mock_fetch):
        result = fetch_worldbank(task)
    assert result["chart_specs"][0]["freq"] == "A"
    assert "efterslæb" in result["chart_specs"][0]["note"]
    # original task dict must not be mutated
    assert "freq" not in task["charts"][0]


def test_dates_converted_to_timestamps():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get", side_effect=_mock_fetch):
        result = fetch_worldbank(task)
    df = result["dataframes"]["BNP-vækst"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index[0] == pd.Timestamp("2019-01-01")


def test_none_values_dropped():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get", side_effect=_mock_fetch):
        result = fetch_worldbank(task)
    df = result["dataframes"]["BNP-vækst"]
    assert df.isnull().sum().sum() == 0  # None row was dropped


def test_kilde_contains_worldbank():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get", side_effect=_mock_fetch):
        result = fetch_worldbank(task)
    assert "Verdensbanken" in result["kilde"]


def test_network_error_returns_empty_result():
    from newsletter_agent.specialists.worldbank import fetch_worldbank
    import requests as req
    task = {
        "series": [
            {"ticker": "NY.GDP.MKTP.KD.ZG", "source": "worldbank",
             "label": "BNP-vækst", "country": "HUN", "years": 5, "unit": "%"}
        ],
        "charts": [{"type": "A", "period_days": 3650}],
    }
    with patch("newsletter_agent.specialists.worldbank.requests.get",
               side_effect=req.RequestException("timeout")):
        result = fetch_worldbank(task)
    assert result["dataframes"] == {}
