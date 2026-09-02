"""Two-stage structured output: image -> caption -> structured fields.

The stage boundary is intentional: visual inference only writes a concise
caption, while a text-only call extracts fields. The default profile keeps
the legacy fixed-Markdown field prompt; custom and named schemas use
schema-driven JSON prompts. Stage two is public and independently retryable,
so a malformed text response does not require repeating visual inference.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from .backends import MemoSightBackend, MemoSightTextBackend
from .errors import MemoSightInputError
from .normalizer import (
    CAPTION_FIELD_KEYS,
    empty_caption_fields,
    normalize_caption_fields,
)
from .parser import (
    find_markdown_field_keys,
    parse_markdown_fields,
    parse_model_output,
)
from .prompt_config import PromptConfigInput
from .profiles import DEFAULT_PROFILE_NAME, MemoSightProfile, resolve_profile
from .prompts import (
    build_caption_field_extraction_prompt,
    build_caption_prompt,
    build_caption_structured_extraction_prompt,
)
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
    """Run image captioning and structured extraction as separate stages."""

    def __init__(
        self,
        image_backend: MemoSightBackend,
        text_backend: MemoSightTextBackend,
        validator: MemoSightValidator | None = None,
        *,
        temp_dir: str | Path | None = None,
    ) -> None:
        self._image_backend = image_backend
        self._text_backend = text_backend
        self._validator = validator or MemoSightValidator()
        self._temp_dir = temp_dir

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
            prompt_config=request.prompt_config,
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

        fields_result = await self._extract_fields_for_profile(
            caption,
            profile,
            language=request.language,
            output_instructions=request.output_instructions,
            prompt_plan=request.prompt_plan,
            prompt_config=request.prompt_config,
        )
        is_default = profile.name == DEFAULT_PROFILE_NAME
        if is_default:
            observation_payload = {
                "caption": caption,
                **fields_result.fields,
            }
            observation = MemoSightObservation(**observation_payload)
            default_observation = observation
            observation_dict = observation.model_dump()
        else:
            observation_dict = fields_result.fields
            default_observation = self._map_default_observation(observation_dict)
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
                observation=observation_dict,
                default_observation=default_observation,
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
            observation=observation_dict,
            default_observation=default_observation,
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
        output_schema: dict[str, Any] | None = None,
        profile: str | None = None,
        prompt_plan: Any | None = None,
        prompt_config: PromptConfigInput = None,
    ) -> MemoSightFieldExtractionResult:
        """Run only caption -> structured fields -> validation."""
        caption = self._normalize_caption(caption)
        try:
            resolved_profile = resolve_profile(
                output_schema=output_schema,
                profile=profile,
            )
        except Exception as exc:
            issue = MemoSightValidationIssue(
                source=f"{_ISSUE_SOURCE}.schema",
                message=str(exc),
            )
            return MemoSightFieldExtractionResult(
                status="failed",
                fields={},
                validation=MemoSightValidationResult(checked=1, issues=[issue]),
                error=str(exc),
            )

        return await self._extract_fields_for_profile(
            caption,
            resolved_profile,
            language=language,
            output_instructions=output_instructions,
            prompt_plan=prompt_plan,
            prompt_config=prompt_config,
        )

    async def _extract_fields_for_profile(
        self,
        caption: str,
        profile: MemoSightProfile,
        *,
        language: str,
        output_instructions: str | None,
        prompt_plan: Any | None = None,
        prompt_config: PromptConfigInput = None,
    ) -> MemoSightFieldExtractionResult:
        """Run caption extraction for an already resolved profile."""
        empty = (
            empty_caption_fields()
            if profile.name == DEFAULT_PROFILE_NAME
            else self._caption_seed(caption, profile)
        )
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

        if profile.name != DEFAULT_PROFILE_NAME:
            return await self._extract_structured_fields(
                caption,
                profile,
                language=language,
                output_instructions=output_instructions,
                prompt_plan=prompt_plan,
                prompt_config=prompt_config,
            )

        prompt = build_caption_field_extraction_prompt(
            caption,
            language=language,
            output_instructions=output_instructions,
            prompt_config=prompt_config,
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

    async def _extract_structured_fields(
        self,
        caption: str,
        profile: MemoSightProfile,
        *,
        language: str,
        output_instructions: str | None,
        prompt_plan: Any | None = None,
        prompt_config: PromptConfigInput = None,
    ) -> MemoSightFieldExtractionResult:
        """Run caption -> schema-shaped JSON for custom and named profiles."""
        prompt = build_caption_structured_extraction_prompt(
            caption,
            profile,
            language=language,
            output_instructions=output_instructions,
            prompt_plan=prompt_plan,
            prompt_config=prompt_config,
        )
        model_started = time.perf_counter()
        try:
            raw_output = await self._text_backend.complete(prompt)
        except Exception as exc:
            logger.exception("Two-stage structured extraction backend failed")
            return MemoSightFieldExtractionResult(
                status="failed",
                fields=self._caption_seed(caption, profile),
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
        parsed = parse_model_output(raw_output)
        issues: list[MemoSightValidationIssue] = []
        if parsed.data is None:
            parse_issue = parsed.error
            issues.append(
                MemoSightValidationIssue(
                    source=f"{_ISSUE_SOURCE}.fields",
                    message=(
                        parse_issue.message
                        if parse_issue
                        else "Field output is not recognized JSON"
                    ),
                    line=parse_issue.line if parse_issue else None,
                    column=parse_issue.column if parse_issue else None,
                )
            )
            fields = self._caption_seed(caption, profile)
        else:
            fields = self._normalize_structured_fields(parsed.data, caption, profile)
            issues.extend(
                self._validator.validate_custom(
                    fields,
                    profile.output_schema,
                    source=f"{_ISSUE_SOURCE}.fields",
                )
            )
        postprocess_duration_s = time.perf_counter() - post_started
        usage = {
            "structured_output_duration_s": structured_duration_s,
            "postprocess_duration_s": postprocess_duration_s,
            "parse_strategy": parsed.strategy,
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
    def _caption_seed(caption: str, profile: MemoSightProfile) -> dict[str, Any]:
        """Seed custom outputs with the stage-one caption when schema allows it."""
        spec = profile.output_schema.get("properties", {}).get("caption")
        if spec and spec.get("type", "string") == "string":
            return {"caption": caption}
        return {}

    @classmethod
    def _normalize_structured_fields(
        cls,
        data: dict[str, Any],
        caption: str,
        profile: MemoSightProfile,
    ) -> dict[str, Any]:
        """Keep only schema fields and pin caption to the first-stage value."""
        properties = profile.output_schema.get("properties", {})
        fields = {key: data[key] for key in properties if key in data}
        fields.update(cls._caption_seed(caption, profile))
        return fields

    @staticmethod
    def _map_default_observation(
        observation: dict[str, Any],
    ) -> MemoSightObservation | None:
        """Best-effort map of schema-shaped output into the default contract."""
        caption = observation.get("caption")
        if not isinstance(caption, str) or not caption.strip():
            return None
        return MemoSightObservation(
            caption=caption.strip(), **normalize_caption_fields(observation)
        )

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
