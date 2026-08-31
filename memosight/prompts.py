"""Prompt construction for MemoSight.

Owns the default zh/en prompts for the ``photography_default`` contract and
schema-driven prompt generation for any profile or custom output schema.
Model output is treated as untrusted downstream, so prompts demand strict
JSON and visible-facts-only content.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .profiles import MAX_ARRAY_ITEMS, MemoSightProfile

# Shared ground rules, adapted from the MLX-VLM describe prompts but
# self-contained so MemoSight stays free of project imports.
_SYSTEM_PROMPT_ZH = (
    "你是 MemoSight 图像结构化描述助手。请仔细观察图片，只描述可见内容，"
    "不要编造细节，不要推断或猜测真实人物身份。"
)
_SYSTEM_PROMPT_EN = (
    "You are the MemoSight structured image description assistant. Examine "
    "the image carefully. Describe only what is visible. Do not invent "
    "details. Do not infer or guess real-world identities of people."
)

_RULES_ZH = (
    "输出要求：\n"
    "- 只输出一个 JSON 对象，不要使用 Markdown 代码块，不要输出任何解释。\n"
    "- 上面给出的字段名（含嵌套字段）必须全部出现，不要新增字段。\n"
    "- 多值字段使用字符串数组；没有内容时输出空数组，不要省略字段名，不要输出 \"unknown\"。\n"
    "- 字段值保持简洁，遵守每个字段的最大条目数限制。\n"
    "- 遇到枚举字段时，只能从给定的可选值中挑选。"
)
_RULES_EN = (
    "Output rules:\n"
    "- Output exactly one JSON object. No Markdown fences, no explanations.\n"
    "- Every field name above (including nested fields) must appear; do not add fields.\n"
    "- Use string arrays for multi-value fields; use empty arrays when there is "
    "nothing to report. Never omit keys, never write \"unknown\".\n"
    "- Keep field values concise and respect each field's maximum item count.\n"
    "- For enum fields, choose only from the listed choices."
)

_REQUIRED_LABEL = {"zh": "必填", "en": "required"}
_MAX_ITEMS_LABEL = {"zh": "最多 {n} 项", "en": "max {n} items"}
_ENUM_LABEL = {"zh": "可选值：", "en": "one of: "}
_FIELDS_HEADER = {
    "zh": "请输出一个严格的 JSON 对象，字段定义如下：",
    "en": "Output a strict JSON object with these fields:",
}

_TYPE_LABEL = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "object": "object",
}


class MemoSightPrompt(BaseModel):
    """A fully-rendered prompt handed to a backend.

    ``text`` is the complete prompt body (ground rules, field definitions,
    instructions). ``system`` carries the standalone ground-rules header for
    backends that support a separate system message. ``schema_name`` records
    which profile produced this prompt.
    """

    text: str
    language: str = "zh"
    system: str | None = None
    schema_name: str | None = None


def build_prompt(
    profile: MemoSightProfile,
    *,
    language: str = "zh",
    output_instructions: str | None = None,
) -> MemoSightPrompt:
    """Render a strict-JSON prompt from ``profile``'s output schema.

    Field names, descriptions, types, enums, and max item counts all come
    from the profile schema, so custom schemas produce matching prompts.
    """
    lang = "zh" if language == "zh" else "en"
    system = _SYSTEM_PROMPT_ZH if lang == "zh" else _SYSTEM_PROMPT_EN

    schema = profile.output_schema
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    lines = [system, "", _FIELDS_HEADER[lang]]
    for name, spec in properties.items():
        lines.extend(_render_field_lines(name, spec, required=name in required, language=lang))
    lines.append("")
    lines.append(_render_example_object(properties, language=lang))
    lines.append("")

    instructions = profile.instructions_for(lang)
    if instructions:
        lines.append(instructions)
    if output_instructions:
        lines.append(output_instructions.strip())
    lines.append("")
    lines.append(_RULES_ZH if lang == "zh" else _RULES_EN)

    return MemoSightPrompt(
        text="\n".join(lines),
        language=lang,
        system=system,
        schema_name=profile.schema_name,
    )


def _render_field_lines(
    name: str,
    spec: dict[str, Any],
    *,
    required: bool,
    language: str,
    indent: int = 0,
) -> list[str]:
    lines = ["  " * indent + _render_field_line(name, spec, required=required, language=language)]
    if spec.get("type") == "object":
        nested_required = set(spec.get("required", []))
        for child_name, child_spec in spec.get("properties", {}).items():
            lines.extend(
                _render_field_lines(
                    child_name,
                    child_spec,
                    required=child_name in nested_required,
                    language=language,
                    indent=indent + 1,
                )
            )
    return lines


def _render_field_line(
    name: str,
    spec: dict[str, Any],
    *,
    required: bool,
    language: str,
) -> str:
    field_type = spec.get("type", "string")
    if field_type == "array":
        item_type = (spec.get("items") or {}).get("type", "string")
        type_label = f"array<{item_type}>"
    else:
        type_label = _TYPE_LABEL.get(field_type, str(field_type))

    annotations = [type_label]
    if required:
        annotations.append(_REQUIRED_LABEL[language])
    if field_type == "array":
        max_items = spec.get("maxItems", MAX_ARRAY_ITEMS)
        annotations.append(_MAX_ITEMS_LABEL[language].format(n=max_items))

    description = spec.get("description_en") if language == "en" else None
    description = description or spec.get("description") or ""

    line = f'- "{name}" ({", ".join(annotations)})'
    if description:
        line += f": {description}"
    enum = spec.get("enum")
    if enum:
        choices = "/".join(str(choice) for choice in enum)
        line += f" {_ENUM_LABEL[language]}{choices}"
    return line


def _render_example_object(properties: dict[str, Any], *, language: str) -> str:
    label = "示例结构：" if language == "zh" else "Example shape:"
    body = _render_example_entries(properties, indent=1)
    return f"{label}\n{{\n{body}\n}}"


def _render_example_entries(properties: dict[str, Any], *, indent: int) -> str:
    pad = "  " * indent
    parts = [f'{pad}"{name}": {_placeholder_for(spec, indent=indent)}' for name, spec in properties.items()]
    return ",\n".join(parts)


def _placeholder_for(spec: dict[str, Any], *, indent: int = 0) -> str:
    field_type = spec.get("type", "string")
    if field_type == "array":
        return "[]"
    if field_type == "boolean":
        return "true"
    if field_type in ("number", "integer"):
        return "0"
    if field_type == "object":
        inner = _render_example_entries(spec.get("properties", {}), indent=indent + 1)
        return "{\n" + inner + "\n" + "  " * indent + "}"
    enum = spec.get("enum")
    if enum:
        return f'"{enum[0]}"'
    return '"..."'
