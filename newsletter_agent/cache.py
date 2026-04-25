from __future__ import annotations
"""
File-based TTL cache for pipeline API responses.
Stores JSON-serialisable values; persists across server restarts.
Cache directory: .pipeline_cache/ in the project root.
"""
import json
import time
import hashlib
from pathlib import Path

_CACHE_DIR = Path(__file__).parent.parent / ".pipeline_cache"
_CACHE_DIR.mkdir(exist_ok=True)


def _path(prefix: str, kwargs: dict) -> Path:
    raw = prefix + json.dumps(kwargs, sort_keys=True, ensure_ascii=False)
    key = hashlib.md5(raw.encode()).hexdigest()
    return _CACHE_DIR / f"{prefix}_{key}.json"


def get(prefix: str, ttl_seconds: int, **kwargs):
    """Return cached value or None if missing / expired."""
    p = _path(prefix, kwargs)
    if not p.exists():
        return None
    try:
        stored = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - stored["cached_at"] > ttl_seconds:
            p.unlink(missing_ok=True)
            return None
        return stored["value"]
    except Exception:
        p.unlink(missing_ok=True)
        return None


def put(prefix: str, value, **kwargs) -> None:
    """Store a value with the current timestamp."""
    p = _path(prefix, kwargs)
    try:
        p.write_text(
            json.dumps({"cached_at": time.time(), "value": value}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # cache write failure is never fatal


def clear(prefix: str | None = None) -> int:
    """Delete cache entries. Returns number of files removed."""
    pattern = f"{prefix}_*.json" if prefix else "*.json"
    removed = 0
    for f in _CACHE_DIR.glob(pattern):
        f.unlink(missing_ok=True)
        removed += 1
    return removed
