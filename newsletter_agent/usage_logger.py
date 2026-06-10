"""
Usage logger — records every newsletter pipeline run to Supabase
for usage intelligence and preference learning.

Failures here never crash the pipeline.
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supabase client (lazy init)
# ---------------------------------------------------------------------------
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        logger.debug("SUPABASE_URL/SUPABASE_KEY not set — usage logging disabled")
        return None

    try:
        from supabase import create_client, Client  # noqa: F401
        _client = create_client(url, key)
        return _client
    except Exception as exc:
        logger.warning("Failed to create Supabase client: %s", exc)
        return None


# ---------------------------------------------------------------------------
# log_run — call after every pipeline execution
# ---------------------------------------------------------------------------
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
        client = _get_client()
        if client is None:
            return

        row = {
            "prompt": prompt,
            "viz_hint": viz_hint,
            "period_days": int(period_days) if period_days is not None else None,
            "start_date": start_date or None,
            "end_date": end_date or None,
            "figure_count": len(figures) if figures else 0,
            "figures": figures or [],
            "duration_seconds": duration_seconds,
            "error": error,
            "session_id": session_id,
            "environment": os.getenv("RAILWAY_ENVIRONMENT", "development"),
        }

        client.table("newsletter_usage").insert(row).execute()
        logger.debug("Usage logged for prompt: %.60s…", prompt)

    except Exception as exc:
        logger.warning("Usage logging failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# get_usage_summary — recent 30-day overview
# ---------------------------------------------------------------------------
def get_usage_summary(days: int = 30) -> Dict[str, Any]:
    """
    Query recent usage and return an aggregate summary.
    Returns an empty dict on any failure.
    """
    try:
        client = _get_client()
        if client is None:
            return {}

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        resp = (
            client.table("newsletter_usage")
            .select("*")
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .execute()
        )
        rows = resp.data or []

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

        # Top prompts (simple frequency on first 80 chars)
        prompt_freq: Dict[str, int] = {}
        for r in rows:
            key = (r.get("prompt") or "")[:80]
            prompt_freq[key] = prompt_freq.get(key, 0) + 1
        top_prompts = sorted(prompt_freq.items(), key=lambda x: x[1], reverse=True)[:10]

        # Preferred viz types
        viz_freq: Dict[str, int] = {}
        for r in rows:
            hint = r.get("viz_hint")
            if hint:
                viz_freq[hint] = viz_freq.get(hint, 0) + 1
        preferred_viz = sorted(viz_freq.items(), key=lambda x: x[1], reverse=True)

        # Average period_days (where set)
        period_vals = [r["period_days"] for r in rows if r.get("period_days")]
        avg_period = round(sum(period_vals) / len(period_vals), 1) if period_vals else None

        # Common topics — extract salient words from prompts (simple heuristic)
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
