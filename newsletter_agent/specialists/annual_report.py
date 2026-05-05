import anthropic
from newsletter_agent.config import API_KEYS
from newsletter_agent.specialists.annual_report_constants import (
    STATUTORY_TAX_RATE, normalize_country,
)
from newsletter_agent.specialists.annual_report_fmp import fetch_all
from newsletter_agent.specialists.annual_report_reformulator import reformulate
from newsletter_agent.specialists.annual_report_checker import check
from newsletter_agent.specialists.annual_report_valuation import (
    compute_wacc, compute_dcf_scenarios, compute_sensitivity,
)
from newsletter_agent.specialists.annual_report_da import (
    review_reformulation, review_valuation, review_final,
)
from newsletter_agent.specialists.annual_report_kpi import build_chart_specs
from newsletter_agent.config import REVIEWER_MODEL


def _generate_summary_bullets(
    company_name: str, ticker: str, currency: str,
    reformulated: dict, wacc_data: dict, dcf_scenarios: dict,
    market_price: float, da_reviews: list[str],
    client: anthropic.Anthropic,
) -> list[str]:
    """Call Claude for 4 concise analyst bullet points tailored to this company's numbers."""
    nopat_margin = reformulated["historical_avgs"]["OG"]
    ato          = reformulated["historical_avgs"]["ATO"]
    base_price   = dcf_scenarios["base"]["price"]
    upside       = (base_price - market_price) / market_price if market_price > 0 else 0
    wacc         = wacc_data["wacc"]
    nfo          = reformulated["NFO"][-1]
    net_cash     = nfo < 0
    cap_str      = "net cash" if net_cash else f"net debt {abs(nfo):,.0f}m {currency}"
    n_avg        = reformulated.get("n_avg_years", "?")
    rev_cagr     = reformulated["historical_avgs"]["revenue_cagr"]

    # Extract any WARN/BLOCK flags from DA reviews
    flags = []
    for review in da_reviews:
        for line in review.splitlines():
            if "WARN" in line or "BLOCK" in line:
                flags.append(line.strip("•– ").strip())
    flags_str = "; ".join(flags[:2]) if flags else "None"

    prompt = (
        f"Skriv præcis 4 korte punkter til en professionel aktieanalyse-opsummering af {company_name} ({ticker}). Skriv på dansk.\n"
        f"Hvert punkt: maks 12 ord. Vær specifik på tallene. Ingen forbehold.\n\n"
        f"Numbers:\n"
        f"- NOPAT margin ({n_avg}yr avg): {nopat_margin:.1%} (benchmark: >10% strong for large-caps)\n"
        f"- ATO (Revenue/NOA): {ato:.2f}× (benchmark: >1× healthy)\n"
        f"- Revenue CAGR: {rev_cagr:.1%}\n"
        f"- WACC: {wacc:.1%} (typical 7–10% investment-grade large-caps)\n"
        f"- Capital structure: {cap_str}\n"
        f"- Base fair value: {base_price:.0f} {currency} vs market: {market_price:.0f} {currency} ({upside:+.0%})\n"
        f"- Model flags: {flags_str}\n\n"
        f"Bullets (return only the 4 lines, no numbering, no bullet symbols):\n"
        f"1. NOPAT margin vs benchmark — what it signals about profitability\n"
        f"2. Capital efficiency (ATO) and revenue growth — what they reveal\n"
        f"3. Fair value vs market — is the gap a model limitation or a real signal?\n"
        f"4. Key risk or flag — or 'No critical model flags' if clean\n"
    )
    msg = client.messages.create(
        model=REVIEWER_MODEL,
        max_tokens=180,
        messages=[{"role": "user", "content": prompt}],
    )
    lines = [ln.strip() for ln in msg.content[0].text.strip().splitlines() if ln.strip()]
    return lines[:4]


def fetch_annual_report(task: dict) -> dict:
    _series0 = task.get("series", [{}])[0] if task.get("series") else {}
    ticker = (
        task.get("ticker") or
        _series0.get("ticker") or
        task.get("label") or
        ""
    ).upper().strip()
    if not ticker:
        raise ValueError("annual_report specialist requires 'ticker' field in task.")

    fmp_key = API_KEYS.get("fmp", "")
    if not fmp_key:
        raise ValueError("FMP_API_KEY not configured. Set FMP_API_KEY env var.")

    client = anthropic.Anthropic()

    print(f"  [annual_report] Fetching FMP data for {ticker}...")
    fmp_data = fetch_all(ticker, fmp_key)

    profile      = fmp_data["profile"]
    hq_country   = profile.get("country", "_default")
    company_name = profile.get("companyName", ticker)
    currency     = profile.get("currency", "USD")
    iso3         = normalize_country(hq_country)
    t            = STATUTORY_TAX_RATE.get(iso3, STATUTORY_TAX_RATE["_default"])

    print(f"  [annual_report] Reformulating Penman financials...")
    reformulated = reformulate(fmp_data, t=t)

    if reformulated["NOA"][-1] <= 0:
        raise ValueError(
            f"NOA for {ticker} is non-positive ({reformulated['NOA'][-1]:,.0f}). "
            "Check balance sheet classification — possible data quality issue."
        )

    da1 = review_reformulation(reformulated, client)
    print(f"  [annual_report] DA #1 (reformulation): {da1[:120]}...")

    print(f"  [annual_report] Computing WACC...")
    wacc_data = compute_wacc(fmp_data, reformulated, hq_country)

    print(f"  [annual_report] Running consistency check...")
    check_result = check(wacc_data["checker_inputs"])
    if not check_result["passed"]:
        print(f"  [annual_report] WARNING: Consistency check issues for {ticker}:")
        for issue in check_result["issues"]:
            print(f"    • {issue}")

    print(f"  [annual_report] Running DCF scenarios (Bear / Base / Bull)...")
    NFO            = reformulated["NFO"][-1]
    NCI            = reformulated["NCI"][-1]
    diluted_shares = float(
        fmp_data["income"][0].get("weightedAverageShsOutDil") or
        profile.get("sharesOutstanding") or 1
    )
    base_year = reformulated["years"][-1]
    wacc      = wacc_data["wacc"]
    estimates = fmp_data.get("estimates", [])

    dcf_scenarios = compute_dcf_scenarios(
        reformulated, wacc_base=wacc,
        NFO=NFO, NCI=NCI,
        diluted_shares=diluted_shares, base_year=base_year,
        estimates=estimates,
        ltm_income=fmp_data.get("ltm_income"),
    )
    sensitivity = compute_sensitivity(
        reformulated, wacc_base=wacc, g_base=0.02,
        NFO=NFO, NCI=NCI,
        diluted_shares=diluted_shares, base_year=base_year,
    )

    market_price = float(profile.get("price") or 0)
    base_price   = dcf_scenarios["base"]["price"]
    if base_price < 0:
        print(f"  [annual_report] WARNING: base fair value={base_price:.2f} < 0 "
              f"(EV={dcf_scenarios['base']['detail']['EV']:,.0f} < NFO+NCI={NFO+NCI:,.0f}).")

    da3 = review_valuation(wacc_data, dcf_scenarios, market_price, client)
    print(f"  [annual_report] DA #3 (valuation): {da3[:120]}...")

    print(f"  [annual_report] Building chart specs...")
    chart_specs, dataframes = build_chart_specs(
        ticker, company_name, iso3,
        reformulated, wacc_data, dcf_scenarios, sensitivity, fmp_data,
    )

    bear_price = dcf_scenarios["bear"]["price"]
    bull_price = dcf_scenarios["bull"]["price"]
    da5 = review_final(chart_specs, (bear_price, base_price, bull_price), market_price, client)
    print(f"  [annual_report] DA #2 (final): {da5[:120]}...")

    # Analyst summary card — prepended so it appears first in the output
    print(f"  [annual_report] Generating analyst summary...")
    try:
        bullets = _generate_summary_bullets(
            company_name, ticker, currency,
            reformulated, wacc_data, dcf_scenarios,
            market_price, [da3, da5], client,
        )
        summary_spec = {
            "type":    "summary",
            "title":   f"{company_name} ({ticker}) — Analyst Summary",
            "bullets": bullets,
            "note":    "Penman DCF-model. Data: FMP, Damodaran. Modeloutput — ikke et faktisk resultat.",
            "kilde":   "FMP, Damodaran",
        }
        chart_specs = [summary_spec] + chart_specs
    except Exception as exc:
        print(f"  [annual_report] Summary generation failed (non-fatal): {exc}")

    return {
        "dataframes":  dataframes,
        "kilde":       ["FMP", "Damodaran"],
        "chart_specs": chart_specs,
    }
