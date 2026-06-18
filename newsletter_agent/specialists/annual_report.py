import anthropic
from newsletter_agent.config import API_KEYS
from newsletter_agent.specialists.annual_report_constants import (
    STATUTORY_TAX_RATE, normalize_country,
)
from newsletter_agent.specialists.annual_report_fmp import fetch_all, fetch_peer_comparison
from newsletter_agent.specialists.annual_report_reformulator import reformulate
from newsletter_agent.specialists.annual_report_checker import check
from newsletter_agent.specialists.annual_report_valuation import (
    compute_wacc, compute_dcf_scenarios, compute_sensitivity,
)
from newsletter_agent.specialists.annual_report_da import (
    review_reformulation, review_valuation, review_final,
)
from newsletter_agent.specialists.annual_report_kpi import build_chart_specs, build_peer_comparison_spec
from newsletter_agent.specialists.annual_report_auditor import audit_statements
from newsletter_agent.specialists.annual_report_market_researcher import fetch_market_researcher


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
    _data_source = fmp_data.get("_source", "FMP")

    profile      = fmp_data["profile"]
    hq_country   = profile.get("country", "_default")
    company_name = profile.get("companyName", ticker)
    currency     = profile.get("currency", "USD")
    iso3         = normalize_country(hq_country)
    t            = STATUTORY_TAX_RATE.get(iso3, STATUTORY_TAX_RATE["_default"])
    sector       = profile.get("sector", "")

    _FINANCIAL_SECTORS = {"Financial Services", "Financial"}
    _is_financial = sector in _FINANCIAL_SECTORS
    if _is_financial:
        print(f"  [annual_report] WARNING: {ticker} is in sector '{sector}' — "
              "Penman reformulation is not designed for banks/insurers. "
              "Results will carry a reliability warning.")

    print(f"  [annual_report] Reformulating Penman financials...")
    reformulated = reformulate(fmp_data, t=t)

    if reformulated["NOA"][-1] <= 0 and not _is_financial:
        raise ValueError(
            f"NOA for {ticker} is non-positive ({reformulated['NOA'][-1]:,.0f}). "
            "Check balance sheet classification — possible data quality issue."
        )
    if reformulated["NOA"][-1] <= 0 and _is_financial:
        print(f"  [annual_report] WARNING: NOA={reformulated['NOA'][-1]:,.0f} (negative) — "
              "expected for financial institutions, proceeding with warning")

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
        market_price=float(profile.get("price") or 0),
        currency_mismatch=bool(profile.get("currencyMismatch")),
    )
    if _is_financial:
        dcf_scenarios["_financial_warning"] = (
            f"{ticker} er en finansiel institution (sektor: {sector}). "
            "Penman-modellen adskiller drifts- og finansieringsaktiviteter, "
            "hvilket ikke er meningsfuldt for banker og forsikringsselskaber. "
            "Fair value-estimaterne er IKKE pålidelige for denne type selskab."
        )
    sensitivity = compute_sensitivity(
        reformulated, wacc_base=wacc, g_base=0.02,
        NFO=NFO, NCI=NCI,
        diluted_shares=diluted_shares, base_year=base_year,
    )

    market_price = float(profile.get("price") or 0)
    base_price   = dcf_scenarios["base"]["price"]
    if base_price is not None and base_price < 0:
        print(f"  [annual_report] WARNING: base fair value={base_price:.2f} < 0 "
              f"(EV={dcf_scenarios['base']['detail']['EV']:,.0f} < NFO+NCI={NFO+NCI:,.0f}).")

    base_fcf = dcf_scenarios["base"]["detail"].get("FCF_forecast", [])
    post_check = check({
        **wacc_data["checker_inputs"],
        "scenarios": dcf_scenarios,
        "diluted_shares": diluted_shares,
        "fcf_forecast": base_fcf,
    })
    if not post_check["passed"]:
        print(f"  [annual_report] BLOCK: Post-DCF validation failed for {ticker}:")
        for issue in post_check["issues"]:
            print(f"    • {issue}")

    da3 = review_valuation(wacc_data, dcf_scenarios, market_price, client)
    print(f"  [annual_report] DA #3 (valuation): {da3[:120]}...")

    print(f"  [annual_report] Building chart specs...")
    chart_specs, dataframes = build_chart_specs(
        ticker, company_name, iso3,
        reformulated, wacc_data, dcf_scenarios, sensitivity, fmp_data,
    )

    if _data_source == "yfinance" and chart_specs:
        chart_specs[0]["note"] = (
            chart_specs[0].get("note", "") +
            " NB: Baseret på historisk CAGR — ingen analytikerestimater tilgængelige."
        ).strip()

    bear_price = dcf_scenarios["bear"]["price"]
    bull_price = dcf_scenarios["bull"]["price"]
    da5 = review_final(chart_specs, (bear_price, base_price, bull_price), market_price, client)
    print(f"  [annual_report] DA #2 (final): {da5[:120]}...")

    # Statement Auditor — disabled for clean macro-team output
    # To restore: uncomment the block below
    # print(f"  [annual_report] Running statement auditor...")
    # try:
    #     audit_spec = audit_statements(fmp_data, reformulated)
    #     if audit_spec:
    #         chart_specs.insert(1, audit_spec)
    # except Exception as exc:
    #     print(f"  [annual_report] Auditor failed (non-fatal): {exc}")

    # Peer Comparison — append after main valuation, before news
    print(f"  [annual_report] Fetching peer comparison...")
    try:
        peer_data = fetch_peer_comparison(ticker, fmp_key)
        peer_spec = build_peer_comparison_spec(peer_data, company_name, ticker)
        if peer_spec:
            chart_specs.append(peer_spec)
    except Exception as exc:
        print(f"  [annual_report] Peer comparison failed (non-fatal): {exc}")

    # Market Researcher — append news card at end
    print(f"  [annual_report] Fetching market news...")
    try:
        news_spec = fetch_market_researcher(ticker, company_name, client)
        if news_spec:
            chart_specs.append(news_spec)
    except Exception as exc:
        print(f"  [annual_report] Market researcher failed (non-fatal): {exc}")

    source_label = "Yahoo Finance" if _data_source == "yfinance" else "FMP"
    return {
        "dataframes":  dataframes,
        "kilde":       [source_label, "Damodaran"],
        "chart_specs": chart_specs,
    }
