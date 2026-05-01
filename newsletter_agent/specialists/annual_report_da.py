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
        f"Cash FCF (latest year): {reformulated['cash_fcf'][-1]:,.0f}\n"
        f"Penman FCF (latest year): {fcf_str}\n"
        f"OG avg: {reformulated['historical_avgs']['OG']:.3f}\n"
        f"ATO avg: {reformulated['historical_avgs']['ATO']:.3f}\n"
        f"Revenue CAGR: {reformulated['historical_avgs']['revenue_cagr']:.3f}\n"
        f"Flags raised: {flags}\n\n"
        "Review: Is NOA > 0? Is ATO avg positive and plausible? "
        "Are flagged years properly excluded? Is Cash FCF directionally consistent with Penman FCF?"
    )
    return _call(client, _SYSTEM, user)


def review_valuation(wacc_data: dict, dcf_scenarios: dict,
                     market_price: float, client: anthropic.Anthropic) -> str:
    base       = dcf_scenarios["base"]
    base_price = base["price"]
    bear_price = dcf_scenarios["bear"]["price"]
    bull_price = dcf_scenarios["bull"]["price"]
    ratio      = base_price / market_price if market_price > 0 else 0
    ev         = base["detail"]["EV"]
    tv_share   = f"{base['detail']['PV_TV']/ev:.0%}" if ev != 0 else "N/A (EV≤0)"
    user = (
        f"WACC: {wacc_data['wacc']:.4f}, rf: {wacc_data['rf']:.4f}, "
        f"rE: {wacc_data['rE']:.4f}, rD: {wacc_data['rD']:.4f}\n"
        f"β_raw={wacc_data['beta_raw']:.2f}, β_adj={wacc_data['beta_adj']:.4f}\n"
        f"Fair value range: {bear_price:.2f} – {bull_price:.2f} (base: {base_price:.2f})\n"
        f"Market price: {market_price:.2f} (base ratio: {ratio:.2f}x)\n"
        f"EV (base): {ev:,.0f}, TV share: {tv_share}\n"
        f"g (base)={base['g']:.3f}, Rev CAGR (base)={base['cagr']:.3f}\n\n"
        "Review: Is rf consistent? Is β_adj applied? Is terminal growth ≤ long-run GDP? "
        "Is EV > 0? Flag if base fair value is outside 0.2x–5x of market price. "
        "Is the range bear < base < bull?"
    )
    return _call(client, _SYSTEM, user)


def review_final(chart_specs: list, price_range: tuple,
                 market_price: float, client: anthropic.Anthropic) -> str:
    bear, base, bull = price_range
    ratio = base / market_price if market_price > 0 else 0
    user = (
        f"Fair value range: {bear:.0f} – {bull:.0f}, base: {base:.2f}\n"
        f"Market price: {market_price:.2f} (base/market ratio: {ratio:.2f}x)\n"
        f"Charts generated: {len(chart_specs)}\n\n"
        "Final gate: Is bear < base < bull ordering correct? "
        "Is the valuation conclusion directionally consistent with the sensitivity table midpoint? "
        "Are all values plausible?"
    )
    return _call(client, _SYSTEM, user)
