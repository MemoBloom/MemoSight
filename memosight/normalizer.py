"""Normalize default caption field payloads into a stable list-of-strings shape.

Migrated from ``MemoRAGService._normalize_caption_fields`` and
``MemoRAGService._empty_caption_fields`` (behavior unchanged).
"""
from __future__ import annotations

from typing import Any

CAPTION_FIELD_KEYS = (
    "scene_labels",
    "people",
    "actions",
    "objects",
    "lighting",
    "mood",
    "search_tags",
)
DEFAULT_MAX_ITEMS_PER_FIELD = 6


def empty_caption_fields() -> dict[str, list[str]]:
    """Return the default caption fields with empty lists."""
    return {key: [] for key in CAPTION_FIELD_KEYS}


def normalize_caption_fields(
    payload: dict[str, Any] | None,
    *,
    max_items: int = DEFAULT_MAX_ITEMS_PER_FIELD,
) -> dict[str, list[str]]:
    """Keep only allowed keys and sanitize each value list.

    - unknown keys are dropped
    - string values become single-item arrays
    - null, empty, and ``"unknown"`` items are dropped
    - duplicates are removed (first occurrence wins)
    - items are trimmed and capped at ``max_items`` per field
    - language-specific text is kept intact
    """
    payload = payload or {}
    result: dict[str, list[str]] = {}
    for key in CAPTION_FIELD_KEYS:
        value = payload.get(key, [])
        if isinstance(value, str):
            value = [value]
        elif not isinstance(value, list):
            value = [] if value is None else [str(value)]

        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if item is None:
                continue
            item_text = str(item).strip()
            if not item_text or item_text.lower() == "unknown":
                continue
            if item_text not in seen:
                seen.add(item_text)
                normalized.append(item_text)
            if len(normalized) >= max_items:
                break
        result[key] = normalized
    return result
