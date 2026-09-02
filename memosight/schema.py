"""Public request and response models for the MemoSight module."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .validator import MemoSightValidationResult


class MemoSightImageSource(BaseModel):
    """An image input: filesystem path, raw bytes, or base64 payload."""

    kind: Literal["path", "bytes", "base64"] = "path"
    image_path: str | None = None
    data: bytes | str | None = None
    mime_type: str | None = None
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoSightRequest(BaseModel):
    """Caller request for a structured visual observation."""

    image: MemoSightImageSource
    asset_id: str | None = None
    language: Literal["zh", "en"] | str = "zh"
    domain_hint: str | None = None
    profile: str = "photography_default"
    output_schema: dict[str, Any] | None = None
    output_instructions: str | None = None
    prompt_plan: dict[str, Any] | None = None
    prompt_config: dict[str, Any] | str | Path | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class MemoSightObservation(BaseModel):
    """Stable default structured visual observation."""

    caption: str
    scene_labels: list[str] = Field(default_factory=list, max_length=6)
    people: list[str] = Field(default_factory=list, max_length=6)
    actions: list[str] = Field(default_factory=list, max_length=6)
    objects: list[str] = Field(default_factory=list, max_length=6)
    lighting: list[str] = Field(default_factory=list, max_length=6)
    mood: list[str] = Field(default_factory=list, max_length=6)
    search_tags: list[str] = Field(default_factory=list, max_length=6)


class MemoSightResult(BaseModel):
    """Pipeline result: caller-requested observation plus validation metadata.

    ``observation`` is the actual caller-requested output.
    ``default_observation`` is populated when the default schema is used, or
    when MemoSight can safely map custom output back to the default
    observation; MemoBrain persistence should prefer it for search/RAG flows.
    """

    status: Literal["ok", "failed", "partial"]
    observation: dict[str, Any]
    default_observation: MemoSightObservation | None = None
    raw_output: str | None = None
    schema_name: str | None = None
    schema_version: str = "1.0.0"
    model_name: str | None = None
    model_version: str | None = None
    validation: MemoSightValidationResult
    usage: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class MemoSightFieldExtractionResult(BaseModel):
    """Independent stage-two result, suitable for retry without an image."""

    status: Literal["ok", "failed"]
    fields: dict[str, Any]
    raw_output: str | None = None
    validation: MemoSightValidationResult
    usage: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class TwoStageMemoSightResult(MemoSightResult):
    """MemoSight result with the two raw stage outputs kept separately."""

    caption_raw_output: str | None = None
    structured_raw_output: str | None = None
    failed_stage: Literal["caption", "field_extraction"] | None = None
