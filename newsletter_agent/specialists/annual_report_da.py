import anthropic
from newsletter_agent.config import REVIEWER_MODEL
from newsletter_agent.llm_retry import llm_call_with_retry
from newsletter_agent.corrections_store import load_corrections, format_corrections_prompt


def _call(client: anthropic.Anthropic, system: str, user: str) -> str:
    msg = llm_call_with_retry(
        client.messages.create,
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
    ratio      = base_price / market_price if market_price > 0 and base_price is not None else 0
    ev         = base["detail"]["EV"]
    tv_share   = f"{base['detail']['PV_TV']/ev:.0%}" if ev != 0 else "N/A (EV≤0)"
    D, E, NFO  = wacc_data["D"], wacc_data["E"], wacc_data.get("D", 0) + wacc_data.get("E", 0)
    net_cash   = wacc_data["D"] == 0 and base["detail"]["NFO"] < 0
    cap_note   = (
        "Net cash company (NFO < 0): D=0 by model design, so WACC = rE is EXPECTED and correct. "
        "Do NOT flag WACC = rE as an error for net-cash companies."
        if net_cash else
        f"D={wacc_data['D']:,.0f}, E={wacc_data['E']:,.0f}, V={wacc_data['V']:,.0f}"
    )
    user = (
        f"WACC: {wacc_data['wacc']:.4f}, rf: {wacc_data['rf']:.4f}, "
        f"rE: {wacc_data['rE']:.4f}, rD: {wacc_data['rD']:.4f}\n"
        f"β_raw={wacc_data['beta_raw']:.2f}, β_adj={wacc_data['beta_adj']:.4f}\n"
        f"Capital structure: {cap_note}\n"
        f"Fair value range: {bear_price or 'N/A'} – {bull_price or 'N/A'} (base: {base_price or 'N/A'})\n"
        f"Market price: {market_price:.2f} (base ratio: {ratio:.2f}x)\n"
        f"EV (base): {ev:,.0f}, TV share: {tv_share}\n"
        f"g (base)={base['g']:.3f}, Rev CAGR (base)={base['cagr']:.3f}\n\n"
        "Review: Is rf consistent? Is β_adj applied? Is terminal growth ≤ long-run GDP? "
        "Is EV > 0? Flag if base fair value is outside 0.2x–5x of market price. "
        "Is the range bear < base < bull? "
        "IMPORTANT: Do NOT flag WACC = rE as suspicious if the capital structure note says net cash."
    )
    return _call(client, _SYSTEM, user)


def review_final(chart_specs: list, price_range: tuple,
                 market_price: float, client: anthropic.Anthropic) -> str:
    bear, base, bull = price_range
    ratio = base / market_price if market_price > 0 and base is not None else 0
    all_valid = all(v is not None for v in (bear, base, bull))
    ordering_ok = bear < base < bull if all_valid else False
    def _fmt(v):
        return f"{v:.2f}" if v is not None else "N/A"
    user = (
        f"Bear fair value:  {_fmt(bear)}\n"
        f"Base fair value:  {_fmt(base)}\n"
        f"Bull fair value:  {_fmt(bull)}\n"
        f"Market price:     {market_price:.2f} (base/market ratio: {ratio:.2f}x)\n"
        f"Bear < Base < Bull ordering: {'CORRECT' if ordering_ok else 'N/A — some scenarios undefined' if not all_valid else 'VIOLATED'}\n"
        f"Charts generated: {len(chart_specs)}\n\n"
        "Final gate: confirm ordering is correct, base/market ratio is plausible (0.1x–10x), "
        "and all values are positive. Flag only real issues with WARN or BLOCK."
    )
    return _call(client, _SYSTEM, user)
