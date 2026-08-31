"""Structured output validation for MemoSight (non-LLM, machine-readable).

Migrated from ``app.services.caption_harness`` — ``CaptionHarness`` becomes
``MemoSightValidator``, ``HarnessIssue`` becomes ``MemoSightValidationIssue``,
and ``HarnessReport`` becomes ``MemoSightValidationResult``. Behavior is
unchanged; the legacy module re-exports these names.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .normalizer import CAPTION_FIELD_KEYS
from .profiles import MAX_ARRAY_ITEMS

EXPECTED_KEYS = ("caption", *CAPTION_FIELD_KEYS)


@dataclass(frozen=True)
class MemoSightValidationIssue:
    """A syntax or schema issue found by the validator."""

    source: str
    message: str
    line: int | None = None
    column: int | None = None
    snippet: str | None = None
    severity: str = "error"


@dataclass
class MemoSightValidationResult:
    """Aggregated validation result."""

    checked: int = 0
    valid: int = 0
    issues: list[MemoSightValidationIssue] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return len({issue.source for issue in self.issues if issue.severity == "error"})

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def extend(self, other: "MemoSightValidationResult") -> None:
        self.checked += other.checked
        self.valid += other.valid
        self.issues.extend(other.issues)


class MemoSightValidator:
    """Validate caption JSON/JSONL files and structured caption payloads."""

    def validate_path(
        self,
        path: Path,
        *,
        recursive: bool = True,
        strict: bool = True,
    ) -> MemoSightValidationResult:
        report = MemoSightValidationResult()
        for file_path in self._iter_json_files(path, recursive=recursive):
            report.extend(self.validate_file(file_path, strict=strict))
        if report.checked == 0:
            report.issues.append(
                MemoSightValidationIssue(
                    source=str(path),
                    message="No .json or .jsonl files found",
                    severity="error",
                )
            )
        return report

    def validate_file(self, path: Path, *, strict: bool = True) -> MemoSightValidationResult:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".jsonl":
            return self._validate_jsonl_text(text, str(path), strict=strict)
        return self.validate_json_text(text, str(path), strict=strict)

    def validate_json_text(
        self,
        text: str,
        source: str,
        *,
        strict: bool = True,
    ) -> MemoSightValidationResult:
        report = MemoSightValidationResult(checked=1)
        try:
            payload = json.loads(text)
        except JSONDecodeError as exc:
            report.issues.append(self._syntax_issue(source, text, exc))
            return report

        issues = self.validate_payload(payload, source=source, strict=strict)
        if issues:
            report.issues.extend(issues)
        else:
            report.valid = 1
        return report

    def validate_payload(
        self,
        payload: Any,
        *,
        source: str = "<payload>",
        strict: bool = True,
    ) -> list[MemoSightValidationIssue]:
        if not strict:
            return []
        candidates = list(self._iter_caption_payloads(payload))
        if not candidates:
            return [
                MemoSightValidationIssue(
                    source=source,
                    message=(
                        "No caption structured payload found; expected fields include "
                        f"{', '.join(EXPECTED_KEYS)}"
                    ),
                )
            ]

        issues: list[MemoSightValidationIssue] = []
        for label, candidate in candidates:
            issues.extend(self._validate_caption_payload(candidate, source=f"{source}{label}"))
        return issues

    def validate_custom(
        self,
        payload: Any,
        schema: dict[str, Any],
        *,
        source: str = "<payload>",
        strict: bool = True,
    ) -> list[MemoSightValidationIssue]:
        """Validate ``payload`` against a (previously validated) output schema.

        Checks required fields, scalar types, array item types and maxItems,
        enum membership, and simple nested objects. Unknown payload keys are
        tolerated (normalization drops them); everything else produces
        machine-readable issues.
        """
        if not strict:
            return []
        if not isinstance(payload, dict):
            return [
                MemoSightValidationIssue(
                    source=source,
                    message=f"Payload must be a JSON object, got {type(payload).__name__}",
                )
            ]

        properties = schema.get("properties", {})
        issues: list[MemoSightValidationIssue] = []
        for key in schema.get("required", []):
            if key not in payload:
                issues.append(
                    MemoSightValidationIssue(
                        source=source, message=f"Missing required field: {key}"
                    )
                )
        for key, spec in properties.items():
            if key not in payload:
                continue
            issues.extend(
                self._validate_custom_value(payload[key], spec, source=f"{source}.{key}")
            )
        return issues

    def _validate_custom_value(
        self,
        value: Any,
        spec: dict[str, Any],
        *,
        source: str,
    ) -> list[MemoSightValidationIssue]:
        issues: list[MemoSightValidationIssue] = []
        field_type = spec.get("type", "string")

        if field_type == "string":
            if not isinstance(value, str):
                issues.append(self._type_issue(source, "a string", value))
        elif field_type == "boolean":
            if not isinstance(value, bool):
                issues.append(self._type_issue(source, "a boolean", value))
        elif field_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                issues.append(self._type_issue(source, "an integer", value))
        elif field_type == "number":
            if not isinstance(value, int | float) or isinstance(value, bool):
                issues.append(self._type_issue(source, "a number", value))
        elif field_type == "array":
            if not isinstance(value, list):
                issues.append(self._type_issue(source, "an array", value))
            else:
                # Absent maxItems means the default cap applies ("maximum array
                # length 20 unless overridden lower").
                max_items = spec.get("maxItems", MAX_ARRAY_ITEMS)
                if len(value) > max_items:
                    issues.append(
                        MemoSightValidationIssue(
                            source=source,
                            message=f"Field has {len(value)} items; maximum is {max_items}",
                        )
                    )
                item_type = (spec.get("items") or {}).get("type", "string")
                bad = [
                    index
                    for index, item in enumerate(value)
                    if not self._matches_scalar_type(item, item_type)
                ]
                if bad:
                    shown = ", ".join(str(index) for index in bad[:5])
                    issues.append(
                        MemoSightValidationIssue(
                            source=source,
                            message=f"Array items must be of type {item_type}; bad indexes: {shown}",
                        )
                    )
        elif field_type == "object":
            if not isinstance(value, dict):
                issues.append(self._type_issue(source, "an object", value))
            else:
                nested = spec.get("properties", {})
                for key in spec.get("required", []):
                    if key not in value:
                        issues.append(
                            MemoSightValidationIssue(
                                source=source, message=f"Missing required field: {key}"
                            )
                        )
                for key, child_spec in nested.items():
                    if key in value:
                        issues.extend(
                            self._validate_custom_value(
                                value[key], child_spec, source=f"{source}.{key}"
                            )
                        )

        enum = spec.get("enum")
        if enum is not None and not issues and value not in enum:
            issues.append(
                MemoSightValidationIssue(
                    source=source,
                    message=f"Value {value!r} is not one of the allowed enum choices",
                )
            )
        return issues

    @staticmethod
    def _matches_scalar_type(value: Any, item_type: str) -> bool:
        if item_type == "string":
            return isinstance(value, str)
        if item_type == "boolean":
            return isinstance(value, bool)
        if item_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if item_type == "number":
            return isinstance(value, int | float) and not isinstance(value, bool)
        return False

    @staticmethod
    def _type_issue(source: str, expected: str, value: Any) -> MemoSightValidationIssue:
        return MemoSightValidationIssue(
            source=source,
            message=f"Field must be {expected}, got {type(value).__name__}",
        )

    def render_report(self, report: MemoSightValidationResult, *, color: bool = True) -> str:
        palette = _Palette(color)
        lines: list[str] = []
        for issue in report.issues:
            marker = palette.red("[ERROR]") if issue.severity == "error" else palette.yellow("[WARN]")
            location = ""
            if issue.line is not None and issue.column is not None:
                location = f":{issue.line}:{issue.column}"
            lines.append(f"{marker} {palette.bold(issue.source)}{location}")
            lines.append(f"  {issue.message}")
            if issue.snippet is not None:
                lines.extend(f"  {line}" for line in issue.snippet.splitlines())
        summary = (
            f"caption harness summary: checked={report.checked} "
            f"valid={report.valid} errors={sum(1 for i in report.issues if i.severity == 'error')} "
            f"warnings={sum(1 for i in report.issues if i.severity == 'warning')}"
        )
        lines.append(palette.green(summary) if report.ok else palette.red(summary))
        return "\n".join(lines)

    def _validate_jsonl_text(
        self,
        text: str,
        source: str,
        *,
        strict: bool,
    ) -> MemoSightValidationResult:
        report = MemoSightValidationResult()
        for index, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            child = self.validate_json_text(line, f"{source}:{index}", strict=strict)
            report.extend(child)
        if report.checked == 0:
            report.issues.append(MemoSightValidationIssue(source=source, message="JSONL file is empty"))
        return report

    def _iter_json_files(self, path: Path, *, recursive: bool) -> list[Path]:
        if path.is_file():
            return [path] if path.suffix.lower() in {".json", ".jsonl"} else []
        if not path.exists():
            return []
        pattern = "**/*" if recursive else "*"
        return sorted(
            child
            for child in path.glob(pattern)
            if child.is_file() and child.suffix.lower() in {".json", ".jsonl"}
        )

    def _syntax_issue(self, source: str, text: str, exc: JSONDecodeError) -> MemoSightValidationIssue:
        lines = text.splitlines()
        line_text = lines[exc.lineno - 1] if 0 < exc.lineno <= len(lines) else ""
        pointer = " " * max(exc.colno - 1, 0) + "^"
        snippet = f"{exc.lineno:>4} | {line_text}\n     | {pointer}"
        return MemoSightValidationIssue(
            source=source,
            message=f"Invalid JSON syntax: {exc.msg}",
            line=exc.lineno,
            column=exc.colno,
            snippet=snippet,
        )

    def _iter_caption_payloads(self, payload: Any, label: str = ""):
        if isinstance(payload, list):
            for index, item in enumerate(payload):
                yield from self._iter_caption_payloads(item, f"{label}[{index}]")
            return
        if not isinstance(payload, dict):
            return

        key_set = set(payload)
        if key_set.intersection(EXPECTED_KEYS):
            yield label, payload
        for key in ("structured_fields", "fields", "result", "caption_fields"):
            nested = payload.get(key)
            if isinstance(nested, dict | list):
                yield from self._iter_caption_payloads(nested, f"{label}.{key}")
        for key in ("items", "results", "assets", "records", "samples"):
            nested = payload.get(key)
            if isinstance(nested, list):
                yield from self._iter_caption_payloads(nested, f"{label}.{key}")

    def _validate_caption_payload(self, payload: dict[str, Any], *, source: str) -> list[MemoSightValidationIssue]:
        issues: list[MemoSightValidationIssue] = []
        for key in EXPECTED_KEYS:
            if key not in payload:
                issues.append(MemoSightValidationIssue(source=source, message=f"Missing field: {key}"))

        caption = payload.get("caption")
        if "caption" in payload and not isinstance(caption, str):
            issues.append(MemoSightValidationIssue(source=source, message="Field caption must be a string"))
        if isinstance(caption, str) and not caption.strip():
            issues.append(MemoSightValidationIssue(source=source, message="Field caption must not be empty"))

        for key in CAPTION_FIELD_KEYS:
            value = payload.get(key)
            if key not in payload:
                continue
            if not isinstance(value, list):
                issues.append(MemoSightValidationIssue(source=source, message=f"Field {key} must be an array"))
                continue
            if len(value) > 6:
                issues.append(
                    MemoSightValidationIssue(source=source, message=f"Field {key} has {len(value)} items; maximum is 6")
                )
            bad_indexes = [index for index, item in enumerate(value) if not isinstance(item, str)]
            if bad_indexes:
                shown = ", ".join(str(index) for index in bad_indexes[:5])
                issues.append(
                    MemoSightValidationIssue(source=source, message=f"Field {key} must contain only strings; bad indexes: {shown}")
                )
        return issues


class _Palette:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"
