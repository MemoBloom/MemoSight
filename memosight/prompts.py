"""Prompt construction for MemoSight.

Owns the default zh/en prompts for the ``photography_default`` contract and
schema-driven prompt generation for any profile or custom output schema.
Model output is treated as untrusted downstream, so prompts demand strict
JSON and visible-facts-only content.
"""
from __future__ import annotations

from typing import Any, Literal

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
    max_tokens: int | None = None


_CAPTION_SYSTEM_PROMPT_ZH = "只描述图片中可见内容，不猜测身份或不可见信息。"
_CAPTION_USER_TEXT_ZH = (
    "只用一句完整中文短句（50–80字）描述照片，尽量包含主要场景、人物与动作、"
    "重要物体、光线和氛围。只输出这句话。"
)
_CAPTION_USER_TEXT_ZH_V2 = (
    "用一段80–120字中文高密度描述照片。依次写清主要场景；人物数量、外观/服装和动作；"
    "重要物体、背景与清晰可见文字；光线和明确氛围。优先具体名词、颜色、数量和位置，"
    "避免空泛修饰与重复。只输出caption。"
)
_CAPTION_USER_TEXT_ZH_V3 = (
    "只输出90–110字的单段自然语言caption，不要字段标题、列表或换行。优先写主体数量、"
    "外观服装与动作，再写场景背景、关键物体或清晰文字，最后写光线和明确氛围。"
    "只保留可见、可搜索的具体事实，不重复。"
)
_CAPTION_SYSTEM_PROMPT_EN = (
    "Describe only visible image content. Do not guess identities or unseen facts."
)
_CAPTION_USER_TEXT_EN = (
    "Write one natural-language photo caption in at most 100 words, covering the "
    "main scene, people cues, actions, important objects, lighting, and mood. "
    "Output only the caption."
)
_CAPTION_USER_TEXT_EN_V2 = (
    "Write one dense 100–150 word photo caption. Cover the main scene; people "
    "count, appearance, clothing, and actions; important objects, background, and "
    "clearly readable text; lighting and explicit mood. Prefer concrete nouns, "
    "colors, counts, and positions. Avoid vague modifiers and repetition. Output "
    "only the caption."
)
_CAPTION_USER_TEXT_EN_V3 = (
    "Output only one natural-language caption of 100–130 words, with no field "
    "headings, lists, or line breaks. Prioritize subject count, appearance, "
    "clothing, and actions; then scene, background, key objects or readable text; "
    "finally lighting and explicit mood. Keep only visible, searchable concrete "
    "facts and do not repeat them."
)

_FIELD_EXTRACTION_SYSTEM_PROMPT_ZH_V1 = (
    "你是照片检索字段抽取器。只使用 caption 明确写出的事实，不猜测或补充。"
)
_FIELD_EXTRACTION_TEMPLATE_ZH_V1 = """将上面的 caption 转成固定 7 行 Markdown。字段含义：场景标签、人物线索、动作状态、物体环境、光线、氛围、去重检索词。字段值用 1–8 字短语，逗号分隔，每行最多 6 项；无内容写 none。不要复述 caption，只输出：
**scene_labels:** ...
**people:** ...
**actions:** ...
**objects:** ...
**lighting:** ...
**mood:** ...
**search_tags:** ..."""

_FIELD_EXTRACTION_SYSTEM_PROMPT_ZH_V2 = (
    "从 caption 抽取照片检索字段。只使用原文明确事实，不猜测、补充或改写。"
)
_FIELD_EXTRACTION_TEMPLATE_ZH_V2 = """完整抽取上面 caption 中的具体信息，不要只写概括词。
字段重点：scene_labels=场景类型/室内外/活动；people=人物数量/角色/服装/位置；actions=动作/状态；objects=重要物体/背景元素/清晰文字；lighting=光源/明暗/色调；mood=明确氛围；search_tags=前述高价值检索词。
每项用 2–12 字短语，逗号分隔；有明确信息时每行尽量 2–6 项，确实没有才写 none。只输出固定 7 行 Markdown：
**scene_labels:** ...
**people:** ...
**actions:** ...
**objects:** ...
**lighting:** ...
**mood:** ...
**search_tags:** ..."""

_FIELD_EXTRACTION_SYSTEM_PROMPT_ZH_V3 = (
    "从 caption 原文提取照片检索事实。不得猜测、补充、同义改写或改变字段归属。"
)
_FIELD_EXTRACTION_TEMPLATE_ZH_V3 = """不要遗漏 caption 中明确出现的专有名词、可见文字、数量、颜色、服装、动作、物体和背景。
字段边界：scene_labels=场景类型/地点类别/活动；people=人物数量/角色/服装/位置姿态；actions=明确动作或状态；objects=物体/道具/背景元素/清晰文字；lighting=明确光线/明暗/色调；mood=caption 明确写出的氛围；search_tags=从以上字段选择 4–6 个最具体的去重词。
同一事实只放最匹配字段；caption 未说明室内外时不要推断。每项用 2–12 字短语，逗号分隔，每行最多 6 项；确实没有才写 none。只输出固定 7 行 Markdown：
**scene_labels:** ...
**people:** ...
**actions:** ...
**objects:** ...
**lighting:** ...
**mood:** ...
**search_tags:** ..."""

_FIELD_EXTRACTION_SYSTEM_PROMPT_ZH_V4 = (
    "严格抽取 caption 中的原有事实，不推断。必须只输出指定的 7 行 Markdown。"
)
_FIELD_EXTRACTION_TEMPLATE_ZH_V4 = """逐项保留 caption 中的具体词，不要只写概括：scene_labels=场景/地点/活动；people=人物数量/角色/服装；actions=动作/状态；objects=物体/背景/可见文字；lighting=明确光线/色调；mood=明确氛围；search_tags=选 4–6 个最具体词。
同一事实只放最匹配字段；每项 2–12 字，逗号分隔，每行最多 6 项，无则 none。只输出：
**scene_labels:** ...
**people:** ...
**actions:** ...
**objects:** ...
**lighting:** ...
**mood:** ...
**search_tags:** ..."""

_FIELD_EXTRACTION_SYSTEM_PROMPT_ZH_V5 = (
    "你是照片检索字段抽取器。每一项都必须能在 caption 原文中找到对应表述，"
    "找不到就不写；禁止推断、补充或引入新词。"
)
_FIELD_EXTRACTION_TEMPLATE_ZH_V5 = """将上面的 caption 转成固定 7 行 Markdown。每一项都必须能在 caption 原文中找到对应表述，找不到就不写，禁止推断或补充：actions 只写 caption 明确写出的动作，不要补充"站立"等通用动作；mood 只写 caption 明确写出的氛围词，没写就写 none，不要根据场景推断；光线词放 lighting，不是物体；search_tags 从其他字段选 3–6 个最具体词，不引入新词。字段值用 1–8 字中文短语，逗号分隔，每行最多 6 项；无内容写 none。不要复述 caption，只输出：
**scene_labels:** ...
**people:** ...
**actions:** ...
**objects:** ...
**lighting:** ...
**mood:** ...
**search_tags:** ..."""

_FIELD_EXTRACTION_SYSTEM_PROMPT_EN_V1 = (
    "You extract photo retrieval fields. Use only facts explicit in the caption; "
    "do not guess or add facts."
)
_FIELD_EXTRACTION_TEMPLATE_EN_V1 = """Convert the caption above into exactly 7 Markdown lines. Use short comma-separated phrases, at most 6 per line; write none when empty. Do not repeat the caption. Output only these lines:
**scene_labels:** ...
**people:** ...
**actions:** ...
**objects:** ...
**lighting:** ...
**mood:** ...
**search_tags:** ..."""

_FIELD_EXTRACTION_SYSTEM_PROMPT_EN_V2 = (
    "Extract photo retrieval fields from the caption. Use only explicit facts; "
    "do not guess, add, or rewrite facts."
)
_FIELD_EXTRACTION_TEMPLATE_EN_V2 = """Extract all concrete information from the caption instead of broad summaries.
Field focus: scene_labels=scene type/indoor-outdoor/activity; people=count/role/clothing/position; actions=actions/states; objects=important objects/background/readable text; lighting=source/brightness/color; mood=explicit mood; search_tags=high-value terms above.
Use 2–12 character/word phrases separated by commas. When facts exist, aim for 2–6 items per line; write none only when truly empty. Output exactly 7 Markdown lines:
**scene_labels:** ...
**people:** ...
**actions:** ...
**objects:** ...
**lighting:** ...
**mood:** ...
**search_tags:** ..."""

_FIELD_EXTRACTION_SYSTEM_PROMPT_EN_V3 = (
    "Extract photo retrieval facts directly from the caption. Do not guess, add, "
    "paraphrase, or move facts into the wrong field."
)
_FIELD_EXTRACTION_TEMPLATE_EN_V3 = """Do not omit explicit proper names, readable text, counts, colors, clothing, actions, objects, or background details.
Field boundaries: scene_labels=scene type/place category/activity; people=count/role/clothing/position or pose; actions=explicit actions/states; objects=objects/props/background/readable text; lighting=explicit light/brightness/color tone; mood=explicit mood; search_tags=4–6 most specific deduplicated terms from those fields.
Put each fact in only its best field. Do not infer indoor/outdoor when the caption does not say so. Use short 2–12 character/word phrases separated by commas, at most 6 per line; write none only when truly empty. Output exactly 7 Markdown lines:
**scene_labels:** ...
**people:** ...
**actions:** ...
**objects:** ...
**lighting:** ...
**mood:** ...
**search_tags:** ..."""

_FIELD_EXTRACTION_SYSTEM_PROMPT_EN_V4 = (
    "Strictly extract existing caption facts without inference. Output only the "
    "specified 7 Markdown lines."
)
_FIELD_EXTRACTION_TEMPLATE_EN_V4 = """Keep each concrete caption term instead of broad summaries: scene_labels=scene/place/activity; people=count/role/clothing; actions=actions/states; objects=objects/background/readable text; lighting=explicit light/color tone; mood=explicit mood; search_tags=4–6 most specific terms.
Put each fact only in its best field. Use short 2–12 character/word phrases separated by commas, at most 6 per line; write none when empty. Output only:
**scene_labels:** ...
**people:** ...
**actions:** ...
**objects:** ...
**lighting:** ...
**mood:** ...
**search_tags:** ..."""

_FIELD_EXTRACTION_SYSTEM_PROMPT_EN_V5 = (
    "You extract photo retrieval fields. Every item must trace back to a phrase "
    "explicitly written in the caption; if it cannot, omit it. Do not infer, "
    "add, or introduce new terms."
)
_FIELD_EXTRACTION_TEMPLATE_EN_V5 = """Convert the caption above into exactly 7 Markdown lines. Every item must trace back to a phrase explicitly written in the caption; if it cannot, omit it — no inference or additions: actions only includes actions the caption explicitly states, do not add generic ones like "standing"; mood only includes mood words the caption explicitly states, write none when it states none, never infer mood from the scene; light words belong to lighting, they are not objects; search_tags picks 3–6 of the most specific terms from the other fields, no new terms. Use short comma-separated phrases, at most 6 per line; write none when empty. Do not repeat the caption. Output only:
**scene_labels:** ...
**people:** ...
**actions:** ...
**objects:** ...
**lighting:** ...
**mood:** ...
**search_tags:** ..."""


def build_caption_prompt(
    *,
    language: str = "zh",
    version: Literal["v1", "v2", "v3"] = "v1",
) -> MemoSightPrompt:
    """Build stage-one prompt: image to one natural-language caption."""
    lang = "zh" if language == "zh" else "en"
    system = (
        _CAPTION_SYSTEM_PROMPT_ZH if lang == "zh" else _CAPTION_SYSTEM_PROMPT_EN
    )
    if version not in ("v1", "v2", "v3"):
        raise ValueError(f"Unsupported caption prompt version: {version}")
    user_texts = {
        ("zh", "v1"): _CAPTION_USER_TEXT_ZH,
        ("zh", "v2"): _CAPTION_USER_TEXT_ZH_V2,
        ("zh", "v3"): _CAPTION_USER_TEXT_ZH_V3,
        ("en", "v1"): _CAPTION_USER_TEXT_EN,
        ("en", "v2"): _CAPTION_USER_TEXT_EN_V2,
        ("en", "v3"): _CAPTION_USER_TEXT_EN_V3,
    }
    max_tokens = {"v1": 96, "v2": 160, "v3": 128}[version]
    return MemoSightPrompt(
        text=user_texts[(lang, version)],
        language=lang,
        system=system,
        schema_name=f"photography_caption_{version}",
        max_tokens=max_tokens,
    )


def build_caption_field_extraction_prompt(
    caption: str,
    *,
    language: str = "zh",
    output_instructions: str | None = None,
    version: Literal["v1", "v2", "v3", "v4", "v5"] = "v1",
) -> MemoSightPrompt:
    """Build stage-two prompt: caption to the fixed seven Markdown fields."""
    lang = "zh" if language == "zh" else "en"
    prompt_versions = {
        ("zh", "v1"): (
            _FIELD_EXTRACTION_SYSTEM_PROMPT_ZH_V1,
            _FIELD_EXTRACTION_TEMPLATE_ZH_V1,
            192,
        ),
        ("zh", "v2"): (
            _FIELD_EXTRACTION_SYSTEM_PROMPT_ZH_V2,
            _FIELD_EXTRACTION_TEMPLATE_ZH_V2,
            256,
        ),
        ("zh", "v3"): (
            _FIELD_EXTRACTION_SYSTEM_PROMPT_ZH_V3,
            _FIELD_EXTRACTION_TEMPLATE_ZH_V3,
            224,
        ),
        ("zh", "v4"): (
            _FIELD_EXTRACTION_SYSTEM_PROMPT_ZH_V4,
            _FIELD_EXTRACTION_TEMPLATE_ZH_V4,
            192,
        ),
        ("zh", "v5"): (
            _FIELD_EXTRACTION_SYSTEM_PROMPT_ZH_V5,
            _FIELD_EXTRACTION_TEMPLATE_ZH_V5,
            192,
        ),
        ("en", "v1"): (
            _FIELD_EXTRACTION_SYSTEM_PROMPT_EN_V1,
            _FIELD_EXTRACTION_TEMPLATE_EN_V1,
            192,
        ),
        ("en", "v2"): (
            _FIELD_EXTRACTION_SYSTEM_PROMPT_EN_V2,
            _FIELD_EXTRACTION_TEMPLATE_EN_V2,
            256,
        ),
        ("en", "v3"): (
            _FIELD_EXTRACTION_SYSTEM_PROMPT_EN_V3,
            _FIELD_EXTRACTION_TEMPLATE_EN_V3,
            224,
        ),
        ("en", "v4"): (
            _FIELD_EXTRACTION_SYSTEM_PROMPT_EN_V4,
            _FIELD_EXTRACTION_TEMPLATE_EN_V4,
            192,
        ),
        ("en", "v5"): (
            _FIELD_EXTRACTION_SYSTEM_PROMPT_EN_V5,
            _FIELD_EXTRACTION_TEMPLATE_EN_V5,
            192,
        ),
    }
    if version not in ("v1", "v2", "v3", "v4", "v5"):
        raise ValueError(f"Unsupported field extraction prompt version: {version}")
    system, template, max_tokens = prompt_versions[(lang, version)]
    caption_label = "caption：" if lang == "zh" else "caption:"
    parts = [f"{caption_label}\n{caption.strip()}"]
    if output_instructions and output_instructions.strip():
        parts.append(output_instructions.strip())
    parts.append(template)
    text = "\n\n".join(parts)
    return MemoSightPrompt(
        text=text,
        language=lang,
        system=system,
        schema_name=f"caption_fields_markdown_{version}",
        max_tokens=max_tokens,
    )


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
