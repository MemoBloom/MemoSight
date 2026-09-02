"""Schema-to-prompt planning helpers.

This module keeps local-model prompt design on a short leash: an LLM may
propose field guidance, but MemoSight validates, sanitizes, and deterministically
assembles the final extraction prompt from the schema.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field

from .parser import parse_model_output
from .profiles import MAX_ARRAY_ITEMS, MemoSightProfile, validate_output_schema
from .prompts import MemoSightPrompt

if TYPE_CHECKING:
    from .backends import MemoSightTextBackend

_MAX_RULES = 5
_MAX_GUIDANCE_CHARS = 160
_MAX_SUMMARY_CHARS = 120
_MAX_FINAL_PROMPT_CHARS = 900
_BAD_RULE_PATTERNS = (
    re.compile(r"JSON\s*(数组|array)", re.IGNORECASE),
    re.compile(r"(十六进制|hex(?:adecimal)?)", re.IGNORECASE),
    re.compile(r"\bunknown\b|Unknown|UNKNOWN"),
    re.compile(r"不得留空|不能留空|must not be empty", re.IGNORECASE),
    re.compile(
        r"task_summary|field_guidance|negative_rules|output_rules|"
        r"final_prompt|\bguidance\b",
        re.IGNORECASE,
    ),
    re.compile(r"Prompt Designer|设计\s*prompt", re.IGNORECASE),
)
_META_PLAN_PATTERNS = (
    re.compile(
        r"Prompt Designer|设计\s*prompt|供下游|指导模型|task_summary|"
        r"field_guidance|negative_rules|output_rules|final_prompt",
        re.IGNORECASE,
    ),
)


class MemoSightPromptPlan(BaseModel):
    """LLM-designed guidance used to enrich schema-driven prompts."""

    task_summary: str
    field_guidance: dict[str, str] = Field(default_factory=dict)
    negative_rules: list[str] = Field(default_factory=list)
    output_rules: list[str] = Field(default_factory=list)
    final_prompt: str = ""
    schema_hash: str | None = None
    source: str = "heuristic"


def infer_output_schema_from_example(example: dict[str, Any]) -> dict[str, Any]:
    """Infer MemoSight's supported JSON-schema subset from one example object."""
    if not isinstance(example, dict) or not example:
        raise ValueError("example must be a non-empty JSON object")
    schema = {
        "type": "object",
        "properties": {
            name: _schema_for_value(value) for name, value in example.items()
        },
        "required": list(example),
    }
    validate_output_schema(schema)
    return schema


def build_prompt_plan_design_prompt(
    profile: MemoSightProfile,
    *,
    language: str = "zh",
    domain_hint: str | None = None,
    output_instructions: str | None = None,
    output_example: dict[str, Any] | None = None,
) -> MemoSightPrompt:
    """Build the prompt sent to a local model to draft ``MemoSightPromptPlan``."""
    lang = "zh" if language == "zh" else "en"
    properties = profile.output_schema.get("properties", {})
    fields = ", ".join(properties)
    schema_json = json.dumps(profile.output_schema, ensure_ascii=False, indent=2)
    hint = (domain_hint or profile.instructions_for(lang) or "").strip()
    instructions = (output_instructions or "").strip()
    example_json = (
        json.dumps(output_example, ensure_ascii=False, indent=2)
        if output_example
        else ""
    )
    shape = {
        "task_summary": "string",
        "field_guidance": {field: "string" for field in properties},
        "negative_rules": ["string"],
        "output_rules": ["string"],
        "final_prompt": "string",
    }
    shape_json = json.dumps(shape, ensure_ascii=False, indent=2)

    if lang == "zh":
        system = (
            "你是严谨的视觉结构化抽取 Prompt Designer。你只设计 prompt，"
            "不抽取图片内容。只输出有效 JSON 对象。"
        )
        text = (
            "请根据 JSON schema 反向设计一个 prompt_plan，供下游视觉或文本模型"
            "生成结构化 JSON 使用。\n\n"
            f"业务/领域提示：{hint or '未提供'}\n"
            f"额外要求：{instructions or '未提供'}\n"
            f"schema 字段：{fields}\n\n"
            f"期望输出样例（只用于理解字段语义，不要照抄具体值）：\n"
            f"{example_json or '未提供'}\n\n"
            "输出必须严格符合这个 JSON shape，field_guidance 必须覆盖每个 schema 字段：\n"
            f"{shape_json}\n\n"
            "限制：task_summary 不超过 60 字；每个 field_guidance 不超过 80 字；"
            "negative_rules 最多 5 条；output_rules 最多 5 条；final_prompt 不超过 450 字。"
            "不得要求输出 JSON 数组；不得发明 schema 未要求的格式约束；不得使用 unknown "
            "作为缺失值规则。\n\n"
            f"schema:\n{schema_json}"
        )
    else:
        system = (
            "You are a rigorous visual structured-extraction Prompt Designer. "
            "Design prompts only; do not extract image content. Output only a "
            "valid JSON object."
        )
        text = (
            "Design a prompt_plan from the JSON schema for a downstream vision or "
            "text model that must produce structured JSON.\n\n"
            f"Domain hint: {hint or 'not provided'}\n"
            f"Extra instructions: {instructions or 'not provided'}\n"
            f"Schema fields: {fields}\n\n"
            "Expected output example, for field semantics only; do not copy values:\n"
            f"{example_json or 'not provided'}\n\n"
            "The output must strictly match this JSON shape, and field_guidance "
            "must cover every schema field:\n"
            f"{shape_json}\n\n"
            "Limits: task_summary <= 60 words; each field_guidance <= 80 words; "
            "negative_rules <= 5 items; output_rules <= 5 items; final_prompt "
            "<= 450 words. Do not require a JSON array. Do not invent format "
            "constraints absent from the schema. Do not use unknown as the "
            "missing-value rule.\n\n"
            f"schema:\n{schema_json}"
        )
    return MemoSightPrompt(
        text=text,
        language=lang,
        system=system,
        schema_name=f"{profile.schema_name}_prompt_plan_request",
        max_tokens=900,
    )


async def design_prompt_plan(
    profile: MemoSightProfile,
    backend: "MemoSightTextBackend",
    *,
    language: str = "zh",
    domain_hint: str | None = None,
    output_instructions: str | None = None,
    output_example: dict[str, Any] | None = None,
) -> MemoSightPromptPlan:
    """Ask ``backend`` for a plan, then sanitize it against ``profile``."""
    prompt = build_prompt_plan_design_prompt(
        profile,
        language=language,
        domain_hint=domain_hint,
        output_instructions=output_instructions,
        output_example=output_example,
    )
    raw_output = await backend.complete(prompt)
    return prompt_plan_from_model_output(
        raw_output,
        profile,
        language=language,
        source=backend.name,
    )


def prompt_plan_from_model_output(
    raw_output: str,
    profile: MemoSightProfile,
    *,
    language: str = "zh",
    source: str = "model",
) -> MemoSightPromptPlan:
    """Parse and sanitize a model-generated prompt plan."""
    parsed = parse_model_output(raw_output)
    if parsed.data is None:
        return heuristic_prompt_plan(profile, language=language, source="heuristic")
    return sanitize_prompt_plan(parsed.data, profile, language=language, source=source)


def sanitize_prompt_plan(
    data: dict[str, Any],
    profile: MemoSightProfile,
    *,
    language: str = "zh",
    source: str = "model",
) -> MemoSightPromptPlan:
    """Coerce a raw plan into a schema-aligned, bounded ``MemoSightPromptPlan``."""
    lang = "zh" if language == "zh" else "en"
    properties = profile.output_schema.get("properties", {})
    guidance_raw = data.get("field_guidance", {})
    guidance = _coerce_guidance(guidance_raw, properties)
    for field, spec in properties.items():
        if not guidance.get(field):
            guidance[field] = _fallback_guidance(field, spec, language=lang)

    negative_rules = _clean_rules(data.get("negative_rules"), language=lang)
    output_rules = _clean_rules(data.get("output_rules"), language=lang)
    final_prompt = _clean_text(data.get("final_prompt", ""), _MAX_FINAL_PROMPT_CHARS)
    if not final_prompt or any(
        pattern.search(final_prompt) for pattern in _META_PLAN_PATTERNS
    ):
        final_prompt = _fallback_final_prompt(profile, guidance, language=lang)

    summary = _clean_text(data.get("task_summary", ""), _MAX_SUMMARY_CHARS)
    if not summary or any(pattern.search(summary) for pattern in _META_PLAN_PATTERNS):
        summary = _default_summary(profile, language=lang)

    return MemoSightPromptPlan(
        task_summary=summary,
        field_guidance=guidance,
        negative_rules=negative_rules,
        output_rules=output_rules,
        final_prompt=final_prompt,
        schema_hash=schema_hash(profile.output_schema),
        source=source,
    )


def heuristic_prompt_plan(
    profile: MemoSightProfile,
    *,
    language: str = "zh",
    source: str = "heuristic",
) -> MemoSightPromptPlan:
    """Build a deterministic fallback plan directly from schema metadata."""
    lang = "zh" if language == "zh" else "en"
    properties = profile.output_schema.get("properties", {})
    guidance = {
        field: _fallback_guidance(field, spec, language=lang)
        for field, spec in properties.items()
    }
    return MemoSightPromptPlan(
        task_summary=_default_summary(profile, language=lang),
        field_guidance=guidance,
        negative_rules=_default_negative_rules(language=lang),
        output_rules=_default_output_rules(language=lang),
        final_prompt=_fallback_final_prompt(profile, guidance, language=lang),
        schema_hash=schema_hash(profile.output_schema),
        source=source,
    )


def schema_hash(schema: dict[str, Any]) -> str:
    """Stable hash suitable for caching prompt plans per schema."""
    encoded = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _schema_for_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, list):
        item_type = "string"
        for item in value:
            item_type = _scalar_type_name(item)
            break
        return {
            "type": "array",
            "items": {"type": item_type},
            "maxItems": min(max(len(value), 1), MAX_ARRAY_ITEMS),
        }
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {
                name: _schema_for_value(child)
                for name, child in value.items()
            },
            "required": list(value),
        }
    return {"type": "string"}


def _scalar_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _coerce_guidance(raw: Any, properties: dict[str, Any]) -> dict[str, str]:
    if isinstance(raw, dict):
        return {
            field: _clean_text(raw.get(field, ""), _MAX_GUIDANCE_CHARS)
            for field in properties
        }
    if isinstance(raw, str):
        return {
            field: _clean_text(_extract_named_guidance(raw, field), _MAX_GUIDANCE_CHARS)
            for field in properties
        }
    return {}


def _extract_named_guidance(text: str, field: str) -> str:
    pattern = re.compile(
        rf"{re.escape(field)}\s*[:：]\s*(.*?)(?=(?:\b[a-zA-Z_][\w]*\s*[:：])|$)",
        flags=re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip(" 。；;\n") if match else ""


def _clean_rules(raw: Any, *, language: str) -> list[str]:
    items = raw if isinstance(raw, list) else [raw] if isinstance(raw, str) else []
    cleaned: list[str] = []
    for item in items:
        text = _clean_text(item, 140)
        if not text or any(pattern.search(text) for pattern in _BAD_RULE_PATTERNS):
            continue
        if text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= _MAX_RULES:
            break
    if cleaned:
        return cleaned
    return _default_negative_rules(language=language)


def _clean_text(value: Any, max_chars: int) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.strip().split())
    return text[:max_chars].rstrip()


def _fallback_guidance(field: str, spec: dict[str, Any], *, language: str) -> str:
    field_type = spec.get("type", "string")
    description = (
        spec.get("description_en") if language == "en" else spec.get("description")
    )
    description = description or spec.get("description") or field.replace("_", " ")
    enum = spec.get("enum")
    if language == "zh":
        if enum:
            return f"{description} 只能选择：{'/'.join(str(v) for v in enum)}。"
        if field_type == "array":
            max_items = spec.get("maxItems", MAX_ARRAY_ITEMS)
            return f"{description} 使用简短数组，最多 {max_items} 项。"
        if field_type == "boolean":
            return f"{description} 只在可见证据明确支持时为 true。"
        return str(description)
    if enum:
        return f"{description} Choose only: {'/'.join(str(v) for v in enum)}."
    if field_type == "array":
        max_items = spec.get("maxItems", MAX_ARRAY_ITEMS)
        return f"{description} Use a concise array, max {max_items} items."
    if field_type == "boolean":
        return f"{description} Use true only when visible evidence clearly supports it."
    return str(description)


def _default_summary(profile: MemoSightProfile, *, language: str) -> str:
    if language == "zh":
        if profile.schema_name == "custom":
            return "根据目标 JSON schema 进行可见事实结构化抽取。"
        return f"根据 {profile.schema_name} schema 进行可见事实结构化抽取。"
    name = "target JSON" if profile.schema_name == "custom" else profile.schema_name
    return f"Extract visible facts according to the {name} schema."


def _default_negative_rules(*, language: str) -> list[str]:
    if language == "zh":
        return [
            "不要推断图片中不可见的信息。",
            "不要添加 schema 中不存在的字段。",
            "不要把不确定内容写成确定事实。",
        ]
    return [
        "Do not infer information that is not visible.",
        "Do not add fields outside the schema.",
        "Do not turn uncertain content into certain facts.",
    ]


def _default_output_rules(*, language: str) -> list[str]:
    if language == "zh":
        return [
            "只输出一个 JSON 对象。",
            "字段名、嵌套结构和类型必须匹配 schema。",
            "数组字段遵守 maxItems 限制。",
        ]
    return [
        "Output exactly one JSON object.",
        "Field names, nesting, and types must match the schema.",
        "Array fields must respect maxItems.",
    ]


def _fallback_final_prompt(
    profile: MemoSightProfile,
    guidance: dict[str, str],
    *,
    language: str,
) -> str:
    if language == "zh":
        return (
            f"{_default_summary(profile, language=language)}\n"
            "结合字段判断策略抽取可见事实；不猜测身份、意图或不可见信息。"
        )
    return (
        f"{_default_summary(profile, language=language)}\n"
        "Use the field guidance to extract visible facts; do not guess identities, "
        "intent, or unseen details."
    )
