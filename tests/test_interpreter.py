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
