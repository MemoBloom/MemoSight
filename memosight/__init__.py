"""MemoSight — reusable image-to-structured-visual-text module.

Pure foundations: schemas, errors, output parsing, field normalization,
validation, and backend adapters. No database, FastAPI, Arq, or Redis
dependencies; the MLX-VLM client is lazy-imported by the backend adapter.
"""
from .backends import (
    DEFAULT_MOCK_RESPONSE,
    MemoSightBackend,
    MemoSightBackendCall,
    MemoSightTextBackend,
    MlXTextMemoSightBackend,
    MlXVlmMemoSightBackend,
    MockMemoSightBackend,
    MockMemoSightTextBackend,
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
    find_markdown_field_keys,
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
from .prompts import (
    MemoSightPrompt,
    build_caption_field_extraction_prompt,
    build_caption_prompt,
    build_prompt,
)
from .schema import (
    MemoSightFieldExtractionResult,
    MemoSightImageSource,
    MemoSightObservation,
    MemoSightRequest,
    MemoSightResult,
    TwoStageMemoSightResult,
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
from .two_stage import TwoStageMemoSightPipeline

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
    "MemoSightFieldExtractionResult",
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
    "MemoSightTextBackend",
    "MemoSightSchemaError",
    "MemoSightValidationError",
    "MemoSightValidationIssue",
    "MemoSightValidationResult",
    "MemoSightValidator",
    "MlXVlmMemoSightBackend",
    "MlXTextMemoSightBackend",
    "MockMemoSightBackend",
    "MockMemoSightTextBackend",
    "ResolvedImageSource",
    "TwoStageMemoSightPipeline",
    "TwoStageMemoSightResult",
    "build_caption_field_extraction_prompt",
    "build_caption_prompt",
    "build_prompt",
    "empty_caption_fields",
    "find_markdown_field_keys",
    "get_profile",
    "list_profiles",
    "normalize_caption_fields",
    "parse_markdown_fields",
    "parse_model_output",
    "resolve_image_source",
    "resolve_profile",
    "validate_output_schema",
]
