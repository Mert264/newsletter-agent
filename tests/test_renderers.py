import os
import tempfile
import pandas as pd
import pytest
from newsletter_agent.renderers.charts import render_type_p, render_type_f, render_type_g


def _tmp(suffix=".png"):
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.close()
    return f.name


SPEC = {
    "title": "Test Chart",
    "x_label": "År",
    "y_label": "Pct. af total",
    "note": "Test note.",
    "kilde": "Test",
}


def test_render_type_p_single_column():
    df = pd.DataFrame(
        {"value": [40.0, 25.0, 20.0, 15.0]},
        index=["Olie", "Gas", "Kul", "Vedvarende"],
    )
    out = _tmp()
    result = render_type_p(df, {**SPEC, "title": "Energimix 2024"}, out)
    assert os.path.exists(result)
    assert os.path.getsize(result) > 10_000
    os.unlink(result)


def test_render_type_p_wide_uses_latest_row():
    df = pd.DataFrame(
        {"Olie": [50.0, 42.0], "Gas": [30.0, 28.0], "Vedvarende": [20.0, 30.0]},
        index=["2020", "2024"],
    )
    out = _tmp()
    result = render_type_p(df, {**SPEC, "snapshot_year": "2024"}, out)
    assert os.path.exists(result)
    os.unlink(result)


def test_render_type_p_normalises_to_100():
    df = pd.DataFrame(
        {"value": [400.0, 300.0, 200.0, 100.0]},
        index=["A", "B", "C", "D"],
    )
    out = _tmp()
    result = render_type_p(df, SPEC, out)
    assert os.path.exists(result)
    os.unlink(result)
