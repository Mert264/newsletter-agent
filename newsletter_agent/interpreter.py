"""
Chart interpreter sub-agent (Task: per-chart expert bullet points).
Receives a rendered PNG + chart spec + data summary.
Returns 3-4 Danish bullet strings following the Maj Invest editorial reasoning chain.
Never raises — returns [] on any error so pipeline continues.
"""
import base64
import json
import os
import re
from typing import List

import anthropic
from newsletter_agent.config import API_KEYS, INTERPRETER_MODEL

# ── Load editorial profile once at import time ────────────────────────────────
_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "editorial_profile.json")

_FALLBACK_PROFILE = {
    "reasoning_chain": [
        "Claim: Lead with the conclusion. Never describe what the chart shows.",
        "Quantity: Always cite exact numbers with unit and reference point.",
        "Cause: Explain the structural or geopolitical mechanism driving the move.",
        "Implication: State what this means for economies or markets.",
        "Investor: Always close with explicit investor consequence. Never implicit.",
    ],
    "tone": [
        "Authoritative Danish. No hedging (undgå: 'kan muligvis', 'det lader til').",
        "First-person plural where appropriate: 'Vi vurderer at...', 'I Maj Invest ser vi...'",
        "Declarative statements only. Never questions or passive observations.",
        "Never describe visual elements: forbudt: 'kurven stiger', 'søjlerne viser'.",
    ],
    "forbidden": [
        "Describing chart visuals: 'søjlerne viser', 'kurven stiger', 'figuren illustrerer'",
        "Hedging: 'kan muligvis', 'det lader til', 'måske', 'potentielt set'",
        "Vague quantities: 'markant stigning', 'betydeligt fald' without a number",
        "Leaving investor implication implicit — always state it explicitly",
    ],
    "examples": [],
}

try:
    with open(_PROFILE_PATH, encoding="utf-8") as _f:
        _PROFILE = json.load(_f)
except FileNotFoundError:
    print("[interpreter] WARNING: editorial_profile.json not found — using fallback profile. "
          "Run: python -m newsletter_agent.analyzer")
    _PROFILE = _FALLBACK_PROFILE


def _profile_to_text(profile: dict) -> str:
    lines = ["REASONING CHAIN (follow this exact order):"]
    for step in profile.get("reasoning_chain", []):
        lines.append(f"  {step}")
    lines.append("\nTONE RULES:")
    for rule in profile.get("tone", []):
        lines.append(f"  {rule}")
    lines.append("\nFORBIDDEN (never do these):")
    for item in profile.get("forbidden", []):
        lines.append(f"  \u2717 {item}")
    examples = profile.get("examples", [])
    if examples:
        lines.append("\nSTYLE EXAMPLE (match this quality and voice):")
        ex = examples[0]
        lines.append(f"  Context: {ex.get('context', '')}")
        for b in ex.get("bullets", []):
            lines.append(f"  \u2022 {b}")
    return "\n".join(lines)


_PROFILE_TEXT = _profile_to_text(_PROFILE)

SYSTEM_PROMPT = f"""Du er seniorøkonom hos Maj Invest. Du skriver korte, klare pointer til vores investorbrev.
Læserne er velinformerede investorer — ikke økonomer. Skriv, som du ville tale til en intelligent voksen
der kender til aktier, renter og inflation, men ikke nødvendigvis fagtermer. Klart og direkte, aldrig tungt.

{_PROFILE_TEXT}

VIGTIGT: Returner præcis 2-3 bullet points på dansk.
Hver bullet er én kort sætning — maks. 20 ord. Start med det vigtigste og ét præcist tal.
Brug hverdagssprog: "olieprisen er steget" fremfor "råvarepriserne er apprecieret".
Fagtermer som rente, inflation og vækst er fine — undgå alt andet jargon.
Ingen markdown. Ingen intro. Kun bullets — én per linje, starter med "\u2022"."""


def _load_image_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _format_data_summary(data_summary: dict) -> str:
    """Convert data_summary dict to a compact readable text for the LLM."""
    if not data_summary:
        return "Ingen datasummary tilgængelig."

    chart_type = data_summary.get("chart_type", "?")
    lines = [f"Chart type: {chart_type}"]

    if chart_type in ("A", "B", "E", "C"):
        lines.append(f"Period: {data_summary.get('period_days', '?')} days | Direction: {data_summary.get('direction', '?')}")
        for label, vals in data_summary.get("series", {}).items():
            sign = "+" if vals.get("change_abs", 0) >= 0 else ""
            lines.append(
                f"  {label}: latest={vals.get('latest')} {vals.get('unit', '')} | "
                f"change={sign}{vals.get('change_abs')} ({sign}{vals.get('change_pct')}%)"
            )

    elif chart_type in ("F", "P"):
        for cat, vals in data_summary.get("categories", {}).items():
            change = round(vals.get("last_year", 0) - vals.get("first_year", 0), 1)
            sign = "+" if change >= 0 else ""
            lines.append(
                f"  {cat}: {vals.get('first_label')}={vals.get('first_year')}% \u2192 "
                f"{vals.get('last_label')}={vals.get('last_year')}% ({sign}{change}pp)"
            )

    elif chart_type == "G":
        for entity, vals in data_summary.get("entities", {}).items():
            lines.append(f"  {entity}: {vals.get('value')} {vals.get('unit', '')}")

    return "\n".join(lines)


def interpret_chart(image_path: str, spec: dict, data_summary: dict) -> List[str]:
    """
    Generate 3-4 expert Danish bullet points interpreting a chart.
    Returns [] on any error — pipeline always continues.

    Args:
        image_path: Absolute path to rendered PNG.
        spec: Chart metadata dict (title, type/chart_type, note, y_label).
        data_summary: Numerical summary from _build_data_summary().
    """
    try:
        img_b64 = _load_image_b64(image_path)
    except Exception as e:
        print(f"[interpreter] Could not read image '{image_path}': {e}")
        return []

    try:
        data_text = _format_data_summary(data_summary)
        chart_type = spec.get("chart_type") or spec.get("type", "?")

        user_text = (
            f"Titel: {spec.get('title', '')}\n"
            f"Graftype: {chart_type}\n"
            f"Y-akse: {spec.get('y_label', '')}\n"
            f"Note: {spec.get('note', '')}\n\n"
            f"Datasummary (brug disse præcise tal):\n{data_text}"
        )

        content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
            },
            {"type": "text", "text": user_text},
        ]

        client = anthropic.Anthropic(api_key=API_KEYS["anthropic"])
        message = client.messages.create(
            model=INTERPRETER_MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        raw = message.content[0].text.strip()

        # Parse bullet lines — accept •, -, –, —, * as bullet markers
        bullets = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            if re.match(r"^[•·\-–—*]", line):
                cleaned = re.sub(r"^[•·\-–—*]\s*", "", line).strip()
                if cleaned:
                    bullets.append(cleaned)

        # Fallback: if no bullet markers found, treat each non-empty line as a bullet
        if not bullets:
            bullets = [ln.strip() for ln in raw.split("\n") if ln.strip()]

        return bullets[:3]

    except Exception as e:
        print(f"[interpreter] Failed for '{spec.get('title', '?')}': {e}")
        return []
