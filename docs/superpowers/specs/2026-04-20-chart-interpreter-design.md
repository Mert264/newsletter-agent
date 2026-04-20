# Chart Interpreter & Newsletter Analyzer — Implementation Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a macroeconomics expert sub-agent that interprets every rendered chart with 3–4 professional Danish bullet points, replicating the Maj Invest editorial reasoning chain (Claim → Quantity → Cause → Implication → Investor consequence), informed by deep analysis of 6 original newsletter editions.

**Architecture:** Two components. `analyzer.py` runs once offline on the 6 HTML newsletters and writes `editorial_profile.json`. `interpreter.py` is a per-chart sub-agent (same pattern as `reviewer.py`) that receives the rendered PNG + chart spec + data summary + profile, makes one multimodal Claude Sonnet call, and returns 3–4 bullet strings. The pipeline streams the `figure` SSE event first (chart immediately visible), then calls the interpreter, then streams an `interpretation` SSE event with the bullets. The UI renders a styled insight panel directly below each chart.

**Tech Stack:** Python (anthropic SDK, BeautifulSoup4 for HTML stripping), Flask SSE, Matplotlib PNG output, Claude Sonnet (interpreter), Claude Opus (analyzer — runs once).

---

## Editorial Pattern (extracted from Maj Invest newsletters)

The reasoning chain for every chart commentary:

1. **Claim first** — Lead with the conclusion, not a description of the chart. Never "the chart shows X rose." Always "X ligger stadig 20 dollar over niveauet før krigen."
2. **Exact quantity** — Always specific numbers. Never "prices rose significantly." Always "steget fra 7 pct. til 31 pct." or "ca. 15 euro højere."
3. **Causal mechanism** — Why did this happen? What structural or geopolitical force is driving it?
4. **Macro implication** — What does this mean for economies, markets, trade flows, or the geopolitical situation?
5. **Investor consequence** — Always explicit. Never left for the reader to derive. "Markederne ser… Investorerne har prissat… Vi vurderer at…"

**Tone rules:**
- Authoritative Danish. No hedging words (undgå: "may potentially", "could possibly", "it seems").
- First-person plural where appropriate: "Vi vurderer at…", "I Maj Invest ser vi…"
- Bullets are declarative statements, not questions or observations.
- Forbidden: describing what the chart shows visually ("søjlerne viser…", "kurven stiger…").

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `newsletter_agent/analyzer.py` | Create | Offline CLI — analyzes 6 newsletters, writes editorial profile |
| `newsletter_agent/editorial_profile.json` | Created by analyzer, commit to repo | Persistent editorial rules loaded at interpreter startup |
| `newsletter_agent/interpreter.py` | Create | Per-chart sub-agent — multimodal LLM call, returns bullet list |
| `newsletter_agent/pipeline.py` | Modify | Add `_build_data_summary()`, attach summary to package dict |
| `app.py` | Modify | Replace batch done_msg with per-figure stream + interpreter calls |
| `templates/index.html` | Modify | Handle `interpretation` SSE event, render styled bullet panel |

---

## Component 1: `newsletter_agent/analyzer.py`

**Purpose:** One-shot offline tool. Reads all 6 HTML newsletters, extracts clean text, sends to Claude Opus with a structured extraction prompt, writes `editorial_profile.json`.

**Run:** `python -m newsletter_agent.analyzer` from the project root.

### HTML newsletters to analyze
```python
NEWSLETTER_PATHS = [
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer 200326.html",
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer_ 13 marts.html",
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer_ 17042026.html",
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer_ En vej gennem Hormuzstrædet for Kina og.html",
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer_ Krig i Mellemøsten, Indien investerer i guld.html",
    "/Users/mertcandogusoy/Desktop/Privat/Maj Invest Jobsamtale/Ugeskrift for investorer_ Status på krigen i Mellemøsten og Volkswagen vil tage del i Europas oprustning.html",
]
```

### Analyzer prompt (sent to Claude Opus)
The prompt instructs Claude to:
- Read all editions and identify every instance where the authors comment on data, charts, or figures
- Extract the recurring 5-step reasoning chain with verbatim examples
- Identify tone rules, forbidden patterns (hedging, description-first), sentence construction
- Identify how they quantify (always exact numbers, with context like "20 dollar over niveauet før krigen")
- Identify how the investor angle is framed
- Output a compact JSON profile (≤350 words total across all fields) — rules, not prose

### Output: `editorial_profile.json`
```json
{
  "reasoning_chain": [
    "Claim: Lead with the conclusion. Never describe what the chart shows.",
    "Quantity: Always cite exact numbers with context (unit + reference point).",
    "Cause: Explain the structural or geopolitical mechanism driving the move.",
    "Implication: State what this means for economies or markets.",
    "Investor: Always close with explicit investor consequence. Never implicit."
  ],
  "tone": [
    "Authoritative Danish. No hedging (undgå: 'kan muligvis', 'det lader til').",
    "First-person plural where appropriate: 'Vi vurderer at...', 'I Maj Invest ser vi...'",
    "Declarative statements only. Never questions or passive observations.",
    "Never describe visual elements: forbudt: 'kurven stiger', 'søjlerne viser'."
  ],
  "examples": [
    {
      "context": "Oil price chart after Hormuz crisis",
      "bullets": [
        "Olieprisen ligger stadig ca. 20 dollar over niveauet før Iran-krigen — trods et midlertidigt fald efter våbenhvilen.",
        "Europa og Japan er mest eksponerede: begge importerer over 60 pct. af deres energi og rammes direkte af prisforhøjelsen.",
        "IEA-chef Fatih Birol kaldte krisen for den største trussel mod global energisikkerhed nogensinde — markederne undervurderer stadig konsekvenserne.",
        "Investorer bør fastholde eksponering mod energiproducenter og overveje obligationer som buffer mod fortsat usikkerhed."
      ]
    },
    {
      "context": "AI adoption by sector chart",
      "bullets": [
        "50 pct. af amerikanske virksomheder betaler i dag for AI-teknologi — en fordobling på under to år.",
        "Anthropics Claude er på ét år vokset fra 7 til 31 pct. markedsandel, mens OpenAI har stagneret på 35 pct. siden sidste sommer.",
        "Spredningen afspejler en strukturel produktivitetsbølge, ikke blot eksperimenter — AI er ved at blive en fast driftsomkostning.",
        "Selskaber med stærk AI-integration vil opnå varige konkurrencefordele; investorer bør prioritere eksponering mod platformsejere og enterprise-software."
      ]
    }
  ],
  "forbidden": [
    "Describing chart visuals: 'søjlerne viser', 'kurven stiger', 'figuren illustrerer'",
    "Hedging: 'kan muligvis', 'det lader til', 'måske', 'potentielt set'",
    "Vague quantities: 'markant stigning', 'betydeligt fald' without a number",
    "Leaving investor implication implicit — always state it explicitly"
  ]
}
```

**Error handling:** If any HTML file is missing, log a warning and skip it. If fewer than 3 files load successfully, abort with a clear error message.

---

## Component 2: `newsletter_agent/interpreter.py`

**Purpose:** Per-chart sub-agent. Receives rendered PNG + chart spec + data summary + editorial profile. Makes one multimodal Claude Sonnet call. Returns `list[str]` of 3–4 bullet strings.

### Signature
```python
def interpret_chart(
    image_path: str,
    spec: dict,
    data_summary: dict,
) -> list[str]:
    """
    Returns 3-4 Danish bullet strings interpreting the chart.
    Returns [] on any error — pipeline continues without bullets.
    """
```

### Profile loading
- Load `editorial_profile.json` once at module import (top-level constant).
- If file missing: log warning, use `FALLBACK_PROFILE` (hardcoded compact version of the 5-step chain + tone rules).
- Never crash on missing profile.

### System prompt
```
Du er seniorøkonom og chefanalytiker hos Maj Invest med dyb ekspertise i makroøkonomi,
globale finansmarkeder og investeringsstrategi. Du fortolker finansielle visualiseringer
med præcision og skarp analytisk indsigt.

Du følger altid denne rækkefølge:
1. Konklusion først — aldrig en beskrivelse af hvad figuren viser
2. Præcise tal — altid specifikke tal med kontekst (enhed + referencepunkt)
3. Mekanisme — hvad driver bevægelsen strukturelt eller geopolitisk
4. Makroimplikation — hvad betyder det for økonomi eller markeder
5. Investorkonsekvens — altid eksplicit, aldrig implicit

Returner præcis 3-4 bullet points på dansk. Ingen markdown. Ingen intro-sætning.
Kun bullets, én per linje, starter med "•".
```

### User message (multimodal)
- Image: the rendered PNG (base64 encoded or file path via `anthropic` SDK)
- Text block containing: chart title, type, note, y_label, and the data_summary JSON
- Editorial profile rules injected as additional text context

### Data summary format passed to interpreter
```python
# Time series (Type A/B/E):
{
  "chart_type": "A",
  "series": {
    "Brent Crude": {"latest": 87.4, "change_abs": +13.6, "change_pct": +18.2, "unit": "USD/barrel"},
    "WTI":         {"latest": 83.1, "change_abs": +12.0, "change_pct": +16.9, "unit": "USD/barrel"},
  },
  "period_days": 365,
  "direction": "up"
}

# Compositional (Type F/P):
{
  "chart_type": "F",
  "categories": {
    "Naturgas":    {"first_year": 19.0, "last_year": 17.0, "first_label": "2021", "last_label": "2024"},
    "Bioenergi":   {"first_year": 28.0, "last_year": 30.0, "first_label": "2021", "last_label": "2024"},
    "Kerneenergi": {"first_year": 10.0, "last_year":  9.0, "first_label": "2021", "last_label": "2024"},
  },
  "direction": "mixed"
}

# Ranking (Type G):
{
  "chart_type": "G",
  "entities": {
    "USA":     {"value": 45.2, "unit": "%"},
    "EU":      {"value": 28.1, "unit": "%"},
    "Kina":    {"value": 15.7, "unit": "%"},
  },
  "direction": "snapshot"
}
```

### Error handling
```python
try:
    bullets = _call_llm(image_path, spec, data_summary)
    return bullets
except Exception as e:
    print(f"[interpreter] failed for '{spec.get('title')}': {e}")
    return []
```

---

## Component 3: `_build_data_summary()` in `pipeline.py`

**Purpose:** Extract a type-aware numerical summary from the aligned DataFrames before rendering. Called after normalization, before the renderer.

```python
def _build_data_summary(dfs: dict, chart_spec: dict) -> dict:
    """
    Build a compact numerical summary for the interpreter sub-agent.
    Type-aware: A/B/E get latest+change; F/P get compositional shares; G gets ranked snapshot.
    """
```

**Type dispatch:**
- **A, B, E**: For each series DataFrame, take `.iloc[-1]` (latest) and compute change vs `.iloc[0]` (or `period_days` ago). Include unit from spec.
- **F, P**: For each category column, take first and last year values from the normalized % DataFrame.
- **G**: Take each entity's single value, sorted descending.
- **D**: Return `{}` — tables are skipped by interpreter, summary not needed.

---

## Component 4: `pipeline.py` — `_build_data_summary()`

`pipeline.py` gets ONE addition: a `_build_data_summary()` helper that runs just before each chart renders and attaches the summary to the returned package dict.

```python
# In _render_figure(), before calling renderer:
data_summary = _build_data_summary(chart_dfs, chart_spec)
# ... render as before ...
# Add to returned package:
package["data_summary"] = data_summary
```

The pipeline's output contract (`packages` list) doesn't change — each package dict now carries an extra `data_summary` key.

---

## Component 4b: `app.py` — per-figure streaming with interpretation

**Why here, not pipeline.py:** The current pipeline runs to completion and returns all packages at once. `app.py`'s background thread currently puts one big `done_msg` on the queue. The interpreter slots in between: after `run()` returns, iterate packages, stream each figure immediately, call interpreter, stream bullets, then send `done`.

```python
# In app.py background thread, replacing the current done_msg block:
packages = run(brief, output_dir=run_dir, preferred_types=preferred_types, period_days=period_days)

for i, p in enumerate(packages):
    # 1. Stream figure immediately
    figure_event = {
        "type": "figure",
        "figure_index": i,
        "path": f"/figures/{run_id}/{os.path.basename(p['path'])}",
        "title": p.get("title", ""),
        "figure_id": p.get("figure_id", i),
        # ... rerender_ctx fields ...
    }
    _run_queue.put(figure_event)

    # 2. Interpret (only non-table charts)
    if p.get("chart_type") != "D" and p.get("data_summary"):
        from newsletter_agent.interpreter import interpret_chart
        bullets = interpret_chart(p["path"], p["spec"], p["data_summary"])
        if bullets:
            _run_queue.put({
                "type": "interpretation",
                "figure_index": i,
                "bullets": bullets,
            })

_run_queue.put({"type": "done"})
```

**`figure_index`** matches each interpretation to its chart — the JS uses this to find the right figure card and append the bullet panel.

---

## Component 5: UI (`templates/index.html`)

### SSE handler addition
```javascript
if (data.type === 'interpretation') {
    const cards = document.querySelectorAll('.figure-card');
    const card = cards[data.figure_index];
    if (!card) return;

    const panel = document.createElement('div');
    panel.className = 'interpretation-panel';
    panel.innerHTML = '<div class="interp-header">Analyse</div>' +
        data.bullets.map(b => `<div class="interp-bullet">${b}</div>`).join('');
    card.appendChild(panel);
}
```

### CSS
```css
.interpretation-panel {
    margin-top: 8px;
    padding: 14px 16px;
    background: #f8fafa;
    border-left: 3px solid #0d9488;
    border-radius: 0 6px 6px 0;
    font-size: 13px;
    line-height: 1.6;
    color: #1f2937;
}
.interp-header {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #0d9488;
    margin-bottom: 8px;
}
.interp-bullet {
    margin-bottom: 6px;
    padding-left: 4px;
}
.interp-bullet:last-child { margin-bottom: 0; }
```

---

## Deployment notes

- `editorial_profile.json` is generated locally by `python -m newsletter_agent.analyzer` and **committed to the repo** — Railway picks it up on deploy. No need to re-run the analyzer in production.
- If the profile is absent (fresh clone without running analyzer), interpreter falls back silently to hardcoded profile and logs a warning. Pipeline never breaks.
- Newsletter HTML files stay on Mert's local machine — they are not needed after the analyzer has run and the profile is committed.

---

## What is NOT in scope

- Re-running the analyzer automatically on each pipeline run (too slow, unnecessary)
- Interpreting Type D tables (they are data reference, not narrative)
- Translating bullets to English (all output is Danish)
- User-editable interpretation in the UI
