"""MemoSight — reusable image-to-structured-visual-text module.

Pure foundations: schemas, errors, output parsing, field normalization,
validation, and backend adapters. No database, FastAPI, Arq, or Redis
dependencies; the MLX-VLM client is lazy-imported by the backend adapter.
"""
from .backends import (
    DEFAULT_MOCK_RESPONSE,
    MemoSightBackend,
    MemoSightBackendCall,
    MlXVlmMemoSightBackend,
    MockMemoSightBackend,
)
from .errors import (
    MemoSightBackendError,
    MemoSightError,
    MemoSightInputError,
    MemoSightParseError,
    MemoSightSchemaError,
    MemoSightValidationError,
)
from .normalizer import (
    CAPTION_FIELD_KEYS,
    empty_caption_fields,
    normalize_caption_fields,
)
from .pipeline import MemoSightPipeline
from .parser import (
    MemoSightParseIssue,
    MemoSightParseResult,
    parse_markdown_fields,
    parse_model_output,
)
from .profiles import (
    CUSTOM_PROFILE_NAME,
    DEFAULT_PROFILE_NAME,
    MAX_ARRAY_ITEMS,
    MAX_ENUM_CHOICES,
    MAX_NESTED_DEPTH,
    MAX_SCHEMA_JSON_BYTES,
    MAX_TOP_LEVEL_FIELDS,
    PROFILES,
    MemoSightProfile,
    get_profile,
    list_profiles,
    resolve_profile,
    validate_output_schema,
)
from .prompts import MemoSightPrompt, build_prompt
from .schema import (
    MemoSightImageSource,
    MemoSightObservation,
    MemoSightRequest,
    MemoSightResult,
)
from .source import (
    ResolvedImageSource,
    resolve_image_source,
)
from .validator import (
    MemoSightValidationIssue,
    MemoSightValidationResult,
    MemoSightValidator,
)

__all__ = [
    "CAPTION_FIELD_KEYS",
    "CUSTOM_PROFILE_NAME",
    "DEFAULT_MOCK_RESPONSE",
    "DEFAULT_PROFILE_NAME",
    "MAX_ARRAY_ITEMS",
    "MAX_ENUM_CHOICES",
    "MAX_NESTED_DEPTH",
    "MAX_SCHEMA_JSON_BYTES",
    "MAX_TOP_LEVEL_FIELDS",
    "PROFILES",
    "MemoSightBackend",
    "MemoSightBackendCall",
    "MemoSightBackendError",
    "MemoSightError",
    "MemoSightImageSource",
    "MemoSightInputError",
    "MemoSightObservation",
    "MemoSightParseError",
    "MemoSightParseIssue",
    "MemoSightParseResult",
    "MemoSightPipeline",
    "MemoSightProfile",
    "MemoSightPrompt",
    "MemoSightRequest",
    "MemoSightResult",
    "MemoSightSchemaError",
    "MemoSightValidationError",
    "MemoSightValidationIssue",
    "MemoSightValidationResult",
    "MemoSightValidator",
    "MlXVlmMemoSightBackend",
    "MockMemoSightBackend",
    "ResolvedImageSource",
    "build_prompt",
    "empty_caption_fields",
    "get_profile",
    "list_profiles",
    "normalize_caption_fields",
    "parse_markdown_fields",
    "parse_model_output",
    "resolve_image_source",
    "resolve_profile",
    "validate_output_schema",
]
