import json
import os
import tempfile
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock


def test_interpret_chart_returns_list_of_strings(tmp_path):
    """interpret_chart returns a list of 1-4 strings on success."""
    from newsletter_agent.interpreter import interpret_chart

    # Create a tiny dummy PNG (1×1 white pixel)
    import struct, zlib
    def _minimal_png() -> bytes:
        def chunk(name, data):
            c = name + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        raw = b"\x89PNG\r\n\x1a\n"
        raw += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        raw += chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        raw += chunk(b"IEND", b"")
        return raw

    png_path = tmp_path / "test.png"
    png_path.write_bytes(_minimal_png())

    spec = {"title": "Test Chart", "type": "A", "note": "Test note", "y_label": "%", "chart_type": "A"}
    data_summary = {
        "chart_type": "A",
        "series": {"Serie A": {"latest": 5.0, "change_abs": 1.0, "change_pct": 25.0, "unit": "%"}},
        "period_days": 365,
        "direction": "up",
    }

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="• Bullet one\n• Bullet two\n• Bullet three")]

    with patch("newsletter_agent.interpreter.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = mock_message
        result = interpret_chart(str(png_path), spec, data_summary)

    assert isinstance(result, list)
    assert 1 <= len(result) <= 4
    assert all(isinstance(b, str) and len(b) > 5 for b in result)


def test_interpret_chart_returns_empty_list_on_error():
    """interpret_chart returns [] (not raises) when LLM call fails."""
    from newsletter_agent.interpreter import interpret_chart

    spec = {"title": "Bad Chart", "type": "A", "note": "", "y_label": "%", "chart_type": "A"}
    data_summary = {}

    with patch("newsletter_agent.interpreter.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.side_effect = Exception("API timeout")
        result = interpret_chart("/nonexistent/path.png", spec, data_summary)

    assert result == []


def test_build_data_summary_type_a():
    """Type A: extracts latest value and period change per series."""
    from newsletter_agent.pipeline import _build_data_summary
    import pandas as pd

    dates = pd.date_range("2024-01-01", periods=10, freq="ME")
    dfs = {
        "Brent": pd.DataFrame({"Brent": [70.0, 71, 72, 73, 74, 75, 76, 77, 78, 80.0]}, index=dates),
        "WTI":   pd.DataFrame({"WTI":   [65.0, 66, 67, 68, 69, 70, 71, 72, 73, 75.0]}, index=dates),
    }
    spec = {"type": "A", "y_label": "USD/barrel", "period_days": 365}
    result = _build_data_summary(dfs, spec)

    assert result["chart_type"] == "A"
    assert "Brent" in result["series"]
    assert result["series"]["Brent"]["latest"] == 80.0
    assert result["series"]["Brent"]["change_abs"] == pytest.approx(10.0, abs=0.1)
    assert result["direction"] in ("up", "down", "stable", "mixed")


def test_build_data_summary_type_d_returns_empty():
    """Type D (table): returns empty dict — no interpretation needed."""
    from newsletter_agent.pipeline import _build_data_summary
    import pandas as pd

    dfs = {"Serie": pd.DataFrame({"v": [1.0]}, index=pd.date_range("2024-01-01", periods=1))}
    result = _build_data_summary(dfs, {"type": "D"})
    assert result == {}


def test_build_data_summary_type_f():
    """Type F: extracts first/last year share per category."""
    from newsletter_agent.pipeline import _build_data_summary
    import pandas as pd

    idx = ["2021", "2022", "2023", "2024"]
    wide = pd.DataFrame({
        "Naturgas":    [19.0, 18.0, 17.0, 17.0],
        "Bioenergi":   [28.0, 28.0, 29.0, 30.0],
        "Kerneenergi": [10.0, 9.0, 9.0, 9.0],
    }, index=idx)
    dfs = {"_wide": wide}
    spec = {"type": "F", "period_days": 4 * 365}
    result = _build_data_summary(dfs, spec)

    assert result["chart_type"] == "F"
    assert "Naturgas" in result["categories"]
    assert result["categories"]["Naturgas"]["first_label"] == "2021"
    assert result["categories"]["Naturgas"]["last_label"] == "2024"
