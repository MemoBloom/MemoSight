"""Tests for memosight.pipeline — MemoSightPipeline end-to-end behavior."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from memosight import (
    MemoSightImageSource,
    MemoSightPipeline,
    MemoSightRequest,
    MockMemoSightBackend,
)
from memosight.prompts import MemoSightPrompt
from memosight.source import ResolvedImageSource

# 1x1 transparent PNG.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode("ascii")

PRODUCT_SCHEMA = {
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
        },
    },
    "required": ["product_type", "brand_visible"],
}


class SequenceBackend:
    """Backend double returning a scripted sequence of responses."""

    name = "sequence-mock"
    version = "9.9.9"

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.prompts: list[MemoSightPrompt] = []

    async def describe(
        self, image: ResolvedImageSource, prompt: MemoSightPrompt
    ) -> str:
        self.prompts.append(prompt)
        try:
            index = min(len(self.prompts) - 1, len(self._responses) - 1)
            return self._responses[index]
        finally:
            image.cleanup()


class NoCleanupBackend:
    """Backend double that deliberately ignores the cleanup contract."""

    name = "no-cleanup-mock"
    version = "0.0.1"

    def __init__(self, response: str):
        self._response = response

    async def describe(
        self, image: ResolvedImageSource, prompt: MemoSightPrompt
    ) -> str:
        return self._response


class RaisingBackend:
    """Backend double that fails the model call with a raw (unwrapped) error."""

    name = "raising-mock"
    version = "0.0.1"

    async def describe(
        self, image: ResolvedImageSource, prompt: MemoSightPrompt
    ) -> str:
        raise RuntimeError("server unreachable")


def _image_file(tmp_path: Path, name: str = "photo.jpg") -> Path:
    image = tmp_path / name
    image.write_bytes(b"\xff\xd8\xff\xe0")
    return image


def _request_for(image: Path, **overrides) -> MemoSightRequest:
    return MemoSightRequest(
        image=MemoSightImageSource(image_path=str(image)), **overrides
    )


@pytest.mark.asyncio
async def test_valid_model_json_returns_ok(tmp_path):
    image = _image_file(tmp_path)
    pipeline = MemoSightPipeline(backend=MockMemoSightBackend())

    result = await pipeline.analyze(_request_for(image))

    assert result.status == "ok"
    assert result.error is None
    assert result.observation["caption"] == "mock caption"
    assert result.observation["scene_labels"] == ["mock"]
    assert result.default_observation is not None
    assert result.default_observation.caption == "mock caption"
    assert result.schema_name == "photography_default"
    assert result.schema_version == "1.0.0"
    assert result.model_name == "mock"
    assert result.model_version == "1.0.0"
    assert json.loads(result.raw_output)["caption"] == "mock caption"
    assert result.validation.ok


@pytest.mark.asyncio
async def test_fenced_json_parses(tmp_path):
    image = _image_file(tmp_path)
    payload = {
        "caption": "暖光婚礼现场",
        "scene_labels": ["婚礼"],
        "people": [],
        "actions": [],
        "objects": [],
        "lighting": ["暖光"],
        "mood": [],
        "search_tags": ["婚礼"],
    }
    backend = MockMemoSightBackend(
        response="这是结果：\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    )
    pipeline = MemoSightPipeline(backend=backend)

    result = await pipeline.analyze(_request_for(image))

    assert result.status == "ok"
    assert result.observation["caption"] == "暖光婚礼现场"
    assert result.observation["lighting"] == ["暖光"]


@pytest.mark.asyncio
async def test_markdown_fallback_parses_legacy_field_output(tmp_path):
    image = _image_file(tmp_path)
    legacy_output = (
        "**caption:** 暖光下的婚礼现场\n"
        "**scene_labels:** 婚礼, 室内\n"
        "**people:** 穿白色婚纱的新娘、背景宾客\n"
        "### actions\n"
        "- 站立\n"
        "- 互动\n"
        "**objects:** 餐桌, 红色装饰\n"
        "**lighting:** 暖光\n"
        "**mood:** 温馨, 热闹\n"
        "**search_tags:** 婚礼; 新娘; 室内; none\n"
    )
    pipeline = MemoSightPipeline(backend=MockMemoSightBackend(response=legacy_output))

    result = await pipeline.analyze(_request_for(image))

    assert result.status == "ok"
    assert result.observation["caption"] == "暖光下的婚礼现场"
    assert result.observation["scene_labels"] == ["婚礼", "室内"]
    assert result.observation["people"] == ["穿白色婚纱的新娘", "背景宾客"]
    assert result.observation["actions"] == ["站立", "互动"]
    assert result.observation["search_tags"] == ["婚礼", "新娘", "室内"]
    assert result.default_observation is not None
    assert result.default_observation.mood == ["温馨", "热闹"]


@pytest.mark.asyncio
async def test_invalid_output_fails_after_repair_attempts_exhausted(tmp_path):
    image = _image_file(tmp_path)
    backend = SequenceBackend(["totally not json", "still not json"])
    pipeline = MemoSightPipeline(backend=backend, max_repair_attempts=1)

    result = await pipeline.analyze(_request_for(image))

    assert result.status == "failed"
    assert result.raw_output == "still not json"
    assert not result.validation.ok
    assert result.validation.issues
    # One initial call plus exactly one repair attempt.
    assert len(backend.prompts) == 2
    repair_prompt = backend.prompts[1].text
    assert repair_prompt != backend.prompts[0].text
    assert backend.prompts[0].text in repair_prompt


@pytest.mark.asyncio
async def test_repair_attempt_succeeds_when_second_output_is_valid(tmp_path):
    image = _image_file(tmp_path)
    valid = json.dumps(
        {
            "caption": "修复后的描述",
            "scene_labels": [],
            "people": [],
            "actions": [],
            "objects": [],
            "lighting": [],
            "mood": [],
            "search_tags": [],
        },
        ensure_ascii=False,
    )
    backend = SequenceBackend(["garbage output without structure", valid])
    pipeline = MemoSightPipeline(backend=backend, max_repair_attempts=1)

    result = await pipeline.analyze(_request_for(image))

    assert result.status == "ok"
    assert result.observation["caption"] == "修复后的描述"
    assert len(backend.prompts) == 2
    assert result.usage.get("attempts") == 2


@pytest.mark.asyncio
async def test_no_repair_when_max_repair_attempts_is_zero(tmp_path):
    image = _image_file(tmp_path)
    backend = SequenceBackend(["garbage"])
    pipeline = MemoSightPipeline(backend=backend, max_repair_attempts=0)

    result = await pipeline.analyze(_request_for(image))

    assert result.status == "failed"
    assert len(backend.prompts) == 1


@pytest.mark.asyncio
async def test_custom_schema_valid_output_returns_ok(tmp_path):
    image = _image_file(tmp_path)
    payload = {
        "product_type": "手表",
        "brand_visible": True,
        "dominant_colors": ["黑色", "银色"],
        "extra_unknown_key": "dropped",
    }
    backend = MockMemoSightBackend(response=json.dumps(payload, ensure_ascii=False))
    pipeline = MemoSightPipeline(backend=backend)

    result = await pipeline.analyze(
        _request_for(image, profile="custom", output_schema=PRODUCT_SCHEMA)
    )

    assert result.status == "ok"
    assert result.schema_name == "custom"
    assert result.observation == {
        "product_type": "手表",
        "brand_visible": True,
        "dominant_colors": ["黑色", "银色"],
    }
    # No caption in the payload: not safely mappable to the default observation.
    assert result.default_observation is None


@pytest.mark.asyncio
async def test_prompt_config_flows_through_one_stage_pipeline(tmp_path):
    image = _image_file(tmp_path)
    backend = MockMemoSightBackend()
    pipeline = MemoSightPipeline(backend=backend)
    config = {
        "zh": {
            "one_stage": {
                "system": "运行时自定义一段式系统提示。",
                "rules": "运行时自定义一段式输出规则。",
            }
        }
    }

    result = await pipeline.analyze(_request_for(image, prompt_config=config))

    assert result.status == "ok"
    prompt = backend.calls[0].prompt
    assert prompt.system == "运行时自定义一段式系统提示。"
    assert prompt.text.endswith("运行时自定义一段式输出规则。")


@pytest.mark.asyncio
async def test_custom_schema_type_errors_fail_with_issues(tmp_path):
    image = _image_file(tmp_path)
    payload = {"product_type": "手表", "brand_visible": "yes"}
    backend = MockMemoSightBackend(response=json.dumps(payload, ensure_ascii=False))
    pipeline = MemoSightPipeline(backend=backend, max_repair_attempts=0)

    result = await pipeline.analyze(
        _request_for(image, profile="custom", output_schema=PRODUCT_SCHEMA)
    )

    assert result.status == "failed"
    messages = [issue.message for issue in result.validation.issues]
    assert any("brand_visible" in issue.source for issue in result.validation.issues)
    assert any("boolean" in message for message in messages)


@pytest.mark.asyncio
async def test_custom_schema_missing_required_field_fails(tmp_path):
    image = _image_file(tmp_path)
    payload = {"product_type": "手表"}
    backend = MockMemoSightBackend(response=json.dumps(payload, ensure_ascii=False))
    pipeline = MemoSightPipeline(backend=backend, max_repair_attempts=0)

    result = await pipeline.analyze(
        _request_for(image, profile="custom", output_schema=PRODUCT_SCHEMA)
    )

    assert result.status == "failed"
    assert any(
        "brand_visible" in issue.message for issue in result.validation.issues
    )


@pytest.mark.asyncio
async def test_analyze_batch_one_bad_request_does_not_abort(tmp_path):
    good_a = _image_file(tmp_path, "a.jpg")
    good_b = _image_file(tmp_path, "b.jpg")
    missing = tmp_path / "missing.jpg"
    pipeline = MemoSightPipeline(backend=MockMemoSightBackend())

    results = await pipeline.analyze_batch(
        [
            _request_for(good_a),
            _request_for(missing),
            _request_for(good_b),
        ]
    )

    assert [result.status for result in results] == ["ok", "failed", "ok"]
    assert results[1].error is not None
    assert "missing.jpg" in results[1].error


@pytest.mark.asyncio
async def test_missing_input_file_returns_failed_result_not_exception(tmp_path):
    pipeline = MemoSightPipeline(backend=MockMemoSightBackend())

    result = await pipeline.analyze(_request_for(tmp_path / "nope.jpg"))

    assert result.status == "failed"
    assert result.error is not None
    assert "nope.jpg" in result.error
    assert result.observation == {}


@pytest.mark.asyncio
async def test_backend_error_returns_failed_result(tmp_path):
    image = _image_file(tmp_path)
    pipeline = MemoSightPipeline(backend=RaisingBackend())

    result = await pipeline.analyze(_request_for(image))

    assert result.status == "failed"
    assert result.error is not None
    assert "server unreachable" in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["bytes", "base64"])
async def test_temp_files_cleaned_up_on_success(tmp_path, kind):
    data = PNG_BYTES if kind == "bytes" else PNG_BASE64
    temp_dir = tmp_path / "memosight-tmp"
    pipeline = MemoSightPipeline(backend=MockMemoSightBackend(), temp_dir=temp_dir)
    request = MemoSightRequest(
        image=MemoSightImageSource(kind=kind, data=data, mime_type="image/png")
    )

    result = await pipeline.analyze(request)

    assert result.status == "ok"
    assert temp_dir.exists()
    assert list(temp_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_temp_file_cleaned_up_when_backend_ignores_cleanup_contract(tmp_path):
    temp_dir = tmp_path / "memosight-tmp"
    pipeline = MemoSightPipeline(
        backend=NoCleanupBackend(response="garbage, no structure"),
        max_repair_attempts=0,
        temp_dir=temp_dir,
    )
    request = MemoSightRequest(
        image=MemoSightImageSource(kind="bytes", data=PNG_BYTES, mime_type="image/png")
    )

    result = await pipeline.analyze(request)

    # Output is invalid, and the temp file is still removed by the
    # pipeline-level safety net even though the backend skipped cleanup.
    assert result.status == "failed"
    assert list(temp_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_temp_file_cleaned_up_on_backend_error(tmp_path):
    temp_dir = tmp_path / "memosight-tmp"
    pipeline = MemoSightPipeline(backend=RaisingBackend(), temp_dir=temp_dir)
    request = MemoSightRequest(
        image=MemoSightImageSource(kind="base64", data=PNG_BASE64, mime_type="image/png")
    )

    result = await pipeline.analyze(request)

    assert result.status == "failed"
    assert list(temp_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_invalid_output_schema_returns_failed_result(tmp_path):
    image = _image_file(tmp_path)
    pipeline = MemoSightPipeline(backend=MockMemoSightBackend())

    result = await pipeline.analyze(
        _request_for(image, output_schema={"type": "array"})
    )

    assert result.status == "failed"
    assert result.error is not None
    assert "object" in result.error


class TestMlXVlmClientDescribeOverrides:
    """MlXVlmClient.describe prompt overrides (transport layer faked)."""

    @staticmethod
    def _make_client(monkeypatch):
        from memosight.mlx_client import MlXVlmClient

        client = MlXVlmClient(base_url="http://unused")
        captured: dict = {}

        async def fake_chat_with_image(image_path, system_prompt, user_text):
            captured["image_path"] = image_path
            captured["system_prompt"] = system_prompt
            captured["user_text"] = user_text
            return '{"caption": "ok"}'

        monkeypatch.setattr(client, "_chat_with_image", fake_chat_with_image)
        return client, captured

    @pytest.mark.asyncio
    async def test_describe_without_overrides_uses_builtin_prompts(self, monkeypatch):
        client, captured = self._make_client(monkeypatch)

        await client.describe("/tmp/x.jpg", language="zh")

        assert captured["image_path"] == "/tmp/x.jpg"
        assert captured["system_prompt"] == client._describe_prompt_for_language("zh")
        assert captured["user_text"] == client._describe_user_text_for_language("zh")

    @pytest.mark.asyncio
    async def test_describe_without_overrides_english(self, monkeypatch):
        client, captured = self._make_client(monkeypatch)

        await client.describe("/tmp/x.jpg", language="en")

        assert captured["system_prompt"] == client._describe_prompt_for_language("en")
        assert captured["user_text"] == client._describe_user_text_for_language("en")

    @pytest.mark.asyncio
    async def test_describe_passes_overrides_through(self, monkeypatch):
        client, captured = self._make_client(monkeypatch)

        await client.describe(
            "/tmp/x.jpg",
            language="zh",
            system_prompt="CUSTOM SYSTEM",
            user_text="CUSTOM USER TEXT",
        )

        assert captured["system_prompt"] == "CUSTOM SYSTEM"
        assert captured["user_text"] == "CUSTOM USER TEXT"

    @pytest.mark.asyncio
    async def test_describe_partial_override_keeps_builtin_for_the_rest(
        self, monkeypatch
    ):
        client, captured = self._make_client(monkeypatch)

        await client.describe("/tmp/x.jpg", user_text="ONLY USER OVERRIDE")

        assert captured["user_text"] == "ONLY USER OVERRIDE"
        assert captured["system_prompt"] == client._describe_prompt_for_language("zh")


def test_qwen_generation_config_is_deterministic_and_compact():
    from memosight.mlx_client import QWEN_VL_NON_THINKING_GENERATION_CONFIG

    assert QWEN_VL_NON_THINKING_GENERATION_CONFIG["temperature"] == 0.1
    assert QWEN_VL_NON_THINKING_GENERATION_CONFIG["top_p"] == 0.9
    assert QWEN_VL_NON_THINKING_GENERATION_CONFIG["presence_penalty"] == 0.0
