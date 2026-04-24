#!/usr/bin/env python3
"""Quick retest of the 4 previously failing/warning prompts."""
import json, requests, time, sys

BASE = "http://localhost:5050"

PROMPTS = [
    (17, "routing",    "EU og Kinas BNP-vækst de seneste 20 år"),           # was: JSON parse FAIL
    (2,  "language",   "Montrez l'économie de la France — croissance du PIB et inflation"),  # was: inventing FRED codes
    (1,  "language",   "Macaristan ekonomisi — BNP-vækst og inflation"),     # was: y-axis reviewer flag
    (18, "routing",    "Vis Japans økonomi — BNP-vækst, inflation og arbejdsløshed"),  # was: gæld missing
]

def run(n, category, brief):
    print(f"\n[{n:02d}] ({category}) {brief[:80]}")
    r = {"n": n, "specialist": None, "figures": 0, "errors": [], "warnings": [], "passed": False}
    try:
        requests.post(f"{BASE}/run", json={"brief": brief, "preferred_types": ["A", "D"]}, timeout=10)
        with requests.get(f"{BASE}/stream", stream=True, timeout=120) as s:
            for line in s.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"): continue
                p = json.loads(line[5:].strip())
                if p.get("type") == "log":
                    t = p.get("text", "")
                    print(f"  {t.strip()[:120]}")
                    if "Specialists activated:" in t:
                        r["specialist"] = t.split("Specialists activated:")[-1].strip()
                    if "[warn]" in t.lower(): r["warnings"].append(t.strip())
                    if "error" in t.lower() or "failed" in t.lower(): r["errors"].append(t.strip()[:200])
                elif p.get("type") == "done":
                    r["figures"] = len(p.get("figures", []))
                    r["passed"] = r["figures"] > 0
                    break
                elif p.get("type") == "error":
                    r["errors"].append(p.get("text", ""))
                    break
    except Exception as e:
        r["errors"].append(str(e))
    status = "✅ PASS" if r["passed"] else "❌ FAIL"
    print(f"  → {status} | specialist={r['specialist']} | figs={r['figures']}")
    for e in r["errors"]: print(f"  ⚠ ERR: {e[:150]}")
    for w in r["warnings"]: print(f"  ⚠ WARN: {w[:150]}")
    return r

for args in PROMPTS:
    run(*args)
    time.sleep(2)
