import anthropic
from newsletter_agent.config import API_KEYS
from newsletter_agent.specialists.annual_report_constants import (
    STATUTORY_TAX_RATE, normalize_country,
)
from newsletter_agent.specialists.annual_report_fmp import fetch_all
from newsletter_agent.specialists.annual_report_reformulator import reformulate
from newsletter_agent.specialists.annual_report_checker import check
from newsletter_agent.specialists.annual_report_valuation import (
    compute_wacc, compute_dcf, compute_sensitivity,
)
from newsletter_agent.specialists.annual_report_da import (
    review_reformulation, review_consistency, review_valuation,
    review_kpi_specs, review_final,
)
from newsletter_agent.specialists.annual_report_kpi import build_chart_specs


def fetch_annual_report(task: dict) -> dict:
    ticker = (task.get("ticker") or task.get("label") or "").upper().strip()
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
    da2 = review_consistency(check_result, client)
    print(f"  [annual_report] DA #2 (consistency): {da2[:120]}...")

    if not check_result["passed"]:
        raise ValueError(
            f"Consistency check failed for {ticker}:\n" +
            "\n".join(check_result["issues"])
        )

    print(f"  [annual_report] Running DCF valuation...")
    NFO           = reformulated["NFO"][-1]
    NCI           = reformulated["NCI"][-1]
    diluted_shares = float(
        fmp_data["income"][0].get("weightedAverageShsOutDil") or
        profile.get("sharesOutstanding") or 1
    )
    base_year = reformulated["years"][-1]
    wacc      = wacc_data["wacc"]

    dcf_results = compute_dcf(
        reformulated, wacc=wacc, g=0.02,
        NFO=NFO, NCI=NCI,
        diluted_shares=diluted_shares, base_year=base_year,
    )
    sensitivity = compute_sensitivity(
        reformulated, wacc_base=wacc, g_base=0.02,
        NFO=NFO, NCI=NCI,
        diluted_shares=diluted_shares, base_year=base_year,
    )

    market_price = float(profile.get("price") or 0)
    da3 = review_valuation(wacc_data, dcf_results, market_price, client)
    print(f"  [annual_report] DA #3 (valuation): {da3[:120]}...")

    print(f"  [annual_report] Building chart specs...")
    chart_specs, dataframes = build_chart_specs(
        ticker, company_name, iso3,
        reformulated, wacc_data, dcf_results, sensitivity, fmp_data,
    )

    da4 = review_kpi_specs(chart_specs, client)
    print(f"  [annual_report] DA #4 (KPI specs): {da4[:120]}...")

    da5 = review_final(chart_specs, dcf_results["price_per_share"], market_price, client)
    print(f"  [annual_report] DA #5 (final): {da5[:120]}...")

    if chart_specs:
        da_summary = (
            f"\n\nDA Reviews: "
            f"[#1 Reformulation] {da1[:80]} | "
            f"[#3 Valuation] {da3[:80]} | "
            f"[#5 Final] {da5[:80]}"
        )
        chart_specs[0]["note"] = chart_specs[0].get("note", "") + da_summary

    return {
        "dataframes":  dataframes,
        "kilde":       ["FMP", "Damodaran"],
        "chart_specs": chart_specs,
    }
