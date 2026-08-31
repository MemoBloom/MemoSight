"""MemoSightPipeline — coordinates the full image-to-structured-text flow.

Stages:

    MemoSightRequest
      -> resolve image source
      -> resolve profile/output schema
      -> build prompt
      -> call backend
      -> parse output (JSON / fenced JSON / embedded JSON / Markdown fallback)
      -> normalize output
      -> validate output
      -> optional repair/retry
      -> MemoSightResult

Error policy (documented contract):

- Input errors (missing file, undecodable base64), schema errors, and backend
  errors are captured into ``status="failed"`` results with ``error`` set;
  ``analyze()`` never raises for expected failure modes, so batch callers can
  rely on one bad request not aborting the batch.
- Invalid model output (parse or validation failure) triggers up to
  ``max_repair_attempts`` repair calls with a prompt that includes the
  validation issues. If output is still invalid, the result is
  ``status="failed"`` with the validation issues and the last raw output.
  Malformed data is never returned as ``ok``.
- Temp files materialized for bytes/base64 sources are re-resolved per
  attempt (backends own per-call cleanup) and additionally removed by a
  pipeline-level ``try/finally`` safety net, so they never leak even when a
  backend ignores the cleanup contract.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .backends import MemoSightBackend
from .errors import MemoSightInputError, MemoSightSchemaError
from .normalizer import normalize_caption_fields
from .parser import parse_markdown_fields, parse_model_output
from .profiles import (
    DEFAULT_PROFILE_NAME,
    MemoSightProfile,
    resolve_profile,
)
from .prompts import MemoSightPrompt, build_prompt
from .schema import MemoSightObservation, MemoSightRequest, MemoSightResult
from .source import resolve_image_source
from .validator import (
    MemoSightValidationIssue,
    MemoSightValidationResult,
    MemoSightValidator,
)

_ISSUE_SOURCE = "memosight.pipeline"
_MAX_REPAIR_ISSUES_SHOWN = 10
_MAX_REPAIR_RAW_OUTPUT_CHARS = 2000

logger = logging.getLogger(__name__)


class MemoSightPipeline:
    """Run MemoSightRequests through backend, parse, normalize, validate."""

    def __init__(
        self,
        backend: MemoSightBackend,
        validator: MemoSightValidator | None = None,
        max_repair_attempts: int = 1,
        *,
        temp_dir: str | Path | None = None,
    ) -> None:
        if max_repair_attempts < 0:
            raise ValueError("max_repair_attempts must be >= 0")
        self._backend = backend
        self._validator = validator or MemoSightValidator()
        self._max_repair_attempts = max_repair_attempts
        self._temp_dir = temp_dir

    async def analyze(self, request: MemoSightRequest) -> MemoSightResult:
        """Analyze one image; expected failures come back as failed results."""
        try:
            profile = resolve_profile(
                output_schema=request.output_schema,
                profile=request.profile or None,
            )
        except MemoSightSchemaError as exc:
            return self._failed_result(request, error=str(exc))

        prompt = build_prompt(
            profile,
            language=request.language,
            output_instructions=self._combined_instructions(request),
        )
        is_default = profile.name == DEFAULT_PROFILE_NAME

        issues: list[MemoSightValidationIssue] = []
        raw_output: str | None = None
        current_prompt = prompt
        attempts = 0
        for attempt in range(self._max_repair_attempts + 1):
            attempts = attempt + 1
            # Re-resolve per attempt: backends own cleanup of each resolved
            # source, so a repair retry needs a fresh materialization.
            try:
                resolved = resolve_image_source(request.image, temp_dir=self._temp_dir)
            except MemoSightInputError as exc:
                return self._failed_result(request, error=str(exc), profile=profile)
            try:
                raw_output = await self._backend.describe(resolved, current_prompt)
            except Exception as exc:
                # Backends are expected to raise MemoSightBackendError, but any
                # failure is captured so analyze() never raises mid-batch.
                logger.exception(
                    "MemoSight backend describe failed for asset %s",
                    request.asset_id,
                )
                return self._failed_result(
                    request,
                    error=f"Backend describe failed: {exc}",
                    profile=profile,
                    raw_output=raw_output,
                )
            finally:
                # Pipeline-level safety net; cleanup() is idempotent and never
                # touches caller-owned path sources.
                resolved.cleanup()

            observation, issues, strategy = self._process_output(
                raw_output, profile, is_default=is_default
            )
            if not issues:
                return self._ok_result(
                    profile,
                    observation=observation,
                    raw_output=raw_output,
                    attempts=attempts,
                    strategy=strategy,
                    is_default=is_default,
                )
            if attempt < self._max_repair_attempts:
                current_prompt = self._build_repair_prompt(
                    prompt, raw_output=raw_output, issues=issues
                )

        return self._failed_result(
            request,
            profile=profile,
            issues=issues,
            raw_output=raw_output,
            error=(
                f"Model output failed validation after {attempts} attempt(s) "
                f"({len(issues)} issue(s))"
            ),
            usage={"attempts": attempts},
        )

    async def analyze_batch(
        self, requests: list[MemoSightRequest]
    ) -> list[MemoSightResult]:
        """Analyze requests sequentially; one failure never aborts the batch."""
        results: list[MemoSightResult] = []
        for request in requests:
            try:
                results.append(await self.analyze(request))
            except Exception as exc:  # defensive: analyze() should not raise
                results.append(
                    self._failed_result(request, error=f"Unexpected error: {exc}")
                )
        return results

    # ── Output processing ──

    def _process_output(
        self,
        raw_output: str,
        profile: MemoSightProfile,
        *,
        is_default: bool,
    ) -> tuple[dict[str, Any], list[MemoSightValidationIssue], str | None]:
        """Parse, normalize, and validate one raw model output.

        Returns ``(observation, issues, parse_strategy)``; a non-empty issue
        list means the output is invalid.
        """
        parsed = parse_model_output(raw_output)
        data = parsed.data
        strategy = parsed.strategy

        if data is None and is_default:
            markdown_data = parse_markdown_fields(raw_output)
            if markdown_data is not None:
                data = markdown_data
                strategy = "markdown"

        if data is None:
            issue = parsed.error
            return {}, [
                MemoSightValidationIssue(
                    source=_ISSUE_SOURCE,
                    message=issue.message if issue else "Unparseable model output",
                    line=issue.line if issue else None,
                    column=issue.column if issue else None,
                )
            ], strategy

        if is_default:
            observation = self._normalize_default(data)
            issues = self._validator.validate_payload(observation, source=_ISSUE_SOURCE)
        else:
            properties = profile.output_schema.get("properties", {})
            observation = {key: data[key] for key in properties if key in data}
            issues = self._validator.validate_custom(
                observation, profile.output_schema, source=_ISSUE_SOURCE
            )
        return observation, issues, strategy

    @staticmethod
    def _normalize_default(data: dict[str, Any]) -> dict[str, Any]:
        """Normalize a default-profile payload into the 8-field contract."""
        caption_raw = data.get("caption")
        if isinstance(caption_raw, str):
            caption = caption_raw.strip()
        elif caption_raw is None:
            caption = ""
        else:
            caption = str(caption_raw).strip()
        return {"caption": caption, **normalize_caption_fields(data)}

    @staticmethod
    def _map_default_observation(
        observation: dict[str, Any],
    ) -> MemoSightObservation | None:
        """Map a non-default observation back to the default contract.

        Only safe when the payload carries a non-empty string ``caption``;
        the seven array fields are normalized (missing fields become empty).
        """
        caption = observation.get("caption")
        if not isinstance(caption, str) or not caption.strip():
            return None
        return MemoSightObservation(
            caption=caption.strip(), **normalize_caption_fields(observation)
        )

    # ── Result builders ──

    def _ok_result(
        self,
        profile: MemoSightProfile,
        *,
        observation: dict[str, Any],
        raw_output: str,
        attempts: int,
        strategy: str | None,
        is_default: bool,
    ) -> MemoSightResult:
        if is_default:
            default_observation = MemoSightObservation(**observation)
        else:
            default_observation = self._map_default_observation(observation)
        return MemoSightResult(
            status="ok",
            observation=observation,
            default_observation=default_observation,
            raw_output=raw_output,
            schema_name=profile.schema_name,
            schema_version=profile.schema_version,
            model_name=self._backend.name,
            model_version=self._backend.version,
            validation=MemoSightValidationResult(checked=1, valid=1),
            usage={"attempts": attempts, "parse_strategy": strategy},
        )

    def _failed_result(
        self,
        request: MemoSightRequest,
        *,
        error: str,
        profile: MemoSightProfile | None = None,
        issues: list[MemoSightValidationIssue] | None = None,
        raw_output: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> MemoSightResult:
        issues = list(issues or [])
        return MemoSightResult(
            status="failed",
            observation={},
            raw_output=raw_output,
            schema_name=profile.schema_name if profile else request.profile or None,
            schema_version=profile.schema_version if profile else "1.0.0",
            model_name=self._backend.name,
            model_version=self._backend.version,
            validation=MemoSightValidationResult(
                checked=1 if issues else 0, valid=0, issues=issues
            ),
            usage=usage or {},
            error=error,
        )

    # ── Prompt helpers ──

    @staticmethod
    def _combined_instructions(request: MemoSightRequest) -> str | None:
        """Fold ``domain_hint`` into the prompt instructions."""
        hint = request.domain_hint.strip() if request.domain_hint else ""
        instructions = (request.output_instructions or "").strip()
        if hint:
            language = "en" if request.language == "en" else "zh"
            hint_line = (
                f"Domain hint: {hint}"
                if language == "en"
                else f"画面领域提示：{hint}"
            )
            return f"{hint_line}\n{instructions}" if instructions else hint_line
        return instructions or None

    @staticmethod
    def _build_repair_prompt(
        base_prompt: MemoSightPrompt,
        *,
        raw_output: str | None,
        issues: list[MemoSightValidationIssue],
    ) -> MemoSightPrompt:
        """Append validation issues and the failing output to the prompt."""
        if base_prompt.language == "en":
            header = (
                "Your previous output failed validation. Fix the issues below and "
                "output exactly one JSON object matching the field definitions. "
                "No Markdown fences, no explanations."
            )
            issues_label = "Issues found:"
            previous_label = "Your previous output:"
        else:
            header = (
                "上一次输出未通过校验。请修正下面的问题，只输出一个符合字段定义的 "
                "JSON 对象，不要使用 Markdown 代码块，不要输出解释。"
            )
            issues_label = "发现的问题："
            previous_label = "上一次输出："

        issue_lines = "\n".join(
            f"- {issue.message}" for issue in issues[:_MAX_REPAIR_ISSUES_SHOWN]
        )
        previous = (raw_output or "")[:_MAX_REPAIR_RAW_OUTPUT_CHARS]
        text = (
            f"{base_prompt.text}\n\n{header}\n{issues_label}\n{issue_lines}\n"
            f"{previous_label}\n{previous}"
        )
        return MemoSightPrompt(
            text=text,
            language=base_prompt.language,
            system=base_prompt.system,
            schema_name=base_prompt.schema_name,
        )
