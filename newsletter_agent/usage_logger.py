"""
Usage logger — records every newsletter pipeline run to Supabase
via the PostgREST API (no SDK dependency).

Failures here never crash the pipeline.
"""
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests as _http

logger = logging.getLogger(__name__)

_URL = None
_KEY = None


def _get_config():
    global _URL, _KEY
    if _URL is not None:
        return _URL, _KEY
    _URL = os.getenv("SUPABASE_URL") or ""
    _KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY") or ""
    if not _URL or not _KEY:
        logger.debug("SUPABASE_URL/SUPABASE_SERVICE_KEY not set — usage logging disabled")
    return _URL, _KEY


def _headers():
    _, key = _get_config()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _rest_url(table: str):
    url, _ = _get_config()
    return f"{url}/rest/v1/{table}"


def log_run(
    *,
    prompt: str,
    viz_hint: Optional[str] = None,
    period_days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    figures: Optional[List[Dict[str, Any]]] = None,
    duration_seconds: Optional[float] = None,
    error: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Insert a row into newsletter_usage. Silently no-ops on failure."""
    try:
        url, key = _get_config()
        if not url or not key:
            return

        row = {
            "prompt": prompt,
            "viz_hint": viz_hint,
            "period_days": int(period_days) if period_days is not None else None,
            "start_date": start_date or None,
            "end_date": end_date or None,
            "figure_count": len(figures) if figures else 0,
            "figures": json.dumps(figures or []),
            "duration_seconds": duration_seconds,
            "error": error,
            "session_id": session_id,
            "environment": os.getenv("RAILWAY_ENVIRONMENT", "development"),
        }

        resp = _http.post(
            _rest_url("newsletter_usage"),
            headers=_headers(),
            json=row,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            logger.debug("Usage logged for prompt: %.60s…", prompt)
        else:
            logger.warning("Usage log insert failed (%s): %s", resp.status_code, resp.text[:200])

    except Exception as exc:
        logger.warning("Usage logging failed (non-fatal): %s", exc)


def get_usage_summary(days: int = 30) -> Dict[str, Any]:
    """Query recent usage and return an aggregate summary."""
    try:
        url, key = _get_config()
        if not url or not key:
            return {}

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        resp = _http.get(
            _rest_url("newsletter_usage"),
            headers=_headers(),
            params={
                "select": "*",
                "created_at": f"gte.{cutoff}",
                "order": "created_at.desc",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("Usage summary query failed (%s)", resp.status_code)
            return {}

        rows = resp.json()
        if not rows:
            return {
                "total_runs": 0,
                "error_rate": 0.0,
                "top_prompts": [],
                "preferred_viz_types": [],
                "avg_period_days": None,
                "common_topics": [],
            }

        total = len(rows)
        errors = sum(1 for r in rows if r.get("error"))

        prompt_freq: Dict[str, int] = {}
        for r in rows:
            k = (r.get("prompt") or "")[:80]
            prompt_freq[k] = prompt_freq.get(k, 0) + 1
        top_prompts = sorted(prompt_freq.items(), key=lambda x: x[1], reverse=True)[:10]

        viz_freq: Dict[str, int] = {}
        for r in rows:
            hint = r.get("viz_hint")
            if hint:
                viz_freq[hint] = viz_freq.get(hint, 0) + 1
        preferred_viz = sorted(viz_freq.items(), key=lambda x: x[1], reverse=True)

        period_vals = [r["period_days"] for r in rows if r.get("period_days")]
        avg_period = round(sum(period_vals) / len(period_vals), 1) if period_vals else None

        _stop = {
            "og", "i", "en", "et", "den", "det", "de", "er", "var", "til",
            "på", "med", "for", "af", "om", "at", "fra", "som", "der",
            "the", "and", "of", "in", "to", "a", "is", "for", "on", "with",
            "lav", "vis", "skriv", "giv", "mig", "hvad", "hvordan",
        }
        word_freq: Dict[str, int] = {}
        for r in rows:
            words = (r.get("prompt") or "").lower().split()
            for w in words:
                w = w.strip(".,;:!?()[]\"'")
                if len(w) > 2 and w not in _stop:
                    word_freq[w] = word_freq.get(w, 0) + 1
        common_topics = [w for w, _ in sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:15]]

        return {
            "total_runs": total,
            "error_rate": round(errors / total, 3) if total else 0.0,
            "top_prompts": [{"prompt": p, "count": c} for p, c in top_prompts],
            "preferred_viz_types": [{"type": t, "count": c} for t, c in preferred_viz],
            "avg_period_days": avg_period,
            "common_topics": common_topics,
        }

    except Exception as exc:
        logger.warning("Usage summary query failed: %s", exc)
        return {}
