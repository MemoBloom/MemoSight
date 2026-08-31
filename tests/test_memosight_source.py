"""Tests for memosight.source — image source normalization."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

import pytest

from memosight.errors import MemoSightInputError
from memosight.schema import MemoSightImageSource
from memosight.source import ResolvedImageSource, resolve_image_source

# 1x1 transparent PNG.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode("ascii")


def test_path_source_resolves_existing_file(tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0")
    source = MemoSightImageSource(
        kind="path",
        image_path=str(image),
        filename="photo.jpg",
        mime_type="image/jpeg",
        width=100,
        height=80,
        metadata={"camera": "x100v"},
    )

    resolved = resolve_image_source(source)

    assert resolved.kind == "path"
    assert resolved.image_path == str(image)
    assert resolved.original_filename == "photo.jpg"
    assert resolved.mime_type == "image/jpeg"
    assert resolved.width == 100
    assert resolved.height == 80
    assert resolved.metadata == {"camera": "x100v"}
    assert resolved.cleanup_required is False


def test_path_source_cleanup_never_touches_original(tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0")
    resolved = resolve_image_source(MemoSightImageSource(image_path=str(image)))

    resolved.cleanup()

    assert image.exists()
    assert resolved.cleanup_required is False


def test_missing_path_raises_input_error(tmp_path):
    source = MemoSightImageSource(image_path=str(tmp_path / "nope.jpg"))

    with pytest.raises(MemoSightInputError, match="not found"):
        resolve_image_source(source)


def test_path_source_requires_image_path():
    with pytest.raises(MemoSightInputError, match="image_path"):
        resolve_image_source(MemoSightImageSource(kind="path"))


def test_bytes_source_writes_temp_file():
    source = MemoSightImageSource(
        kind="bytes",
        data=PNG_BYTES,
        filename="pixel.png",
        mime_type="image/png",
        metadata={"origin": "upload"},
    )

    resolved = resolve_image_source(source)

    try:
        assert resolved.kind == "bytes"
        assert resolved.cleanup_required is True
        temp_path = Path(resolved.image_path)
        assert temp_path.is_file()
        assert temp_path.read_bytes() == PNG_BYTES
        assert temp_path.suffix == ".png"
        assert resolved.original_filename == "pixel.png"
        assert resolved.metadata == {"origin": "upload"}
    finally:
        resolved.cleanup()


def test_base64_source_writes_temp_file():
    source = MemoSightImageSource(kind="base64", data=PNG_BASE64, mime_type="image/png")

    resolved = resolve_image_source(source)

    try:
        assert resolved.kind == "base64"
        assert resolved.cleanup_required is True
        assert Path(resolved.image_path).read_bytes() == PNG_BYTES
    finally:
        resolved.cleanup()


def test_base64_source_accepts_data_uri_prefix():
    source = MemoSightImageSource(
        kind="base64", data=f"data:image/png;base64,{PNG_BASE64}"
    )

    resolved = resolve_image_source(source)

    try:
        assert Path(resolved.image_path).read_bytes() == PNG_BYTES
        assert resolved.mime_type == "image/png"
        assert Path(resolved.image_path).suffix == ".png"
    finally:
        resolved.cleanup()


def test_invalid_base64_raises_input_error():
    source = MemoSightImageSource(kind="base64", data="not-valid-base64!!!")

    with pytest.raises(MemoSightInputError, match="base64"):
        resolve_image_source(source)


def test_bytes_source_requires_bytes_data():
    source = MemoSightImageSource(kind="bytes", data="a string, not bytes")

    with pytest.raises(MemoSightInputError, match="bytes"):
        resolve_image_source(source)


def test_missing_data_raises_input_error():
    with pytest.raises(MemoSightInputError, match="data"):
        resolve_image_source(MemoSightImageSource(kind="base64"))


def test_temp_files_live_under_controlled_temp_dir():
    resolved = resolve_image_source(MemoSightImageSource(kind="bytes", data=PNG_BYTES))

    try:
        temp_root = os.path.realpath(tempfile.gettempdir())
        assert os.path.realpath(resolved.image_path).startswith(temp_root + os.sep)
    finally:
        resolved.cleanup()


def test_custom_temp_dir_is_used(tmp_path):
    custom = tmp_path / "memosight-tmp"

    resolved = resolve_image_source(
        MemoSightImageSource(kind="bytes", data=PNG_BYTES), temp_dir=custom
    )

    try:
        assert Path(resolved.image_path).parent == custom
    finally:
        resolved.cleanup()


def test_temp_file_cleaned_up_after_pipeline_execution(tmp_path):
    """Simulate a pipeline run: resolve, use the path, then clean up."""
    resolved = resolve_image_source(
        MemoSightImageSource(kind="base64", data=PNG_BASE64), temp_dir=tmp_path
    )
    temp_path = Path(resolved.image_path)
    assert temp_path.exists()

    resolved.cleanup()

    assert not temp_path.exists()
    assert resolved.cleanup_required is False
    # Cleanup is idempotent.
    resolved.cleanup()
    assert not temp_path.exists()


def test_cleanup_refuses_files_outside_temp_root(tmp_path):
    """A hand-built resolved source must not be able to delete arbitrary files."""
    victim = tmp_path / "important.jpg"
    victim.write_bytes(b"keep me")
    resolved = ResolvedImageSource(
        kind="bytes", image_path=str(victim), cleanup_required=True
    )

    resolved.cleanup()

    assert victim.exists()
