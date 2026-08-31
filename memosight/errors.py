"""Typed errors for the MemoSight module."""
from __future__ import annotations


class MemoSightError(Exception):
    """Base error for all MemoSight failures."""


class MemoSightInputError(MemoSightError):
    """Invalid or unusable image source / request input."""


class MemoSightBackendError(MemoSightError):
    """Model backend call failed."""


class MemoSightParseError(MemoSightError):
    """Model output could not be parsed into structured data."""


class MemoSightValidationError(MemoSightError):
    """Parsed output failed schema validation."""


class MemoSightSchemaError(MemoSightError):
    """Caller-supplied output schema is invalid or unsupported."""
