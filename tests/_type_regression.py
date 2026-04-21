#!/usr/bin/env python3
"""
Chart type regression test — one real pipeline run per chart type family.
Reports every reviewer flag with its reason.
Run from the newsletter-site root:
    python3 tests/_type_regression.py 2>&1 | tee /tmp/regression_output.txt
"""
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Triggers load_dotenv() via config.py
from newsletter_agent.config import API_KEYS  # noqa: F401
from newsletter_agent.pipeline import run

TESTS = [
    {
        "name": "TYPE A+D — Time-series + companion table",
        "brief": "Vis US 10-årig og 2-årig Treasury yield samt Fed Funds raten siden 2022. Vis renterne som de er — ikke YoY.",
        "preferred_types": ["A", "D"],
        "period_days": 1566,
    },
    {
        "name": "TYPE F — 100% stacked composition bar",
        "brief": "Vis EU's samlede energimix over de seneste 5 år som 100% stacked bar fordelt på alle energikilder.",
        "preferred_types": ["F"],
        "period_days": 1826,
    },
    {
        "name": "TYPE P — Pie chart snapshot",
        "brief": (
            "Vis EU's energimix fordelt på naturgas, kul, kerneenergi, vind, sol og vandkraft "
            "som cirkeldiagram for det seneste tilgængelige år."
        ),
        "preferred_types": ["P"],
        "period_days": 730,
    },
    {
        "name": "TYPE G — Horizontal bar spread comparison",
        "brief": "Vis europæiske statsobligationsspænd vs. Tyskland: Frankrig, Italien, Spanien og Portugal.",
        "preferred_types": ["G"],
        "period_days": 730,
    },
    {
        "name": "TYPE B — Vertical bar cross-entity",
        "brief": "Sammenlign BNP-vækst i USA, Eurozone og Japan for de seneste tilgængelige år.",
        "preferred_types": ["B"],
        "period_days": 730,
    },
    {
        "name": "TYPE E — Before/after bars",
        "brief": (
            "Sammenlign Brent olie, guld og S&P 500 kurs før og efter Ruslands invasion af Ukraine "
            "den 24. februar 2022."
        ),
        "preferred_types": ["E"],
        "period_days": 1566,
    },
]

PASS = 0
FAIL = 0
FLAGS = []
ERRORS = []

for test in TESTS:
    print(f"\n{'='*72}")
    print(f"TEST: {test['name']}")
    print(f"Brief: {test['brief'][:90]}")
    print(f"{'='*72}")
    try:
        outdir = tempfile.mkdtemp(prefix="nl_test_")
        packages = run(
            brief=test["brief"],
            output_dir=outdir,
            preferred_types=test.get("preferred_types"),
            period_days=test.get("period_days", 730),
        )
        print(f"\n→ Produced {len(packages)} figure(s)")
        test_had_flag = False
        for pkg in packages:
            flag       = pkg["metadata"].get("reviewer_flag", "")
            title      = pkg["metadata"].get("title", "?")
            chart_type = pkg["metadata"].get("chart_type", "?")
            if flag:
                status = "🚩 FLAGGED"
                print(f"  {status} [{chart_type}] {title}")
                print(f"       → {flag}")
                FLAGS.append({
                    "test":  test["name"],
                    "type":  chart_type,
                    "title": title,
                    "flag":  flag,
                })
                test_had_flag = True
            else:
                print(f"  ✅ APPROVED [{chart_type}] {title}")
        if test_had_flag:
            FAIL += 1
        else:
            PASS += 1
    except Exception as exc:
        print(f"  ❌ EXCEPTION: {exc}")
        traceback.print_exc()
        ERRORS.append({"test": test["name"], "error": str(exc)})
        FAIL += 1

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n\n{'='*72}")
print(f"REGRESSION SUMMARY")
print(f"{'='*72}")
print(f"  Passed (zero flags):  {PASS}")
print(f"  Failed (flags/error): {FAIL}")

if FLAGS:
    print(f"\n--- Reviewer Flags ({len(FLAGS)}) ---")
    for f in FLAGS:
        print(f"  [{f['test']}]")
        print(f"    Type  : {f['type']}")
        print(f"    Title : {f['title']}")
        print(f"    Reason: {f['flag']}")
else:
    print("\n  No reviewer flags — all figures approved!")

if ERRORS:
    print(f"\n--- Exceptions ({len(ERRORS)}) ---")
    for e in ERRORS:
        print(f"  [{e['test']}]: {e['error']}")

print(f"{'='*72}")
