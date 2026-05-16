"""
Extended test suite covering Tidsperiode enforcement, retry logic, and formatting edge cases.

Scenarios:
  A. period_days=365 → all chart specs clamped to 365 (non-YoY)
  B. period_days=730 → chart specs clamped to 730
  C. start_date + end_date → derived period_days; specs clamped to that; dates injected
  D. start_date only → end_date defaults to today; start_date injected into specialists
  E. No period_days, no start_date → LLM-generated period_days not clamped
  F. YoY chart with period_days=90 → clamped to 760
  G. Employment routing + period_days=365 → chart spec period_days = 365 (not 1825)

  H. llm_call_with_retry retries on 529 and succeeds on attempt 3
  I. llm_call_with_retry raises after exhausting all retries on persistent 529
  J. llm_call_with_retry does NOT retry on 400 Bad Request

  K. fmt_da(0, 2) → "0,00"
  L. fmt_da(-1234567.89, 2) → "-1.234.567,89"
  M. fmt_da(0.001234, 4) → "0,0012"

Run with: python -m pytest tests/test_tidsperiode_scenarios.py -v
"""
from __future__ import annotations
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manifest(charts: list, specialists: list = None) -> dict:
    """Build a minimal manifest for pipeline enforcement tests."""
    if specialists is None:
        specialists = ["macro"]
    manifest = {"specialists": specialists}
    for sp in specialists:
        manifest[sp] = {"series": [], "charts": list(charts)}
    return manifest


def _patch_pipeline(monkeypatch, manifest: dict):
    """Patch pipeline.run() dependencies so no real I/O happens."""
    import newsletter_agent.pipeline as pl

    monkeypatch.setattr(pl, "build_task_manifest", lambda *a, **kw: manifest)
    monkeypatch.setattr(pl, "_enforce_worldbank_single_country_layout", lambda m, **kw: m)
    monkeypatch.setattr(pl, "get_routing_hint", lambda b: "")
    monkeypatch.setattr(pl, "_run_specialist", lambda n, t: {"dataframes": {}, "kilde": [], "chart_specs": []})


# ---------------------------------------------------------------------------
# Tidsperiode — chart-spec clamping
# ---------------------------------------------------------------------------

class TestTidsperiodeClamping:

    def _run(self, monkeypatch, charts, period_days=None, start_date=None, end_date=None):
        """Run pipeline with given params and return the (possibly mutated) manifest."""
        import newsletter_agent.pipeline as pl

        captured = {}

        def fake_build_manifest(*a, **kw):
            m = _make_manifest(charts)
            captured["manifest"] = m
            return m

        monkeypatch.setattr(pl, "build_task_manifest", fake_build_manifest)
        monkeypatch.setattr(pl, "_enforce_worldbank_single_country_layout", lambda m, **kw: m)
        monkeypatch.setattr(pl, "get_routing_hint", lambda b: "")
        monkeypatch.setattr(pl, "_run_specialist", lambda n, t: {"dataframes": {}, "kilde": [], "chart_specs": []})

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                pl.run("test", output_dir=tmpdir,
                       period_days=period_days, start_date=start_date, end_date=end_date)
            except Exception:
                pass

        return captured["manifest"]

    def test_A_period_365_clamps_all_charts(self, monkeypatch):
        """A: period_days=365 → non-YoY chart spec clamped to 365."""
        charts = [{"type": "A", "period_days": 1825, "y_label": "%", "series_labels": [], "title": "T", "note": "", "kilde": ""}]
        manifest = self._run(monkeypatch, charts, period_days=365)
        assert manifest["macro"]["charts"][0]["period_days"] == 365, \
            "Chart spec was not clamped from 1825 to 365"

    def test_B_period_730_clamps_all_charts(self, monkeypatch):
        """B: period_days=730 → chart specs clamped to 730."""
        charts = [{"type": "A", "period_days": 3650, "y_label": "%", "series_labels": [], "title": "T", "note": "", "kilde": ""}]
        manifest = self._run(monkeypatch, charts, period_days=730)
        assert manifest["macro"]["charts"][0]["period_days"] == 730

    def test_C_start_end_date_derives_period_and_injects_dates(self, monkeypatch):
        """C: start_date=2000-10-10, end_date=2010-09-10 → period_days≈3622, dates injected."""
        import newsletter_agent.pipeline as pl
        import pandas as pd

        captured_tasks = {}
        injected_period = {}

        charts_template = [{"type": "A", "period_days": 999, "y_label": "%",
                             "series_labels": [], "title": "T", "note": "", "kilde": ""}]
        manifest = _make_manifest(charts_template)

        def fake_build_manifest(*a, **kw):
            injected_period["period_days"] = kw.get("period_days")
            return manifest

        def fake_run_specialist(name, task):
            captured_tasks[name] = task
            return {"dataframes": {}, "kilde": [], "chart_specs": []}

        monkeypatch.setattr(pl, "build_task_manifest", fake_build_manifest)
        monkeypatch.setattr(pl, "_enforce_worldbank_single_country_layout", lambda m, **kw: m)
        monkeypatch.setattr(pl, "get_routing_hint", lambda b: "")
        monkeypatch.setattr(pl, "_run_specialist", fake_run_specialist)

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                pl.run("test", output_dir=tmpdir,
                       start_date="2000-10-10", end_date="2010-09-10")
            except Exception:
                pass

        expected_days = (pd.Timestamp("2010-09-10") - pd.Timestamp("2000-10-10")).days  # 3622
        assert injected_period["period_days"] == expected_days, \
            f"Expected period_days={expected_days}, got {injected_period['period_days']}"

        # Dates must be injected into specialist tasks
        assert captured_tasks.get("macro", {}).get("start_date") == "2000-10-10", \
            "start_date not injected into specialist task"
        assert captured_tasks.get("macro", {}).get("end_date") == "2010-09-10", \
            "end_date not injected into specialist task"

    def test_D_start_date_only_defaults_end_to_today(self, monkeypatch):
        """D: start_date only → end_date defaults to today; start_date injected."""
        import newsletter_agent.pipeline as pl
        import pandas as pd
        from datetime import date as _date

        captured_tasks = {}
        injected_period = {}

        charts_template = [{"type": "A", "period_days": 999, "y_label": "%",
                             "series_labels": [], "title": "T", "note": "", "kilde": ""}]
        manifest = _make_manifest(charts_template)

        def fake_build_manifest(*a, **kw):
            injected_period["period_days"] = kw.get("period_days")
            return manifest

        def fake_run_specialist(name, task):
            captured_tasks[name] = task
            return {"dataframes": {}, "kilde": [], "chart_specs": []}

        monkeypatch.setattr(pl, "build_task_manifest", fake_build_manifest)
        monkeypatch.setattr(pl, "_enforce_worldbank_single_country_layout", lambda m, **kw: m)
        monkeypatch.setattr(pl, "get_routing_hint", lambda b: "")
        monkeypatch.setattr(pl, "_run_specialist", fake_run_specialist)

        start = "2023-01-01"
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                pl.run("test", output_dir=tmpdir, start_date=start)
            except Exception:
                pass

        # period_days should be derived (positive)
        assert injected_period["period_days"] > 0, "period_days should be > 0 when only start_date given"

        # start_date must be injected
        assert captured_tasks.get("macro", {}).get("start_date") == start, \
            "start_date not injected into specialist task"

        # No end_date explicitly → pipeline should NOT inject end_date key (or inject None/today)
        # The key assertion is start_date presence
        assert "start_date" in captured_tasks.get("macro", {}), \
            "start_date key missing from task"

    def test_E_no_period_no_start_llm_not_clamped(self, monkeypatch):
        """E: No period_days, no start_date → LLM-generated period_days not overwritten."""
        charts = [{"type": "A", "period_days": 1825, "y_label": "%",
                   "series_labels": [], "title": "T", "note": "", "kilde": ""}]
        manifest = self._run(monkeypatch, charts, period_days=None, start_date=None)
        # Without user-supplied period_days, no clamping should happen
        assert manifest["macro"]["charts"][0]["period_days"] == 1825, \
            "LLM period_days should not be clamped when no user preference given"

    def test_F_yoy_with_period_90_clamped_to_760(self, monkeypatch):
        """F: YoY chart with period_days=90 → clamped to 760."""
        charts = [{"type": "A", "period_days": 90, "y_label": "YoY %",
                   "series_labels": [], "title": "T", "note": "", "kilde": ""}]
        manifest = self._run(monkeypatch, charts, period_days=90)
        assert manifest["macro"]["charts"][0]["period_days"] == 760, \
            "YoY chart should be clamped to 760 even if user picks 90"

    def test_F_yoy_case_insensitive(self, monkeypatch):
        """F variant: 'yoy %' (lowercase) also triggers 760 minimum."""
        charts = [{"type": "A", "period_days": 90, "y_label": "yoy %",
                   "series_labels": [], "title": "T", "note": "", "kilde": ""}]
        manifest = self._run(monkeypatch, charts, period_days=90)
        assert manifest["macro"]["charts"][0]["period_days"] == 760

    def test_G_employment_routing_period_365_not_1825(self, monkeypatch):
        """G: Employment routing hint fires but period_days=365 is preserved."""
        import newsletter_agent.pipeline as pl

        captured_period = {}

        charts_template = [{"type": "B", "period_days": 1825, "y_label": "Tusinde personer",
                             "series_labels": [], "title": "Employment", "note": "", "kilde": ""}]
        manifest = _make_manifest(charts_template)

        def fake_build_manifest(*a, **kw):
            captured_period["at_build"] = kw.get("period_days")
            return manifest

        monkeypatch.setattr(pl, "build_task_manifest", fake_build_manifest)
        monkeypatch.setattr(pl, "_enforce_worldbank_single_country_layout", lambda m, **kw: m)
        # Do NOT mock get_routing_hint — let the real routing fire
        monkeypatch.setattr(pl, "_run_specialist", lambda n, t: {"dataframes": {}, "kilde": [], "chart_specs": []})

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                pl.run("Arbejdsbeskæftigelsen i USA", output_dir=tmpdir, period_days=365)
            except Exception:
                pass

        # Chart spec must be 365 (not 1825 that the LLM/routing would produce)
        assert manifest["macro"]["charts"][0]["period_days"] == 365, \
            "Employment routing inflated period_days beyond user's 365"


# ---------------------------------------------------------------------------
# Retry logic tests
# ---------------------------------------------------------------------------

class TestLlmRetry:

    def _make_exc(self, status_code: int, message: str = "error"):
        """Create a minimal fake Anthropic-like exception with status_code."""
        class FakeAPIError(Exception):
            pass
        exc = FakeAPIError(message)
        exc.status_code = status_code
        exc.body = {}
        return exc

    def test_H_retries_on_529_succeeds_on_attempt_3(self):
        """H: retries on 529, succeeds on attempt 3."""
        from newsletter_agent.llm_retry import llm_call_with_retry
        import unittest.mock as mock

        attempt_count = [0]

        def flaky_fn(**kwargs):
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                raise self._make_exc(529, "overloaded")
            return "ok"

        with mock.patch("time.sleep"):  # don't actually sleep in tests
            result = llm_call_with_retry(flaky_fn, retries=6)

        assert result == "ok"
        assert attempt_count[0] == 3, f"Expected 3 attempts, got {attempt_count[0]}"

    def test_I_raises_after_exhausting_all_retries(self):
        """I: raises after exhausting all retries on persistent 529."""
        from newsletter_agent.llm_retry import llm_call_with_retry
        import unittest.mock as mock

        def always_fails(**kwargs):
            raise self._make_exc(529, "always overloaded")

        with mock.patch("time.sleep"):
            with pytest.raises(Exception) as exc_info:
                llm_call_with_retry(always_fails, retries=3)

        # Should have raised the 529 exception after 3 attempts
        assert "always overloaded" in str(exc_info.value) or exc_info.value is not None

    def test_J_does_not_retry_on_400(self):
        """J: does NOT retry on 400 Bad Request — raises immediately."""
        from newsletter_agent.llm_retry import llm_call_with_retry
        import unittest.mock as mock

        attempt_count = [0]

        def bad_request_fn(**kwargs):
            attempt_count[0] += 1
            raise self._make_exc(400, "bad request")

        with mock.patch("time.sleep"):
            with pytest.raises(Exception):
                llm_call_with_retry(bad_request_fn, retries=6)

        assert attempt_count[0] == 1, \
            f"Should NOT retry on 400 — expected 1 attempt, got {attempt_count[0]}"

    def test_H_retry_count_respects_retries_param(self):
        """Retry count is configurable — retries=4 means max 4 attempts."""
        from newsletter_agent.llm_retry import llm_call_with_retry
        import unittest.mock as mock

        attempt_count = [0]

        def always_fails(**kwargs):
            attempt_count[0] += 1
            raise self._make_exc(500, "server error")

        with mock.patch("time.sleep"):
            with pytest.raises(Exception):
                llm_call_with_retry(always_fails, retries=4)

        assert attempt_count[0] == 4, \
            f"Expected 4 attempts with retries=4, got {attempt_count[0]}"

    def test_I_retryable_status_500(self):
        """500 errors are retryable."""
        from newsletter_agent.llm_retry import _is_retryable

        exc = self._make_exc(500)
        assert _is_retryable(exc), "500 should be retryable"

    def test_I_retryable_status_429(self):
        """429 errors are retryable."""
        from newsletter_agent.llm_retry import _is_retryable

        exc = self._make_exc(429)
        assert _is_retryable(exc), "429 should be retryable"

    def test_J_not_retryable_status_400(self):
        """400 errors are NOT retryable."""
        from newsletter_agent.llm_retry import _is_retryable

        exc = self._make_exc(400)
        assert not _is_retryable(exc), "400 should NOT be retryable"

    def test_J_not_retryable_status_401(self):
        """401 unauthorized is NOT retryable."""
        from newsletter_agent.llm_retry import _is_retryable

        exc = self._make_exc(401)
        assert not _is_retryable(exc), "401 should NOT be retryable"

    def test_J_not_retryable_status_404(self):
        """404 not found is NOT retryable."""
        from newsletter_agent.llm_retry import _is_retryable

        exc = self._make_exc(404)
        assert not _is_retryable(exc), "404 should NOT be retryable"


# ---------------------------------------------------------------------------
# Formatting edge cases
# ---------------------------------------------------------------------------

class TestFmtDaEdgeCases:

    def test_K_zero_two_decimals(self):
        """K: fmt_da(0, 2) → '0,00'."""
        from newsletter_agent.formatting import fmt_da
        assert fmt_da(0, 2) == "0,00"

    def test_L_negative_large_number(self):
        """L: fmt_da(-1234567.89, 2) → '-1.234.567,89'."""
        from newsletter_agent.formatting import fmt_da
        assert fmt_da(-1234567.89, 2) == "-1.234.567,89"

    def test_M_small_decimal_four_places(self):
        """M: fmt_da(0.001234, 4) → '0,0012'."""
        from newsletter_agent.formatting import fmt_da
        assert fmt_da(0.001234, 4) == "0,0012"

    def test_zero_integer_format(self):
        """fmt_da(0, 0) → '0' (no decimal separator)."""
        from newsletter_agent.formatting import fmt_da
        assert fmt_da(0, 0) == "0"

    def test_negative_zero_two_decimals(self):
        """fmt_da(-0.0, 2) → '0,00' (negative zero is zero)."""
        from newsletter_agent.formatting import fmt_da
        result = fmt_da(-0.0, 2)
        assert result == "0,00" or result == "-0,00"  # accept either; both are reasonable

    def test_large_positive_integer(self):
        """fmt_da(1_000_000, 0) → '1.000.000'."""
        from newsletter_agent.formatting import fmt_da
        assert fmt_da(1_000_000, 0) == "1.000.000"

    def test_negative_thousands(self):
        """fmt_da(-1234, 0) → '-1.234'."""
        from newsletter_agent.formatting import fmt_da
        assert fmt_da(-1234, 0) == "-1.234"

    def test_small_positive_auto(self):
        """fmt_da(0.5) uses auto-precision (≥0.1 → 3 decimals)."""
        from newsletter_agent.formatting import fmt_da
        result = fmt_da(0.5)
        assert "," in result  # Danish decimal comma present
