"""Devil's advocate reviewer for newsletter figures and tables (Task 9).

Performs meticulous quality checks on chart/table metadata via LLM.
Returns {"status": "APPROVED"|"REVISION NEEDED", "reason": str}.
"""
import json
import re
import anthropic
from newsletter_agent.config import API_KEYS, REVIEWER_MODEL

REVIEWER_PROMPT = """Du er kvalitetskontrollør af finansielle grafer til et makroøkonomisk investornewsletter.
Du modtager metadata om en graf eller tabel. Markér KUN reelle, substantielle fejl, der ville
vildlede eller forvirre en investor. Markér IKKE mindre stilistiske præferencer.

SPROG: Dansk er det primære sprog. Titler, noter og etiketter forventes på dansk. Markér IKKE fraværet af engelske labels — dansk er korrekt.
Returner altid JSON på engelsk (status/reason-felterne) uanset inputsproget.

APPROVE if all of these pass:
1. Title is present and describes what the chart shows.
2. Y-axis label has units (e.g. "%", "USD/barrel", "Indexed (base=100)"). EXCEPTION: tables (type D) and pie charts (type P) have no axes — never check or flag axis labels on these types.
3. For time-series charts: x-axis can simply say "Date" or be blank — do NOT flag this.
4. Note is present and explains what the data shows.
5. Kilde (source) is present.
6. Units are market-standard (oil=USD/barrel, rates=%, indexed charts state base=100).

FLAG only if:
- Title is missing entirely.
- Y-axis has WRONG units (e.g. showing raw index level when it should be YoY %). Never apply this rule to type P or type D.
- Note is missing entirely.
- Kilde is missing entirely.
- The chart type is clearly wrong for the data (e.g. bar chart for time series).

Do NOT flag:
- ANYTHING about axis labels on type P (pie chart) — pie charts have no axes. Never flag x-axis, y-axis, or units on type P. Auto-approve axis checks for type P.
- Missing x-axis label when the axis clearly shows dates.
- "Date" as ambiguous — it is standard.
- Country/region labels not appearing on the chart body (legend is sufficient).
- Source granularity (e.g. "Yahoo Finance" is fine, no need for ticker symbols).
- Minor wording preferences.
- For type G (horizontal bar): the Y-axis shows category/country names — this is correct and needs no unit label. The X-axis carries the metric with units. Do NOT flag "missing y-axis units" or "swapped axes" on type G charts.
- Y-axis label "Index" or "Index level" for raw market instruments like DXY (US Dollar Index),
  VIX (volatility index), or similar instruments that trade as indices by nature. These are NOT
  rebased series and do NOT need a "base=100" specification. Only require "base=100" when the
  chart title or note explicitly says the series has been rebased/indexed to a start value.
- Event dates or event names mentioned in the Note — NEVER challenge whether an event is real,
  whether a date seems recent or unusual, or whether a date is "in the future". The pipeline
  operates with live market data and may include events that occurred after your training cutoff.
  Event dates in the Note are always provided by the user and are correct by definition.
  Do NOT flag phrases like "Iran war outbreak", "Iran conflict", or any geopolitical event name.

Return ONLY valid JSON:
{"status": "APPROVED", "reason": ""}
OR
{"status": "REVISION NEEDED", "reason": "One sentence describing the real issue"}

No markdown. No explanation outside the JSON."""


def call_llm_text(prompt: str) -> str:
    """Make LLM call returning raw text (JSON string).

    Args:
        prompt: User prompt containing chart metadata.

    Returns:
        Raw JSON string from LLM.
    """
    client = anthropic.Anthropic(api_key=API_KEYS["anthropic"])
    message = client.messages.create(
        model=REVIEWER_MODEL,
        max_tokens=256,
        system=REVIEWER_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def review_figure(figure_path: str, metadata: dict) -> dict:
    """Review a figure for quality and correctness.

    Makes one LLM call per figure. Returns approval status with reason.

    Args:
        figure_path: Path to figure file (PNG, etc).
        metadata: Dict with keys: title, x_label, y_label, note, kilde, region_labels.

    Returns:
        {"status": "APPROVED"|"REVISION NEEDED", "reason": str}

    Raises:
        json.JSONDecodeError: If LLM returns invalid JSON (caught and converted to REVISION NEEDED).
    """
    prompt = f"""Chart metadata:
Chart type: {metadata.get('chart_type', '?')}
  A = time series line chart (x=date, y=metric)
  B = vertical bar chart (x=entity/year, y=metric)
  D = snapshot table (no axis labels needed)
  E = before/after grouped bar chart
  F = 100% stacked bar chart (x=year, y=% share — composition over time)
  G = horizontal bar chart (y=category names like countries/sectors, x=metric value) — this is VALID for cross-entity snapshots. Do NOT flag type G as invalid.
  P = pie chart (single-year composition snapshot)
Title: {metadata.get('title', '[MISSING]')}
X-axis label: {metadata.get('x_label', '[MISSING]')}
Y-axis label: {metadata.get('y_label', '[MISSING]')}
Note: {metadata.get('note', '[MISSING]')}
Kilde: {metadata.get('kilde', '[MISSING]')}
Region labels on chart: {metadata.get('region_labels', [])}
"""
    raw = call_llm_text(prompt)
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "status": "REVISION NEEDED",
            "reason": f"Reviewer returned invalid JSON: {raw}",
        }
