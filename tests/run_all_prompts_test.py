"""
Full prompt test suite — runs orchestrator validation for all 22 HTML prompts.
Tier 1: LLM manifest check for every prompt (fast — ~5-10s each).
Tier 2: Full pipeline render for highest-risk prompts.

Run:  cd /Users/mertcandogusoy/newsletter-site && python3 tests/run_all_prompts_test.py
"""
import sys, os, json, re, io, time, traceback
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)

# ── All 22 prompts from index.html ──────────────────────────────────────────
PROMPTS = {
    1:  {"brief": "Iran erklærede krig mod Israel den 28. februar 2026. Vis Brent-råolie og europæisk naturgas (TTF), og markér udbruddet den 28. februar 2026. Vis også amerikansk naturgas (Henry Hub) for at illustrere prisforskellen mellem EU og USA på gas.",
         "period": 730,  "label": "Iran-krig — Olie & Gas"},
    2:  {"brief": "Iran-krigen og Ukraine-krigen har accelereret det globale forsvarsforbrug. Vis Lockheed Martin, Rheinmetall, BAE Systems og Northrop Grumman indekseret til 100. Markér de geopolitiske begivenheder der falder inden for den valgte tidsperiode.",
         "period": 1825, "label": "Forsvarsaktier — Genoprusning"},
    3:  {"brief": "Guld er steget som safe haven siden Iran-krigen brød ud den 28. februar 2026. Vis guldpriser og markér 28. februar 2026. Vis også kobberpriser for at sammenligne safe haven-rally med industrimetallers signal.",
         "period": 730,  "label": "Guld & Safe Haven"},
    4:  {"brief": "Rentespændet inden for Europa afspejler investorernes tillid til de enkelte landes økonomi. Vis 10-årige statsobligationsrenter for Tyskland, Frankrig, Italien, Spanien og UK i et horisontalt søjlediagram sorteret fra højest til lavest rente og sammenlign med den amerikanske 10-årige statsobligationsrente.",
         "period": 0,    "label": "Europæiske Statsrenter"},
    5:  {"brief": "Den amerikanske rentekurve har været en vigtig recessionindikator. Vis den 2-årige statsobligationsrente (DGS2) og den 10-årige statsobligationsrente (DGS10), og vis spændet (T10Y2Y) separat for at vise, hvornår kurven inverterede og normaliserede sig.",
         "period": 1825, "label": "Rentekurve & Recessionsignal"},
    6:  {"brief": "Sammenlign de tre store centralbankers politikrenter: Federal Reserve (USA), ECB (Eurozonen) og Bank of England (UK). Vis hvornår de begyndte at hæve renter for at bekæmpe inflation, og hvornår de begyndte at sænke dem igen.",
         "period": 1825, "label": "Fed, ECB & Bank of England"},
    7:  {"brief": "Sammenlign kursudviklingen for de globale aktiemarkeder: S&P 500 (USA), Euro Stoxx 50 (Europa), Nikkei 225 (Japan) og MSCI Emerging Markets — indekseret til 100 for at illustrere, hvilke regioner der har leveret det bedste afkast.",
         "period": 1826, "label": "Globale Aktiemarked"},
    8:  {"brief": "Den amerikanske dollar er styrket på baggrund af geopolitisk risiko fra Iran-krigen (28. februar 2026) og Trump-toldsatserne (2. april 2025). Vis DXY-indekset, EUR/USD, GBP/USD og JPY/USD og markér begge begivenheder.",
         "period": 730,  "label": "Dollarstyrke & Geopolitisk Risiko"},
    9:  {"brief": "Vis kursudviklingen for europæiske vedvarende energiselskaber (Ørsted: ORSTED.CO, Vestas: VWS.CO, Iberdrola: IBE.MC) sammenlignet med store oliemajorer (Shell: SHEL.L, TotalEnergies: TTE.PA) — alle indekseret til 100. Illustrér om den grønne energiomstilling har leveret afkast til investorerne.",
         "period": 3650, "label": "Grøn Energi vs. Oliemagter"},
    10: {"brief": "Vis 10-årige statsobligationsrenter for Tyskland, Frankrig og Italien som absolutte niveauer — og vis rentespændet (Frankrig og Italien vs. Tyskland) i en separat figur. Dette illustrerer stressniveauer i europæiske obligationsmarkeder og presset på perifere landes finansiering.",
         "period": 730,  "label": "EU Obligationsrenter & Stress"},
    11: {"brief": "Trump-administrationen indførte historiske toldsatser den 2. april 2025. Vis Brent olie, S&P 500, EUR/USD og guld — sammenlign markedspriserne før og efter toldannoncen den 2. april 2025.",
         "period": 730,  "label": "Trump-toldsatser"},
    12: {"brief": "Vis EU's energiomstilling over tid som 100% stacked bar — fra kul og gas mod vedvarende energi. Vis andelen af naturgas, kul, kerneenergi, vind, sol og vandkraft for de seneste tilgængelige år.",
         "period": 0,    "label": "EU Energiomstilling"},
    13: {"brief": "Sammenlign den globale inflationsudvikling — USA, Euroområdet, UK og Japan — headline CPI/HICP år-over-år i procent. Vis inflationstoppen i 2021–2022, disinflationen og nærheden til centralbankernes 2%-mål.",
         "period": 0,    "label": "Global Inflation — US, EU, UK, CN"},
    14: {"brief": "Vis et globalt markedsscorecard: Brent olie, guld, S&P 500, EUR/USD og den 10-årige amerikanske statsrente — nuværende niveauer sammenlignet med for 1 år siden.",
         "period": 0,    "label": "Globalt Markedsscorecard"},
    15: {"brief": "Vis EU's elproduktion fordelt på energikilder — vind, sol, naturgas, kul og kerneenergi — som andel af samlet produktion over de seneste 10 år. Illustrér den grønne omstilling i elnettet.",
         "period": 3650, "label": "EU Elproduktion"},
    16: {"brief": "Vis Ungarns makroøkonomiske profil — BNP-vækst, inflation, arbejdsløshed, offentlig gæld og betalingsbalance de seneste 20 år.",
         "period": 7300, "label": "Ungarns Økonomi"},
    17: {"brief": "Sammenlign Danmarks og Sveriges økonomi — BNP-vækst, inflation og offentlig gæld de seneste 20 år.",
         "period": 7300, "label": "Danmark vs. Sverige"},
    18: {"brief": "Vis Kinas makroøkonomiske udvikling — BNP-vækst, inflation og betalingsbalance de seneste 20 år.",
         "period": 7300, "label": "Kinas Makroprofil"},
    19: {"brief": "Lav en komplet årsregnskabsanalyse af Apple Inc. (AAPL) — reformulér balancen, dekomponér RNOA, beregn WACC og estimer den fundamentale aktiekurs via en 5-årig DCF-model.",
         "period": 0,    "label": "Apple — AAPL"},
    20: {"brief": "Lav en komplet årsregnskabsanalyse af Amazon.com (AMZN) — reformulér balancen, dekomponér RNOA, beregn WACC og estimer den fundamentale aktiekurs via en 5-årig DCF-model.",
         "period": 0,    "label": "Amazon — AMZN"},
    21: {"brief": "Lav en komplet årsregnskabsanalyse af Microsoft Corp. (MSFT) — reformulér balancen, dekomponér RNOA, beregn WACC og estimer den fundamentale aktiekurs via en 5-årig DCF-model.",
         "period": 0,    "label": "Microsoft — MSFT"},
    22: {"brief": "Lav en komplet årsregnskabsanalyse af Nvidia Corp. (NVDA) — reformulér balancen, dekomponér RNOA, beregn WACC og estimer den fundamentale aktiekurs via en 5-årig DCF-model.",
         "period": 0,    "label": "Nvidia — NVDA"},
}

# ── Known broken/risky tickers and series ───────────────────────────────────
BAD_TICKERS = {
    "BOEBR": "BoE rate — use IUDSOIA",
    "IRSTCB01GBM156N": "BoE rate invalid — use IUDSOIA",
    "CP0000GB": "UK CPI broken — use CPALTT01GBM659N",
    "GBRCPIALLMINMEI": "UK CPI outdated — use CPALTT01GBM659N",
    "JPNCPIALLMINMEI": "Japan CPI outdated — use CPALTT01JPM659N",
}

# Annual report prompts require FMP API — skip full pipeline for these
ANNUAL_REPORT_IDS = {19, 20, 21, 22}

def check_manifest(pid, manifest, period_sent):
    issues, warnings = [], []
    for specialist, spec in manifest.items():
        if specialist == "specialists" or not isinstance(spec, dict):
            continue
        for s in spec.get("series", []):
            t = s.get("ticker", "")
            for bad, msg in BAD_TICKERS.items():
                if bad in t:
                    issues.append(f"[{specialist}] Bad ticker '{t}': {msg}")

        for c in spec.get("charts", []):
            ctype  = c.get("type", "")
            ylabel = c.get("y_label", "")
            title  = c.get("title", "")
            note   = c.get("note", "")
            period = c.get("period_days", 0)
            events = c.get("events", [])
            labels = c.get("series_labels", [])

            if not title or len(title) < 5:
                issues.append(f"[{specialist}] Missing/trivial chart title")

            if ylabel.strip().lower() == "indeks":
                issues.append(f"[{specialist}] '{title[:35]}': y_label='Indeks' too vague — use 'Indekseret (basis=100)'")

            if ctype == "P":
                rate_kw = ["rente", "yield", "rate", "obligat", "inflation", "cpi", "fed", "dgs", "ecb", "t10y"]
                if any(k in title.lower() or k in ylabel.lower() for k in rate_kw):
                    issues.append(f"[{specialist}] Pie chart used for rate/yield data: '{title[:40]}'")

            if re.search(r"kilde:|source:|data fra:", note, re.IGNORECASE):
                issues.append(f"[{specialist}] '{title[:35]}': note contains source attribution")

            # Only flag if orchestrator period is extremely short (<90 days) — pipeline
            # enforces the user's period at runtime so Tier-1-only checks are misleading.
            if period > 0 and period < 90:
                issues.append(f"[{specialist}] '{title[:35]}': period_days={period} dangerously short (<90d)")

            for ev in events:
                ev_date_str = ev.get("date", "")
                try:
                    ev_date = date.fromisoformat(ev_date_str)
                    if period > 0:
                        earliest = date.today() - timedelta(days=period)
                        if ev_date < earliest:
                            issues.append(f"[{specialist}] Event '{ev.get('label','')}' ({ev_date_str}) outside window (period={period}d)")
                except Exception:
                    issues.append(f"[{specialist}] Invalid event date: {ev_date_str}")

            if ctype in ("A", "B", "G", "D", "E") and not labels:
                warnings.append(f"[{specialist}] '{title[:35]}' type {ctype} has no series_labels")

    return issues, warnings


def run_orchestrator_test(pid, brief, period_days):
    from newsletter_agent.orchestrator import build_task_manifest
    buf = io.StringIO()
    manifest = {}
    issues, warnings = [], []
    try:
        with redirect_stdout(buf):
            manifest = build_task_manifest(brief)
        issues, warnings = check_manifest(pid, manifest, period_days)
    except Exception as e:
        issues.append(f"EXCEPTION: {type(e).__name__}: {e}")
    return manifest, issues, warnings


def run_full_pipeline(pid, brief, period_days):
    from newsletter_agent.pipeline import run as pipeline_run
    buf = io.StringIO()
    figures = []
    pipe_issues = []
    try:
        with redirect_stdout(buf):
            figures = pipeline_run(
                brief=brief,
                output_dir=f"demo_output/test/prompt_{pid}",
                period_days=period_days if period_days > 0 else None,
            )
    except Exception as e:
        pipe_issues.append(f"EXCEPTION: {type(e).__name__}: {e}")
        buf.write(traceback.format_exc())

    log = buf.getvalue()
    if "Failed to fetch FRED" in log:
        pipe_issues += re.findall(r"Failed to fetch FRED.*", log)
    if "Bad Request" in log or "does not exist" in log:
        pipe_issues += re.findall(r".*(?:Bad Request|does not exist).*", log)
    if "REVISION NEEDED" in log:
        pipe_issues += re.findall(r"\[reviewer\] REVISION NEEDED.*", log)
    if "[warn]" in log:
        pipe_issues += re.findall(r"\[warn\].*", log)

    for fig in figures:
        if not isinstance(fig, dict):
            pipe_issues.append(f"Unexpected figure type in result: {type(fig).__name__}")
            continue
        meta = fig.get("metadata", {})
        flag = meta.get("reviewer_flag", "")
        if flag:
            pipe_issues.append(f"Reviewer flag on '{meta.get('title','?')[:50]}': {flag[:120]}")
        if not meta.get("title", "").strip():
            pipe_issues.append(f"Figure missing title")
        if not meta.get("kilde", "").strip():
            pipe_issues.append(f"Figure '{meta.get('title','?')[:40]}' missing kilde")

    return figures, log, pipe_issues


# ── TIER 2: which prompts to run full pipeline ───────────────────────────────
FULL_PIPELINE_IDS = {1, 5, 6, 7, 8, 11, 13, 14}  # representative mix

def main():
    os.makedirs("demo_output/test", exist_ok=True)
    results = {}

    print("\n" + "="*72)
    print("TIER 1 — ORCHESTRATOR VALIDATION (all 22 prompts, ~5-10s each)")
    print("="*72)

    for pid in sorted(PROMPTS):
        info   = PROMPTS[pid]
        brief  = info["brief"]
        period = info["period"]
        label  = info["label"]
        print(f"\n[{pid:>2}] {label}")
        t0 = time.time()
        manifest, issues, warnings = run_orchestrator_test(pid, brief, period)
        elapsed = time.time() - t0
        specialists = manifest.get("specialists", [])
        print(f"     Specialists: {specialists}  ({elapsed:.1f}s)")
        status = "✅" if not issues else "❌"
        if issues:
            for iss in issues:
                print(f"     ❌ {iss}")
        else:
            print(f"     ✅ Manifest OK")
        for w in warnings:
            print(f"     ⚠️  {w}")
        results[pid] = {"label": label, "manifest_issues": issues,
                        "manifest_warnings": warnings, "pipeline_issues": [], "figures": 0}

    print("\n" + "="*72)
    print("TIER 2 — FULL PIPELINE (representative + high-risk prompts)")
    print("="*72)

    for pid in sorted(FULL_PIPELINE_IDS):
        if pid in ANNUAL_REPORT_IDS:
            print(f"\n[{pid:>2}] SKIPPED — årsregnskab requires FMP API key")
            continue
        info   = PROMPTS[pid]
        brief  = info["brief"]
        period = info["period"]
        label  = info["label"]
        print(f"\n[{pid:>2}] {label}")
        t0 = time.time()
        figs, log, pipe_issues = run_full_pipeline(pid, brief, period)
        elapsed = time.time() - t0
        print(f"     Figures: {len(figs)}, elapsed: {elapsed:.1f}s")
        if pipe_issues:
            for iss in pipe_issues:
                print(f"     ❌ {iss}")
        else:
            print(f"     ✅ Pipeline clean")
        results[pid]["pipeline_issues"] = pipe_issues
        results[pid]["figures"] = len(figs)

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "="*72)
    print("SUMMARY")
    print("="*72)
    total = len(results)
    manifest_fails = [pid for pid, r in results.items() if r["manifest_issues"]]
    pipeline_fails = [pid for pid, r in results.items() if r["pipeline_issues"]]
    print(f"Total prompts tested: {total}")
    print(f"Manifest failures:    {len(manifest_fails)} — {manifest_fails}")
    print(f"Pipeline failures:    {len(pipeline_fails)} — {pipeline_fails}")

    out_path = "tests/test_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nFull results saved → {out_path}")

    return results


if __name__ == "__main__":
    main()
