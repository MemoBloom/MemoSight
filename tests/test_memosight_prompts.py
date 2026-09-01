"""Tests for memosight.prompts — default zh/en prompts and schema-driven builds."""
from __future__ import annotations

import pytest

from memosight.profiles import get_profile, resolve_profile
from memosight.prompts import (
    MemoSightPrompt,
    build_caption_field_extraction_prompt,
    build_prompt,
)

DEFAULT_FIELDS = (
    "caption",
    "scene_labels",
    "people",
    "actions",
    "objects",
    "lighting",
    "mood",
    "search_tags",
)

CUSTOM_SCHEMA = {
    "type": "object",
    "properties": {
        "product_type": {
            "type": "string",
            "description": "Visible product category.",
        },
        "brand_visible": {
            "type": "boolean",
            "description": "Whether a brand logo or brand name is visible.",
        },
        "mood": {
            "type": "string",
            "enum": ["warm", "cool", "neutral"],
            "description": "Overall color mood.",
        },
        "dominant_colors": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
            "description": "Dominant visible colors.",
        },
    },
    "required": ["product_type", "brand_visible"],
}


def test_build_prompt_default_profile_zh_includes_all_fields_and_descriptions():
    prompt = build_prompt(get_profile("photography_default"), language="zh")

    assert isinstance(prompt, MemoSightPrompt)
    assert prompt.language == "zh"
    assert prompt.schema_name == "photography_default"
    for field in DEFAULT_FIELDS:
        assert f'"{field}"' in prompt.text
    # Chinese descriptions from the profile schema are rendered.
    assert "对照片可见内容的一句简洁自然语言描述" in prompt.text
    assert "便于检索的简短标签" in prompt.text
    # Strict JSON + ground rules.
    assert "JSON" in prompt.text
    assert "只描述可见内容" in prompt.text
    assert "不要推断" in prompt.text
    assert "最多 6 项" in prompt.text
    assert prompt.system and "MemoSight" in prompt.system


def test_build_prompt_default_profile_en_uses_english_wording():
    prompt = build_prompt(get_profile("photography_default"), language="en")

    assert prompt.language == "en"
    for field in DEFAULT_FIELDS:
        assert f'"{field}"' in prompt.text
    assert "One concise natural-language description" in prompt.text
    assert "Short retrieval-friendly tags" in prompt.text
    assert "Describe only what is visible" in prompt.text
    assert "max 6 items" in prompt.text


def test_build_prompt_custom_schema_respects_names_descriptions_enums():
    profile = resolve_profile(output_schema=CUSTOM_SCHEMA)
    prompt = build_prompt(profile, language="en")

    assert prompt.schema_name == "custom"
    assert '"product_type"' in prompt.text
    assert '"brand_visible"' in prompt.text
    assert '"dominant_colors"' in prompt.text
    assert "Visible product category." in prompt.text
    assert "Whether a brand logo or brand name is visible." in prompt.text
    # Enum choices are listed so the model picks only allowed values.
    assert "warm/cool/neutral" in prompt.text
    # maxItems and required annotations are rendered.
    assert "max 5 items" in prompt.text
    assert "required" in prompt.text
    # No fields beyond the custom schema.
    assert '"caption"' not in prompt.text


def test_build_prompt_appends_profile_and_caller_instructions():
    profile = resolve_profile(
        output_schema=CUSTOM_SCHEMA,
        instructions_zh="这是电商场景。",
    )
    prompt = build_prompt(profile, language="zh", output_instructions="请重点关注包装。")

    assert "这是电商场景。" in prompt.text
    assert "请重点关注包装。" in prompt.text


def test_named_profile_prompt_uses_its_own_schema_and_instructions():
    prompt = build_prompt(get_profile("wedding_selection"), language="zh")

    assert prompt.schema_name == "wedding_selection"
    assert '"moment_type"' in prompt.text
    assert '"selection_worthy"' in prompt.text
    assert "婚礼" in prompt.text
    assert '"scene_labels"' not in prompt.text


NESTED_SCHEMA = {
    "type": "object",
    "properties": {
        "product_type": {"type": "string", "description": "Visible product category."},
        "tags": {"type": "array", "items": {"type": "string"}},
        "dimensions": {
            "type": "object",
            "description": "Visible size cues.",
            "properties": {
                "width_cm": {"type": "number", "description": "Visible width in cm."},
                "unit_visible": {
                    "type": "boolean",
                    "description": "Whether a size unit label is visible.",
                },
            },
            "required": ["width_cm"],
        },
    },
    "required": ["product_type", "dimensions"],
}


def test_build_prompt_renders_nested_object_fields():
    profile = resolve_profile(output_schema=NESTED_SCHEMA)
    prompt = build_prompt(profile, language="en")

    # Nested field lines are rendered, indented, with their own
    # descriptions/types and the nested required marker.
    assert '"dimensions" (object, required)' in prompt.text
    assert '  - "width_cm" (number, required): Visible width in cm.' in prompt.text
    assert '  - "unit_visible" (boolean)' in prompt.text
    assert "Whether a size unit label is visible." in prompt.text

    # The example skeleton shows the nested shape, not an empty {}.
    assert '"dimensions": {\n    "width_cm": 0,\n    "unit_visible": true\n  }' in prompt.text

    # Array fields without maxItems show the effective default cap of 20.
    assert '"tags" (array<string>, max 20 items)' in prompt.text


def test_build_prompt_nested_object_zh():
    profile = resolve_profile(output_schema=NESTED_SCHEMA)
    prompt = build_prompt(profile, language="zh")

    assert '"dimensions" (object, 必填)' in prompt.text
    assert '"width_cm" (number, 必填)' in prompt.text
    assert "最多 20 项" in prompt.text


def test_field_extraction_prompt_v2_increases_coverage_budget():
    prompt = build_caption_field_extraction_prompt(
        "一人在暖光舞台上挥手。", version="v2"
    )

    assert prompt.schema_name == "caption_fields_markdown_v2"
    assert prompt.max_tokens == 256
    assert "每行尽量 2–6 项" in prompt.text
    assert "重要物体/背景元素/清晰文字" in prompt.text
    assert prompt.text.endswith("**search_tags:** ...")


def test_caption_prompt_v2_targets_dense_longer_output():
    from memosight.prompts import build_caption_prompt

    baseline = build_caption_prompt(language="zh")
    candidate = build_caption_prompt(language="zh", version="v2")

    assert baseline.schema_name == "photography_caption_v1"
    assert baseline.max_tokens == 96
    assert candidate.schema_name == "photography_caption_v2"
    assert candidate.max_tokens == 160
    assert "80–120字" in candidate.text
    assert "可见文字" in candidate.text
    assert "避免空泛修饰与重复" in candidate.text


def test_caption_prompt_rejects_unknown_version():
    from memosight.prompts import build_caption_prompt

    with pytest.raises(ValueError, match="Unsupported caption"):
        build_caption_prompt(version="v4")


def test_caption_prompt_v3_is_bounded_natural_language():
    from memosight.prompts import build_caption_prompt

    prompt = build_caption_prompt(language="zh", version="v3")

    assert prompt.schema_name == "photography_caption_v3"
    assert prompt.max_tokens == 128
    assert "90–110字" in prompt.text
    assert "不要字段标题、列表或换行" in prompt.text
    assert "可搜索的具体事实" in prompt.text


def test_field_extraction_prompt_v1_remains_available_for_comparison():
    prompt = build_caption_field_extraction_prompt("一人在暖光舞台上挥手。")

    assert prompt.schema_name == "caption_fields_markdown_v1"
    assert prompt.max_tokens == 192
    assert "1–8 字短语" in prompt.text


def test_field_extraction_prompt_v3_preserves_detail_and_field_boundaries():
    prompt = build_caption_field_extraction_prompt(
        "一人在暖光舞台上挥手。", version="v3"
    )

    assert prompt.schema_name == "caption_fields_markdown_v3"
    assert prompt.max_tokens == 224
    assert "不要遗漏" in prompt.text
    assert "同一事实只放最匹配字段" in prompt.text
    assert "未说明室内外时不要推断" in prompt.text
    assert "4–6 个最具体的去重词" in prompt.text


def test_field_extraction_prompt_v4_is_short_and_keeps_original_budget():
    v1 = build_caption_field_extraction_prompt("caption", version="v1")
    v3 = build_caption_field_extraction_prompt("caption", version="v3")
    prompt = build_caption_field_extraction_prompt("caption", version="v4")

    assert prompt.schema_name == "caption_fields_markdown_v4"
    assert prompt.max_tokens == 192
    assert len(prompt.text) < len(v3.text)
    assert "逐项保留" in prompt.text
    assert "同一事实只放最匹配字段" in prompt.text
    assert len(prompt.text) > len(v1.text)


def test_field_extraction_prompt_v5_requires_caption_grounding():
    prompt = build_caption_field_extraction_prompt("caption", version="v5")

    assert prompt.schema_name == "caption_fields_markdown_v5"
    assert prompt.max_tokens == 192
    assert "caption 原文" in prompt.system or "caption" in prompt.system
    assert "不要补充" in prompt.text
    assert "光线词放 lighting" in prompt.text
    assert "不要根据场景推断" in prompt.text


def test_field_extraction_prompt_rejects_unknown_version():
    with pytest.raises(ValueError, match="Unsupported"):
        build_caption_field_extraction_prompt("caption", version="v6")
