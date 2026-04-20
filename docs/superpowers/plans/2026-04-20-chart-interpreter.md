# Chart Interpreter & Newsletter Analyzer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a macroeconomics expert sub-agent that generates 3–4 professional Danish bullet points for every rendered chart, replicating the Maj Invest editorial reasoning chain (Claim → Quantity → Cause → Implication → Investor consequence), informed by deep analysis of 6 original newsletter editions.

**Architecture:** `analyzer.py` runs once offline on 6 HTML newsletters and writes `editorial_profile.json`. `interpreter.py` is a per-chart sub-agent (multimodal Claude Sonnet — sees the PNG + data summary + profile) called in `app.py` after the pipeline finishes. `app.py` streams `done` first (charts render immediately), then streams `interpretation` events one by one as each interpreter call completes, then sends `interpretation_done` to close SSE. JS appends a styled bullet panel below each chart card as events arrive.

**Tech Stack:** Python (anthropic SDK, stdlib HTMLParser, base64), Flask SSE via queue, Claude Sonnet (interpreter + analyzer).

---

## File Map

| File | Action |
|---|---|
| `newsletter_agent/analyzer.py` | Create — one-shot CLI tool, reads 6 HTML files, writes `editorial_profile.json` |
| `newsletter_agent/editorial_profile.json` | Created by running analyzer; commit to repo |
| `newsletter_agent/interpreter.py` | Create — per-chart sub-agent, multimodal LLM call |
| `newsletter_agent/config.py` | Modify — add `INTERPRETER_MODEL` constant |
| `newsletter_agent/pipeline.py` | Modify — add `_build_data_summary()`, attach to each package |
| `app.py` | Modify — stream `done` then `interpretation` events, send `interpretation_done` |
| `templates/index.html` | Modify — CSS + JS for bullet panel, handle new SSE event types |
| `tests/test_interpreter.py` | Create — unit tests for `interpret_chart` and `_build_data_summary` |

---

## Task 1: Add `INTERPRETER_MODEL` to config

**Files:**
- Modify: `newsletter_agent/config.py`

- [ ] **Step 1: Add the model constant**

Open `newsletter_agent/config.py`. After the existing model constants (around line 36–38), add:

```python
INTERPRETER_MODEL  = "claude-sonnet-4-6"   # chart interpretation sub-agent
ANALYZER_MODEL     = "claude-sonnet-4-6"   # newsletter style extraction (one-shot)
```

- [ ] **Step 2: Verify imports work**

```bash
python -c "from newsletter_agent.config import INTERPRETER_MODEL, ANALYZER_MODEL; print(INTERPRETER_MODEL)"
```

Expected output: `claude-sonnet-4-6`

- [ ] **Step 3: Commit**

```bash
git add newsletter_agent/config.py
git commit -m "feat: add INTERPRETER_MODEL and ANALYZER_MODEL to config"
```

---

## Task 2: `newsletter_agent/analyzer.py` — offline newsletter analysis

**Files:**
- Create: `newsletter_agent/analyzer.py`

This is a one-shot CLI tool. Run it once locally; it writes `editorial_profile.json` which gets committed to the repo. Newsletter HTML files never leave your machine.

- [ ] **Step 1: Write the analyzer**

Create `newsletter_agent/analyzer.py` with this exact content:

```python
"""
One-shot newsletter analyzer.
Run: python -m newsletter_agent.analyzer
Reads 6 Maj Invest HTML newsletters, extracts editorial patterns via LLM,
writes newsletter_agent/editorial_profile.json.
"""
import json
import os
import re
from html.parser import HTMLParser

import anthropic
from newsletter_agent.config import API_KEYS, ANALYZER_MODEL

NEWSLETTER_PATHS = [
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer 200326.html",
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer_ 13 marts.html",
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer_ 17042026.html",
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer_ En vej gennem Hormuzstrædet for Kina og.html",
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer_ Krig i Mellemøsten, Indien investerer i guld.html",
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer_ Status på krigen i Mellemøsten og Volkswagen vil tage del i Europas oprustning.html",
]

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "editorial_profile.json")

SYSTEM_PROMPT = """Du er ekspert i finansjournalistik og redaktionel analyse.
Din opgave er at analysere en samling af originale investornewslettere og udtrække de præcise redaktionelle mønstre,
der kendetegner forfatterens tænknings- og skriveproces når de kommenterer finansielle data og visualiseringer.

Returner KUN valid JSON — ingen markdown, ingen forklaringer udenfor JSON."""

EXTRACTION_PROMPT = """Analysér disse {n} udgaver af Maj Invest's "Ugeskrift for investorer" skrevet af Jeppe Christiansen.

OPGAVE: Find og beskriv præcist, hvordan forfatterne kommenterer data, grafer og tal i nyhedsbrevene.
Fokusér specifikt på:
1. Den rækkefølge de præsenterer information (hvad kommer først: konklusionen eller beskrivelsen?)
2. Hvordan de bruger præcise tal (aldrig vage udtryk som "markant stigning")
3. Hvordan de forklarer årsagssammenhænge (hvad driver bevægelsen?)
4. Hvordan de kobler data til makroøkonomiske implikationer
5. Hvordan de altid slutter med en eksplicit investorkonsekvens
6. Tone og sproglige mønstre (autoritativ, ingen hedging, 1. person flertal)
7. Hvad de ALDRIG gør (fx beskriver hvad grafen viser visuelt)

Udtræk 2 konkrete eksempler på bullet points fra nyhedsbrevene der illustrerer stilen perfekt.

Returner JSON med denne struktur (hold den under 400 ord total):
{{
  "reasoning_chain": [
    "Claim: ...",
    "Quantity: ...",
    "Cause: ...",
    "Implication: ...",
    "Investor: ..."
  ],
  "tone": [
    "...",
    "..."
  ],
  "examples": [
    {{
      "context": "kort beskrivelse af grafen",
      "bullets": ["bullet 1", "bullet 2", "bullet 3", "bullet 4"]
    }},
    {{
      "context": "kort beskrivelse af grafen",
      "bullets": ["bullet 1", "bullet 2", "bullet 3", "bullet 4"]
    }}
  ],
  "forbidden": [
    "...",
    "..."
  ]
}}

Nyhedsbrevstekster:
{texts}"""


class _TextExtractor(HTMLParser):
    """Strip HTML to clean readable text."""
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._skip = False

    def handle_data(self, data):
        if self._skip:
            return
        s = data.strip()
        # Skip invisible unicode filler characters used by HubSpot email clients
        if s and not all(c in "\u034f\u00ad\u200b\u200c\u200d\ufeff \n\r\t" for c in s):
            self._parts.append(s)

    def get_text(self) -> str:
        raw = "\n".join(self._parts)
        raw = re.sub(r"[\u034f\u00ad\u200b-\u200f\ufeff]+", "", raw)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def _load_newsletter(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            html = f.read()
        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        if len(text) < 200:
            print(f"  [warn] Very short text extracted from {os.path.basename(path)} — skipping")
            return None
        return text
    except FileNotFoundError:
        print(f"  [warn] File not found: {path} — skipping")
        return None
    except Exception as e:
        print(f"  [warn] Failed to read {os.path.basename(path)}: {e} — skipping")
        return None


def run_analysis() -> dict:
    print("Loading newsletters...")
    texts = []
    for path in NEWSLETTER_PATHS:
        text = _load_newsletter(path)
        if text:
            name = os.path.basename(path)
            texts.append(f"=== {name} ===\n{text[:6000]}")  # cap each at 6000 chars
            print(f"  Loaded: {name} ({len(text)} chars)")

    if len(texts) < 3:
        raise RuntimeError(
            f"Only {len(texts)} newsletters loaded successfully. Need at least 3. "
            "Check that the file paths in NEWSLETTER_PATHS are correct."
        )

    print(f"\nAnalyzing {len(texts)} newsletters with Claude...")
    combined = "\n\n".join(texts)
    prompt = EXTRACTION_PROMPT.format(n=len(texts), texts=combined)

    client = anthropic.Anthropic(api_key=API_KEYS["anthropic"])
    message = client.messages.create(
        model=ANALYZER_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw.strip())

    profile = json.loads(raw)
    print("Analysis complete.")
    return profile


def main():
    profile = run_analysis()
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    print(f"\nEditorial profile written to: {OUTPUT_PATH}")
    print("Commit it to the repo so Railway and other environments pick it up.")
    print("\nProfile preview:")
    print(f"  reasoning_chain: {len(profile.get('reasoning_chain', []))} steps")
    print(f"  tone rules:      {len(profile.get('tone', []))} rules")
    print(f"  examples:        {len(profile.get('examples', []))}")
    print(f"  forbidden:       {len(profile.get('forbidden', []))} items")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the analyzer**

```bash
python -m newsletter_agent.analyzer
```

Expected output:
```
Loading newsletters...
  Loaded: Ugeskrift for investorer 200326.html (XXXX chars)
  Loaded: Ugeskrift for investorer_ 13 marts.html (XXXX chars)
  ...
Analyzing 6 newsletters with Claude...
Analysis complete.
Editorial profile written to: .../newsletter_agent/editorial_profile.json
```

If fewer than 3 files load, the script aborts with a clear error. Fix the path(s) and re-run.

- [ ] **Step 3: Verify the output**

```bash
python -c "
import json
with open('newsletter_agent/editorial_profile.json') as f:
    p = json.load(f)
print('reasoning_chain:', len(p.get('reasoning_chain', [])), 'steps')
print('tone rules:', len(p.get('tone', [])))
print('examples:', len(p.get('examples', [])))
print('forbidden:', len(p.get('forbidden', [])))
assert len(p.get('reasoning_chain', [])) >= 3, 'Too few chain steps'
assert len(p.get('examples', [])) >= 1, 'No examples extracted'
print('OK')
"
```

Expected: prints counts and `OK`. If assertions fail, the LLM returned a malformed profile — re-run the analyzer.

- [ ] **Step 4: Commit**

```bash
git add newsletter_agent/analyzer.py newsletter_agent/editorial_profile.json
git commit -m "feat: add newsletter analyzer + editorial_profile.json"
```

---

## Task 3: `newsletter_agent/interpreter.py` — per-chart sub-agent

**Files:**
- Create: `newsletter_agent/interpreter.py`
- Create: `tests/test_interpreter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_interpreter.py`:

```python
import json
import os
import tempfile
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock


def test_interpret_chart_returns_list_of_strings(tmp_path):
    """interpret_chart returns a list of 1-4 strings on success."""
    from newsletter_agent.interpreter import interpret_chart

    # Create a tiny dummy PNG (1×1 white pixel)
    import struct, zlib
    def _minimal_png() -> bytes:
        def chunk(name, data):
            c = name + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        raw = b"\x89PNG\r\n\x1a\n"
        raw += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        raw += chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        raw += chunk(b"IEND", b"")
        return raw

    png_path = tmp_path / "test.png"
    png_path.write_bytes(_minimal_png())

    spec = {"title": "Test Chart", "type": "A", "note": "Test note", "y_label": "%", "chart_type": "A"}
    data_summary = {
        "chart_type": "A",
        "series": {"Serie A": {"latest": 5.0, "change_abs": 1.0, "change_pct": 25.0, "unit": "%"}},
        "period_days": 365,
        "direction": "up",
    }

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="• Bullet one\n• Bullet two\n• Bullet three")]

    with patch("newsletter_agent.interpreter.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = mock_message
        result = interpret_chart(str(png_path), spec, data_summary)

    assert isinstance(result, list)
    assert 1 <= len(result) <= 4
    assert all(isinstance(b, str) and len(b) > 5 for b in result)


def test_interpret_chart_returns_empty_list_on_error():
    """interpret_chart returns [] (not raises) when LLM call fails."""
    from newsletter_agent.interpreter import interpret_chart

    spec = {"title": "Bad Chart", "type": "A", "note": "", "y_label": "%", "chart_type": "A"}
    data_summary = {}

    with patch("newsletter_agent.interpreter.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.side_effect = Exception("API timeout")
        result = interpret_chart("/nonexistent/path.png", spec, data_summary)

    assert result == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_interpreter.py -v
```

Expected: `ModuleNotFoundError` — `interpreter.py` doesn't exist yet.

- [ ] **Step 3: Write `interpreter.py`**

Create `newsletter_agent/interpreter.py`:

```python
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
        lines.append(f"  ✗ {item}")
    examples = profile.get("examples", [])
    if examples:
        lines.append("\nSTYLE EXAMPLE (match this quality and voice):")
        ex = examples[0]
        lines.append(f"  Context: {ex.get('context', '')}")
        for b in ex.get("bullets", []):
            lines.append(f"  • {b}")
    return "\n".join(lines)


_PROFILE_TEXT = _profile_to_text(_PROFILE)

SYSTEM_PROMPT = f"""Du er seniorøkonom og chefanalytiker hos Maj Invest med dyb ekspertise i makroøkonomi,
globale finansmarkeder og investeringsstrategi. Du fortolker finansielle visualiseringer
med præcision og skarp analytisk indsigt til professionelle investorer.

{_PROFILE_TEXT}

VIGTIGT: Returner præcis 3-4 bullet points på dansk.
Ingen markdown. Ingen intro-sætning. Ingen forklaring.
Kun bullets — én per linje, starter med tegnet "•".
Brug de præcise tal fra datasummarien i dine bullets."""


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
                f"  {cat}: {vals.get('first_label')}={vals.get('first_year')}% → "
                f"{vals.get('last_label')}={vals.get('last_year')}% ({sign}{change}pp)"
            )

    elif chart_type == "G":
        for entity, vals in data_summary.get("entities", {}).items():
            lines.append(f"  {entity}: {vals.get('value')} {vals.get('unit', '')}")

    return "\n".join(lines)


def interpret_chart(image_path: str, spec: dict, data_summary: dict) -> list[str]:
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

        return bullets[:4]

    except Exception as e:
        print(f"[interpreter] Failed for '{spec.get('title', '?')}': {e}")
        return []
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_interpreter.py -v
```

Expected:
```
PASSED tests/test_interpreter.py::test_interpret_chart_returns_list_of_strings
PASSED tests/test_interpreter.py::test_interpret_chart_returns_empty_list_on_error
```

- [ ] **Step 5: Commit**

```bash
git add newsletter_agent/interpreter.py tests/test_interpreter.py
git commit -m "feat: add chart interpreter sub-agent"
```

---

## Task 4: `_build_data_summary()` in `pipeline.py`

**Files:**
- Modify: `newsletter_agent/pipeline.py`
- Modify: `tests/test_interpreter.py` (add data summary tests)

- [ ] **Step 1: Write failing tests for `_build_data_summary`**

Add to `tests/test_interpreter.py`:

```python
def test_build_data_summary_type_a():
    """Type A: extracts latest value and period change per series."""
    from newsletter_agent.pipeline import _build_data_summary
    import pandas as pd, numpy as np

    dates = pd.date_range("2024-01-01", periods=10, freq="ME")
    dfs = {
        "Brent": pd.DataFrame({"Brent": [70.0, 71, 72, 73, 74, 75, 76, 77, 78, 80.0]}, index=dates),
        "WTI":   pd.DataFrame({"WTI":   [65.0, 66, 67, 68, 69, 70, 71, 72, 73, 75.0]}, index=dates),
    }
    spec = {"type": "A", "y_label": "USD/barrel", "period_days": 365}
    result = _build_data_summary(dfs, spec)

    assert result["chart_type"] == "A"
    assert "Brent" in result["series"]
    assert result["series"]["Brent"]["latest"] == 80.0
    assert result["series"]["Brent"]["change_abs"] == pytest.approx(10.0, abs=0.1)
    assert result["direction"] in ("up", "down", "stable", "mixed")


def test_build_data_summary_type_d_returns_empty():
    """Type D (table): returns empty dict — no interpretation needed."""
    from newsletter_agent.pipeline import _build_data_summary
    import pandas as pd

    dfs = {"Serie": pd.DataFrame({"v": [1.0]}, index=pd.date_range("2024-01-01", periods=1))}
    result = _build_data_summary(dfs, {"type": "D"})
    assert result == {}


def test_build_data_summary_type_f():
    """Type F: extracts first/last year share per category."""
    from newsletter_agent.pipeline import _build_data_summary
    import pandas as pd

    idx = ["2021", "2022", "2023", "2024"]
    wide = pd.DataFrame({
        "Naturgas":    [19.0, 18.0, 17.0, 17.0],
        "Bioenergi":   [28.0, 28.0, 29.0, 30.0],
        "Kerneenergi": [10.0, 9.0, 9.0, 9.0],
    }, index=idx)
    dfs = {"_wide": wide}
    spec = {"type": "F", "period_days": 4 * 365}
    result = _build_data_summary(dfs, spec)

    assert result["chart_type"] == "F"
    assert "Naturgas" in result["categories"]
    assert result["categories"]["Naturgas"]["first_label"] == "2021"
    assert result["categories"]["Naturgas"]["last_label"] == "2024"
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_interpreter.py::test_build_data_summary_type_a tests/test_interpreter.py::test_build_data_summary_type_d_returns_empty tests/test_interpreter.py::test_build_data_summary_type_f -v
```

Expected: `ImportError` — `_build_data_summary` not defined yet.

- [ ] **Step 3: Add `_build_data_summary()` to `pipeline.py`**

In `newsletter_agent/pipeline.py`, add this function **before** `_render_figure()` (around line 253). Insert it after the `_build_before_after_bars` function:

```python
def _build_data_summary(dfs: dict, chart_spec: dict) -> dict:
    """
    Build a type-aware numerical summary for the interpreter sub-agent.
    Called with the same dfs dict passed to _render_figure().
    Returns {} for Type D (tables) — interpreter skips those.
    Never raises.
    """
    chart_type = chart_spec.get("type", "A")

    if chart_type == "D":
        return {}

    try:
        # ── Types A, B, E, C — time series / bar charts ───────────────────
        if chart_type in ("A", "B", "E", "C"):
            aligned = align_dates(dfs)
            series_data: dict = {}
            for label, df in aligned.items():
                s = df.iloc[:, 0].dropna()
                if s.empty:
                    continue
                latest = float(s.iloc[-1])
                first  = float(s.iloc[0])
                change_abs = latest - first
                change_pct = (change_abs / abs(first) * 100) if first != 0 else 0.0
                series_data[label] = {
                    "latest":     round(latest, 2),
                    "change_abs": round(change_abs, 2),
                    "change_pct": round(change_pct, 1),
                    "unit":       chart_spec.get("y_label", ""),
                }
            deltas = [v["change_abs"] for v in series_data.values()]
            if not deltas:
                direction = "unknown"
            elif all(d > 0 for d in deltas):
                direction = "up"
            elif all(d < 0 for d in deltas):
                direction = "down"
            elif all(abs(d) < 0.5 for d in deltas):
                direction = "stable"
            else:
                direction = "mixed"
            return {
                "chart_type":  chart_type,
                "series":      series_data,
                "period_days": chart_spec.get("period_days", 0),
                "direction":   direction,
            }

        # ── Types F, P — compositional (100% stacked / pie) ──────────────
        if chart_type in ("F", "P"):
            if len(dfs) == 1:
                wide = list(dfs.values())[0].copy()
                # Single-key dfs may already be wide (all categories as columns)
                if isinstance(wide.index, pd.DatetimeIndex):
                    wide.index = wide.index.year.astype(str)
            else:
                parts: dict = {}
                for lbl, df in dfs.items():
                    s = df.iloc[:, 0].dropna()
                    if isinstance(s.index, pd.DatetimeIndex):
                        s.index = s.index.year.astype(str)
                    parts[lbl] = s
                wide = pd.DataFrame(parts).dropna(how="all")

            period_days = chart_spec.get("period_days")
            if period_days:
                year_cap = max(1, round(period_days / 365))
                wide = wide.tail(year_cap)

            if wide.empty:
                return {}

            row_totals = wide.sum(axis=1).replace(0, float("nan"))
            pct = wide.div(row_totals, axis=0) * 100

            categories: dict = {}
            for col in pct.columns:
                first_val = float(pct.iloc[0][col]) if not pct.empty else 0.0
                last_val  = float(pct.iloc[-1][col]) if not pct.empty else 0.0
                categories[col] = {
                    "first_year":  round(first_val, 1),
                    "last_year":   round(last_val, 1),
                    "first_label": str(pct.index[0]),
                    "last_label":  str(pct.index[-1]),
                }
            return {"chart_type": chart_type, "categories": categories, "direction": "mixed"}

        # ── Type G — horizontal bar (entity ranking) ──────────────────────
        if chart_type == "G":
            if len(dfs) == 1:
                g_df = list(dfs.values())[0]
            else:
                latest = {
                    lbl: float(df.iloc[:, 0].dropna().iloc[-1])
                    for lbl, df in dfs.items()
                    if not df.empty and not df.iloc[:, 0].dropna().empty
                }
                g_df = pd.DataFrame.from_dict(
                    latest, orient="index", columns=[chart_spec.get("y_label", "%")]
                )
            col = g_df.columns[0]
            unit = chart_spec.get("y_label", "%")
            entities = {
                str(entity): {"value": round(float(g_df.loc[entity, col]), 1), "unit": unit}
                for entity in g_df.index
            }
            return {"chart_type": "G", "entities": entities, "direction": "snapshot"}

    except Exception as e:
        print(f"    [data_summary] Failed for type={chart_type}: {e}")

    return {}
```

- [ ] **Step 4: Attach `data_summary` to each package in `_render_figure()`**

In `_render_figure()`, find the final package construction block near line 517–529:

```python
    metadata = {
        "title":         chart_spec["title"],
        "chart_type":    chart_spec.get("type", "?"),
        ...
    }
    pkg = {"path": path, "metadata": metadata}
    if merged_for_events is not None:
        pkg["_merged"] = merged_for_events
    return pkg
```

Replace it with:

```python
    metadata = {
        "title":         chart_spec["title"],
        "chart_type":    chart_spec.get("type", "?"),
        "x_label":       chart_spec.get("x_label", ""),
        "y_label":       chart_spec.get("y_label", ""),
        "note":          chart_spec.get("note", ""),
        "kilde":         kilde_str,
        "region_labels": list(dfs.keys()),
    }
    pkg = {
        "path":         path,
        "metadata":     metadata,
        "spec":         chart_spec,
        "data_summary": _build_data_summary(dfs, chart_spec),
    }
    if merged_for_events is not None:
        pkg["_merged"] = merged_for_events
    return pkg
```

Note: adding `"spec": chart_spec` to the package so `app.py` can pass it to the interpreter without a separate lookup.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_interpreter.py -v
```

Expected: all tests pass including the 3 new data summary tests.

- [ ] **Step 6: Commit**

```bash
git add newsletter_agent/pipeline.py tests/test_interpreter.py
git commit -m "feat: add _build_data_summary() and attach to pipeline packages"
```

---

## Task 5: `app.py` — per-figure streaming with interpretation

**Files:**
- Modify: `app.py` (lines ~109–154, the `do_run()` function)

The key change: after `run()` returns all packages, send `done_msg` immediately (charts render in browser), then call interpreter per chart and stream `interpretation` events, then send `interpretation_done` to signal SSE can close.

- [ ] **Step 1: Replace `do_run()` in `app.py`**

Find the `do_run()` function (lines ~109–154). Replace the entire function body with:

```python
    def do_run():
        orig = sys.stdout
        sys.stdout = _StreamWriter(_run_queue, orig)
        try:
            from newsletter_agent.pipeline import run
            from newsletter_agent.interpreter import interpret_chart
            from datetime import datetime
            import json as _json

            run_dir = os.path.join(OUTPUT_DIR, datetime.now().strftime("%Y%m%d_%H%M%S"))
            os.makedirs(run_dir, exist_ok=True)
            packages = run(brief, output_dir=run_dir, preferred_types=preferred_types, period_days=period_days)

            # Load rerender context
            ctx_path = os.path.join(run_dir, "rerender_context.json")
            rerender_ctx = {}
            if os.path.exists(ctx_path):
                with open(ctx_path) as f:
                    for entry in _json.load(f):
                        rerender_ctx[entry["figure_id"]] = entry

            figures = [
                {
                    "path":          os.path.basename(p["path"]),
                    "title":         p["metadata"]["title"],
                    "note":          p["metadata"]["note"],
                    "kilde":         p["metadata"]["kilde"],
                    "reviewer_flag": p["metadata"].get("reviewer_flag", ""),
                    "chart_type":    p["metadata"].get("chart_type", "A"),
                    "figure_id":     i,
                    "rerender_ctx":  rerender_ctx.get(i, {}),
                }
                for i, p in enumerate(packages)
            ]

            # 1. Send done_msg immediately — browser renders all charts now
            done_msg = {"type": "done", "figures": figures}
            _last_result.update(done_msg)
            with open(_LAST_RESULT_PATH, "w") as _f:
                json.dump(done_msg, _f, ensure_ascii=False)
            _run_queue.put(done_msg)

            # 2. Run interpreters sequentially; stream bullets as each completes
            for i, p in enumerate(packages):
                chart_type = p["metadata"].get("chart_type", "A")
                if chart_type == "D":
                    continue  # skip snapshot tables
                data_summary = p.get("data_summary", {})
                if not data_summary:
                    continue
                spec = p.get("spec", p["metadata"])  # spec has type/y_label/note/title
                bullets = interpret_chart(p["path"], spec, data_summary)
                if bullets:
                    _run_queue.put({
                        "type":         "interpretation",
                        "figure_index": i,
                        "bullets":      bullets,
                    })

            # 3. Signal that interpretation is complete — JS closes SSE on this
            _run_queue.put({"type": "interpretation_done"})

        except Exception as exc:
            err_msg = {"type": "error", "text": str(exc)}
            _last_result.update(err_msg)
            _run_queue.put(err_msg)
        finally:
            sys.stdout = orig
            _run_lock.release()
```

- [ ] **Step 2: Verify the server starts without errors**

```bash
pkill -f "python app.py" 2>/dev/null; sleep 1
python app.py &
sleep 2
curl -s http://localhost:5050/ | head -5
```

Expected: HTML response (no Python traceback).

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: stream done then interpretation events per chart in app.py"
```

---

## Task 6: `templates/index.html` — bullet panel UI

**Files:**
- Modify: `templates/index.html`

Three changes: (1) CSS for the bullet panel, (2) JS handler for `interpretation` event, (3) JS handler for `interpretation_done` (replaces `done` as the SSE-close trigger).

- [ ] **Step 1: Add CSS for the interpretation panel**

In `templates/index.html`, find the CSS block (inside `<style>`). Add the following **before the closing `</style>` tag**:

```css
    /* ── Interpretation bullet panel ── */
    .interp-panel {
      margin-top: 10px;
      padding: 12px 16px;
      background: #f0fafa;
      border-left: 3px solid #11716c;
      border-radius: 0 6px 6px 0;
      font-size: 13px;
      line-height: 1.65;
      color: #1a2a2a;
    }
    .interp-header {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: #11716c;
      margin-bottom: 8px;
    }
    .interp-bullet {
      display: flex;
      gap: 8px;
      margin-bottom: 5px;
      padding-left: 2px;
    }
    .interp-bullet::before {
      content: "•";
      color: #11716c;
      font-weight: 700;
      flex-shrink: 0;
      margin-top: 1px;
    }
    .interp-bullet:last-child { margin-bottom: 0; }
    .interp-loading {
      color: #6b9e9a;
      font-size: 12px;
      font-style: italic;
      margin-top: 10px;
      padding: 8px 12px;
      border-left: 3px solid #cce8e6;
      background: #f8fcfc;
      border-radius: 0 4px 4px 0;
    }
```

- [ ] **Step 2: Update the SSE message handler**

Find the `eventSource.onmessage` handler in `templates/index.html` (around line 668). It currently looks like:

```javascript
  eventSource.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'connected') return;
    if (msg.type === 'heartbeat') return;
    if (msg.type === 'log') {
      appendLog(msg.text);
    } else if (msg.type === 'done') {
      finishAllSteps();
      renderFigures(msg.figures);
      document.getElementById('runBtn').disabled = false;
      document.getElementById('statusMsg').textContent = `Færdig — ${msg.figures.length} figur(er) genereret`;
      document.getElementById('statusMsg').className = '';
      eventSource.close();
    } else if (msg.type === 'error') {
      appendLog('ERROR: ' + msg.text);
      document.getElementById('runBtn').disabled = false;
      document.getElementById('statusMsg').textContent = 'Fejl — se log';
      document.getElementById('statusMsg').className = 'error';
      eventSource.close();
    }
  };
```

Replace it with:

```javascript
  eventSource.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'connected') return;
    if (msg.type === 'heartbeat') return;
    if (msg.type === 'log') {
      appendLog(msg.text);
    } else if (msg.type === 'done') {
      // Render all charts immediately; keep SSE open for interpretation events
      finishAllSteps();
      renderFigures(msg.figures);
      document.getElementById('runBtn').disabled = false;
      document.getElementById('statusMsg').textContent =
        `Figurer klar — analyserer... (${msg.figures.length} figur(er))`;
      document.getElementById('statusMsg').className = '';
      // Do NOT close eventSource here — interpretation events follow
    } else if (msg.type === 'interpretation') {
      const card = document.getElementById(`figcard-${msg.figure_index}`);
      if (!card) return;
      // Remove loading placeholder if present
      const placeholder = card.querySelector('.interp-loading');
      if (placeholder) placeholder.remove();
      // Build and append bullet panel
      const panel = document.createElement('div');
      panel.className = 'interp-panel';
      panel.innerHTML =
        '<div class="interp-header">Analyse</div>' +
        msg.bullets.map(b =>
          `<div class="interp-bullet">${b}</div>`
        ).join('');
      card.appendChild(panel);
    } else if (msg.type === 'interpretation_done') {
      // All interpretations complete — close SSE and update status
      document.getElementById('statusMsg').textContent =
        `Færdig — ${document.querySelectorAll('.fig-card').length} figur(er) med analyse`;
      eventSource.close();
      eventSource = null;
    } else if (msg.type === 'error') {
      appendLog('ERROR: ' + msg.text);
      document.getElementById('runBtn').disabled = false;
      document.getElementById('statusMsg').textContent = 'Fejl — se log';
      document.getElementById('statusMsg').className = 'error';
      eventSource.close();
      eventSource = null;
    }
  };
```

- [ ] **Step 3: Add loading placeholder in `renderFigures()`**

Find `renderFigures()` in `templates/index.html` (around line 708). Find where each card's `innerHTML` is built:

```javascript
    card.innerHTML = `
      <img src="/figures/${fig.path}?t=${Date.now()}" alt="${fig.title}"
           id="figimg-${i}" onclick="openLightbox(this.src)" />
      <div class="fig-footer">
        <a href="/figures/${fig.path}" download="${fig.path}" class="fig-download">
          &#8681; Download
        </a>
      </div>
      ${flagHtml ? `<div class="fig-meta">${flagHtml}</div>` : ''}`;
```

Replace with:

```javascript
    // Interpretation placeholder — shown while bullets are being generated.
    // Hidden for Type D tables (no interpretation) and restored runs (bullets already there).
    const showPlaceholder = fig.chart_type !== 'D';
    const placeholderHtml = showPlaceholder
      ? `<div class="interp-loading">Analyse genereres...</div>`
      : '';

    card.innerHTML = `
      <img src="/figures/${fig.path}?t=${Date.now()}" alt="${fig.title}"
           id="figimg-${i}" onclick="openLightbox(this.src)" />
      <div class="fig-footer">
        <a href="/figures/${fig.path}" download="${fig.path}" class="fig-download">
          &#8681; Download
        </a>
      </div>
      ${flagHtml ? `<div class="fig-meta">${flagHtml}</div>` : ''}
      ${placeholderHtml}`;
```

- [ ] **Step 4: Restart server and test end-to-end**

```bash
pkill -f "python app.py" 2>/dev/null; sleep 1
python app.py &
sleep 2
echo "Server running — open http://localhost:5050 and run a prompt"
```

Run a prompt (e.g. "EU energimix"). Verify:
1. Charts render as soon as pipeline finishes
2. "Analyse genereres..." placeholder appears below each chart
3. Bullet panel appears below each chart, one by one, as interpreters complete
4. Status bar updates to "Færdig — N figur(er) med analyse" at the end
5. Type D (snapshot table) cards have no placeholder and no bullet panel

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "feat: add interpretation bullet panel to UI"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] `analyzer.py` — Task 2
- [x] `editorial_profile.json` — Task 2, Step 2
- [x] `interpreter.py` — Task 3
- [x] Fallback profile when JSON missing — Task 3, Step 3 (try/except at import)
- [x] `_build_data_summary()` type-aware — Task 4 (A/B/E, F/P, G, D)
- [x] `data_summary` attached to package — Task 4, Step 4
- [x] `app.py` streams `done` first, then `interpretation`, then `interpretation_done` — Task 5
- [x] Type D tables skipped by interpreter — Task 5, Step 1
- [x] Error handling: interpreter returns [] on failure — Task 3, Step 3
- [x] UI: loading placeholder → replaced by bullet panel — Task 6
- [x] SSE closes on `interpretation_done` not `done` — Task 6, Step 2

**Type consistency:**
- `interpret_chart(image_path: str, spec: dict, data_summary: dict) -> list[str]` — consistent across Task 3 (definition) and Task 5 (call site)
- `_build_data_summary(dfs: dict, chart_spec: dict) -> dict` — consistent across Task 4 (definition) and Task 4 Step 4 (call site)
- `figure_index` key in `interpretation` event — consistent between Task 5 (emit) and Task 6 (consume)
- `figcard-${i}` ID — consistent between `renderFigures()` (Task 6 Step 3) and interpretation handler (Task 6 Step 2)
