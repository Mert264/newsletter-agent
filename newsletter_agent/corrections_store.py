"""Dual-write corrections store: Supabase (source of truth) + repo file (local cache).

Handles layer classification, persistence, and filtered loading for three-layer
injection (orchestrator, specialist, reviewer).
"""
import json
import os
import requests
from datetime import datetime

_SUPABASE_URL = os.getenv("SUPABASE_URL", "")
_SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
_REPO_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "corrections.jsonl")

_LAYER_KEYWORDS = {
    "orchestrator": [
        "chart type", "layout", "ordering", "type d", "type a", "type b",
        "type k", "type g", "type f", "type e", "place first", "should be first",
        "wrong type", "use type",
    ],
    "specialist": [
        "series", "data value", "wrong number", "incorrect value", "fred series",
        "world bank", "fetch", "wrong source", "ticker", "indicator",
        "wrong metric", "wrong cpi", "wrong gdp", "pulling wrong", "should use",
        "growth rate", "index level",
    ],
    "rendering": [
        "axis", "label", "legend", "visible", "color", "colour", "line missing",
        "not visible", "missing from chart", "trendline", "x-axis", "y-axis",
        "mislabel", "render", "display", "both lines", "both series",
    ],
}


def classify_layer(comment: str) -> str:
    low = comment.lower()
    scores = {layer: 0 for layer in _LAYER_KEYWORDS}
    for layer, keywords in _LAYER_KEYWORDS.items():
        for kw in keywords:
            if kw in low:
                scores[layer] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "all"


def save_correction(entry: dict) -> bool:
    if "layer" not in entry:
        entry["layer"] = classify_layer(entry.get("comment", ""))
    if "ts" not in entry:
        entry["ts"] = datetime.utcnow().isoformat() + "Z"

    repo_ok = _write_repo(entry)
    supa_ok = _write_supabase(entry)
    return repo_ok or supa_ok


def load_corrections(specialists: list[str] = None, layer: str = None,
                     limit: int = 5, output_dir: str = "") -> list[dict]:
    entries = _read_supabase(specialists=specialists, layer=layer, limit=limit)
    if not entries:
        entries = _read_local(specialists=specialists, layer=layer,
                              limit=limit, output_dir=output_dir)
    return entries


def format_corrections_prompt(entries: list[dict], prefix: str = "") -> str:
    if not entries:
        return ""
    label = prefix or "PAST CORRECTIONS (from feedback — avoid repeating these mistakes)"
    lines = [f"{label}:"]
    for e in entries:
        ct = e.get("chart_type", "?")
        cmt = e.get("comment", "")
        title = e.get("title", e.get("figure", ""))
        lines.append(f"  - Type {ct} '{title}': {cmt}")
    return "\n".join(lines)


def _write_repo(entry: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(_REPO_FILE), exist_ok=True)
        with open(_REPO_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _write_supabase(entry: dict) -> bool:
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        return False
    try:
        resp = requests.post(
            f"{_SUPABASE_URL}/rest/v1/newsletter_corrections",
            json={
                "figure": entry.get("figure", entry.get("title", "")),
                "specialist": entry.get("specialist", ""),
                "chart_type": entry.get("chart_type", ""),
                "comment": entry.get("comment", ""),
                "layer": entry.get("layer", "all"),
                "source": entry.get("source", "user"),
                "title": entry.get("title", ""),
                "brief": entry.get("brief", ""),
            },
            headers={
                "apikey": _SUPABASE_KEY,
                "Authorization": f"Bearer {_SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            timeout=5,
        )
        return resp.status_code in (200, 201)
    except Exception:
        return False


def _read_supabase(specialists: list[str] = None, layer: str = None,
                   limit: int = 5) -> list[dict]:
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        return []
    try:
        params = {"order": "ts.desc", "limit": str(limit * 3)}
        if layer and layer != "all":
            params["or"] = f"(layer.eq.{layer},layer.eq.all)"
        resp = requests.get(
            f"{_SUPABASE_URL}/rest/v1/newsletter_corrections",
            params=params,
            headers={
                "apikey": _SUPABASE_KEY,
                "Authorization": f"Bearer {_SUPABASE_KEY}",
            },
            timeout=5,
        )
        if resp.status_code != 200:
            return []
        entries = resp.json()
        if specialists:
            entries = [e for e in entries
                       if e.get("specialist", "") in specialists or not e.get("specialist")]
        if layer and layer != "all":
            entries = [e for e in entries if e.get("layer") in (layer, "all")]
        seen = set()
        deduped = []
        for e in entries:
            key = (e.get("chart_type", ""), (e.get("comment", "") or "").lower()[:80])
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        return deduped[:limit]
    except Exception:
        return []


def _read_local(specialists: list[str] = None, layer: str = None,
                limit: int = 5, output_dir: str = "") -> list[dict]:
    sources = [_REPO_FILE]
    if output_dir:
        sources.append(os.path.join(output_dir, "corrections.jsonl"))
    entries = []
    for src in sources:
        if not os.path.isfile(src):
            continue
        with open(src) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    if not entries:
        return []
    if specialists:
        relevant = [e for e in entries if e.get("specialist", "") in specialists]
        if not relevant:
            relevant = entries
        entries = relevant
    if layer and layer != "all":
        filtered = [e for e in entries if e.get("layer", "all") in (layer, "all")]
        if filtered:
            entries = filtered
    seen = set()
    deduped = []
    for e in entries:
        key = (e.get("chart_type", ""), e.get("comment", "").lower()[:80])
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    return deduped[-limit:]
