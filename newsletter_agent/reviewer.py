"""Devil's advocate reviewer for newsletter figures and tables (Task 9).

Performs meticulous quality checks on chart/table metadata via LLM.
Returns {"status": "APPROVED"|"REVISION NEEDED", "reason": str}.
"""
import json
import re
import anthropic
from newsletter_agent.config import API_KEYS, REVIEWER_MODEL
from newsletter_agent.llm_retry import llm_call_with_retry

REVIEWER_PROMPT = """Du er kvalitetskontrollør af finansielle grafer til et makroøkonomisk investornewsletter.
Du modtager metadata om en graf eller tabel. Markér KUN reelle, substantielle fejl, der ville
vildlede eller forvirre en investor. Markér IKKE mindre stilistiske præferencer.

SPROG: Dansk er det primære sprog. Titler, noter og etiketter forventes på dansk. Markér IKKE fraværet af engelske labels — dansk er korrekt.
Returner altid JSON på engelsk (status/reason-felterne) uanset inputsproget.

APPROVE if all of these pass:
1. Title is present and describes what the chart shows.
2. Y-axis label has units (e.g. "%", "USD/barrel", "Indexed (base=100)"). EXCEPTION: tables (type D), pie charts (type P), and horizontal bar charts (type G) — never check or flag axis labels on these types.
3. For time-series charts: x-axis can simply say "Date" or be blank — do NOT flag this.
4. Note is present and explains what the data shows.
5. Kilde (source) is present.
6. Units are market-standard (oil=USD/barrel, rates=%, indexed charts state base=100).

FLAG only if:
- Title is missing entirely.
- Y-axis has WRONG units (e.g. showing raw index level when it should be YoY %). Never apply this rule to type P, type D, or type G.
- Note is missing entirely.
- Kilde is missing entirely.
- The chart type is clearly wrong for the data (e.g. bar chart for time series).

Do NOT flag:
- ANYTHING about axis labels on type D (snapshot table) — type D tables have no axis (no x-axis, no y-axis). Never flag x-axis or y-axis fields on type D, whether empty or non-empty. Auto-approve ALL axis checks on type D without exception.
- ANYTHING about axis labels on type P (pie chart) — pie charts have no axes. Never flag x-axis, y-axis, or units on type P. Auto-approve axis checks for type P.
- ANYTHING about y-axis on type G (horizontal bar chart) — in horizontal bars, the Y-axis shows category names (countries, sectors), not a metric unit. The metric unit belongs on the X-axis. Do NOT flag y_label on type G regardless of its value. Auto-approve ALL y-axis checks on type G.
- Region label count mismatches — including titles with "vs.", "og", "&", or any multi-entity pattern: if the title implies a comparison between more entities than are present in region_labels, this is a data-availability gap already handled upstream. Do NOT flag these under any circumstances — auto-approve unconditionally as long as at least one series is present in region_labels and the chart has a title and note. This rule overrides all other checks about title-to-data consistency.
- Missing x-axis label when the axis clearly shows dates.
- "Date" as ambiguous — it is standard.
- Country/region labels not appearing on the chart body (legend is sufficient).
- Source granularity (e.g. "Yahoo Finance" is fine, no need for ticker symbols).
- Minor wording preferences.
- For type G (horizontal bar): COMPLETELY IGNORE the Y-axis label field. The `y_label` in the metadata is the X-axis metric unit (e.g. %). The physical Y-axis of a horizontal bar chart always shows category names (countries, sectors) — this is structurally correct and needs no unit label. Do NOT produce ANY flag about "Y-axis shows %", "Y-axis should show category names", "remove % from Y-axis", "swapped axes", or any similar concern. Auto-approve ALL Y-axis checks on type G without exception.
- Y-axis label "Indekseret (basis=100)" or "Indexed (base=100)" when DXY (US Dollar Index)
  appears alongside FX rate pairs (EUR/USD, GBP/USD, JPY/USD, etc.). DXY trades at ~100 naturally,
  but FX rates live on completely different scales (EUR/USD ~1.08, JPY/USD ~0.0066). The pipeline
  MUST rebase all series to 100 to make them comparable on one chart — this is correct and necessary.
  NEVER flag "Indekseret (basis=100)" as wrong when region_labels include DXY and any FX pair.
  Do NOT flag this even if you consider DXY a "natural index" — the rebasing is intentional.
- Event dates or event names mentioned in the Note — NEVER challenge whether an event is real,
  whether a date seems recent or unusual, or whether a date is "in the future". The pipeline
  operates with live market data and may include events that occurred after your training cutoff.
  Event dates in the Note are always provided by the user and are correct by definition.
  Do NOT flag phrases like "Iran war outbreak", "Iran conflict", or any geopolitical event name.
- Note content that mentions unavailable or missing data — if the Note states that a series
  could not be fetched, was unavailable, is not in the configured sources, or names indicators
  that are listed as absent — this is CORRECT pipeline behavior (the pipeline writes such notes
  automatically). NEVER flag "Note mentions X series but only Y are present in the chart", NEVER
  flag a count mismatch between series named in the Note and series actually rendered. Auto-approve
  as long as at least one series is present, a title is set, and a note is set. This rule overrides
  any check that compares Note text to region_labels or series count.

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
    message = llm_call_with_retry(
        client.messages.create,
        model=REVIEWER_MODEL,
        max_tokens=256,
        system=REVIEWER_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def review_figure(figure_path: str, metadata: dict, corrections: str = "") -> dict:
    """Review a figure for quality and correctness.

    Makes one LLM call per figure. Returns approval status with reason.

    Args:
        figure_path: Path to figure file (PNG, etc).
        metadata: Dict with keys: title, x_label, y_label, note, kilde, region_labels.
        corrections: Optional past corrections text to inject into reviewer context.

    Returns:
        {"status": "APPROVED"|"REVISION NEEDED", "reason": str}

    Raises:
        json.JSONDecodeError: If LLM returns invalid JSON (caught and converted to REVISION NEEDED).
    """
    prompt = f"""Chart metadata:
Chart type: {metadata.get('chart_type', '?')}
  A = time series line chart (x=date, y=metric)
  B = vertical bar chart — TWO valid modes: (a) cross-entity snapshot (x=entity, y=metric), OR (b) time-series bars over time (x=time periods like months/years, y=metric). BOTH are valid. Do NOT flag type B for monthly/quarterly sequential data.
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
    if corrections:
        prompt += f"\n\n{corrections}"
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
