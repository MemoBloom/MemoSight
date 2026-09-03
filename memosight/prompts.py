"""Prompt construction for MemoSight.

Owns the default zh/en prompts for the ``photography_default`` contract and
schema-driven prompt generation for any profile or custom output schema.
Model output is treated as untrusted downstream, so prompts demand strict
JSON and visible-facts-only content.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .prompt_config import (
    PromptConfigInput,
    language_prompt_config,
    load_prompt_config,
    prompt_config_section,
    prompt_config_text,
)
from .profiles import MAX_ARRAY_ITEMS, MemoSightProfile

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


def build_caption_prompt(
    *,
    language: str = "zh",
    prompt_config: PromptConfigInput = None,
) -> MemoSightPrompt:
    """Build stage-one prompt: image to one natural-language caption."""
    lang = "zh" if language == "zh" else "en"
    lang_config = language_prompt_config(load_prompt_config(prompt_config), lang)
    stage_config = prompt_config_section(lang_config, "caption_stage")
    system = prompt_config_text(stage_config, "system", section="caption_stage")
    text = prompt_config_text(stage_config, "text", section="caption_stage")
    max_tokens = stage_config.get("max_tokens")
    return MemoSightPrompt(
        text=text,
        language=lang,
        system=system,
        schema_name="photography_caption",
        max_tokens=max_tokens if isinstance(max_tokens, int) else None,
    )


def build_caption_field_extraction_prompt(
    caption: str,
    *,
    language: str = "zh",
    output_instructions: str | None = None,
    prompt_config: PromptConfigInput = None,
) -> MemoSightPrompt:
    """Build stage-two prompt: caption to the fixed seven Markdown fields."""
    lang = "zh" if language == "zh" else "en"
    lang_config = language_prompt_config(load_prompt_config(prompt_config), lang)
    labels = prompt_config_section(lang_config, "labels")
    stage_config = prompt_config_section(lang_config, "markdown_field_stage")
    system = prompt_config_text(
        stage_config,
        "system",
        section="markdown_field_stage",
    )
    template = prompt_config_text(
        stage_config,
        "template",
        section="markdown_field_stage",
    )
    max_tokens = stage_config.get("max_tokens")
    caption_label = prompt_config_text(labels, "caption_label", section="labels")
    parts = [f"{caption_label}\n{caption.strip()}"]
    if output_instructions and output_instructions.strip():
        parts.append(output_instructions.strip())
    parts.append(template)
    text = "\n\n".join(parts)
    return MemoSightPrompt(
        text=text,
        language=lang,
        system=system,
        schema_name="caption_fields_markdown",
        max_tokens=max_tokens if isinstance(max_tokens, int) else None,
    )


def build_caption_structured_extraction_prompt(
    caption: str,
    profile: MemoSightProfile,
    *,
    language: str = "zh",
    output_instructions: str | None = None,
    prompt_plan: Any | None = None,
    prompt_config: PromptConfigInput = None,
) -> MemoSightPrompt:
    """Render a caption-to-JSON prompt from ``profile``'s output schema."""
    lang = "zh" if language == "zh" else "en"
    lang_config = language_prompt_config(load_prompt_config(prompt_config), lang)
    labels = prompt_config_section(lang_config, "labels")
    stage_config = prompt_config_section(lang_config, "caption_json_stage")
    system = prompt_config_text(
        stage_config,
        "system",
        section="caption_json_stage",
    )
    max_tokens = stage_config.get("max_tokens")

    schema = profile.output_schema
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    caption_label = prompt_config_text(labels, "caption_label", section="labels")

    lines = [
        f"{caption_label}\n{caption.strip()}",
        "",
        prompt_config_text(
            labels,
            "caption_json_fields_header",
            section="labels",
        ),
    ]
    for name, spec in properties.items():
        lines.extend(
            _render_field_lines(
                name,
                spec,
                required=name in required,
                language=lang,
                labels=labels,
            )
        )
    lines.append("")
    lines.append(_render_example_object_compact(properties, language=lang, labels=labels))
    lines.append("")
    lines.extend(
        _render_prompt_plan_lines(
            prompt_plan,
            properties,
            language=lang,
            labels=labels,
        )
    )

    instructions = profile.instructions_for(lang)
    if instructions:
        lines.append(instructions)
    if output_instructions:
        lines.append(output_instructions.strip())
    lines.append("")
    lines.append(
        prompt_config_text(
            stage_config,
            "rules",
            section="caption_json_stage",
        )
    )

    return MemoSightPrompt(
        text="\n".join(lines),
        language=lang,
        system=system,
        schema_name=f"{profile.schema_name}_caption_json",
        max_tokens=max_tokens if isinstance(max_tokens, int) else None,
    )


def build_prompt(
    profile: MemoSightProfile,
    *,
    language: str = "zh",
    output_instructions: str | None = None,
    prompt_plan: Any | None = None,
    prompt_config: PromptConfigInput = None,
) -> MemoSightPrompt:
    """Render a strict-JSON prompt from ``profile``'s output schema.

    Field names, descriptions, types, enums, and max item counts all come
    from the profile schema, so custom schemas produce matching prompts.
    """
    lang = "zh" if language == "zh" else "en"
    lang_config = language_prompt_config(load_prompt_config(prompt_config), lang)
    labels = prompt_config_section(lang_config, "labels")
    one_stage = prompt_config_section(lang_config, "one_stage")
    system = prompt_config_text(one_stage, "system", section="one_stage")

    schema = profile.output_schema
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    lines = [
        system,
        "",
        prompt_config_text(labels, "fields_header", section="labels"),
    ]
    for name, spec in properties.items():
        lines.extend(
            _render_field_lines(
                name,
                spec,
                required=name in required,
                language=lang,
                labels=labels,
            )
        )
    lines.append("")
    lines.append(_render_example_object(properties, language=lang, labels=labels))
    lines.append("")
    lines.extend(
        _render_prompt_plan_lines(
            prompt_plan,
            properties,
            language=lang,
            labels=labels,
        )
    )

    instructions = profile.instructions_for(lang)
    if instructions:
        lines.append(instructions)
    if output_instructions:
        lines.append(output_instructions.strip())
    lines.append("")
    lines.append(prompt_config_text(one_stage, "rules", section="one_stage"))

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
    labels: dict[str, Any],
    indent: int = 0,
) -> list[str]:
    lines = [
        "  " * indent
        + _render_field_line(
            name,
            spec,
            required=required,
            language=language,
            labels=labels,
        )
    ]
    if spec.get("type") == "object":
        nested_required = set(spec.get("required", []))
        for child_name, child_spec in spec.get("properties", {}).items():
            lines.extend(
                _render_field_lines(
                    child_name,
                    child_spec,
                    required=child_name in nested_required,
                    language=language,
                    labels=labels,
                    indent=indent + 1,
                )
            )
    return lines


def _render_prompt_plan_lines(
    prompt_plan: Any | None,
    properties: dict[str, Any],
    *,
    language: str,
    labels: dict[str, Any] | None = None,
) -> list[str]:
    if prompt_plan is None:
        return []

    def get_value(name: str, default: Any) -> Any:
        if isinstance(prompt_plan, dict):
            return prompt_plan.get(name, default)
        return getattr(prompt_plan, name, default)

    task_summary = str(get_value("task_summary", "") or "").strip()
    field_guidance = get_value("field_guidance", {}) or {}
    negative_rules = get_value("negative_rules", []) or []
    output_rules = get_value("output_rules", []) or []
    final_prompt = str(get_value("final_prompt", "") or "").strip()

    lines: list[str] = []
    if task_summary:
        lines.append(_label(labels, "task", language=language))
        lines.append(task_summary)
        lines.append("")
    if isinstance(field_guidance, dict):
        lines.append(_label(labels, "field_guidance", language=language))
        for name in properties:
            guidance = str(field_guidance.get(name, "") or "").strip()
            if guidance:
                lines.append(f'- "{name}": {guidance}')
        lines.append("")
    if negative_rules:
        lines.append(_label(labels, "avoid", language=language))
        for rule in negative_rules:
            text = str(rule).strip()
            if text:
                lines.append(f"- {text}")
        lines.append("")
    if output_rules:
        lines.append(_label(labels, "additional_output_rules", language=language))
        for rule in output_rules:
            text = str(rule).strip()
            if text:
                lines.append(f"- {text}")
        lines.append("")
    if final_prompt:
        lines.append(_label(labels, "task_guidance", language=language))
        lines.append(final_prompt)
        lines.append("")
    return lines


def _render_field_line(
    name: str,
    spec: dict[str, Any],
    *,
    required: bool,
    language: str,
    labels: dict[str, Any],
) -> str:
    field_type = spec.get("type", "string")
    if field_type == "array":
        item_type = (spec.get("items") or {}).get("type", "string")
        type_label = f"array<{item_type}>"
    else:
        type_label = str(field_type)

    annotations = [type_label]
    if required:
        annotations.append(_label(labels, "required", language=language))
    if field_type == "array":
        max_items = spec.get("maxItems", MAX_ARRAY_ITEMS)
        annotations.append(
            _label(labels, "max_items", language=language).format(n=max_items)
        )

    description = spec.get("description_en") if language == "en" else None
    description = description or spec.get("description") or ""

    line = f'- "{name}" ({", ".join(annotations)})'
    if description:
        line += f": {description}"
    enum = spec.get("enum")
    if enum:
        choices = "/".join(str(choice) for choice in enum)
        line += f" {_label(labels, 'enum', language=language)}{choices}"
    return line


def _render_example_object(
    properties: dict[str, Any],
    *,
    language: str,
    labels: dict[str, Any],
) -> str:
    label = _label(labels, "example_shape", language=language)
    body = _render_example_entries(properties, indent=1)
    return f"{label}\n{{\n{body}\n}}"


def _render_example_object_compact(
    properties: dict[str, Any],
    *,
    language: str,
    labels: dict[str, Any],
) -> str:
    """Render the example as single-line compact JSON for small text models.

    Two-stage caption extraction runs on a tight token budget; a pretty-printed
    example teaches the model to burn tokens on indentation and newlines.
    """
    label = _label(labels, "example_shape", language=language)
    body = ", ".join(
        f'"{name}": {_compact_placeholder_for(spec)}'
        for name, spec in properties.items()
    )
    return f"{label}\n{{{body}}}"


def _compact_placeholder_for(spec: dict[str, Any]) -> str:
    if spec.get("type") == "object":
        inner = ", ".join(
            f'"{name}": {_compact_placeholder_for(child)}'
            for name, child in spec.get("properties", {}).items()
        )
        return "{" + inner + "}"
    return _placeholder_for(spec)


def _label(labels: dict[str, Any] | None, key: str, *, language: str) -> str:
    fallback = {
        ("zh", "required"): "必填",
        ("en", "required"): "required",
        ("zh", "max_items"): "最多 {n} 项",
        ("en", "max_items"): "max {n} items",
        ("zh", "enum"): "可选值：",
        ("en", "enum"): "one of: ",
        ("zh", "example_shape"): "示例结构：",
        ("en", "example_shape"): "Example shape:",
        ("zh", "task"): "抽取任务：",
        ("en", "task"): "Extraction task:",
        ("zh", "field_guidance"): "字段判断策略：",
        ("en", "field_guidance"): "Field guidance:",
        ("zh", "avoid"): "不要这样做：",
        ("en", "avoid"): "Avoid:",
        ("zh", "additional_output_rules"): "补充输出规则：",
        ("en", "additional_output_rules"): "Additional output rules:",
        ("zh", "task_guidance"): "任务说明：",
        ("en", "task_guidance"): "Task guidance:",
    }
    value = labels.get(key) if isinstance(labels, dict) else None
    return str(value) if isinstance(value, str) and value else fallback[(language, key)]


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
