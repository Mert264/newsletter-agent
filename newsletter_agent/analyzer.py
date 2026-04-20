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
from typing import Optional

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


def _load_newsletter(path: str) -> Optional[str]:
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
