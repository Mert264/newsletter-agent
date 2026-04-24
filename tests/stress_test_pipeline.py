#!/usr/bin/env python3
"""
20-prompt stress test for the newsletter pipeline.
Runs each brief sequentially, collects SSE output, reports pass/fail.

Usage: python3 tests/stress_test_pipeline.py
"""
import json
import requests
import time
import sys

BASE = "http://localhost:5050"

PROMPTS = [
    # --- Language variety ---
    (1,  "language",    "Macaristan ekonomisi — BNP-vækst og inflation"),               # Turkish for Hungary
    (2,  "language",    "Montrez l'économie de la France — croissance du PIB et inflation"),  # French
    (3,  "language",    "Wirtschaft Deutschlands — BNP-Wachstum und Inflation"),         # German
    (4,  "language",    "Polandin talous — BNP-kasvu ja inflaatio"),                     # Finnish for Poland

    # --- Ambiguous country names ---
    (5,  "ambiguous",   "Vis Koreas økonomi — BNP-vækst og inflation de seneste 20 år"),
    (6,  "ambiguous",   "Sammenlign begge Congo-landes BNP-vækst"),
    (7,  "ambiguous",   "Vis Arabiens økonomi — offentlig gæld og betalingsbalance"),

    # --- Multi-country comparisons ---
    (8,  "comparison",  "Sammenlign Polen og Tjekkiet — BNP-vækst og inflation de seneste 20 år"),
    (9,  "comparison",  "Danmark, Sverige og Norge — sammenlign inflation de seneste 15 år"),
    (10, "comparison",  "G7-landenes offentlige gæld — USA, UK, Japan, Tyskland, Frankrig, Italien, Canada"),

    # --- Specific single indicators ---
    (11, "indicator",   "Vis kun Tyrkiets inflation de seneste 30 år"),
    (12, "indicator",   "Hvad er Brasiliens arbejdsløshed de seneste 20 år?"),

    # --- Small/data-sparse countries ---
    (13, "sparse",      "Vis Luxembourgs makroøkonomiske profil"),
    (14, "sparse",      "Vis Maltas BNP-vækst og inflation"),
    (15, "sparse",      "Libyens BNP-vækst de seneste 20 år"),

    # --- Routing collision tests ---
    (16, "routing",     "Vis inflation i USA og Ungarn — sammenlign de to lande"),
    (17, "routing",     "EU og Kinas BNP-vækst de seneste 20 år"),
    (18, "routing",     "Vis Japans økonomi — BNP-vækst, inflation og arbejdsløshed"),

    # --- Time horizon edge cases ---
    (19, "time",        "Vis Spaniens økonomi de seneste 5 år"),
    (20, "time",        "Vis Indiens BNP-vækst siden 1990 — de seneste 35 år"),
]


def run_brief(n, category, brief):
    print(f"\n{'='*70}")
    print(f"[{n:02d}/{len(PROMPTS)}] ({category}) {brief[:80]}")
    print(f"{'='*70}")

    result = {
        "n": n, "category": category, "brief": brief,
        "specialist": None, "series_count": None,
        "figures": 0, "errors": [], "warnings": [], "passed": False,
    }

    try:
        r = requests.post(f"{BASE}/run",
                          json={"brief": brief, "preferred_types": ["A", "D"]},
                          timeout=10)
        if r.status_code != 200:
            result["errors"].append(f"POST /run returned {r.status_code}")
            return result

        # Stream SSE
        with requests.get(f"{BASE}/stream", stream=True, timeout=120) as stream:
            for line in stream.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:].strip())
                ptype = payload.get("type")

                if ptype == "log":
                    text = payload.get("text", "")
                    print(f"  {text.strip()[:120]}")

                    if "Specialists activated:" in text:
                        result["specialist"] = text.split("Specialists activated:")[-1].strip()
                    if "[worldbank] Done —" in text:
                        try:
                            result["series_count"] = int(text.split("Done —")[1].split("series")[0].strip())
                        except Exception:
                            pass
                    if "[warn]" in text.lower() or "warning" in text.lower():
                        result["warnings"].append(text.strip())
                    if "error" in text.lower() or "traceback" in text.lower() or "exception" in text.lower():
                        result["errors"].append(text.strip()[:200])

                elif ptype == "done":
                    figs = payload.get("figures", [])
                    result["figures"] = len(figs)
                    result["passed"] = len(figs) > 0
                    break

                elif ptype == "error":
                    result["errors"].append(payload.get("text", "unknown error"))
                    break

    except Exception as e:
        result["errors"].append(str(e))

    status = "✅ PASS" if result["passed"] else "❌ FAIL"
    print(f"  → {status} | specialist={result['specialist']} | series={result['series_count']} | figs={result['figures']}")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  ⚠ ERROR: {e[:150]}")
    if result["warnings"]:
        for w in result["warnings"]:
            print(f"  ⚠ WARN: {w[:150]}")

    return result


def main():
    print(f"Newsletter Pipeline Stress Test — {len(PROMPTS)} prompts")
    print(f"Target: {BASE}")
    print()

    # Health check
    try:
        requests.get(BASE, timeout=5)
    except Exception as e:
        print(f"ERROR: Server not reachable at {BASE}: {e}")
        sys.exit(1)

    results = []
    for n, category, brief in PROMPTS:
        r = run_brief(n, category, brief)
        results.append(r)
        time.sleep(2)  # brief pause between runs

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    passed = sum(1 for r in results if r["passed"])
    print(f"Passed: {passed}/{len(results)}")
    print()
    print(f"{'#':>3}  {'Cat':<12} {'Spec':<20} {'Ser':>4} {'Figs':>5}  {'Status'}")
    print("-" * 70)
    for r in results:
        status = "✅" if r["passed"] else "❌"
        spec = (r["specialist"] or "?")[:20]
        print(f"{r['n']:>3}  {r['category']:<12} {spec:<20} {str(r['series_count'] or '?'):>4} {r['figures']:>5}  {status}")

    print()
    print("FAILURES:")
    failures = [r for r in results if not r["passed"]]
    if not failures:
        print("  None — all prompts produced figures.")
    for r in failures:
        print(f"  [{r['n']:02d}] ({r['category']}) {r['brief'][:70]}")
        for e in r["errors"]:
            print(f"       ERROR: {e[:150]}")

    print()
    print("WARNINGS:")
    warned = [r for r in results if r["warnings"]]
    if not warned:
        print("  None.")
    for r in warned:
        for w in r["warnings"]:
            print(f"  [{r['n']:02d}] {w[:150]}")

    # Save JSON report
    with open("/tmp/stress_test_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nFull results saved to /tmp/stress_test_results.json")


if __name__ == "__main__":
    main()
