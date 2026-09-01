"""Regression tests for selecting the model already loaded by mlx-vlm."""
from __future__ import annotations

import pytest

from memosight import mlx_client
from memosight.mlx_client import MlXVlmClient


class FakeResponse:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakeHttpClient:
    def __init__(self, models: list[str], loaded_model: str):
        self.models = models
        self.loaded_model = loaded_model

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url: str) -> FakeResponse:
        if url.endswith("/v1/models"):
            return FakeResponse({"data": [{"id": model} for model in self.models]})
        return FakeResponse({"loaded_model": self.loaded_model})


@pytest.mark.asyncio
async def test_loaded_model_wins_over_unrelated_first_list_entry(monkeypatch):
    local_model = "/models/Qwen3.5-2B-MLX-4bit"
    fake = FakeHttpClient(["mlx-community/Qwen3.5-0.8B-bf16"], local_model)
    client = MlXVlmClient("http://localhost:8081")

    async def get_client():
        return fake

    monkeypatch.setattr(client, "_get_client", get_client)
    monkeypatch.setattr(mlx_client.settings, "MLX_VLM_MODEL_NAME", local_model)

    assert await client._get_model_id() == local_model


@pytest.mark.asyncio
async def test_configured_short_name_can_match_server_model_id(monkeypatch):
    listed_model = "mlx-community/Qwen3.5-2B-MLX-4bit"
    fake = FakeHttpClient([listed_model], "/models/another-model")
    client = MlXVlmClient("http://localhost:8081")

    async def get_client():
        return fake

    monkeypatch.setattr(client, "_get_client", get_client)
    monkeypatch.setattr(
        mlx_client.settings, "MLX_VLM_MODEL_NAME", "Qwen3.5-2B-MLX-4bit"
    )

    assert await client._get_model_id() == listed_model
