"""Two-stage structured output: image -> caption -> Markdown fields.

The stage boundary is intentional: visual inference only writes a concise
caption, while a text-only call extracts the fixed retrieval fields. Stage
two is public and independently retryable, so a malformed Markdown response
does not require repeating visual inference.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Literal

from .backends import MemoSightBackend, MemoSightTextBackend
from .errors import MemoSightInputError
from .normalizer import CAPTION_FIELD_KEYS, empty_caption_fields, normalize_caption_fields
from .parser import find_markdown_field_keys, parse_markdown_fields
from .profiles import DEFAULT_PROFILE_NAME, resolve_profile
from .prompts import build_caption_field_extraction_prompt, build_caption_prompt
from .schema import (
    MemoSightFieldExtractionResult,
    MemoSightObservation,
    MemoSightRequest,
    TwoStageMemoSightResult,
)
from .source import resolve_image_source
from .validator import (
    MemoSightValidationIssue,
    MemoSightValidationResult,
    MemoSightValidator,
)

_ISSUE_SOURCE = "memosight.two_stage"
_CAPTION_PREFIX_RE = re.compile(r"^(?:caption|描述)\s*[:：]\s*", re.IGNORECASE)

logger = logging.getLogger(__name__)


class TwoStageMemoSightPipeline:
    """Run the fixed default contract through separate vision/text stages."""

    def __init__(
        self,
        image_backend: MemoSightBackend,
        text_backend: MemoSightTextBackend,
        validator: MemoSightValidator | None = None,
        *,
        temp_dir: str | Path | None = None,
        caption_prompt_version: Literal["v1", "v2", "v3"] = "v1",
        field_prompt_version: Literal["v1", "v2", "v3", "v4", "v5"] = "v1",
    ) -> None:
        if caption_prompt_version not in ("v1", "v2", "v3"):
            raise ValueError("caption_prompt_version must be 'v1', 'v2', or 'v3'")
        if field_prompt_version not in ("v1", "v2", "v3", "v4", "v5"):
            raise ValueError(
                "field_prompt_version must be 'v1', 'v2', 'v3', 'v4', or 'v5'"
            )
        self._image_backend = image_backend
        self._text_backend = text_backend
        self._validator = validator or MemoSightValidator()
        self._temp_dir = temp_dir
        self._caption_prompt_version = caption_prompt_version
        self._field_prompt_version = field_prompt_version

    async def analyze(self, request: MemoSightRequest) -> TwoStageMemoSightResult:
        """Analyze an image while preserving both raw stage outputs and timings."""
        total_started = time.perf_counter()
        try:
            profile = resolve_profile(
                output_schema=request.output_schema,
                profile=request.profile or None,
            )
        except Exception as exc:
            return self._failed_result(
                request,
                error=str(exc),
                failed_stage="caption",
                total_started=total_started,
            )
        if profile.name != DEFAULT_PROFILE_NAME:
            return self._failed_result(
                request,
                error=(
                    "Two-stage structured output currently supports only the "
                    f"{DEFAULT_PROFILE_NAME!r} profile"
                ),
                failed_stage="caption",
                total_started=total_started,
                schema_name=profile.schema_name,
                schema_version=profile.schema_version,
            )

        source_started = time.perf_counter()
        try:
            resolved = resolve_image_source(request.image, temp_dir=self._temp_dir)
        except MemoSightInputError as exc:
            return self._failed_result(
                request,
                error=str(exc),
                failed_stage="caption",
                total_started=total_started,
                schema_name=profile.schema_name,
                schema_version=profile.schema_version,
            )
        source_duration_s = time.perf_counter() - source_started

        caption_prompt = build_caption_prompt(
            language=request.language,
            version=self._caption_prompt_version,
        )
        caption_started = time.perf_counter()
        try:
            caption_raw = await self._image_backend.describe(resolved, caption_prompt)
        except Exception as exc:
            logger.exception("Two-stage caption backend failed for %s", request.asset_id)
            return self._failed_result(
                request,
                error=f"Caption backend failed: {exc}",
                failed_stage="caption",
                total_started=total_started,
                schema_name=profile.schema_name,
                schema_version=profile.schema_version,
                usage={"source_duration_s": source_duration_s},
            )
        finally:
            resolved.cleanup()
        caption_duration_s = time.perf_counter() - caption_started
        caption = self._normalize_caption(caption_raw)
        if not caption:
            issue = MemoSightValidationIssue(
                source=f"{_ISSUE_SOURCE}.caption",
                message="Caption output is empty",
            )
            return self._failed_result(
                request,
                error="Caption output failed validation",
                failed_stage="caption",
                total_started=total_started,
                schema_name=profile.schema_name,
                schema_version=profile.schema_version,
                caption_raw_output=caption_raw,
                issues=[issue],
                usage={
                    "source_duration_s": source_duration_s,
                    "caption_duration_s": caption_duration_s,
                },
            )

        fields_result = await self.extract_fields(
            caption,
            language=request.language,
            output_instructions=request.output_instructions,
            prompt_version=self._field_prompt_version,
        )
        observation_payload = {
            "caption": caption,
            **fields_result.fields,
        }
        observation = MemoSightObservation(**observation_payload)
        usage = {
            "source_duration_s": source_duration_s,
            "caption_duration_s": caption_duration_s,
            "structured_output_duration_s": fields_result.usage.get(
                "structured_output_duration_s", 0.0
            ),
            "postprocess_duration_s": fields_result.usage.get(
                "postprocess_duration_s", 0.0
            ),
            "total_duration_s": time.perf_counter() - total_started,
            "caption_chars": len(caption),
            "parse_strategy": fields_result.usage.get("parse_strategy"),
            "stages": {
                "caption_backend": self._image_backend.name,
                "field_backend": self._text_backend.name,
            },
        }
        if fields_result.status == "failed":
            return TwoStageMemoSightResult(
                status="partial",
                observation=observation.model_dump(),
                default_observation=observation,
                raw_output=fields_result.raw_output,
                caption_raw_output=caption_raw,
                structured_raw_output=fields_result.raw_output,
                failed_stage="field_extraction",
                schema_name=profile.schema_name,
                schema_version=profile.schema_version,
                model_name=self._image_backend.name,
                model_version=self._image_backend.version,
                validation=fields_result.validation,
                usage=usage,
                error=fields_result.error,
            )

        return TwoStageMemoSightResult(
            status="ok",
            observation=observation.model_dump(),
            default_observation=observation,
            raw_output=fields_result.raw_output,
            caption_raw_output=caption_raw,
            structured_raw_output=fields_result.raw_output,
            schema_name=profile.schema_name,
            schema_version=profile.schema_version,
            model_name=self._image_backend.name,
            model_version=self._image_backend.version,
            validation=fields_result.validation,
            usage=usage,
        )

    async def extract_fields(
        self,
        caption: str,
        *,
        language: str = "zh",
        output_instructions: str | None = None,
        prompt_version: Literal["v1", "v2", "v3", "v4", "v5"] = "v1",
    ) -> MemoSightFieldExtractionResult:
        """Run only caption -> fixed Markdown -> normalized fields -> validation."""
        caption = self._normalize_caption(caption)
        empty = empty_caption_fields()
        if not caption:
            issue = MemoSightValidationIssue(
                source=f"{_ISSUE_SOURCE}.caption",
                message="Caption is required for field extraction",
            )
            return MemoSightFieldExtractionResult(
                status="failed",
                fields=empty,
                validation=MemoSightValidationResult(checked=1, issues=[issue]),
                error=issue.message,
            )

        prompt = build_caption_field_extraction_prompt(
            caption,
            language=language,
            output_instructions=output_instructions,
            version=prompt_version,
        )
        model_started = time.perf_counter()
        try:
            raw_output = await self._text_backend.complete(prompt)
        except Exception as exc:
            logger.exception("Two-stage field extraction backend failed")
            return MemoSightFieldExtractionResult(
                status="failed",
                fields=empty,
                validation=MemoSightValidationResult(),
                usage={
                    "structured_output_duration_s": time.perf_counter()
                    - model_started,
                    "postprocess_duration_s": 0.0,
                },
                error=f"Field extraction backend failed: {exc}",
            )
        structured_duration_s = time.perf_counter() - model_started

        post_started = time.perf_counter()
        parsed = parse_markdown_fields(raw_output)
        present = find_markdown_field_keys(raw_output)
        missing = [key for key in CAPTION_FIELD_KEYS if key not in present]
        issues: list[MemoSightValidationIssue] = []
        if parsed is None:
            issues.append(
                MemoSightValidationIssue(
                    source=f"{_ISSUE_SOURCE}.fields",
                    message="Field output is not recognized fixed Markdown",
                )
            )
            fields = empty
        else:
            fields = normalize_caption_fields(parsed)
        if missing:
            issues.append(
                MemoSightValidationIssue(
                    source=f"{_ISSUE_SOURCE}.fields",
                    message=f"Missing required Markdown fields: {', '.join(missing)}",
                )
            )
        if not issues:
            issues.extend(
                self._validator.validate_payload(
                    {"caption": caption, **fields},
                    source=f"{_ISSUE_SOURCE}.fields",
                )
            )
        postprocess_duration_s = time.perf_counter() - post_started
        usage = {
            "structured_output_duration_s": structured_duration_s,
            "postprocess_duration_s": postprocess_duration_s,
            "parse_strategy": "markdown" if parsed is not None else None,
        }
        validation = MemoSightValidationResult(
            checked=1,
            valid=0 if issues else 1,
            issues=issues,
        )
        if issues:
            return MemoSightFieldExtractionResult(
                status="failed",
                fields=fields,
                raw_output=raw_output,
                validation=validation,
                usage=usage,
                error=f"Field output failed validation ({len(issues)} issue(s))",
            )
        return MemoSightFieldExtractionResult(
            status="ok",
            fields=fields,
            raw_output=raw_output,
            validation=validation,
            usage=usage,
        )

    async def analyze_batch(
        self, requests: list[MemoSightRequest]
    ) -> list[TwoStageMemoSightResult]:
        """Analyze sequentially; one failed item never aborts the batch."""
        results: list[TwoStageMemoSightResult] = []
        for request in requests:
            started = time.perf_counter()
            try:
                results.append(await self.analyze(request))
            except Exception as exc:  # defensive: analyze() should not raise
                results.append(
                    self._failed_result(
                        request,
                        error=f"Unexpected error: {exc}",
                        failed_stage="caption",
                        total_started=started,
                    )
                )
        return results

    @staticmethod
    def _normalize_caption(value: str | None) -> str:
        text = "" if value is None else str(value).strip()
        if text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()
        text = _CAPTION_PREFIX_RE.sub("", text)
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'", "“", "”"}:
            text = text[1:-1].strip()
        return " ".join(text.split())

    def _failed_result(
        self,
        request: MemoSightRequest,
        *,
        error: str,
        failed_stage: str,
        total_started: float,
        schema_name: str | None = None,
        schema_version: str = "1.0.0",
        caption_raw_output: str | None = None,
        issues: list[MemoSightValidationIssue] | None = None,
        usage: dict | None = None,
    ) -> TwoStageMemoSightResult:
        usage = dict(usage or {})
        usage["total_duration_s"] = time.perf_counter() - total_started
        issue_list = list(issues or [])
        return TwoStageMemoSightResult(
            status="failed",
            observation={},
            raw_output=caption_raw_output,
            caption_raw_output=caption_raw_output,
            failed_stage=failed_stage,
            schema_name=schema_name or request.profile or None,
            schema_version=schema_version,
            model_name=self._image_backend.name,
            model_version=self._image_backend.version,
            validation=MemoSightValidationResult(
                checked=1 if issue_list else 0,
                issues=issue_list,
            ),
            usage=usage,
            error=error,
        )
