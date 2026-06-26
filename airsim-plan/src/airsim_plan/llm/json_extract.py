"""Helpers to coerce SLM output into well-formed JSON.

Small local language models (especially Llama-3-8B served by LM Studio)
often wrap the JSON in ``` fences or add a short preamble. These helpers
try a few robust extraction strategies before giving up.
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional


# A *balanced* regex would be ideal but Python's ``re`` doesn't support
# recursive patterns. The trick we use here is greedy-with-overlap: find
# every opening brace and scan forward, counting nested braces, until we
# find a balanced substring that ``json.loads`` accepts. Cheap and good
# enough for model outputs of a few KB.
_OPEN_BRACE = re.compile(r"\{")
_CLOSE_BRACE = re.compile(r"\}")


def _balanced_objects(text: str) -> List[str]:
    """Yield candidate JSON object substrings by tracking brace depth."""
    out: List[str] = []
    depth = 0
    start: Optional[int] = None
    for idx, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    out.append(text[start : idx + 1])
                    start = None
    return out


def _strip_code_fence(text: str) -> str:
    """Remove a leading ```json ...``` fence if present."""
    fence = re.match(r"\s*```(?:json|JSON)?\s*([\s\S]*?)```\s*$", text.strip())
    if fence:
        return fence.group(1).strip()
    return text.strip()


def _first_parsable_object(text: str) -> Optional[str]:
    """Return the first balanced substring that ``json.loads`` accepts."""
    for candidate in _balanced_objects(text):
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return None


def extract_json_object(text: str) -> Optional[dict]:
    """Best-effort extraction of a JSON object from raw model output."""
    if not text:
        return None
    cleaned = _strip_code_fence(text)
    candidate = _first_parsable_object(cleaned)
    if candidate is None:
        return None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# Minimal structural fingerprint for our Manifest.
_MANIFEST_KEYS = {"mission_id", "waypoints", "rules_of_engagement"}


def looks_like_manifest(payload: Any) -> bool:
    """Return ``True`` when ``payload`` has the top-level shape of a manifest."""
    if not isinstance(payload, dict):
        return False
    return _MANIFEST_KEYS.issubset(payload.keys())
