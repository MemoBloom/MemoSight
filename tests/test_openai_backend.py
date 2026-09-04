"""Tests for the OpenAI-compatible backend adapters (vLLM et al.)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from memosight.backends import DEFAULT_MOCK_RESPONSE
from memosight.errors import MemoSightBackendError
from memosight.openai_backend import OpenAICompatBackend, OpenAICompatTextBackend
from memosight.pipeline import MemoSightPipeline
from memosight.profiles import get_profile
from memosight.prompts import build_caption_field_extraction_prompt, build_prompt
from memosight.schema import MemoSightImageSource, MemoSightRequest
from memosight.source import resolve_image_source


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


def _make_backend(
    handler, *, api_key: str | None = None, model: str | None = "test-model"
) -> OpenAICompatBackend:
    return OpenAICompatBackend(
        "http://test/v1",
        model,
        api_key=api_key,
        transport=httpx.MockTransport(handler),
    )


def _make_source(tmp_path: Path):
    return resolve_image_source(
        MemoSightImageSource(kind="bytes", data=b"\x89PNG\r\n", mime_type="image/png"),
        temp_dir=tmp_path,
    )


def test_describe_posts_openai_payload_and_returns_content(tmp_path):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return _chat_response('{"caption": "a cat"}')

    backend = _make_backend(handler, api_key="secret")
    source = _make_source(tmp_path)
    prompt = build_prompt(get_profile("photography_default"))

    output = asyncio.run(backend.describe(source, prompt))

    assert output == '{"caption": "a cat"}'
    assert captured["auth"] == "Bearer secret"
    payload = captured["payload"]
    assert payload["model"] == "test-model"
    assert payload["max_tokens"] == 768
    messages = payload["messages"]
    assert messages[0]["role"] == "system" and messages[0]["content"] == prompt.system
    content = messages[1]["content"]
    assert content[0]["type"] == "text"
    # System header is sent once, not duplicated in the user text.
    assert not content[0]["text"].startswith(prompt.system)
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_describe_cleans_up_temp_file_on_success_and_failure(tmp_path):
    def ok(request: httpx.Request) -> httpx.Response:
        return _chat_response("ok")

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    prompt = build_prompt(get_profile("photography_default"))

    source = _make_source(tmp_path)
    asyncio.run(_make_backend(ok).describe(source, prompt))
    assert not source.cleanup_required
    assert not Path(source.image_path).exists()

    source = _make_source(tmp_path)
    with pytest.raises(MemoSightBackendError):
        asyncio.run(_make_backend(server_error).describe(source, prompt))
    assert not source.cleanup_required
    assert not Path(source.image_path).exists()


def test_describe_wraps_failure_in_backend_error_with_cause(tmp_path):
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    backend = _make_backend(refused)
    source = _make_source(tmp_path)
    with pytest.raises(MemoSightBackendError) as excinfo:
        asyncio.run(backend.describe(
            source, build_prompt(get_profile("photography_default"))
        ))
    assert isinstance(excinfo.value.__cause__, httpx.ConnectError)
    assert "describe failed" in str(excinfo.value)


def test_model_id_resolved_from_v1_models_when_not_configured(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "resolved-model"}]})
        assert json.loads(request.content)["model"] == "resolved-model"
        return _chat_response("ok")

    backend = _make_backend(handler, model=None)
    source = _make_source(tmp_path)
    output = asyncio.run(backend.describe(
        source, build_prompt(get_profile("photography_default"))
    ))
    assert output == "ok"


def test_text_backend_complete_posts_system_and_user():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return _chat_response("fields")

    backend = OpenAICompatTextBackend(
        "http://test/v1",
        "test-model",
        transport=httpx.MockTransport(handler),
    )
    prompt = build_caption_field_extraction_prompt("a cat on a mat")
    output = asyncio.run(backend.complete(prompt))

    assert output == "fields"
    payload = captured["payload"]
    assert payload["model"] == "test-model"
    assert payload["max_tokens"] == prompt.max_tokens
    assert payload["messages"][0]["content"] == prompt.system
    assert payload["messages"][1]["content"] == prompt.text


def test_pipeline_integration_end_to_end(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(DEFAULT_MOCK_RESPONSE)

    backend = _make_backend(handler)
    pipeline = MemoSightPipeline(backend=backend)
    image = tmp_path / "img.png"
    image.write_bytes(b"\x89PNG\r\n")
    request = MemoSightRequest(
        image=MemoSightImageSource(kind="path", image_path=str(image))
    )
    result = asyncio.run(pipeline.analyze(request))

    assert result.status == "ok"
    assert result.observation["caption"] == "mock caption"
    assert result.model_name == "openai_compat"
    assert result.usage["parse_strategy"] == "strict"


def test_chat_template_kwargs_forwarded_when_set(tmp_path):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return _chat_response('{"caption": "a cat"}')

    backend = OpenAICompatBackend(
        "http://test/v1",
        "test-model",
        transport=httpx.MockTransport(handler),
        chat_template_kwargs={"enable_thinking": False},
    )
    source = _make_source(tmp_path)
    prompt = build_prompt(get_profile("photography_default"))

    asyncio.run(backend.describe(source, prompt))

    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_chat_template_kwargs_absent_by_default(tmp_path):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return _chat_response("ok")

    backend = OpenAICompatTextBackend(
        "http://test/v1",
        "test-model",
        transport=httpx.MockTransport(handler),
    )
    prompt = build_caption_field_extraction_prompt('{"caption": "a cat"}')

    asyncio.run(backend.complete(prompt))

    assert "chat_template_kwargs" not in captured["payload"]


def test_text_backend_chat_template_kwargs_forwarded_when_set():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return _chat_response("ok")

    backend = OpenAICompatTextBackend(
        "http://test/v1",
        "test-model",
        transport=httpx.MockTransport(handler),
        chat_template_kwargs={"enable_thinking": False},
    )
    prompt = build_caption_field_extraction_prompt('{"caption": "a cat"}')

    asyncio.run(backend.complete(prompt))

    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
