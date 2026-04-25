#!/usr/bin/env python3
"""Handoff verification: Ungarns Økonomi (5yr+10yr), Kinas Makroprofil, Danmark vs. Sverige."""
import json, requests, time

BASE = "http://localhost:5050"

CASES = [
    ("Ungarns Økonomi — 5yr",  "Ungarns Økonomi", ["A", "D"], 1825),
    ("Ungarns Økonomi — 10yr", "Ungarns Økonomi", ["A", "D"], 3650),
    ("Kinas Makroprofil",      "Kinas Makroprofil", ["A", "D"], None),
    ("Danmark vs. Sverige",    "Danmark vs. Sverige — økonomi", ["A", "D"], None),
]

def run(label, brief, types, period_days):
    print(f"\n{'='*70}")
    print(f"TEST: {label}")
    print(f"  brief={brief!r}  types={types}  period_days={period_days}")
    r = {"figures": 0, "errors": [], "warnings": [], "passed": False, "chart_types": []}
    body = {"brief": brief, "preferred_types": types}
    if period_days:
        body["period_days"] = period_days
    try:
        resp = requests.post(f"{BASE}/run", json=body, timeout=10)
        if resp.status_code != 200:
            r["errors"].append(f"POST /run returned {resp.status_code}: {resp.text[:200]}")
            return r
        with requests.get(f"{BASE}/stream", stream=True, timeout=180) as s:
            for line in s.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"): continue
                p = json.loads(line[5:].strip())
                if p.get("type") == "log":
                    t = p.get("text", "").strip()
                    print(f"  {t[:130]}")
                    if "[warn]" in t.lower():
                        r["warnings"].append(t[:200])
                    if "error" in t.lower() or "failed" in t.lower() or "traceback" in t.lower():
                        r["errors"].append(t[:200])
                elif p.get("type") == "done":
                    r["figures"] = len(p.get("figures", []))
                    r["chart_types"] = [f.get("chart_type","?") for f in p.get("figures", [])]
                    r["titles"] = [f.get("title","") for f in p.get("figures", [])]
                    r["passed"] = r["figures"] > 0
                    break
                elif p.get("type") == "error":
                    r["errors"].append(p.get("text", "")[:300])
                    break
    except Exception as e:
        r["errors"].append(str(e))

    status = "✅ PASS" if r["passed"] else "❌ FAIL"
    print(f"\n  → {status} | figures={r['figures']} | chart_types={r['chart_types']}")
    if r.get("titles"):
        for i, t in enumerate(r["titles"]):
            print(f"     [{i+1}] {t}")
    for e in r["errors"]:
        print(f"  ⚠ ERR: {e}")
    for w in r["warnings"]:
        print(f"  ⚠ WARN: {w}")
    return r

results = {}
for (label, brief, types, pd_) in CASES:
    results[label] = run(label, brief, types, pd_)
    time.sleep(3)

print(f"\n{'='*70}")
print("SUMMARY")
for label, r in results.items():
    status = "✅" if r["passed"] else "❌"
    warns = f"  {len(r['warnings'])} warn(s)" if r["warnings"] else ""
    errs  = f"  {len(r['errors'])} err(s)"   if r["errors"]   else ""
    print(f"  {status} {label}: {r['figures']} figs{warns}{errs}")
