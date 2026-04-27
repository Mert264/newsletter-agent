import anthropic
from newsletter_agent.config import REVIEWER_MODEL


def _call(client: anthropic.Anthropic, system: str, user: str) -> str:
    msg = client.messages.create(
        model=REVIEWER_MODEL,
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip()


_SYSTEM = (
    "You are a Devil's Advocate financial analyst. Be concise (max 4 bullet points). "
    "Flag only real issues — not hypothetical. Each bullet: issue + severity (WARN/BLOCK)."
)


def review_reformulation(reformulated: dict, client: anthropic.Anthropic) -> str:
    noa_latest = reformulated["NOA"][-1]
    fcf_latest = next((v for v in reversed(reformulated["FCF"]) if v is not None), None)
    flags      = reformulated.get("flags", [])
    fcf_str    = f"{fcf_latest:,.0f}" if fcf_latest is not None else "N/A"
    user = (
        f"NOA (latest year): {noa_latest:,.0f}\n"
        f"FCF (latest year): {fcf_str}\n"
        f"OG avg: {reformulated['historical_avgs']['OG']:.3f}\n"
        f"ATO avg: {reformulated['historical_avgs']['ATO']:.3f}\n"
        f"Revenue CAGR: {reformulated['historical_avgs']['revenue_cagr']:.3f}\n"
        f"Flags raised: {flags}\n\n"
        "Review: Is NOA > 0? Is FCF trend directionally consistent with OI? "
        "Are flagged years properly excluded from averages?"
    )
    return _call(client, _SYSTEM, user)


def review_consistency(check_result: dict, client: anthropic.Anthropic) -> str:
    user = (
        f"Consistency check result: passed={check_result['passed']}\n"
        f"Issues: {check_result['issues']}\n\n"
        "Review: Are the issues complete and correctly described? "
        "Is any critical check missing?"
    )
    return _call(client, _SYSTEM, user)


def review_valuation(wacc_data: dict, dcf_results: dict,
                     market_price: float, client: anthropic.Anthropic) -> str:
    price = dcf_results["price_per_share"]
    ratio = price / market_price if market_price > 0 else 0
    user = (
        f"WACC: {wacc_data['wacc']:.4f}, rf: {wacc_data['rf']:.4f}, "
        f"rE: {wacc_data['rE']:.4f}, rD: {wacc_data['rD']:.4f}\n"
        f"β_raw={wacc_data['beta_raw']:.2f}, β_adj={wacc_data['beta_adj']:.4f}\n"
        f"DCF price/share: {price:.2f}, Market price: {market_price:.2f} "
        f"(ratio: {ratio:.2f}x)\n"
        f"EV: {dcf_results['EV']:,.0f}, TV share: "
        f"{dcf_results['PV_TV']/dcf_results['EV']:.0%}\n"
        f"g={dcf_results['g']:.3f}\n\n"
        "Review: Is rf consistent? Is β_adj applied? Is terminal growth ≤ long-run GDP? "
        "Is EV > 0? Flag if price/share is outside 0.2x–5x of market price."
    )
    return _call(client, _SYSTEM, user)


def review_kpi_specs(chart_specs: list, client: anthropic.Anthropic) -> str:
    missing_notes  = [s.get("title", f"#{i}") for i, s in enumerate(chart_specs) if not s.get("note")]
    missing_kilde  = [s.get("title", f"#{i}") for i, s in enumerate(chart_specs) if not s.get("kilde")]
    user = (
        f"Total chart specs generated: {len(chart_specs)}\n"
        f"Missing 'note' field: {missing_notes or 'none'}\n"
        f"Missing 'kilde' field: {missing_kilde or 'none'}\n\n"
        "Review: Are all 18 charts present? Any missing note or kilde? "
        "Is the over/undervalued conclusion in chart #16 consistent with the sensitivity midpoint in chart #15?"
    )
    return _call(client, _SYSTEM, user)


def review_final(chart_specs: list, price_per_share: float,
                 market_price: float, client: anthropic.Anthropic) -> str:
    unlabeled = [
        s.get("title", f"#{i}") for i, s in enumerate(chart_specs)
        if s.get("table_data") and not any(
            any(tag in str(row) for tag in ["EST]", "CALC]", "ASSUMED]", "SOURCED]"])
            for row in s["table_data"].get("rows", [])
        )
    ]
    ratio = price_per_share / market_price if market_price > 0 else 0
    user = (
        f"Fundamental price: {price_per_share:.2f}, Market price: {market_price:.2f} "
        f"(ratio: {ratio:.2f}x)\n"
        f"Type-D tables without transparency labels: {unlabeled or 'none'}\n\n"
        "Final gate: Are all EST/ASSUMED values labeled in table cells? "
        "Is the over/undervalued conclusion (chart #16) consistent with the sensitivity midpoint (chart #15)?"
    )
    return _call(client, _SYSTEM, user)
