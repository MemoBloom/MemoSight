"""MlXVlmClient — HTTP client adapter for mlx_vlm.server (D-01).

Communicates with the local MLX-VLM FastAPI server via
OpenAI-compatible /v1/chat/completions endpoint with image content.
Supports describe(), answer(), analyze_quality(), complete_text(), and health() operations.

Per D-01: MLX-VLM runs as an HTTP server. This adapter wraps the
HTTP client — it does NOT load the model in-process.
"""

import asyncio

import httpx
import json
import os
from .mlx_prompts import (
    DESCRIBE_SYSTEM_PROMPT,
    DESCRIBE_SYSTEM_PROMPT_EN,
    DESCRIBE_SYSTEM_PROMPT_ZH,
    ANALYZE_QUALITY_SYSTEM_PROMPT,
    ANSWER_QUESTION_SYSTEM_PROMPT,
)


class _Settings:
    """Minimal env-based config replacing the host app's settings object.

    MEMOSIGHT_MLX_SERVER_URL (default http://127.0.0.1:8080)
    MEMOSIGHT_MLX_MODEL_NAME (default "" — first server model is used)
    MEMOSIGHT_MLX_TIMEOUT_S (default 60)
    """

    MLX_VLM_SERVER_URL: str = os.environ.get(
        "MEMOSIGHT_MLX_SERVER_URL", "http://127.0.0.1:8080"
    )
    MLX_VLM_MODEL_NAME: str = os.environ.get("MEMOSIGHT_MLX_MODEL_NAME", "")
    MLX_VLM_TIMEOUT_S: float = float(os.environ.get("MEMOSIGHT_MLX_TIMEOUT_S", "60"))


settings = _Settings()

FASTVLM_GENERATION_CONFIG = {
    "temperature": 0.1,
}

QWEN_VL_NON_THINKING_GENERATION_CONFIG = {
    # Structured extraction benefits from deterministic, compact output.
    # Keep a small non-zero temperature for broad mlx-vlm compatibility.
    "temperature": 0.1,
    "top_p": 0.9,
    "top_k": 20,
    "min_p": 0.0,
    "presence_penalty": 0.0,
    "repetition_penalty": 1.0,
}

# Repetition-abort tuning for streamed decode. Small VLMs sometimes enter a
# repetition loop (e.g. the same array item emitted until max_tokens); once a
# loop is confirmed, the remaining decode is pure waste, so the stream is
# aborted early. Thresholds are deliberately conservative: short duplicate
# runs (a few identical array items) finish normally and are handled by
# normalization downstream — only sustained repetition past
# _REPEAT_MIN_CHARS is treated as a loop.
_REPEAT_CHECK_AFTER = 240  # don't scan before the output reaches this size
_REPEAT_TAIL = 512  # suffix window scanned for loops
_REPEAT_MIN_BLOCK = 8  # shortest repeated block considered a loop
_REPEAT_MAX_BLOCK = 80
_REPEAT_MIN_TIMES = 4  # consecutive repeats required, regardless of block size
_REPEAT_MIN_LOOP_CHARS = 240  # ...and the loop must span at least this many chars

# Stall watchdog for streamed decode. The server's SSE heartbeats keep
# resetting the HTTP read timeout, so a stalled server-side decode would
# otherwise hang forever; abort if no content arrives for this long.
_DECODE_STALL_TIMEOUT_S = 45.0


def _find_repetition_loop(text: str) -> tuple[int, int] | None:
    """Return ``(start, block_size)`` of a repetition-loop suffix, or None.

    A loop is a suffix consisting of one block (8..80 chars, not all
    whitespace) repeated consecutively at least max(4, 240/size) times.
    ``start`` is the index of the first copy in the trailing run.
    """
    if len(text) < _REPEAT_CHECK_AFTER:
        return None
    tail = text[-_REPEAT_TAIL:]
    for size in range(_REPEAT_MIN_BLOCK, _REPEAT_MAX_BLOCK + 1):
        times = max(_REPEAT_MIN_TIMES, -(-_REPEAT_MIN_LOOP_CHARS // size))
        if size * times > len(tail):
            continue
        block = tail[-size:]
        if not block.strip():
            continue
        if tail.endswith(block * times):
            return len(text) - size * times, size
    return None



class MlXVlmClient:
    """HTTP client adapter for mlx_vlm.server.

    All VLM operations go through the server's OpenAI-compatible endpoints.
    Supports health checks, single-image describe/answer, and batch analysis.
    """

    def __init__(self, base_url: str | None = None):
        self._base_url = (base_url or settings.MLX_VLM_SERVER_URL).rstrip("/")

    async def _get_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=float(settings.MLX_VLM_TIMEOUT_S),
            trust_env=False,
        )

    # ── Health ──

    async def health(self) -> dict:
        """Check MLX-VLM server health via GET /health.

        Returns: {"ok": bool, "status_code": int, "body": dict}
        """
        async with await self._get_client() as client:
            r = await client.get(f"{self._base_url}/health")
            body = {}
            try:
                body = r.json()
            except Exception:
                pass
            return {
                "ok": 200 <= r.status_code < 300,
                "status_code": r.status_code,
                "body": body,
            }

    # ── Single-image operations ──

    async def describe(
        self,
        image_path: str,
        language: str = "zh",
        *,
        system_prompt: str | None = None,
        user_text: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a structured description of an image.

        Uses DESCRIBE_SYSTEM_PROMPT to request JSON output with
        caption, retrieval tags, scene labels, and visible subject keys.

        Callers such as MemoSight may pass explicit ``system_prompt`` /
        ``user_text`` overrides; when omitted, the built-in language-based
        prompts are used unchanged (fully backward compatible).
        """
        call_kwargs = {
            "image_path": image_path,
            "system_prompt": (
                system_prompt
                if system_prompt is not None
                else self._describe_prompt_for_language(language)
            ),
            "user_text": (
                user_text
                if user_text is not None
                else self._describe_user_text_for_language(language)
            ),
        }
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens
        return await self._chat_with_image(**call_kwargs)

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_text: str,
        max_tokens: int | None = None,
    ) -> str:
        """Run a text-only completion on the loaded multimodal model."""
        model_id = await self._get_model_id()
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": max_tokens or 384,
            "stream": True,
            **self._generation_config_for_model(model_id),
        }
        return await self._stream_chat(payload)

    async def answer(self, image_path: str, question: str) -> str:
        """Answer a specific question about an image."""
        return await self._chat_with_image(
            image_path=image_path,
            system_prompt=ANSWER_QUESTION_SYSTEM_PROMPT,
            user_text=question,
        )

    async def analyze_quality(self, image_path: str) -> str:
        """Analyze technical quality of an image, returning JSON scores."""
        return await self._chat_with_image(
            image_path=image_path,
            system_prompt=ANALYZE_QUALITY_SYSTEM_PROMPT,
            user_text="Analyze the technical quality of this photograph.",
        )

    # ── Internal helpers ──

    def _describe_prompt_for_language(self, language: str) -> str:
        normalized = (language or "zh").lower()
        if normalized in {"en", "english"}:
            return DESCRIBE_SYSTEM_PROMPT_EN
        if normalized in {"zh", "cn", "chinese"}:
            return DESCRIBE_SYSTEM_PROMPT_ZH
        return DESCRIBE_SYSTEM_PROMPT

    def _describe_user_text_for_language(self, language: str) -> str:
        normalized = (language or "zh").lower()
        if normalized in {"en", "english"}:
            return "Return the compact retrieval JSON only."
        return "用100个字内描述这张照片，方便以后搜索和整理。只描述可见内容。"

    def finish_reason(self, text: str | None = None) -> dict:
        """Return normalized finish diagnostics for the latest VLM response.

        The server-level finish_reason is authoritative when it reports
        ``length``. Text-shape checks catch malformed completions where the
        provider says ``stop`` but the JSON or markdown fence is still open.
        """
        meta = getattr(self, "_last_response_meta", {}) or {}
        reason = meta.get("finish_reason") or "unknown"
        usage = meta.get("usage") or {}
        checks = {
            "server_length": reason == "length",
            "empty_output": text == "",
            "unclosed_markdown_fence": False,
            "unclosed_json_object": False,
            "non_english_output": False,
        }
        if text:
            stripped = text.strip()
            checks["non_english_output"] = self._contains_cjk(stripped)
            checks["unclosed_markdown_fence"] = (
                stripped.startswith("```") and not stripped.endswith("```")
            )
            if "{" in stripped:
                checks["unclosed_json_object"] = stripped.rfind("}") < stripped.find("{")
        truncated = any(
            checks[key]
            for key in (
                "server_length",
                "unclosed_markdown_fence",
                "unclosed_json_object",
            )
        )
        bad_truncation = truncated and reason != "length"
        source = "server" if checks["server_length"] else "text_shape" if truncated else "server"
        return {
            "reason": reason,
            "truncated": truncated,
            "bad_truncation": bad_truncation,
            "language_violation": checks["non_english_output"],
            "source": source,
            "usage": usage,
            "checks": checks,
        }

    def _is_truncated_output(self, text: str | None) -> bool:
        """Best-effort truncation detection for OpenAI-compatible responses."""
        return bool(self.finish_reason(text).get("truncated"))

    def _contains_cjk(self, text: str) -> bool:
        """Return True when text contains CJK characters in English-only output."""
        return any(
            "\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"
            for char in text
        )

    def _generation_config_for_model(self, model_id: str) -> dict:
        normalized = (model_id or "").lower()
        if "qwen" in normalized:
            return QWEN_VL_NON_THINKING_GENERATION_CONFIG
        return FASTVLM_GENERATION_CONFIG

    async def _get_model_id(self) -> str:
        """Resolve the model identifier from the server's /v1/models endpoint.

        MLX-VLM servers often register the full model path as the model_id,
        whereas the configured MLX_VLM_MODEL_NAME may be a short basename.
        We query the server once and cache the result so subsequent calls
        reuse the resolved id without extra HTTP overhead.
        """
        if hasattr(self, "_cached_model_id"):
            return self._cached_model_id
        model_ids: list[str] = []
        async with await self._get_client() as client:
            try:
                r = await client.get(f"{self._base_url}/v1/models")
                if 200 <= r.status_code < 300:
                    body = r.json()
                    model_ids = [
                        item.get("id")
                        for item in body.get("data", [])
                        if isinstance(item, dict) and item.get("id")
                    ]
                    configured = settings.MLX_VLM_MODEL_NAME
                    if configured:
                        for mid in model_ids:
                            if mid == configured or mid.endswith(configured):
                                self._cached_model_id = mid
                                return mid
            except Exception:
                pass

            try:
                health = await client.get(f"{self._base_url}/health")
                if 200 <= health.status_code < 300:
                    body = health.json()
                    loaded_model = body.get("loaded_model")
                    if loaded_model:
                        self._cached_model_id = loaded_model
                        return loaded_model
            except Exception:
                pass
        if model_ids:
            self._cached_model_id = model_ids[0]
            return model_ids[0]
        self._cached_model_id = settings.MLX_VLM_MODEL_NAME
        return self._cached_model_id

    async def _chat_with_image(
        self,
        image_path: str,
        system_prompt: str,
        user_text: str,
        max_tokens: int | None = None,
    ) -> str:
        """Call mlx_vlm.server /v1/chat/completions with an image.

        Uses OpenAI-compatible format with input_image content type
        per mlx-vlm server API. The request is streamed so a repetition
        loop can abort the decode early (``finish_reason`` is then reported
        as ``repetition_aborted``); closing the SSE response cancels the
        server-side generation.
        """
        model_id = await self._get_model_id()
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_text},
                        {"type": "input_image", "image_url": image_path},
                    ],
                },
            ],
            "max_tokens": max_tokens or 768,
            "stream": True,
            **self._generation_config_for_model(model_id),
        }
        return await self._stream_chat(payload)

    async def _stream_chat(self, payload: dict) -> str:
        """Stream one chat completion with repetition and stall protection."""
        parts: list[str] = []
        finish_reason: str | None = None
        usage: dict = {}
        keep_blocks = 1  # copies of the repeated block preserved on abort
        trim_to: int | None = None
        async with await self._get_client() as client:
            async with client.stream(
                "POST", f"{self._base_url}/v1/chat/completions", json=payload
            ) as r:
                r.raise_for_status()
                lines = r.aiter_lines()
                while True:
                    try:
                        line = await asyncio.wait_for(
                            anext(lines), timeout=_DECODE_STALL_TIMEOUT_S
                        )
                    except StopAsyncIteration:
                        break
                    except TimeoutError:
                        finish_reason = "decode_stalled"
                        break
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    choice = (chunk.get("choices") or [{}])[0]
                    content = (choice.get("delta") or {}).get("content")
                    if content:
                        parts.append(content)
                        text = "".join(parts)
                        loop = _find_repetition_loop(text)
                        if loop is not None:
                            start, size = loop
                            finish_reason = "repetition_aborted"
                            # Keep the first copy of the repeated block; the
                            # rest of the loop is discarded.
                            trim_to = start + size * keep_blocks
                            break
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
        text = "".join(parts)
        self._last_response_meta = {
            "finish_reason": finish_reason,
            "usage": usage,
        }
        return text if trim_to is None else text[:trim_to]
