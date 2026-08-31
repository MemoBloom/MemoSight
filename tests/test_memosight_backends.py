"""Tests for memosight.backends — protocol, MLX adapter, mock backend."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from memosight.backends import (
    MemoSightBackend,
    MlXVlmMemoSightBackend,
    MockMemoSightBackend,
)
from memosight.errors import MemoSightBackendError
from memosight.prompts import MemoSightPrompt
from memosight.schema import MemoSightImageSource
from memosight.source import ResolvedImageSource, resolve_image_source

# 1x1 transparent PNG.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode("ascii")


class FakeMlXVlmClient:
    """Test double for MlXVlmClient — records describe() calls, never calls HTTP."""

    def __init__(self, response: str = "{}", error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []
        self.path_existed_during_call: bool | None = None

    async def describe(
        self,
        image_path: str,
        language: str = "zh",
        system_prompt: str | None = None,
        user_text: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "image_path": image_path,
                "language": language,
                "system_prompt": system_prompt,
                "user_text": user_text,
            }
        )
        self.path_existed_during_call = Path(image_path).exists()
        if self.error is not None:
            raise self.error
        return self.response


def _path_source(tmp_path: Path) -> tuple[Path, ResolvedImageSource]:
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0")
    return image, resolve_image_source(MemoSightImageSource(image_path=str(image)))


def test_backends_satisfy_protocol():
    assert isinstance(MockMemoSightBackend(), MemoSightBackend)
    assert isinstance(
        MlXVlmMemoSightBackend(client=FakeMlXVlmClient()), MemoSightBackend
    )


@pytest.mark.asyncio
async def test_mock_backend_returns_deterministic_json(tmp_path):
    image, resolved = _path_source(tmp_path)
    backend = MockMemoSightBackend()
    prompt = MemoSightPrompt(text="Describe this image.", language="zh")

    first = await backend.describe(resolved, prompt)
    second = await backend.describe(resolved, prompt)

    assert first == second
    payload = json.loads(first)
    assert payload["caption"]
    assert payload["search_tags"]
    assert [call.image_path for call in backend.calls] == [str(image), str(image)]
    assert all(call.prompt.text == prompt.text for call in backend.calls)
    assert image.exists()


@pytest.mark.asyncio
async def test_mock_backend_custom_response(tmp_path):
    _, resolved = _path_source(tmp_path)
    backend = MockMemoSightBackend(response='{"product_type": "watch"}')

    result = await backend.describe(resolved, MemoSightPrompt(text="p"))

    assert json.loads(result) == {"product_type": "watch"}
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_mlx_backend_delegates_describe_with_path_and_language(tmp_path):
    image, resolved = _path_source(tmp_path)
    client = FakeMlXVlmClient(response='{"caption": "暖光婚礼"}')
    backend = MlXVlmMemoSightBackend(client=client)

    result = await backend.describe(resolved, MemoSightPrompt(text="p", language="en"))

    assert result == '{"caption": "暖光婚礼"}'
    assert client.calls == [
        {
            "image_path": str(image),
            "language": "en",
            "system_prompt": None,
            "user_text": "p",
        }
    ]
    # Caller-owned path sources are never cleaned up.
    assert image.exists()
    assert resolved.cleanup_required is False


@pytest.mark.asyncio
async def test_mlx_backend_passes_memosight_prompt_text_to_client(tmp_path):
    from memosight.profiles import get_profile
    from memosight.prompts import build_prompt

    _, resolved = _path_source(tmp_path)
    client = FakeMlXVlmClient(response='{"product_type": "手表", "brand_visible": true}')
    backend = MlXVlmMemoSightBackend(client=client)
    prompt = build_prompt(get_profile("product_catalog"), language="zh")

    await backend.describe(resolved, prompt)

    call = client.calls[0]
    assert call["system_prompt"] == prompt.system
    # The ground-rules header is carried by the system message; the user text
    # keeps the schema fields without repeating the header.
    assert "product_type" in call["user_text"]
    assert "brand_visible" in call["user_text"]
    assert not call["user_text"].startswith(prompt.system)


@pytest.mark.asyncio
async def test_mlx_backend_failure_raises_backend_error_chained(tmp_path):
    _, resolved = _path_source(tmp_path)
    boom = RuntimeError("server unreachable")
    backend = MlXVlmMemoSightBackend(client=FakeMlXVlmClient(error=boom))

    with pytest.raises(MemoSightBackendError) as exc_info:
        await backend.describe(resolved, MemoSightPrompt(text="p"))

    assert exc_info.value.__cause__ is boom


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["bytes", "base64"])
async def test_mlx_backend_memory_inputs_use_temp_file_and_clean_up(tmp_path, kind):
    data = PNG_BYTES if kind == "bytes" else PNG_BASE64
    resolved = resolve_image_source(
        MemoSightImageSource(kind=kind, data=data, mime_type="image/png"),
        temp_dir=tmp_path / "memosight-tmp",
    )
    assert resolved.cleanup_required is True
    temp_file = Path(resolved.image_path)
    assert temp_file.exists()

    client = FakeMlXVlmClient(response='{"caption": "ok"}')
    backend = MlXVlmMemoSightBackend(client=client)

    result = await backend.describe(resolved, MemoSightPrompt(text="p", language="zh"))

    assert result == '{"caption": "ok"}'
    assert client.calls[0]["image_path"] == str(temp_file)
    assert client.path_existed_during_call is True
    assert not temp_file.exists()
    assert resolved.cleanup_required is False


@pytest.mark.asyncio
async def test_mlx_backend_failure_still_cleans_up_temp_file(tmp_path):
    resolved = resolve_image_source(
        MemoSightImageSource(kind="bytes", data=PNG_BYTES, mime_type="image/png"),
        temp_dir=tmp_path / "memosight-tmp",
    )
    temp_file = Path(resolved.image_path)
    backend = MlXVlmMemoSightBackend(
        client=FakeMlXVlmClient(error=RuntimeError("boom"))
    )

    with pytest.raises(MemoSightBackendError):
        await backend.describe(resolved, MemoSightPrompt(text="p"))

    assert not temp_file.exists()
