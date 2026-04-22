"""
Bulletproof test suite — all 14 prompts, all known fix categories + novel checks.

Run:  python3 tests/bulletproof_test.py
Output: tests/bulletproof_results.json  +  console summary
"""
import sys, os, json, re, io, time, traceback
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)

# Use Haiku for test LLM calls — cheaper + faster, sufficient for manifest validation
TEST_MODEL = "claude-haiku-4-5-20251001"

# ── Prompt registry (mirrors index.html BRIEFS + BRIEF_PERIODS) ────────────
PROMPTS = {
    1:  {"brief": "Iran erklærede krig mod Israel den 28. februar 2026. Vis Brent-råolie og europæisk naturgas (TTF), og markér udbruddet den 28. februar 2026. Vis også amerikansk naturgas (Henry Hub) for at illustrere prisforskellen mellem EU og USA på gas.",
         "period": 730, "label": "Iran-krig — olie & gas"},
    2:  {"brief": "Iran-krigen og Ukraine-krigen har accelereret det globale forsvarsforbrug. Vis Lockheed Martin, Rheinmetall, BAE Systems og Northrop Grumman indekseret til 100. Markér de geopolitiske begivenheder der falder inden for den valgte tidsperiode.",
         "period": 1825, "label": "Forsvarsaktier — genoprusning"},
    3:  {"brief": "Guld er steget som safe haven siden Iran-krigen brød ud den 28. februar 2026. Vis guldpriser og markér 28. februar 2026. Vis også kobberpriser for at sammenligne safe haven-rally med industrimetallers signal.",
         "period": 730, "label": "Guld & safe haven"},
    11: {"brief": "Trump-administrationen indførte historiske toldsatser den 2. april 2025. Vis Brent olie, S&P 500, EUR/USD og guld — sammenlign markedspriserne før og efter toldannoncen den 2. april 2025.",
         "period": 730, "label": "Trump-toldsatser"},
    4:  {"brief": "Rentespændet inden for Europa afspejler investorernes tillid til de enkelte landes økonomi. Vis 10-årige statsobligationsrenter for Tyskland, Frankrig, Italien, Spanien og UK i et horisontalt søjlediagram sorteret fra højest til lavest rente og sammenlign med den amerikanske 10-årige statsobligationsrente.",
         "period": 0, "label": "Europæiske statsrenter"},
    5:  {"brief": "Den amerikanske rentekurve har været en vigtig recessionindikator. Vis den 2-årige statsobligationsrente (DGS2) og den 10-årige statsobligationsrente (DGS10), og vis spændet (T10Y2Y) separat for at vise, hvornår kurven inverterede og normaliserede sig.",
         "period": 1825, "label": "Rentekurve & recessionssignal"},
    6:  {"brief": "Sammenlign de tre store centralbankers politikrenter: Federal Reserve (USA), ECB (Eurozonen) og Bank of England (UK). Vis hvornår de begyndte at hæve renter for at bekæmpe inflation, og hvornår de begyndte at sænke dem igen.",
         "period": 1825, "label": "Fed, ECB & Bank of England"},
    7:  {"brief": "Sammenlign kursudviklingen for de globale aktiemarkeder: S&P 500 (USA), Euro Stoxx 50 (Europa), Nikkei 225 (Japan) og MSCI Emerging Markets — indekseret til 100 for at illustrere, hvilke regioner der har leveret det bedste afkast.",
         "period": 1826, "label": "Globale aktiemarkeder"},
    8:  {"brief": "Den amerikanske dollar er styrket på baggrund af geopolitisk risiko fra Iran-krigen (28. februar 2026) og Trump-toldsatserne (2. april 2025). Vis DXY-indekset, EUR/USD, GBP/USD og JPY/USD og markér begge begivenheder.",
         "period": 730, "label": "Dollarstyrke & geopolitisk risiko"},
    9:  {"brief": "Vis kursudviklingen for europæiske vedvarende energiselskaber (Ørsted: ORSTED.CO, Vestas: VWS.CO, Iberdrola: IBE.MC) sammenlignet med store oliemajorer (Shell: SHEL.L, TotalEnergies: TTE.PA) — alle indekseret til 100. Illustrér om den grønne energiomstilling har leveret afkast til investorerne.",
         "period": 3650, "label": "Grøn energi vs. oliemajorer"},
    12: {"brief": "Vis EU's energiomstilling over tid som 100% stacked bar — fra kul og gas mod vedvarende energi. Vis andelen af naturgas, kul, kerneenergi, vind, sol og vandkraft for de seneste tilgængelige år.",
         "period": 0, "label": "EU energiomstilling — over tid"},
    10: {"brief": "Vis 10-årige statsobligationsrenter for Tyskland, Frankrig og Italien som absolutte niveauer — og vis rentespændet (Frankrig og Italien vs. Tyskland) i en separat figur. Dette illustrerer stressniveauer i europæiske obligationsmarkeder og presset på perifere landes finansiering.",
         "period": 730, "label": "EU obligationsrenter & stress"},
    13: {"brief": "Sammenlign den globale inflationsudvikling — USA, Euroområdet, UK og Japan — headline inflation år-over-år i procent. Brug følgende serier alle i macro-specialist: CPALTT01USM659N (source='fred', label='USA'), ea_hicp_yoy (source='eurostat_ts', label='Euroområdet'), CPALTT01GBM659N (source='fred', label='UK'), CPALTT01JPM659N (source='fred', label='Japan'). Alle serier er allerede i YoY % — sæt y_label='%'. Vis inflationstoppen i 2021–2022, disinflationen og nærheden til 2%-målet.",
         "period": 0, "label": "Global inflation — US, EA, UK, JP"},
    14: {"brief": "Vis et globalt markedsscorecard: Brent olie, guld, S&P 500, EUR/USD og den 10-årige amerikanske statsrente — nuværende niveauer sammenlignet med for 1 år siden.",
         "period": 0, "label": "Globalt markedsscorecard"},
}

# ── Known-fix check rules (applied to manifest JSON) ──────────────────────
def check_manifest(prompt_id, manifest, period_days_sent):
    """Validate the orchestrator manifest against all known rules. Returns list of issues."""
    issues = []
    warnings = []

    for specialist, spec_data in manifest.items():
        if specialist in ("specialists",):
            continue
        if not isinstance(spec_data, dict):
            continue

        series_list = spec_data.get("series", [])
        charts      = spec_data.get("charts", [])

        # ── Series checks ──────────────────────────────────────────────────
        for s in series_list:
            ticker = s.get("ticker", "")
            label  = s.get("label", "")

            # BOEBR and IRSTCB01GBM156N don't exist — should use IUDSOIA
            if ticker in ("BOEBR", "IRSTCB01GBM156N"):
                issues.append(f"[{specialist}] BoE rate uses invalid series {ticker} — should be IUDSOIA")

            # Old broken UK CPI series
            if "CP0000GB" in ticker:
                issues.append(f"[{specialist}] UK CPI uses broken series {ticker} — should be CPALTT01GBM659N")

            # GBRCPIALLMINMEI outdated
            if ticker in ("GBRCPIALLMINMEI", "JPNCPIALLMINMEI", "CHNCPIALLMINMEI"):
                issues.append(f"[{specialist}] {ticker} may be outdated — prefer CPALTT01*M659N series")

        # ── Chart spec checks ─────────────────────────────────────────────
        for c in charts:
            ctype  = c.get("type", "")
            ylabel = c.get("y_label", "")
            title  = c.get("title", "")
            note   = c.get("note", "")
            period = c.get("period_days", 0)
            labels = c.get("series_labels", [])
            events = c.get("events", [])

            # 1. Period must never be shorter than user's selection (>0)
            if period_days_sent and period_days_sent > 0 and period < period_days_sent:
                issues.append(f"[{specialist}] Chart '{title[:40]}': period_days={period} < user's {period_days_sent}")

            # 2. Pie charts must not be used for rate/yield/inflation data
            if ctype == "P":
                rate_keywords = ["rente", "yield", "rate", "obligat", "inflation", "cpi", "fed",
                                 "dgs", "ecb", "t10y", "spread", "procent", "basis point"]
                if any(k in title.lower() or k in ylabel.lower() for k in rate_keywords):
                    issues.append(f"[{specialist}] Type P pie chart used for rate/yield data: '{title[:50]}'")

            # 3. YoY must not be applied to already-YoY CPALTT series
            if "yoy" in ylabel.lower():
                for s in series_list:
                    if s.get("label", "") in labels and "CPALTT" in s.get("ticker", ""):
                        issues.append(f"[{specialist}] CPALTT series '{s['ticker']}' has y_label='{ylabel}'"
                                      f" — should be '%' (already YoY, double-transform will corrupt data)")

            # 4. Rate/yield companion D tables must have y_label="%" for pp formatting
            if ctype == "D":
                parent_charts = [ch for ch in charts if ch.get("type") == "A"
                                 and set(ch.get("series_labels", [])) & set(labels)]
                for pc in parent_charts:
                    if pc.get("y_label", "") == "%" and ylabel not in ("%", "pp", "Procentpoint", "YoY %"):
                        issues.append(f"[{specialist}] Companion D table '{title[:40]}': y_label='{ylabel}' "
                                      f"but parent A has y_label='%' — change to '%' for pp formatting")

            # 5. Mixed-unit charts must use 'Indekseret (basis=100)' not bare 'Indeks'
            if ylabel.strip().lower() == "indeks":
                issues.append(f"[{specialist}] Chart '{title[:40]}': y_label='Indeks' is too vague — "
                               f"use 'Indekseret (basis=100)' or a specific unit")

            # 6. Note must not contain source attribution
            if re.search(r"kilde:|source:|data fra:", note, re.IGNORECASE):
                issues.append(f"[{specialist}] Chart '{title[:40]}': note contains source attribution "
                               f"(use kilde field instead)")

            # 7. Title must exist and be non-trivial
            if not title or len(title) < 5:
                issues.append(f"[{specialist}] Chart missing title")

            # 8. Events: check dates are plausible (not future beyond 2030, not before 2000)
            for ev in events:
                ev_date = ev.get("date", "")
                try:
                    d = date.fromisoformat(ev_date)
                    if d.year > 2030:
                        warnings.append(f"[{specialist}] Event date {ev_date} seems far future")
                    if d.year < 2000:
                        warnings.append(f"[{specialist}] Event date {ev_date} seems too old")
                    # Event must be within period
                    if period > 0:
                        earliest = date.today() - timedelta(days=period)
                        if d < earliest:
                            issues.append(f"[{specialist}] Event '{ev.get('label','')}' on {ev_date} "
                                          f"is before the data window (period={period} days starts {earliest})")
                except Exception:
                    issues.append(f"[{specialist}] Invalid event date: {ev_date}")

            # 9. series_labels must not be empty for charts that need them
            if ctype in ("A", "B", "G", "D", "E") and not labels:
                warnings.append(f"[{specialist}] Chart '{title[:40]}' type {ctype} has no series_labels")

            # 10. spread chart should have compute_spread_vs matching a series label
            csv = c.get("compute_spread_vs", "")
            if csv:
                all_labels = [s.get("label","") for s in series_list]
                if not any(csv.lower() in l.lower() or l.lower() in csv.lower() for l in all_labels):
                    issues.append(f"[{specialist}] compute_spread_vs='{csv}' doesn't match any series label")

    return issues, warnings


# ── Full pipeline runner ───────────────────────────────────────────────────
def run_pipeline_test(prompt_id, brief, period_days, preferred_types=None):
    """Run the full pipeline for one prompt. Returns (figures, log_text, issues)."""
    from newsletter_agent.pipeline import run as run_pipeline

    buf = io.StringIO()
    figures = []
    pipeline_issues = []

    try:
        with redirect_stdout(buf):
            figures = run_pipeline(
                brief=brief,
                output_dir="demo_output/test",
                preferred_types=preferred_types or ["A", "D"],
                period_days=period_days if period_days > 0 else None,
                # Tier 2 uses Sonnet — Haiku generates noisier manifests that confuse
                # the Haiku reviewer (e.g. "over tid" in D table titles)
            )
    except Exception as e:
        tb = traceback.format_exc()
        pipeline_issues.append(f"EXCEPTION: {type(e).__name__}: {e}\n{tb}")
        buf.write(tb)

    log = buf.getvalue()

    # Scan log for known warning patterns
    if "[warn] series_labels mismatch" in log:
        mismatches = re.findall(r"\[warn\] series_labels mismatch.*", log)
        pipeline_issues.extend(mismatches)

    if "YoY transform" in log and "produced no data" in log:
        drops = re.findall(r"\[warn\] YoY transform.*produced no data.*", log)
        pipeline_issues.extend(drops)

    if "Failed to fetch FRED" in log:
        fails = re.findall(r"Failed to fetch FRED.*", log)
        pipeline_issues.extend(fails)

    if "Bad Request" in log or "does not exist" in log:
        bad = re.findall(r".*Bad Request.*|.*does not exist.*", log)
        pipeline_issues.extend(bad)

    if "REVISION NEEDED" in log:
        revisions = re.findall(r"\[reviewer\] REVISION NEEDED.*", log)
        pipeline_issues.extend(revisions)

    if "No data for chart" in log or "No data for Type" in log:
        nodata = re.findall(r"\[warn\] No data.*", log)
        pipeline_issues.extend(nodata)

    # Check figures
    for fig in figures:
        meta = fig.get("metadata", {})
        path = fig.get("path", "")

        # Max annotation check — should be gone
        # (can only verify visually, but log check is possible)
        if "↑ max" in log:
            pipeline_issues.append(f"Max annotation still present in log output")
            break

        # Reviewer flag in metadata
        flag = meta.get("reviewer_flag", "")
        if flag and "APPROVED" not in str(fig.get("review", {}).get("status", "APPROVED")):
            pipeline_issues.append(f"Reviewer flag on '{meta.get('title','?')[:50]}': {flag[:100]}")

        # Indeks y_label
        if meta.get("y_label", "").strip().lower() == "indeks":
            pipeline_issues.append(f"Figure '{meta.get('title','?')[:40]}' has bare y_label='Indeks'")

        # Missing title
        if not meta.get("title", "").strip():
            pipeline_issues.append(f"Figure at {path} has empty title")

        # Missing kilde
        if not meta.get("kilde", "").strip():
            pipeline_issues.append(f"Figure '{meta.get('title','?')[:40]}' missing kilde")

    return figures, log, pipeline_issues


# ── Orchestrator-only test (fast — just one LLM call per prompt) ──────────
def run_orchestrator_test(prompt_id, brief, period_days):
    from newsletter_agent.orchestrator import build_task_manifest
    buf = io.StringIO()
    manifest = {}
    issues = []
    warnings = []
    try:
        with redirect_stdout(buf):
            manifest = build_task_manifest(
                brief=brief,
                preferred_types=["A", "D"],
                period_days=period_days if period_days > 0 else None,
                model=TEST_MODEL,
            )
        issues, warnings = check_manifest(prompt_id, manifest, period_days if period_days > 0 else 0)
    except Exception as e:
        issues.append(f"Orchestrator EXCEPTION: {type(e).__name__}: {e}")
    return manifest, issues, warnings


# ── Novel checks (things easy to miss) ────────────────────────────────────
NOVEL_CHECKS = [
    # Check that period_days for prompts with events always covers the event
    ("Trump-toldsatser event coverage",
     lambda m, p: check_event_coverage(m, p, "2025-04-02")),
    ("Iran-krig event coverage",
     lambda m, p: check_event_coverage(m, p, "2026-02-28")),
]

def check_event_coverage(manifest, period_sent, event_date_str):
    event_date = date.fromisoformat(event_date_str)
    days_ago = (date.today() - event_date).days
    issues = []
    for specialist, spec_data in manifest.items():
        if not isinstance(spec_data, dict):
            continue
        for c in spec_data.get("charts", []):
            events = c.get("events", [])
            for ev in events:
                if ev.get("date", "") == event_date_str:
                    p = c.get("period_days", 0)
                    if p < days_ago:
                        issues.append(f"Chart period_days={p} too short — event {event_date_str} "
                                      f"is {days_ago} days ago, would fall outside window")
    return issues


# ── Main runner ────────────────────────────────────────────────────────────
def main():
    os.makedirs("demo_output/test", exist_ok=True)
    results = {}

    # ── TIER 1: Orchestrator tests for all 14 prompts (fast) ─────────────
    print("\n" + "="*70)
    print("TIER 1 — ORCHESTRATOR VALIDATION (all 14 prompts)")
    print("="*70)

    for pid, info in PROMPTS.items():
        label  = info["label"]
        brief  = info["brief"]
        period = info["period"]
        print(f"\n[{pid:>2}] {label}")
        t0 = time.time()
        manifest, issues, warnings = run_orchestrator_test(pid, brief, period)
        elapsed = time.time() - t0
        print(f"     Manifest: {len(manifest)} specialists, {elapsed:.1f}s")
        if issues:
            for iss in issues:
                print(f"     ❌ {iss}")
        else:
            print(f"     ✅ No manifest issues")
        if warnings:
            for w in warnings:
                print(f"     ⚠️  {w}")
        results[pid] = {
            "label": label, "manifest_issues": issues,
            "manifest_warnings": warnings, "pipeline_issues": [],
            "figures": 0,
        }

    # ── TIER 2: Full pipeline for highest-risk prompts ────────────────────
    FULL_PIPELINE_PROMPTS = [
        (6,  ["A", "D"],        "BoE fix — IRSTCB01GBM156N"),
        (13, ["A", "D"],        "Global inflation — EA HICP Eurostat + CPALTT US/UK/JP"),
        (5,  ["A", "D", "G"],   "Rentekurve — pie guard + pp format"),
        (10, ["A", "D"],        "EU bond stress — Germany visible"),
        (9,  ["P", "F"],        "EU energimix — product_filter + no axis reviewer flag"),
        (2,  ["A", "D"],        "Forsvarsaktier — indexed no-clip"),
        (3,  ["A", "D"],        "Guld & safe haven — indexed no-clip"),
        (11, ["A", "D"],        "Trump — period respects user slider"),
        (14, ["D"],             "Scorecard — mixed units, pp Ændring"),
        (4,  ["G", "D"],        "Europæiske statsrenter — pp Ændring for spreads"),
    ]

    print("\n" + "="*70)
    print("TIER 2 — FULL PIPELINE (selected high-risk prompts)")
    print("="*70)

    for pid, ptypes, reason in FULL_PIPELINE_PROMPTS:
        info   = PROMPTS[pid]
        label  = info["label"]
        brief  = info["brief"]
        period = info["period"]
        print(f"\n[{pid:>2}] {label}  ({reason})")
        t0 = time.time()
        figs, log, pipe_issues = run_pipeline_test(pid, brief, period, ptypes)
        elapsed = time.time() - t0
        print(f"     Figures: {len(figs)}, elapsed: {elapsed:.1f}s")
        if pipe_issues:
            for iss in pipe_issues:
                print(f"     ❌ {iss}")
        else:
            print(f"     ✅ Pipeline clean")
        # Check data currency for inflation prompt
        if pid == 13:
            for fig in figs:
                note = fig.get("metadata", {}).get("note", "")
                # Extract latest date from note (pattern: "Data: DD Mmm YYYY – DD Mmm YYYY")
                dates = re.findall(r"Data:.*–\s*(\d+ \w+ \d+)", note)
                if dates:
                    print(f"     📅 Latest data: {dates[-1]}")
                    if "2022" in dates[-1]:
                        pipe_issues.append("DATA STOPS AT 2022 — inflation series still outdated")
        results[pid]["pipeline_issues"] = pipe_issues
        results[pid]["figures"] = len(figs)

    # ── TIER 3: Novel checks ─────────────────────────────────────────────
    print("\n" + "="*70)
    print("TIER 3 — NOVEL / MISSED CHECKS")
    print("="*70)
    novel_issues = []

    # 3a: Verify reviewer prompt doesn't have conflicting rules
    from newsletter_agent.reviewer import REVIEWER_PROMPT
    if "type G" in REVIEWER_PROMPT and "auto-approve" in REVIEWER_PROMPT.lower():
        print("  ✅ Reviewer has Type G auto-approve rule")
    else:
        novel_issues.append("Reviewer missing Type G auto-approve rule")

    if "type D" in REVIEWER_PROMPT and "no axis" in REVIEWER_PROMPT.lower():
        print("  ✅ Reviewer has Type D no-axis rule")
    else:
        novel_issues.append("Reviewer missing Type D no-axis rule")

    if "type P" in REVIEWER_PROMPT and "auto-approve" in REVIEWER_PROMPT.lower():
        print("  ✅ Reviewer has Type P auto-approve rule")
    else:
        novel_issues.append("Reviewer missing Type P auto-approve rule")

    # 3b: Check pipeline pp logic covers all rate-related y_labels
    from newsletter_agent.pipeline import _build_table
    import inspect
    src = inspect.getsource(_build_table)
    for expected in ["Procentpoint", "YoY %"]:
        if expected in src:
            print(f"  ✅ _build_table use_absolute includes '{expected}'")
        else:
            novel_issues.append(f"_build_table use_absolute missing '{expected}'")

    # 3c: Check clipping logic skips indexed charts
    from newsletter_agent.renderers.charts import render_type_a
    chart_src = inspect.getsource(render_type_a)
    if "_is_absolute_price" in chart_src:
        print("  ✅ Spike clipping restricted to absolute-price charts")
    else:
        novel_issues.append("Spike clipping still applies to all charts (indexed series get clipped)")

    # 3d: Check max annotation removed
    if "↑ max" not in chart_src:
        print("  ✅ Max annotation removed from render_type_a")
    else:
        novel_issues.append("Max annotation still present in render_type_a")

    # 3e: Check orchestrator period_days wording
    from newsletter_agent.orchestrator import build_task_manifest
    import inspect as _inspect
    bld_src = _inspect.getsource(build_task_manifest)
    if "MINIMUM" in bld_src or "floor" in bld_src.lower():
        print("  ✅ Orchestrator period_days described as minimum/floor")
    else:
        novel_issues.append("Orchestrator period_days wording may still allow event minimum to shrink window")

    # 3f: Check BoE series in orchestrator prompt
    from newsletter_agent.orchestrator import SYSTEM_PROMPT
    if "IUDSOIA" in SYSTEM_PROMPT:
        print("  ✅ BoE rate updated to IRSTCB01GBM156N")
    else:
        novel_issues.append("BoE rate series not updated in SYSTEM_PROMPT")
    if "BOEBR" in SYSTEM_PROMPT and "unreliable" not in SYSTEM_PROMPT:
        novel_issues.append("BOEBR still listed in SYSTEM_PROMPT without 'unreliable' warning")

    # 3g: Check CPALTT inflation series in orchestrator
    if "CPALTT01GBM659N" in SYSTEM_PROMPT:
        print("  ✅ UK CPI updated to CPALTT01GBM659N")
    else:
        novel_issues.append("UK CPI not updated to CPALTT01GBM659N in SYSTEM_PROMPT")

    # 3h: Check pie chart guard in orchestrator
    if "PIE CHART RESTRICTION" in SYSTEM_PROMPT or "NEVER use Type P" in SYSTEM_PROMPT:
        print("  ✅ Pie chart guard present in orchestrator")
    else:
        novel_issues.append("Pie chart guard for non-compositional data missing from orchestrator")

    # 3i: Check F-type legend fix (no percentages in legend labels)
    from newsletter_agent.renderers.charts import render_type_f
    f_src = inspect.getsource(render_type_f)
    if "last_vals" in f_src and "legend_labels = list(pct.columns)" in f_src:
        print("  ✅ F-type legend shows fuel names only (no % suffix)")
    elif "legend_labels = list(pct.columns)" in f_src:
        print("  ✅ F-type legend shows fuel names only")
    else:
        novel_issues.append("F-type legend may still show percentage suffixes")

    # 3j: Check _place_end_labels clamping
    from newsletter_agent.renderers.charts import _place_end_labels
    el_src = inspect.getsource(_place_end_labels)
    if "yhi * 0.97" in el_src or "yhi - margin" in el_src:
        print("  ✅ End-labels clamped within axis range")
    else:
        novel_issues.append("End-labels not clamped — may still appear above title")

    # 3k: Check table header wrapping
    from newsletter_agent.renderers.tables import render_type_d, _wrap_col
    print("  ✅ Table header wrap function present")

    # 3l: Check YoY quarterly detection
    from newsletter_agent.processors.normalize import compute_yoy
    yoy_src = inspect.getsource(compute_yoy)
    if "avg_delta >= 60" in yoy_src or "quarterly" in yoy_src.lower():
        print("  ✅ YoY transform handles quarterly data")
    else:
        novel_issues.append("YoY transform may not detect quarterly data correctly")

    for iss in novel_issues:
        print(f"  ❌ {iss}")

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    total_manifest  = sum(len(r["manifest_issues"]) for r in results.values())
    total_pipeline  = sum(len(r["pipeline_issues"]) for r in results.values())
    total_novel     = len(novel_issues)
    print(f"  Manifest issues:  {total_manifest}")
    print(f"  Pipeline issues:  {total_pipeline}")
    print(f"  Novel/code checks: {total_novel} issues")
    print(f"  Total figures generated: {sum(r['figures'] for r in results.values())}")

    all_issues = {}
    for pid, r in results.items():
        combined = r["manifest_issues"] + r["pipeline_issues"]
        if combined:
            all_issues[r["label"]] = combined
    if novel_issues:
        all_issues["_code_checks"] = novel_issues

    with open("tests/bulletproof_results.json", "w") as f:
        json.dump({"summary": {"manifest": total_manifest, "pipeline": total_pipeline,
                               "novel": total_novel},
                   "issues": all_issues, "per_prompt": results}, f, indent=2)
    print("\n  Results saved → tests/bulletproof_results.json")
    return all_issues


if __name__ == "__main__":
    issues = main()
    if issues:
        print("\n❌ Issues found — see bulletproof_results.json for details")
        sys.exit(1)
    else:
        print("\n✅ All checks passed")
