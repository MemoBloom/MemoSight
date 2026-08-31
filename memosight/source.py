"""Normalize MemoSight image inputs into path-backed resolved sources.

``kind="path"`` sources are validated for existence and never modified.
``kind="bytes"`` / ``kind="base64"`` sources are materialized to a temp file
under a controlled temp directory only when a path is required (i.e. when the
caller resolves them through this module for a path-requiring backend); call
``ResolvedImageSource.cleanup()`` after pipeline execution to remove them.
"""
from __future__ import annotations

import base64
import binascii
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from .errors import MemoSightInputError
from .schema import MemoSightImageSource

DEFAULT_TEMP_DIR = Path(tempfile.gettempdir()) / "memosight"


class ResolvedImageSource(BaseModel):
    """Path-backed image source handed to backends.

    ``cleanup_required`` is True when the resolver materialized a temp file
    for a bytes/base64 input; ``cleanup()`` removes exactly that file and
    nothing else.
    """

    kind: str
    image_path: str
    original_filename: str | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    cleanup_required: bool = False

    _temp_root: str | None = PrivateAttr(default=None)

    def cleanup(self) -> None:
        """Remove the materialized temp file, if any.

        Only files created by :func:`resolve_image_source` under its temp
        root are removed; caller-owned path sources are never touched.
        Idempotent.
        """
        if not self.cleanup_required or self._temp_root is None:
            return
        path = os.path.realpath(self.image_path)
        root = os.path.realpath(self._temp_root)
        if not path.startswith(root + os.sep):
            return
        Path(self.image_path).unlink(missing_ok=True)
        self.cleanup_required = False


def resolve_image_source(
    source: MemoSightImageSource,
    *,
    temp_dir: str | Path | None = None,
) -> ResolvedImageSource:
    """Normalize a ``MemoSightImageSource`` into a path-backed resolved source.

    Path sources are validated and passed through untouched. Bytes and
    base64 sources are decoded and written to a temp file under ``temp_dir``
    (default: ``DEFAULT_TEMP_DIR``); the result carries
    ``cleanup_required=True`` and must be cleaned up by the caller.

    Raises ``MemoSightInputError`` for missing paths, missing payloads, or
    undecodable base64 data.
    """
    if source.kind == "path":
        return _resolve_path_source(source)
    payload, data_uri_mime = _extract_bytes(source)
    return _materialize_temp_file(source, payload, data_uri_mime, temp_dir=temp_dir)


def _resolve_path_source(source: MemoSightImageSource) -> ResolvedImageSource:
    if not source.image_path:
        raise MemoSightInputError("kind='path' requires image_path")
    path = Path(source.image_path)
    if not path.is_file():
        raise MemoSightInputError(f"Image file not found: {source.image_path}")
    return ResolvedImageSource(
        kind="path",
        image_path=str(path),
        original_filename=source.filename or path.name,
        mime_type=source.mime_type,
        width=source.width,
        height=source.height,
        metadata=dict(source.metadata),
        cleanup_required=False,
    )


def _extract_bytes(source: MemoSightImageSource) -> tuple[bytes, str | None]:
    """Return the raw image payload plus any MIME type from a data URI."""
    data = source.data
    if data is None:
        raise MemoSightInputError(f"kind='{source.kind}' requires data")
    if source.kind == "bytes":
        if not isinstance(data, (bytes, bytearray)):
            raise MemoSightInputError("kind='bytes' requires data as bytes, not str")
        return bytes(data), None

    # kind == "base64"
    if isinstance(data, (bytes, bytearray)):
        try:
            text = bytes(data).decode("ascii")
        except UnicodeDecodeError as exc:
            raise MemoSightInputError("base64 data must be ASCII text") from exc
    else:
        text = data
    text = text.strip()

    data_uri_mime: str | None = None
    if text.startswith("data:"):
        header, _, text = text.partition(",")
        if ";base64" not in header:
            raise MemoSightInputError("Unsupported data URI: expected base64 payload")
        data_uri_mime = header[len("data:"):].split(";")[0] or None

    try:
        return base64.b64decode(text, validate=True), data_uri_mime
    except (binascii.Error, ValueError) as exc:
        raise MemoSightInputError(f"Invalid base64 image data: {exc}") from exc


def _materialize_temp_file(
    source: MemoSightImageSource,
    payload: bytes,
    data_uri_mime: str | None,
    *,
    temp_dir: str | Path | None,
) -> ResolvedImageSource:
    root = Path(temp_dir) if temp_dir is not None else DEFAULT_TEMP_DIR
    root.mkdir(parents=True, exist_ok=True)
    mime_type = source.mime_type or data_uri_mime
    fd, temp_path = tempfile.mkstemp(
        prefix="memosight-", suffix=_guess_suffix(source, mime_type), dir=root
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise
    resolved = ResolvedImageSource(
        kind=source.kind,
        image_path=temp_path,
        original_filename=source.filename,
        mime_type=mime_type,
        width=source.width,
        height=source.height,
        metadata=dict(source.metadata),
        cleanup_required=True,
    )
    resolved._temp_root = str(root)
    return resolved


def _guess_suffix(source: MemoSightImageSource, mime_type: str | None) -> str:
    if source.filename:
        suffix = Path(source.filename).suffix
        if suffix:
            return suffix
    if mime_type:
        return mimetypes.guess_extension(mime_type) or ".bin"
    return ".bin"
