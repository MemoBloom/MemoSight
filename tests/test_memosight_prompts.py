"""Tests for memosight.prompts — default zh/en prompts and schema-driven builds."""
from __future__ import annotations

import pytest

from memosight.normalizer import CAPTION_FIELD_KEYS
from memosight.profiles import get_profile, resolve_profile
from memosight.prompt_designer import MemoSightPromptPlan
from memosight.prompts import (
    MemoSightPrompt,
    build_caption_field_extraction_prompt,
    build_caption_prompt,
    build_caption_structured_extraction_prompt,
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


def test_build_prompt_can_include_prompt_plan_guidance():
    profile = resolve_profile(output_schema=CUSTOM_SCHEMA)
    plan = MemoSightPromptPlan(
        task_summary="电商商品图编目",
        field_guidance={
            "product_type": "识别主体商品类别，不要用品牌名代替类别。",
            "brand_visible": "只有 logo 或品牌文字清晰可见时为 true。",
            "mood": "只描述可见色彩带来的整体倾向。",
            "dominant_colors": "优先产品本体主色，最多 5 项。",
        },
        negative_rules=["不要把包装盒当作商品本体。"],
        output_rules=["只输出一个 JSON 对象。"],
        final_prompt="围绕商品主体抽取可见事实。",
    )

    prompt = build_prompt(profile, language="zh", prompt_plan=plan)

    assert "字段判断策略" in prompt.text
    assert "识别主体商品类别" in prompt.text
    assert "不要把包装盒当作商品本体" in prompt.text
    assert "围绕商品主体抽取可见事实" in prompt.text


def test_build_prompt_accepts_config_override():
    config = {
        "zh": {
            "labels": {
                "fields_header": "自定义字段清单：",
                "required": "必须",
            },
            "one_stage": {
                "system": "自定义一段式系统提示。",
                "rules": "自定义一段式输出规则。",
            },
        }
    }

    prompt = build_prompt(
        resolve_profile(output_schema=CUSTOM_SCHEMA),
        language="zh",
        prompt_config=config,
    )

    assert prompt.system == "自定义一段式系统提示。"
    assert "自定义字段清单：" in prompt.text
    assert '"product_type" (string, 必须)' in prompt.text
    assert prompt.text.endswith("自定义一段式输出规则。")


def test_caption_prompt_accepts_config_override():
    config = {
        "zh": {
            "caption_stage": {
                "system": "自定义 caption 系统提示。",
                "text": "自定义 caption 用户提示。",
                "max_tokens": 32,
            }
        }
    }

    prompt = build_caption_prompt(language="zh", prompt_config=config)

    assert prompt.system == "自定义 caption 系统提示。"
    assert prompt.text == "自定义 caption 用户提示。"
    assert prompt.max_tokens == 32


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


def test_caption_prompt_is_bounded_natural_language():
    from memosight.prompts import build_caption_prompt

    prompt = build_caption_prompt(language="zh")

    assert prompt.schema_name == "photography_caption"
    assert prompt.max_tokens == 128
    assert "90–110字" in prompt.text
    assert "不要字段标题、列表或换行" in prompt.text
    assert "可搜索的具体事实" in prompt.text


def test_field_extraction_prompt_requires_caption_grounding():
    prompt = build_caption_field_extraction_prompt("caption")

    assert prompt.schema_name == "caption_fields_markdown"
    assert prompt.max_tokens == 192
    assert "caption 原文" in prompt.system or "caption" in prompt.system
    assert "不要补充" in prompt.text
    assert "光线词放 lighting" in prompt.text
    assert "不要根据场景推断" in prompt.text
    assert prompt.text.endswith("**search_tags:** ...")


def test_caption_structured_extraction_prompt_is_schema_driven():
    profile = resolve_profile(output_schema=CUSTOM_SCHEMA)
    prompt = build_caption_structured_extraction_prompt(
        "A black watch with a visible logo on a white table.",
        profile,
        language="en",
    )

    assert prompt.schema_name == "custom_caption_json"
    assert "Based only on the caption above" in prompt.text
    assert '"product_type"' in prompt.text
    assert '"brand_visible"' in prompt.text
    assert '"dominant_colors"' in prompt.text
    assert '"caption"' not in prompt.text
    assert "warm/cool/neutral" in prompt.text
    assert "Use only facts explicitly stated in the caption" in prompt.system


def test_caption_structured_extraction_prompt_can_include_prompt_plan():
    profile = resolve_profile(output_schema=CUSTOM_SCHEMA)
    plan = MemoSightPromptPlan(
        task_summary="商品 caption 结构化抽取",
        field_guidance={
            "product_type": "从 caption 明确写出的主体商品判断类别。",
            "brand_visible": "caption 写出可见品牌标志或品牌名时为 true。",
            "mood": "只使用 caption 明确出现的色彩氛围。",
            "dominant_colors": "从 caption 中提到的可见主色抽取。",
        },
        negative_rules=["不要补充 caption 没写出的品牌。"],
        output_rules=["字段类型必须匹配 schema。"],
        final_prompt="只根据 caption 生成商品结构化 JSON。",
    )

    prompt = build_caption_structured_extraction_prompt(
        "黑色手表表盘上有品牌标志。",
        profile,
        prompt_plan=plan,
    )

    assert "商品 caption 结构化抽取" in prompt.text
    assert "不要补充 caption 没写出的品牌" in prompt.text
    assert "只根据 caption 生成商品结构化 JSON" in prompt.text


def test_caption_structured_extraction_prompt_accepts_config_override():
    config = {
        "zh": {
            "labels": {
                "caption_json_fields_header": "自定义 caption JSON 字段：",
            },
            "caption_json_stage": {
                "system": "自定义二段式 JSON 系统提示。",
                "rules": "自定义二段式 JSON 输出规则。",
            },
        }
    }

    prompt = build_caption_structured_extraction_prompt(
        "黑色手表表盘上有品牌标志。",
        resolve_profile(output_schema=CUSTOM_SCHEMA),
        prompt_config=config,
    )

    assert prompt.system == "自定义二段式 JSON 系统提示。"
    assert "自定义 caption JSON 字段：" in prompt.text
    assert prompt.text.endswith("自定义二段式 JSON 输出规则。")


def test_caption_structured_extraction_prompt_has_default_max_tokens():
    profile = resolve_profile(output_schema=CUSTOM_SCHEMA)
    prompt = build_caption_structured_extraction_prompt("黑色手表。", profile)

    assert prompt.max_tokens == 224


def test_caption_structured_extraction_prompt_max_tokens_config_override():
    config = {"zh": {"caption_json_stage": {"max_tokens": 96}}}

    prompt = build_caption_structured_extraction_prompt(
        "黑色手表。",
        resolve_profile(output_schema=CUSTOM_SCHEMA),
        prompt_config=config,
    )

    assert prompt.max_tokens == 96


def test_default_fields_schema_prompt_lists_seven_fields_without_caption():
    from memosight.profiles import PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA

    profile = get_profile("photography_default").model_copy(
        update={"output_schema": PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA}
    )
    prompt = build_caption_structured_extraction_prompt("室内暖光下的人。", profile)

    assert prompt.schema_name == "photography_default_caption_json"
    assert prompt.max_tokens == 224
    for field in CAPTION_FIELD_KEYS:
        assert f'"{field}"' in prompt.text
    assert '"caption"' not in prompt.text
