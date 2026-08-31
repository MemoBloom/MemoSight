"""Backend protocol and adapters for MemoSight.

The protocol and mock backend are pure. The MLX adapter lazy-imports the
project's ``MlXVlmClient`` inside ``_get_client()`` so this module stays
importable without the MLX service stack (httpx/settings).

Backend lifecycle contract: implementations own cleanup of the resolved
image source — call ``image.cleanup()`` when done (e.g. in a ``finally``
block) so temp files materialized for bytes/base64 inputs never leak.
Caller-owned path sources are never touched by ``cleanup()``.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel

from .errors import MemoSightBackendError
from .prompts import MemoSightPrompt
from .source import ResolvedImageSource

if TYPE_CHECKING:
    from .mlx_client import MlXVlmClient

DEFAULT_MOCK_RESPONSE = json.dumps(
    {
        "caption": "mock caption",
        "scene_labels": ["mock"],
        "people": [],
        "actions": [],
        "objects": [],
        "lighting": [],
        "mood": [],
        "search_tags": ["mock"],
    },
    ensure_ascii=False,
)


@runtime_checkable
class MemoSightBackend(Protocol):
    """Async image-description backend returning raw model output."""

    name: str
    version: str

    async def describe(
        self, image: ResolvedImageSource, prompt: MemoSightPrompt
    ) -> str:
        """Return the raw model output for ``image`` under ``prompt``."""
        ...


class MlXVlmMemoSightBackend:
    """MemoSight backend over the project's ``MlXVlmClient`` (D-01 HTTP server)."""

    name = "mlx_vlm"
    version = "1.0.0"

    def __init__(self, client: MlXVlmClient | None = None) -> None:
        self._client = client

    def _get_client(self) -> MlXVlmClient:
        if self._client is None:
            from .mlx_client import MlXVlmClient

            self._client = MlXVlmClient()
        return self._client

    async def describe(
        self, image: ResolvedImageSource, prompt: MemoSightPrompt
    ) -> str:
        """Delegate to ``MlXVlmClient.describe`` with path, language, and prompt.

        The MemoSight-constructed prompt is always passed through via the
        client's ``system_prompt``/``user_text`` overrides: the client's
        built-in describe prompts are NOT equivalent to the MemoSight output
        contract (zh built-in asks for free text, en built-in asks for a
        caption-only JSON object), so MemoSight must own prompt delivery for
        default and custom schemas alike. The system ground-rules header is
        sent as the system message and stripped from the user text to avoid
        delivering it twice.

        Backend call failures surface as ``MemoSightBackendError`` with the
        underlying error chained. The resolved source is cleaned up in all
        cases, so temp files for bytes/base64 inputs are removed even when
        the backend call fails.
        """
        overrides: dict[str, str] = {}
        user_text = prompt.text
        if prompt.system:
            overrides["system_prompt"] = prompt.system
            if user_text.startswith(prompt.system):
                user_text = user_text[len(prompt.system):].lstrip()
        overrides["user_text"] = user_text
        try:
            # Client acquisition lives inside the try so a construction
            # failure is wrapped and the resolved source is still cleaned up.
            client = self._get_client()
            return await client.describe(
                image.image_path, language=prompt.language, **overrides
            )
        except Exception as exc:
            raise MemoSightBackendError(
                f"MLX-VLM backend describe failed for {image.image_path}: {exc}"
            ) from exc
        finally:
            image.cleanup()


class MemoSightBackendCall(BaseModel):
    """Recorded mock backend invocation for test assertions."""

    image_path: str
    prompt: MemoSightPrompt


class MockMemoSightBackend:
    """Deterministic backend for tests: fixed response, recorded calls."""

    name = "mock"
    version = "1.0.0"

    def __init__(self, response: str | None = None) -> None:
        self.response = response if response is not None else DEFAULT_MOCK_RESPONSE
        self.calls: list[MemoSightBackendCall] = []

    async def describe(
        self, image: ResolvedImageSource, prompt: MemoSightPrompt
    ) -> str:
        self.calls.append(
            MemoSightBackendCall(image_path=image.image_path, prompt=prompt)
        )
        try:
            return self.response
        finally:
            image.cleanup()
