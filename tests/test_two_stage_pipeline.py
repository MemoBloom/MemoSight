"""Contract tests for caption -> fixed Markdown -> normalized observation."""
from __future__ import annotations

from pathlib import Path

import pytest

from memosight import (
    MemoSightImageSource,
    MemoSightRequest,
    MockMemoSightBackend,
    MockMemoSightTextBackend,
    TwoStageMemoSightPipeline,
)
from memosight.normalizer import CAPTION_FIELD_KEYS


VALID_MARKDOWN = """**scene_labels:** 婚礼, 室内
**people:** 新人, 宾客
**actions:** 站立, 合影
**objects:** 花艺, 舞台, 礼服
**lighting:** 暖光
**mood:** 庄重, 温馨
**search_tags:** 婚礼, 新人, 舞台, 暖光"""


CUSTOM_SCHEMA = {
    "type": "object",
    "properties": {
        "product_type": {"type": "string", "description": "Visible product category."},
        "brand_visible": {
            "type": "boolean",
            "description": "Whether a brand logo or brand name is visible.",
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


def _request(tmp_path: Path, **overrides) -> MemoSightRequest:
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0")
    return MemoSightRequest(
        image=MemoSightImageSource(image_path=str(image)),
        **overrides,
    )


@pytest.mark.asyncio
async def test_two_stage_success_preserves_default_output_contract(tmp_path):
    image_backend = MockMemoSightBackend(
        response="照片中，两位新人站在暖光舞台中央，背景有花艺，氛围庄重温馨。"
    )
    text_backend = MockMemoSightTextBackend(response=VALID_MARKDOWN)
    pipeline = TwoStageMemoSightPipeline(image_backend, text_backend)

    result = await pipeline.analyze(_request(tmp_path))

    assert result.status == "ok"
    assert set(result.observation) == {"caption", *CAPTION_FIELD_KEYS}
    assert result.observation["caption"].startswith("照片中")
    assert result.observation["scene_labels"] == ["婚礼", "室内"]
    assert result.observation["lighting"] == ["暖光"]
    assert result.default_observation is not None
    assert result.caption_raw_output == image_backend.response
    assert result.structured_raw_output == VALID_MARKDOWN
    assert result.raw_output == VALID_MARKDOWN
    assert result.usage["parse_strategy"] == "markdown"
    assert len(image_backend.calls) == 1
    assert len(text_backend.calls) == 1


@pytest.mark.asyncio
async def test_prompts_are_short_and_single_purpose(tmp_path):
    image_backend = MockMemoSightBackend(response="室内暖光下的一人站在桌旁。")
    text_backend = MockMemoSightTextBackend(response=VALID_MARKDOWN)
    pipeline = TwoStageMemoSightPipeline(image_backend, text_backend)

    await pipeline.analyze(_request(tmp_path))

    caption_prompt = image_backend.calls[0].prompt
    field_prompt = text_backend.calls[0]
    assert "JSON" not in caption_prompt.text
    assert "scene_labels" not in caption_prompt.text
    assert len(caption_prompt.text) < 120
    assert "只输出" in caption_prompt.text
    assert "caption 原文" in field_prompt.system
    assert all(key in field_prompt.text for key in CAPTION_FIELD_KEYS)
    assert len(field_prompt.system) < 80
    assert "室内暖光下的一人站在桌旁" in field_prompt.text
    assert field_prompt.schema_name == "caption_fields_markdown"
    assert field_prompt.max_tokens == 192


@pytest.mark.asyncio
async def test_missing_markdown_line_is_partial_and_caption_is_preserved(tmp_path):
    caption = "一人在室内桌旁站立。"
    incomplete = VALID_MARKDOWN.replace("**lighting:** 暖光\n", "")
    pipeline = TwoStageMemoSightPipeline(
        MockMemoSightBackend(response=caption),
        MockMemoSightTextBackend(response=incomplete),
    )

    result = await pipeline.analyze(_request(tmp_path))

    assert result.status == "partial"
    assert result.failed_stage == "field_extraction"
    assert result.observation["caption"] == caption
    assert result.observation["lighting"] == []
    assert any("lighting" in issue.message for issue in result.validation.issues)


@pytest.mark.asyncio
async def test_field_stage_can_be_rerun_without_image(tmp_path):
    image_backend = MockMemoSightBackend(response="不会调用")
    text_backend = MockMemoSightTextBackend(response=VALID_MARKDOWN)
    pipeline = TwoStageMemoSightPipeline(image_backend, text_backend)

    result = await pipeline.extract_fields("两位新人站在暖光舞台中央。")

    assert result.status == "ok"
    assert result.fields["people"] == ["新人", "宾客"]
    assert len(image_backend.calls) == 0
    assert len(text_backend.calls) == 1


@pytest.mark.asyncio
async def test_custom_field_stage_can_be_rerun_without_image(tmp_path):
    image_backend = MockMemoSightBackend(response="不会调用")
    text_backend = MockMemoSightTextBackend(
        response='{"product_type": "手表", "brand_visible": true}'
    )
    pipeline = TwoStageMemoSightPipeline(image_backend, text_backend)

    result = await pipeline.extract_fields(
        "一只带品牌标志的手表。",
        output_schema=CUSTOM_SCHEMA,
    )

    assert result.status == "ok"
    assert result.fields["product_type"] == "手表"
    assert result.fields["brand_visible"] is True
    assert len(image_backend.calls) == 0
    assert len(text_backend.calls) == 1
    assert text_backend.calls[0].schema_name == "custom_caption_json"


@pytest.mark.asyncio
async def test_none_values_become_empty_arrays(tmp_path):
    markdown = "\n".join(f"**{key}:** none" for key in CAPTION_FIELD_KEYS)
    pipeline = TwoStageMemoSightPipeline(
        MockMemoSightBackend(response="空旷室内。"),
        MockMemoSightTextBackend(response=markdown),
    )

    result = await pipeline.analyze(_request(tmp_path))

    assert result.status == "ok"
    assert all(result.observation[key] == [] for key in CAPTION_FIELD_KEYS)


@pytest.mark.asyncio
async def test_chinese_empty_value_becomes_empty_array(tmp_path):
    markdown = VALID_MARKDOWN.replace("**people:** 新人, 宾客", "**people:** 无")
    pipeline = TwoStageMemoSightPipeline(
        MockMemoSightBackend(response="空旷室内。"),
        MockMemoSightTextBackend(response=markdown),
    )

    result = await pipeline.analyze(_request(tmp_path))

    assert result.status == "ok"
    assert result.observation["people"] == []


@pytest.mark.asyncio
async def test_custom_schema_uses_schema_driven_json_field_prompt(tmp_path):
    image_backend = MockMemoSightBackend(response="一只黑色手表，表盘上有可见品牌标志。")
    text_backend = MockMemoSightTextBackend(
        response=(
            '{"product_type": "手表", "brand_visible": true, '
            '"dominant_colors": ["黑色"], "extra": "dropped"}'
        )
    )
    pipeline = TwoStageMemoSightPipeline(image_backend, text_backend)

    result = await pipeline.analyze(_request(tmp_path, output_schema=CUSTOM_SCHEMA))

    assert result.status == "ok"
    assert result.schema_name == "custom"
    assert result.observation == {
        "product_type": "手表",
        "brand_visible": True,
        "dominant_colors": ["黑色"],
    }
    assert result.default_observation is None
    assert result.usage["parse_strategy"] == "strict"
    assert len(image_backend.calls) == 1
    assert len(text_backend.calls) == 1
    prompt = text_backend.calls[0]
    assert prompt.schema_name == "custom_caption_json"
    assert '"product_type"' in prompt.text
    assert '"brand_visible"' in prompt.text
    assert '"caption"' not in prompt.text


@pytest.mark.asyncio
async def test_prompt_config_flows_through_two_stage_pipeline(tmp_path):
    image_backend = MockMemoSightBackend(response="室内暖光下的一人站在桌旁。")
    text_backend = MockMemoSightTextBackend(response=VALID_MARKDOWN)
    pipeline = TwoStageMemoSightPipeline(image_backend, text_backend)
    config = {
        "zh": {
            "caption_stage": {
                "system": "运行时自定义 caption 系统提示。",
                "text": "运行时自定义 caption 用户提示。",
                "max_tokens": 40,
            },
            "markdown_field_stage": {
                "system": "运行时自定义字段系统提示。",
                "template": "运行时自定义字段模板。",
                "max_tokens": 48,
            },
        }
    }

    result = await pipeline.analyze(_request(tmp_path, prompt_config=config))

    assert result.status == "ok"
    caption_prompt = image_backend.calls[0].prompt
    field_prompt = text_backend.calls[0]
    assert caption_prompt.system == "运行时自定义 caption 系统提示。"
    assert caption_prompt.text == "运行时自定义 caption 用户提示。"
    assert caption_prompt.max_tokens == 40
    assert field_prompt.system == "运行时自定义字段系统提示。"
    assert field_prompt.text.endswith("运行时自定义字段模板。")
    assert field_prompt.max_tokens == 48
