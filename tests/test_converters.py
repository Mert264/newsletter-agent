import pandas as pd
import pytest
from newsletter_agent.processors.converters import apply_conversions


def _make_series(values, dates=None):
    if dates is None:
        dates = pd.date_range("2024-01-01", periods=len(values), freq="MS")
    return pd.DataFrame({"value": values}, index=dates)


def test_physical_conversion_USD_MMBtu_to_USD_MWh():
    """Henry Hub at 2 USD/MMBtu should become 2 × 3.41214 = 6.824 USD/MWh."""
    dfs = {"Henry Hub": _make_series([2.0, 3.0, 4.0])}
    specs = [{"label": "Henry Hub", "conversion": "USD_MMBtu_to_USD_MWh"}]
    converted, note = apply_conversions(dfs, specs, period_days=90)
    result = converted["Henry Hub"].iloc[0, 0]
    assert abs(result - 2.0 * 3.41214) < 0.001
    assert "3.41" in note
    assert "Henry Hub" in note


def test_no_conversion_when_field_absent():
    """Series without conversion field must be returned unchanged."""
    dfs = {"TTF": _make_series([30.0, 31.0])}
    specs = [{"label": "TTF"}]  # no "conversion" key
    converted, note = apply_conversions(dfs, specs, period_days=60)
    assert converted["TTF"].iloc[0, 0] == 30.0
    assert note == ""


def test_unknown_label_skipped():
    """Labels in specs that don't exist in dfs are silently skipped."""
    dfs = {"Henry Hub": _make_series([2.0])}
    specs = [{"label": "Missing Series", "conversion": "USD_MMBtu_to_USD_MWh"}]
    converted, note = apply_conversions(dfs, specs, period_days=30)
    assert "Missing Series" not in converted
    assert converted["Henry Hub"].iloc[0, 0] == 2.0


def test_conversion_note_format():
    """Note must mention the series name and conversion direction."""
    dfs = {"Henry Hub": _make_series([2.0])}
    specs = [{"label": "Henry Hub", "conversion": "USD_MMBtu_to_USD_MWh"}]
    _, note = apply_conversions(dfs, specs, period_days=30)
    assert "USD/MWh" in note
    assert "Henry Hub" in note
