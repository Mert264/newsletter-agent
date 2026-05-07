# newsletter_agent/specialists/annual_report_auditor.py
"""
Statement Auditor — automatic accounting consistency checks.
Returns a D-type chart spec if issues are found, None if the statements are clean.
Only material flags are surfaced; minor noise is suppressed.
"""
from __future__ import annotations


def _safe(val) -> float:
    return float(val) if val is not None else 0.0


def audit_statements(fmp_data: dict, reformulated: dict) -> dict | None:
    income   = fmp_data.get("income",   [])
    balance  = fmp_data.get("balance",  [])
    cashflow = fmp_data.get("cashflow", [])

    flags = []

    # ── 1. Balance sheet identity ─────────────────────────────────────────
    # Total Assets ≈ Total Liabilities + Stockholders' Equity + Minority Interest
    for b in balance[:3]:
        year   = (b.get("date") or "")[:4]
        assets = _safe(b.get("totalAssets"))
        liabs  = _safe(b.get("totalLiabilities"))
        equity = _safe(b.get("totalStockholdersEquity"))
        nci    = _safe(b.get("minorityInterest"))
        rhs    = liabs + equity + nci
        if assets > 0 and abs(assets - rhs) / assets > 0.02:
            gap_pct = abs(assets - rhs) / assets
            flags.append({
                "indicator": f"Balanceligning {year}",
                "Fund": f"Aktiver {assets:,.0f}m ≠ Passiver+EK {rhs:,.0f}m (afvigelse {gap_pct:.1%})",
                "Alvorlighed": "⚠ Høj",
            })

    # ── 2. Negative revenue ───────────────────────────────────────────────
    for inc in income[:5]:
        year = (inc.get("date") or "")[:4]
        rev  = _safe(inc.get("revenue"))
        if rev < 0:
            flags.append({
                "indicator": f"Omsætning {year}",
                "Fund": f"Negativ omsætning ({rev:,.0f}m) — sandsynligt dataproblem",
                "Alvorlighed": "⚠ Høj",
            })

    # ── 3. Quality of earnings: extreme OCF / Net Income divergence ───────
    for inc, cf in zip(income[:5], cashflow[:5]):
        year = (inc.get("date") or "")[:4]
        ni   = _safe(inc.get("netIncome"))
        ocf  = _safe(cf.get("operatingCashFlow"))
        if ni != 0 and ocf != 0 and abs(ocf / ni) > 5 and abs(ni) > 100:
            ratio = abs(ocf / ni)
            flags.append({
                "indicator": f"Resultatskvalitet {year}",
                "Fund": f"Driftslikviditet ({ocf:,.0f}m) er {ratio:.1f}× nettoindkomst — mulig stor periodisering",
                "Alvorlighed": "ℹ Middel",
            })

    # ── 4. Goodwill spike — M&A distortion ───────────────────────────────
    for i in range(1, min(5, len(balance))):
        year   = (balance[i - 1].get("date") or "")[:4]
        gw_new = _safe(balance[i - 1].get("goodwillAndIntangibleAssets"))
        gw_old = _safe(balance[i].get("goodwillAndIntangibleAssets"))
        if gw_old > 100 and (gw_new - gw_old) / gw_old > 0.50:
            jump = (gw_new - gw_old) / gw_old
            flags.append({
                "indicator": f"Goodwill {year}",
                "Fund": f"Goodwill steg {jump:.0%} — opkøbsaktivitet kan forvride historiske nøgletal",
                "Alvorlighed": "ℹ Middel",
            })

    # ── 5. Consecutive revenue declines (3+ years) ───────────────────────
    rev_series = [_safe(inc.get("revenue")) for inc in income[:5] if _safe(inc.get("revenue")) > 0]
    if len(rev_series) >= 3:
        # income is newest-first; rev_series[0] = latest
        declines = sum(
            1 for j in range(len(rev_series) - 1) if rev_series[j] < rev_series[j + 1]
        )
        if declines >= 3:
            flags.append({
                "indicator": "Omsætningstrend",
                "Fund": f"Faldende omsætning i {declines} af de seneste {len(rev_series) - 1} år — strukturel udfordring",
                "Alvorlighed": "ℹ Middel",
            })

    # ── 6. High-severity Penman NOA flags ────────────────────────────────
    for flag_text in reformulated.get("flags", []):
        flag_lower = flag_text.lower()
        if ("negativ" in flag_lower or "anomali" in flag_lower) and "[CALC]" in flag_text:
            year_part = flag_text[:4] if flag_text[:4].isdigit() else "?"
            flags.append({
                "indicator": f"NOA-klassificering {year_part}",
                "Fund": flag_text[:110],
                "Alvorlighed": "ℹ Middel",
            })

    if not flags:
        print(f"  [auditor] No material flags — skipping audit card.")
        return None

    print(f"  [auditor] {len(flags)} flag(s) found.")
    return {
        "type": "D",
        "title": "Revisionsflag",
        "note": (
            "Automatisk konsistenstjek af regnskabsdata. "
            "Høje (⚠) flag bør verificeres direkte i originale årsrapporter. "
            "Middel/lav (ℹ) flag er observationer til analytikervurdering."
        ),
        "kilde": "FMP",
        "table_data": {"columns": ["Fund", "Alvorlighed"], "rows": flags},
    }
