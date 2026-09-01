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
    assert len(caption_prompt.text) < 100
    assert "只输出这句话" in caption_prompt.text
    assert "不猜测或补充" in field_prompt.system
    assert all(key in field_prompt.text for key in CAPTION_FIELD_KEYS)
    assert len(field_prompt.system) < 50
    assert "室内暖光下的一人站在桌旁" in field_prompt.text
    assert field_prompt.schema_name == "caption_fields_markdown_v1"
    assert field_prompt.max_tokens == 192


@pytest.mark.asyncio
async def test_caption_prompt_version_can_be_selected(tmp_path):
    image_backend = MockMemoSightBackend(response="一张包含具体细节的照片描述。")
    text_backend = MockMemoSightTextBackend(response=VALID_MARKDOWN)
    pipeline = TwoStageMemoSightPipeline(
        image_backend,
        text_backend,
        caption_prompt_version="v2",
    )

    await pipeline.analyze(_request(tmp_path))

    prompt = image_backend.calls[0].prompt
    assert prompt.schema_name == "photography_caption_v2"
    assert prompt.max_tokens == 160
    assert "80–120字" in prompt.text


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
async def test_custom_schema_is_rejected_before_model_calls(tmp_path):
    image_backend = MockMemoSightBackend(response="caption")
    text_backend = MockMemoSightTextBackend(response=VALID_MARKDOWN)
    pipeline = TwoStageMemoSightPipeline(image_backend, text_backend)
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    result = await pipeline.analyze(_request(tmp_path, output_schema=schema))

    assert result.status == "failed"
    assert "photography_default" in result.error
    assert not image_backend.calls
    assert not text_backend.calls
