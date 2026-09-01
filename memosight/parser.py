"""Parse untrusted VLM/model text output into structured JSON dicts.

Migrated from ``VisionService._parse_vlm_observation`` and
``MemoRAGService._parse_caption_extraction_json``. Model output is never
trusted: parse failures are returned as structured issues instead of raising.

Also owns the legacy Markdown field fallback (reimplemented from
``MemoRAGService.markdown_caption_fields_to_json`` semantics, without
importing project services) for older fixed-Markdown caption field output.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from .normalizer import CAPTION_FIELD_KEYS

_FENCED_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", flags=re.DOTALL)

ParseStrategy = Literal["strict", "fenced", "embedded", "markdown"]

# Recognized Markdown field labels -> default observation keys. Extends the
# legacy MemoRAG alias table with ``caption`` so full legacy-style output can
# satisfy the default observation contract.
_MARKDOWN_FIELD_ALIASES: dict[str, str] = {
    "caption": "caption",
    "描述": "caption",
    "scene labels": "scene_labels",
    "search tags": "search_tags",
    "scene": "scene_labels",
    "scenes": "scene_labels",
    "tags": "search_tags",
}
_MARKDOWN_FIELD_ALIASES.update(
    {key: key for key in ("caption", *CAPTION_FIELD_KEYS)}
)

_MARKDOWN_EMPTY_TOKENS = {
    "none",
    "null",
    "unknown",
    "[]",
    "-",
    "无",
    "没有",
    "无内容",
}


@dataclass(frozen=True)
class MemoSightParseIssue:
    """Structured description of why model output could not be parsed."""

    message: str
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class MemoSightParseResult:
    """Outcome of parsing raw model output; ``raw_output`` is always preserved."""

    raw_output: str
    data: dict[str, Any] | None = None
    strategy: ParseStrategy | None = None
    error: MemoSightParseIssue | None = None

    @property
    def ok(self) -> bool:
        return self.data is not None and self.error is None


def parse_model_output(text: str | None) -> MemoSightParseResult:
    """Parse model output into a dict, trying strict JSON, fenced Markdown
    JSON, then the first ``{`` .. last ``}`` span for prose-wrapped output.

    Never raises; failures come back as ``MemoSightParseIssue``.
    """
    raw = "" if text is None else str(text)
    stripped = raw.strip()
    if not stripped:
        return MemoSightParseResult(
            raw_output=raw,
            error=MemoSightParseIssue(message="Model output is empty"),
        )

    candidates: list[tuple[ParseStrategy, str]] = [("strict", stripped)]
    fenced = _FENCED_BLOCK_RE.search(stripped)
    if fenced:
        candidates.append(("fenced", fenced.group(1).strip()))
    if "{" in stripped and "}" in stripped:
        candidates.append(
            ("embedded", stripped[stripped.find("{"): stripped.rfind("}") + 1])
        )

    last_error: MemoSightParseIssue | None = None
    for strategy, candidate in candidates:
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = MemoSightParseIssue(
                message=f"Invalid JSON ({strategy} candidate): {exc.msg}",
                line=exc.lineno,
                column=exc.colno,
            )
            continue
        if not isinstance(payload, dict):
            last_error = MemoSightParseIssue(
                message=f"Model output is not a JSON object ({strategy} candidate)",
            )
            continue
        return MemoSightParseResult(raw_output=raw, data=payload, strategy=strategy)

    return MemoSightParseResult(
        raw_output=raw,
        error=last_error
        or MemoSightParseIssue(message="No JSON object found in model output"),
    )


def parse_markdown_fields(text: str | None) -> dict[str, Any] | None:
    """Parse legacy fixed-Markdown caption field output into a raw payload.

    Fallback for the pre-JSON output format. Supported shapes (matching the
    legacy ``markdown_caption_fields_to_json`` semantics):

    - ``**scene_labels:** 婚礼, 室内`` (bold label lines)
    - ``scene_labels: 婚礼、室内`` (plain ``key: value`` lines)
    - ``### scene_labels`` followed by ``- item`` bullet lines

    Returns a dict with optional ``caption`` (string) plus the caption field
    keys mapped to raw item lists, or ``None`` when no known field label is
    found. Item values are NOT normalized here — callers should run the
    normalizer. Never raises.
    """
    raw = "" if text is None else str(text)
    if not raw.strip():
        return None

    fields: dict[str, list[str]] = {key: [] for key in CAPTION_FIELD_KEYS}
    caption: str | None = None
    current_key: str | None = None
    found_any = False

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line in {"```", "```markdown"}:
            continue
        line = line.lstrip("#").strip()

        parsed_key, parsed_value = _parse_markdown_field_line(line)
        if parsed_key:
            found_any = True
            current_key = parsed_key
            if parsed_key == "caption":
                if parsed_value and parsed_value.lower() not in _MARKDOWN_EMPTY_TOKENS:
                    caption = parsed_value if caption is None else f"{caption} {parsed_value}"
            else:
                fields[parsed_key].extend(_split_markdown_field_items(parsed_value))
            continue

        if current_key and current_key != "caption" and line.startswith(("-", "*", "+")):
            item_text = line[1:].strip()
            fields[current_key].extend(_split_markdown_field_items(item_text))

    if not found_any:
        return None
    result: dict[str, Any] = dict(fields)
    if caption is not None:
        result["caption"] = caption
    return result


def find_markdown_field_keys(text: str | None) -> set[str]:
    """Return recognized field labels present in fixed-Markdown output.

    Unlike :func:`parse_markdown_fields`, this preserves label presence so a
    caller can distinguish an explicitly empty ``none`` field from a missing
    required line.
    """
    raw = "" if text is None else str(text)
    found: set[str] = set()
    for raw_line in raw.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if not line:
            continue
        key, _ = _parse_markdown_field_line(line)
        if key:
            found.add(key)
    return found


def _parse_markdown_field_line(line: str) -> tuple[str | None, str]:
    """Extract a (field key, value) pair from a single Markdown line."""
    normalized = line.strip()
    if normalized.startswith("**") and "**" in normalized[2:]:
        end = normalized.find("**", 2)
        label = normalized[2:end].strip().rstrip(":：").lower()
        value = normalized[end + 2:].strip().lstrip(":：").strip()
        return _MARKDOWN_FIELD_ALIASES.get(label), value

    if ":" in normalized or "：" in normalized:
        delimiter = ":" if ":" in normalized else "："
        label, value = normalized.split(delimiter, 1)
        label = label.strip().strip("*").strip().lower()
        return _MARKDOWN_FIELD_ALIASES.get(label), value.strip()

    label = normalized.strip("*").strip().rstrip(":：").lower()
    return _MARKDOWN_FIELD_ALIASES.get(label), ""


def _split_markdown_field_items(value: str) -> list[str]:
    """Split a Markdown field value into items on common CJK/ASCII delimiters."""
    value = value.strip()
    if not value or value.lower() in _MARKDOWN_EMPTY_TOKENS:
        return []
    for delimiter in ("，", "、", ";", "；", "|", "\t"):
        value = value.replace(delimiter, ",")
    return [
        item
        for item in (part.strip().strip("-*` ") for part in value.split(","))
        if item and item.lower() not in _MARKDOWN_EMPTY_TOKENS
    ]
