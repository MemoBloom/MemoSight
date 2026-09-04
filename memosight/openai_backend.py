"""OpenAI-compatible backend adapters for MemoSight.

Targets any server exposing ``POST /v1/chat/completions`` with vision content
(vLLM, SGLang, LMDeploy, llama.cpp server, ...). Local image files are sent as
base64 data URIs. When no model name is configured, the model id is resolved
once from ``GET /v1/models``.

Same backend contract as the MLX adapters: backends own cleanup of the
resolved image source, wrap failures in ``MemoSightBackendError``, and return
raw model output (parsing/validation stays in the pipeline).
"""
from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path

import httpx

from .errors import MemoSightBackendError
from .prompts import MemoSightPrompt
from .source import ResolvedImageSource

DEFAULT_OPENAI_BASE_URL = "http://127.0.0.1:8000/v1"


def _image_data_url(path: str) -> str:
    """Encode a local image file as a base64 data URI."""
    mime = mimetypes.guess_type(path)[0] or "image/png"
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


class _OpenAICompatBase:
    """Shared connection and model-id handling for OpenAI-compatible backends."""

    def __init__(
        self,
        base_url: str | None,
        model: str | None,
        *,
        api_key: str | None,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        self._base_url = (
            base_url
            or os.environ.get("MEMOSIGHT_OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)
        ).rstrip("/")
        self._configured_model = model or os.environ.get("MEMOSIGHT_OPENAI_MODEL", "")
        self._api_key = api_key or os.environ.get("MEMOSIGHT_OPENAI_API_KEY", "")
        self._timeout_s = timeout_s
        self._transport = transport
        self._cached_model_id: str | None = None

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    async def _get_model_id(self) -> str:
        """Return the configured model id, or resolve the first /v1/models entry."""
        if self._cached_model_id:
            return self._cached_model_id
        if self._configured_model:
            self._cached_model_id = self._configured_model
            return self._cached_model_id
        async with httpx.AsyncClient(
            timeout=self._timeout_s, trust_env=False, transport=self._transport
        ) as client:
            response = await client.get(
                f"{self._base_url}/models", headers=self._headers()
            )
            response.raise_for_status()
            data = response.json().get("data", [])
        model_id = data[0].get("id") if data and isinstance(data[0], dict) else None
        if not model_id:
            raise MemoSightBackendError(
                "OpenAI-compat server reported no models on /v1/models; "
                "pass the model name explicitly"
            )
        self._cached_model_id = model_id
        return model_id

    async def _complete_chat(self, payload: dict) -> str:
        """POST one non-streaming chat completion and return the message content."""
        async with httpx.AsyncClient(
            timeout=self._timeout_s, trust_env=False, transport=self._transport
        ) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
        choice = (response.json().get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content")
        return content if isinstance(content, str) else ""


class OpenAICompatBackend(_OpenAICompatBase):
    """MemoSight image backend over an OpenAI-compatible vision server."""

    name = "openai_compat"
    version = "1.0.0"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        *,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url,
            model,
            api_key=api_key,
            timeout_s=timeout_s,
            transport=transport,
        )

    async def describe(
        self, image: ResolvedImageSource, prompt: MemoSightPrompt
    ) -> str:
        """Describe ``image`` under ``prompt`` via /v1/chat/completions.

        The system ground-rules header is sent as the system message and
        stripped from the user text to avoid delivering it twice (same
        contract as :class:`MlXVlmMemoSightBackend`).
        """
        try:
            model_id = await self._get_model_id()
            system = prompt.system or ""
            user_text = prompt.text
            if system and user_text.startswith(system):
                user_text = user_text[len(system):].lstrip()
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": _image_data_url(image.image_path)
                                },
                            },
                        ],
                    },
                ],
                "max_tokens": prompt.max_tokens or 768,
                "temperature": 0.1,
            }
            return await self._complete_chat(payload)
        except Exception as exc:
            raise MemoSightBackendError(
                f"OpenAI-compat backend describe failed for {image.image_path}: {exc}"
            ) from exc
        finally:
            image.cleanup()


class OpenAICompatTextBackend(_OpenAICompatBase):
    """Text-only MemoSight backend over an OpenAI-compatible server."""

    name = "openai_compat_text"
    version = "1.0.0"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        *,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url,
            model,
            api_key=api_key,
            timeout_s=timeout_s,
            transport=transport,
        )

    async def complete(self, prompt: MemoSightPrompt) -> str:
        """Run a text-only completion for ``prompt``."""
        try:
            model_id = await self._get_model_id()
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": prompt.system or ""},
                    {"role": "user", "content": prompt.text},
                ],
                "max_tokens": prompt.max_tokens or 384,
                "temperature": 0.1,
            }
            return await self._complete_chat(payload)
        except Exception as exc:
            raise MemoSightBackendError(
                f"OpenAI-compat text completion failed: {exc}"
            ) from exc
