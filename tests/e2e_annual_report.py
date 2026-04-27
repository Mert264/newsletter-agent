"""
End-to-end site simulation for the annual_report specialist.
Mirrors exactly what the site does:
  brief → orchestrator (real LLM) → pipeline specialist call (mocked FMP) → renderers

Usage:
    source ../.env && python3 tests/e2e_annual_report.py
"""
import os, sys, json, tempfile, traceback
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

PASSED, FAILED = [], []

def ok(label):   PASSED.append(label);  print(f"  ✓  {label}")
def fail(label, exc=None, detail=""):
    msg = str(exc) if exc else detail
    FAILED.append((label, msg))
    print(f"  ✗  {label}")
    if msg: print(f"       {msg[:200]}")

# ── Realistic fixture data (same as integration test) ─────────────────────────
def _inc(date, rev, ebit, ni, int_ex, sh):
    return {"date": date, "revenue": rev, "operatingIncome": ebit, "netIncome": ni,
            "comprehensiveIncomePeriodChange": ni, "interestExpense": int_ex,
            "weightedAverageShsOutDil": sh}

def _bal(date, ta, tl, cash, si, li, sd, ld, lse, eq, nci, gw):
    return {"date": date, "totalAssets": ta, "totalLiabilities": tl,
            "cashAndCashEquivalents": cash, "shortTermInvestments": si,
            "longTermInvestments": li, "shortTermDebt": sd, "longTermDebt": ld,
            "capitalLeaseObligations": lse, "totalStockholdersEquity": eq,
            "minorityInterest": nci, "goodwillAndIntangibleAssets": gw}

AAPL_DATA = {
    "income":  [_inc("2024-09-30",391035,123216,93736,2955,15334),
                _inc("2023-09-30",383285,114301,96995,3933,15813),
                _inc("2022-09-30",394328,119437,99803,2828,16215),
                _inc("2021-09-30",365817,108949,94680,2645,16701),
                _inc("2020-09-30",274515,66288,57411,2873,17528),
                _inc("2019-09-30",260174,63930,55256,3576,18595),
                _inc("2018-09-30",265595,70898,59531,3240,20000),
                _inc("2017-09-30",229234,61344,48351,2323,21007),
                _inc("2016-09-30",215639,60024,45687,1456,21883),
                _inc("2015-09-30",233715,71230,53394,1285,22471)],
    "balance": [_bal("2024-09-30",364980,308030,29943,35228,91781,10912,85750,12430,-66382,0,67202),
                _bal("2023-09-30",352583,290437,29965,31590,95805,11334,95281,12842,-62158,0,68510),
                _bal("2022-09-30",352755,302083,23646,24658,92968,11128,98959,12023,-50672,0,69702),
                _bal("2021-09-30",351002,287912,34940,27699,92978,15613,94680,11163,63090,0,69964),
                _bal("2020-09-30",323888,258549,38016,52927,97103,13769,98667,10504,65339,0,35357),
                _bal("2019-09-30",338516,248028,48844,51713,98154,16240,91807,9461,90488,0,34707),
                _bal("2018-09-30",365725,258578,25913,40388,170799,20748,93735,8912,107147,0,33996),
                _bal("2017-09-30",375319,241272,20289,53892,194714,18473,97207,7561,134047,0,33274),
                _bal("2016-09-30",321686,193437,20484,46671,170430,11605,75427,6700,128249,0,32612),
                _bal("2015-09-30",290345,171124,21120,20481,164065,8499,53463,5900,119355,0,31843)],
    "cashflow": [{"date":"2024-09-30","capitalExpenditure":-9447,"depreciationAndAmortization":11445}],
    "profile": {"beta":1.24,"mktCap":3450000,"price":224.87,"country":"US",
                "companyName":"Apple Inc.","currency":"USD","sharesOutstanding":15334},
    "rating":  [{"rating":"Aaa","ratingAgency":"Moody's"}],
    "metrics": [{"peRatio":34.2,"evToEbitda":27.1,"pbRatio":None,"priceToSalesRatio":8.83,"pfcfRatio":36.5}],
    "estimates": [],
}

# ── Step 1: Orchestrator — what manifest does it produce? ──────────────────────

def test_orchestrator(brief, ticker_expected):
    from newsletter_agent.orchestrator import build_task_manifest
    from newsletter_agent.routing import get_routing_hint

    label = f"orchestrator → {ticker_expected}"
    try:
        routing_hint = get_routing_hint(brief)
        manifest = build_task_manifest(brief, preferred_types=["A","D","bar"],
                                       routing_hint=routing_hint, period_days=None)
        specialists = manifest.get("specialists", [])

        if "annual_report" not in specialists:
            fail(label, detail=f"annual_report NOT in specialists. Got: {specialists}. Manifest: {json.dumps(manifest, indent=2)[:500]}")
            return None

        task = manifest.get("annual_report", {})
        ticker = task.get("ticker", "")
        if not ticker:
            fail(label, detail=f"No ticker in annual_report task. Task: {task}")
            return None

        ok(f"{label}: specialists={specialists}, ticker={ticker}, charts_planned={len(task.get('charts',[]))}")
        return task
    except Exception as e:
        fail(label, e, traceback.format_exc()[-300:])
        return None


# ── Step 2: Specialist execution (FMP mocked) ──────────────────────────────────

def _mock_fmp_response(data):
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status.return_value = None
    return m

def test_specialist_execution(task, fmp_fixture, label_prefix):
    from newsletter_agent.specialists.annual_report import fetch_annual_report

    side_effects = [
        _mock_fmp_response(fmp_fixture["income"]),
        _mock_fmp_response(fmp_fixture["balance"]),
        _mock_fmp_response(fmp_fixture["cashflow"]),
        _mock_fmp_response([fmp_fixture["profile"]]),   # FMP returns profile as list
        _mock_fmp_response(fmp_fixture["rating"]),
        _mock_fmp_response(fmp_fixture["metrics"]),
        _mock_fmp_response(fmp_fixture["estimates"]),
    ]

    with patch("newsletter_agent.specialists.annual_report_fmp.requests.get") as mock_get:
        mock_get.side_effect = side_effects
        try:
            os.environ["FMP_API_KEY"] = "test_key"
            from newsletter_agent.config import API_KEYS
            # Patch API_KEYS directly
            with patch.dict("newsletter_agent.config.API_KEYS", {"fmp": "test_key"}):
                result = fetch_annual_report(task)

            chart_specs = result.get("chart_specs", [])
            dataframes  = result.get("dataframes", {})

            if len(chart_specs) != 18:
                fail(f"{label_prefix} chart_specs count", detail=f"Expected 18, got {len(chart_specs)}")
                return None

            ok(f"{label_prefix} specialist: {len(chart_specs)} chart_specs, {len(dataframes)} dataframes")
            return result
        except Exception as e:
            fail(f"{label_prefix} specialist execution", e, traceback.format_exc()[-400:])
            return None


# ── Step 3: Renderer — does each chart spec render without error? ───────────────

def test_renderers(result, label_prefix, output_dir):
    from newsletter_agent.pipeline import _render_figure

    if result is None:
        fail(f"{label_prefix} renderers", detail="Skipped — specialist result is None")
        return

    chart_specs = result.get("chart_specs", [])
    rendered_ok = 0
    rendered_fail = 0
    skipped = 0

    for i, chart_spec in enumerate(chart_specs):
        output_path = os.path.join(output_dir, f"figure_{i:02d}.png")
        title = chart_spec.get("title", f"chart_{i}")
        try:
            package = _render_figure(chart_spec, result, output_path)
            if package is None:
                print(f"    [warn] Chart {i+1} '{title[:50]}' → None (skipped by renderer)")
                skipped += 1
            elif isinstance(package, list):
                rendered_ok += len(package)
                print(f"    ✓ Chart {i+1} '{title[:50]}' → {len(package)} figures (multi-year)")
            else:
                rendered_ok += 1
                file_size = os.path.getsize(package["path"]) if os.path.exists(package["path"]) else 0
                if file_size < 1000:
                    raise ValueError(f"PNG is suspiciously small: {file_size} bytes")
                print(f"    ✓ Chart {i+1} [{chart_spec.get('type')}] '{title[:50]}' → {file_size//1024}KB")
        except Exception as e:
            rendered_fail += 1
            print(f"    ✗ Chart {i+1} [{chart_spec.get('type')}] '{title[:50]}'")
            print(f"        {type(e).__name__}: {str(e)[:150]}")
            print(f"        {traceback.format_exc().splitlines()[-3]}")

    summary = f"{label_prefix} renderers: {rendered_ok} ok, {rendered_fail} failed, {skipped} skipped"
    if rendered_fail > 0:
        fail(summary)
    else:
        ok(summary)


# ── Step 4: Pipeline chart_spec override check ─────────────────────────────────

def test_chart_spec_override(manifest_task, result, label_prefix):
    """
    The pipeline uses result['chart_specs'] (from specialist) NOT manifest['charts'].
    Verify the specialist's chart_specs are what actually get rendered.
    """
    manifest_charts = manifest_task.get("charts", []) if manifest_task else []
    specialist_charts = result.get("chart_specs", []) if result else []

    if len(manifest_charts) == 0 and len(specialist_charts) == 18:
        ok(f"{label_prefix} chart override: manifest has 0 charts, specialist provides all 18 ✓")
    elif len(manifest_charts) > 0:
        fail(f"{label_prefix} chart override",
             detail=f"Manifest has {len(manifest_charts)} charts — specialist may be overridden")
    else:
        fail(f"{label_prefix} chart override",
             detail=f"manifest_charts={len(manifest_charts)}, specialist_charts={len(specialist_charts)}")


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # The actual briefs from the site UI (prompts 20–23)
    BRIEFS = {
        "AAPL": "Lav en komplet årsregnskabsanalyse af Apple Inc. (AAPL) efter Penman-metoden — reformulér balancen til NOA og NFO, dekomponér RNOA i OG og ATO, beregn WACC med Damodaran-konstanter og estimer den fundamentale aktiekurs via en 5-årig DCF-model med terminalværdi og følsomhedsanalyse.",
        "NVO":  "Analyser Novo Nordisk A/S (NVO) som investeringscase — reformulér regnskabet efter Penman-metoden, identificér M&A-distortioner i omsætningsvæksten, beregn WACC for en dansk virksomhed noteret i USA, og estimer den fundamentale aktiekurs via DCF. Sammenlign fundamentalprisen med markedsprisen.",
    }

    output_dir = tempfile.mkdtemp(prefix="e2e_annual_report_")
    print(f"\nOutput dir: {output_dir}")

    # Run for AAPL (full) and NVO (orchestrator only — same fixture, different ticker)
    for ticker, brief in BRIEFS.items():
        print(f"\n{'═'*65}")
        print(f"  E2E: {ticker}")
        print(f"{'═'*65}")

        # Step 1: Orchestrator
        task = test_orchestrator(brief, ticker)

        # If orchestrator returned series-nested ticker, the specialist should still extract it
        if task is not None and not task.get("ticker") and task.get("series"):
            nested = task["series"][0].get("ticker", "")
            print(f"  [check] Orchestrator nested ticker in series[0]: '{nested}' — testing fallback extraction")
            # Verify specialist can extract it
            from newsletter_agent.specialists.annual_report import fetch_annual_report as _far
            import inspect
            src = inspect.getsource(_far)
            if "_series0" not in src:
                fail(f"{ticker} series[0] fallback", detail="fetch_annual_report missing series[0] fallback")
            else:
                ok(f"{ticker} series[0] fallback extraction: specialist has fallback for nested ticker")

        if task is None:
            print(f"  [fallback] Using synthetic task for {ticker}")
            task = {"ticker": ticker, "label": f"{ticker} Analysis", "charts": [], "source": "annual_report"}
        elif not task.get("ticker"):
            # Use the series[0] nested format as-is — specialist should now handle it
            print(f"  [info] Using task as returned by orchestrator (series-nested ticker)")

        # Step 2: Specialist
        result = test_specialist_execution(task, AAPL_DATA, ticker)

        # Step 3: Renderers
        test_renderers(result, ticker, output_dir)

        # Step 4: Chart spec override
        test_chart_spec_override(task, result, ticker)

    print(f"\n{'═'*65}")
    print(f"  RESULTS: {len(PASSED)} passed, {len(FAILED)} failed")
    print(f"{'═'*65}")
    if FAILED:
        print("\nFAILED:")
        for label, msg in FAILED:
            print(f"  ✗ {label}")
            if msg: print(f"    → {msg[:300]}")
    else:
        print("\n  All checks passed.")
    print(f"\nPNGs saved to: {output_dir}")
