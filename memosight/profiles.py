"""Named schema profiles and custom output schema validation for MemoSight.

Profiles bundle a schema name/version, a JSON-Schema-like output schema,
prompt instructions, and optional normalization hints. Resolution priority:

    output_schema > profile > photography_default

Custom (caller-supplied) schemas are validated against a controlled subset
of JSON Schema; anything outside the subset raises ``MemoSightSchemaError``.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from .errors import MemoSightSchemaError

# Custom schema complexity limits (see .planning/MEMOSIGHT_REFACTOR_PLAN.md).
MAX_TOP_LEVEL_FIELDS = 24
MAX_NESTED_DEPTH = 3
MAX_ARRAY_ITEMS = 20
MAX_ENUM_CHOICES = 50
MAX_SCHEMA_JSON_BYTES = 20 * 1024

SCALAR_TYPES = frozenset({"string", "number", "integer", "boolean"})
SUPPORTED_TYPES = SCALAR_TYPES | {"array", "object"}

DEFAULT_PROFILE_NAME = "photography_default"
CUSTOM_PROFILE_NAME = "custom"


class MemoSightProfile(BaseModel):
    """A named output profile: schema plus prompt instructions."""

    name: str
    schema_name: str
    schema_version: str = "1.0.0"
    output_schema: dict[str, Any] = Field(default_factory=dict)
    instructions_zh: str = ""
    instructions_en: str | None = None
    normalization: dict[str, Any] = Field(default_factory=dict)

    def instructions_for(self, language: str) -> str:
        """Return prompt instructions for ``language``, falling back to zh."""
        if language == "en" and self.instructions_en:
            return self.instructions_en
        return self.instructions_zh


def _array_of_strings(description_zh: str, description_en: str, max_items: int = 6) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": max_items,
        "description": description_zh,
        "description_en": description_en,
    }


def _string_field(description_zh: str, description_en: str) -> dict[str, Any]:
    return {
        "type": "string",
        "description": description_zh,
        "description_en": description_en,
    }


def _boolean_field(description_zh: str, description_en: str) -> dict[str, Any]:
    return {
        "type": "boolean",
        "description": description_zh,
        "description_en": description_en,
    }


_PHOTOGRAPHY_DEFAULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "caption": _string_field(
            "对照片可见内容的一句简洁自然语言描述。",
            "One concise natural-language description of the visible image content.",
        ),
        "scene_labels": _array_of_strings(
            "高层场景或类别标签。",
            "High-level scene or category labels.",
        ),
        "people": _array_of_strings(
            "可见的人物、角色或被摄主体描述；不要推断真实身份。",
            "Visible people, roles, or subject descriptions. No real identity inference.",
        ),
        "actions": _array_of_strings(
            "可见的动作或互动。",
            "Visible actions or interactions.",
        ),
        "objects": _array_of_strings(
            "显著的物体、道具、产品、装饰或背景元素。",
            "Salient objects, props, products, decorations, or background elements.",
        ),
        "lighting": _array_of_strings(
            "可见的光线条件。",
            "Visible lighting conditions.",
        ),
        "mood": _array_of_strings(
            "基于可见内容的画面氛围或情绪。",
            "Visual mood or atmosphere, grounded in visible content.",
        ),
        "search_tags": _array_of_strings(
            "便于检索的简短标签。",
            "Short retrieval-friendly tags.",
        ),
    },
    "required": [
        "caption",
        "scene_labels",
        "people",
        "actions",
        "objects",
        "lighting",
        "mood",
        "search_tags",
    ],
}

# Stage-two extraction schema for the default profile: the seven retrieval
# fields only. ``caption`` is dropped because stage one already produced it
# and the pipeline pins it; asking the model to regenerate it wastes output
# tokens and risks truncation.
PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        key: spec
        for key, spec in _PHOTOGRAPHY_DEFAULT_SCHEMA["properties"].items()
        if key != "caption"
    },
    "required": [
        key for key in _PHOTOGRAPHY_DEFAULT_SCHEMA["required"] if key != "caption"
    ],
}

_WEDDING_SELECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "caption": _string_field(
            "对这一帧婚礼画面可见内容的简洁描述。",
            "Concise description of the visible wedding moment.",
        ),
        "moment_type": {
            "type": "string",
            "enum": ["preparation", "ceremony", "portrait", "group_photo", "reception", "detail", "other"],
            "description": "可见画面所属的婚礼环节。",
            "description_en": "Which part of the wedding the visible moment belongs to.",
        },
        "key_people": _array_of_strings(
            "画面中可见的关键人物角色（如新人、伴郎伴娘、父母），不要推断真实身份。",
            "Visible key people by role (e.g. couple, bridesmaids, parents). No real identity inference.",
        ),
        "emotions": _array_of_strings(
            "从可见表情和肢体语言读出的情绪。",
            "Emotions readable from visible expressions and body language.",
            max_items=4,
        ),
        "selection_worthy": _boolean_field(
            "是否值得进入交付候选（构图完整、主体清晰、情绪到位）。",
            "Whether this frame deserves delivery shortlist (complete composition, clear subject, on-point emotion).",
        ),
        "highlight_reason": _string_field(
            "入选或淘汰的简短可见依据。",
            "Short visible-grounded reason for selection or rejection.",
        ),
    },
    "required": ["caption", "moment_type", "selection_worthy"],
}

_PORTRAIT_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "caption": _string_field(
            "对人像画面可见内容的简洁描述。",
            "Concise description of the visible portrait content.",
        ),
        "expression": _string_field(
            "被摄者可见的表情状态。",
            "The subject's visible expression.",
        ),
        "eye_contact": _boolean_field(
            "被摄者是否直视镜头。",
            "Whether the subject looks directly into the camera.",
        ),
        "pose": _string_field(
            "可见的肢体姿态或朝向。",
            "Visible body pose or orientation.",
        ),
        "background_distractions": _array_of_strings(
            "背景中分散注意力的可见元素。",
            "Visible distracting elements in the background.",
            max_items=4,
        ),
        "retouch_notes": _array_of_strings(
            "基于可见瑕疵的修图建议（如杂发、反光、皱纹）。",
            "Retouch suggestions grounded in visible flaws (flyaway hair, glare, wrinkles).",
        ),
    },
    "required": ["caption", "expression", "eye_contact"],
}

_PRODUCT_CATALOG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "product_type": _string_field(
            "可见的产品类别。",
            "Visible product category.",
        ),
        "brand_visible": _boolean_field(
            "画面中是否可见品牌标志或品牌名称。",
            "Whether a brand logo or brand name is visible.",
        ),
        "dominant_colors": _array_of_strings(
            "产品或画面中可见的主色。",
            "Dominant colors visible on the product or in the frame.",
            max_items=5,
        ),
        "defects": _array_of_strings(
            "可见的产品瑕疵或拍摄问题。",
            "Visible product defects or capture issues.",
        ),
        "background_style": {
            "type": "string",
            "enum": ["white", "gradient", "lifestyle", "textured", "other"],
            "description": "可见的背景风格。",
            "description_en": "Visible background style.",
        },
    },
    "required": ["product_type", "brand_visible"],
}

_EVENT_COVERAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "caption": _string_field(
            "对活动现场可见内容的简洁描述。",
            "Concise description of the visible event scene.",
        ),
        "event_phase": _string_field(
            "画面所属的活动环节（如签到、开场、演讲、互动、闭幕）。",
            "Which event phase the frame belongs to (check-in, opening, talk, interaction, closing).",
        ),
        "crowd_density": {
            "type": "string",
            "enum": ["empty", "sparse", "medium", "dense"],
            "description": "可见的人群密度。",
            "description_en": "Visible crowd density.",
        },
        "key_subjects": _array_of_strings(
            "画面中可见的关键主体（如演讲者、舞台、展位），不要推断真实身份。",
            "Visible key subjects (speaker, stage, booth). No real identity inference.",
        ),
        "venue_elements": _array_of_strings(
            "可见的场地元素（如横幅、灯光、屏幕、座位区）。",
            "Visible venue elements (banners, lighting, screens, seating).",
        ),
    },
    "required": ["caption", "event_phase"],
}

PROFILES: dict[str, MemoSightProfile] = {
    "photography_default": MemoSightProfile(
        name="photography_default",
        schema_name="photography_default",
        output_schema=_PHOTOGRAPHY_DEFAULT_SCHEMA,
        instructions_zh="用中文填写各字段值。",
        instructions_en="Write field values in English.",
        normalization={"array_field_max_items": 6},
    ),
    "wedding_selection": MemoSightProfile(
        name="wedding_selection",
        schema_name="wedding_selection",
        output_schema=_WEDDING_SELECTION_SCHEMA,
        instructions_zh="这是婚礼选片场景，关注环节归属、关键人物和是否值得交付。用中文填写文本字段值。",
        instructions_en=(
            "This is a wedding photo-selection context; focus on the moment type, "
            "key people by role, and whether the frame is delivery-worthy. "
            "Write text field values in English."
        ),
        normalization={"array_field_max_items": 6},
    ),
    "portrait_review": MemoSightProfile(
        name="portrait_review",
        schema_name="portrait_review",
        output_schema=_PORTRAIT_REVIEW_SCHEMA,
        instructions_zh="这是人像审片场景，关注表情、姿态、眼神和可修饰的可见瑕疵。用中文填写文本字段值。",
        instructions_en=(
            "This is a portrait review context; focus on expression, pose, eye "
            "contact, and visible retouchable flaws. Write text field values in English."
        ),
        normalization={"array_field_max_items": 6},
    ),
    "product_catalog": MemoSightProfile(
        name="product_catalog",
        schema_name="product_catalog",
        output_schema=_PRODUCT_CATALOG_SCHEMA,
        instructions_zh="这是电商产品图编目场景，关注产品类别、品牌可见性、主色和瑕疵。用中文填写文本字段值。",
        instructions_en=(
            "This is an e-commerce product cataloging context; focus on product "
            "category, brand visibility, dominant colors, and defects. "
            "Write text field values in English."
        ),
        normalization={"array_field_max_items": 6},
    ),
    "event_coverage": MemoSightProfile(
        name="event_coverage",
        schema_name="event_coverage",
        output_schema=_EVENT_COVERAGE_SCHEMA,
        instructions_zh="这是活动跟拍场景，关注活动环节、人群密度和场地元素。用中文填写文本字段值。",
        instructions_en=(
            "This is an event coverage context; focus on event phase, crowd "
            "density, and venue elements. Write text field values in English."
        ),
        normalization={"array_field_max_items": 6},
    ),
    "custom": MemoSightProfile(
        name="custom",
        schema_name="custom",
        output_schema={},
        instructions_zh="",
    ),
}


def list_profiles() -> list[str]:
    """Return the names of all registered profiles."""
    return sorted(PROFILES)


def get_profile(name: str) -> MemoSightProfile:
    """Return the registered profile ``name`` or raise ``MemoSightSchemaError``."""
    profile = PROFILES.get(name)
    if profile is None:
        raise MemoSightSchemaError(
            f"Unknown MemoSight profile: {name!r}; available: {', '.join(list_profiles())}"
        )
    if name == CUSTOM_PROFILE_NAME and not profile.output_schema:
        raise MemoSightSchemaError(
            "Profile 'custom' has no schema of its own; pass output_schema to resolve_profile"
        )
    return profile


def resolve_profile(
    *,
    output_schema: dict[str, Any] | None = None,
    profile: str | None = None,
    instructions_zh: str | None = None,
    instructions_en: str | None = None,
) -> MemoSightProfile:
    """Resolve the effective profile: ``output_schema`` > ``profile`` > default."""
    if output_schema is not None:
        validate_output_schema(output_schema)
        return MemoSightProfile(
            name=CUSTOM_PROFILE_NAME,
            schema_name=CUSTOM_PROFILE_NAME,
            output_schema=output_schema,
            instructions_zh=instructions_zh or "",
            instructions_en=instructions_en,
        )
    if profile:
        return get_profile(profile)
    return get_profile(DEFAULT_PROFILE_NAME)


def validate_output_schema(schema: dict[str, Any]) -> None:
    """Validate a caller-supplied output schema against the supported subset.

    Raises ``MemoSightSchemaError`` on any violation of type support or the
    complexity limits (top-level fields, nesting depth, array length, enum
    size, serialized size).
    """
    if not isinstance(schema, dict):
        raise MemoSightSchemaError("output_schema must be a JSON object (dict)")

    encoded = json.dumps(schema, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_SCHEMA_JSON_BYTES:
        raise MemoSightSchemaError(
            f"output_schema is {len(encoded)} bytes; maximum is {MAX_SCHEMA_JSON_BYTES}"
        )

    top_type = schema.get("type", "object")
    if top_type != "object":
        raise MemoSightSchemaError(
            f"output_schema top-level type must be 'object', got {top_type!r}"
        )

    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise MemoSightSchemaError("output_schema must define at least one property")
    if len(properties) > MAX_TOP_LEVEL_FIELDS:
        raise MemoSightSchemaError(
            f"output_schema has {len(properties)} top-level fields; "
            f"maximum is {MAX_TOP_LEVEL_FIELDS}"
        )

    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise MemoSightSchemaError("output_schema 'required' must be a list of field names")
    unknown_required = [item for item in required if item not in properties]
    if unknown_required:
        raise MemoSightSchemaError(
            f"output_schema 'required' names unknown fields: {', '.join(unknown_required)}"
        )

    for field_name, spec in properties.items():
        _validate_field_spec(field_name, spec, object_depth=1)


def _validate_field_spec(name: str, spec: Any, *, object_depth: int) -> None:
    if not isinstance(spec, dict):
        raise MemoSightSchemaError(f"Field {name!r} must be a schema object (dict)")

    field_type = spec.get("type")
    if field_type not in SUPPORTED_TYPES:
        raise MemoSightSchemaError(
            f"Field {name!r} has unsupported type {field_type!r}; "
            f"supported: {', '.join(sorted(SUPPORTED_TYPES))}"
        )

    description = spec.get("description")
    if description is not None and not isinstance(description, str):
        raise MemoSightSchemaError(f"Field {name!r} 'description' must be a string")

    enum = spec.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum:
            raise MemoSightSchemaError(f"Field {name!r} 'enum' must be a non-empty list")
        if len(enum) > MAX_ENUM_CHOICES:
            raise MemoSightSchemaError(
                f"Field {name!r} has {len(enum)} enum choices; maximum is {MAX_ENUM_CHOICES}"
            )
        for choice in enum:
            if not isinstance(choice, str | int | float | bool):
                raise MemoSightSchemaError(
                    f"Field {name!r} 'enum' choices must be scalar values"
                )

    if field_type == "array":
        items = spec.get("items")
        if not isinstance(items, dict) or items.get("type") not in SCALAR_TYPES:
            raise MemoSightSchemaError(
                f"Field {name!r} is an array; its 'items' must be a scalar type "
                f"({', '.join(sorted(SCALAR_TYPES))})"
            )
        max_items = spec.get("maxItems")
        if max_items is not None:
            if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items < 1:
                raise MemoSightSchemaError(
                    f"Field {name!r} 'maxItems' must be a positive integer"
                )
            if max_items > MAX_ARRAY_ITEMS:
                raise MemoSightSchemaError(
                    f"Field {name!r} has maxItems={max_items}; maximum is {MAX_ARRAY_ITEMS}"
                )

    if field_type == "object":
        child_depth = object_depth + 1
        if child_depth > MAX_NESTED_DEPTH:
            raise MemoSightSchemaError(
                f"Field {name!r} would nest objects to depth {child_depth}; "
                f"maximum is {MAX_NESTED_DEPTH}"
            )
        nested = spec.get("properties")
        if not isinstance(nested, dict) or not nested:
            raise MemoSightSchemaError(
                f"Field {name!r} is an object and must define nested 'properties'"
            )
        nested_required = spec.get("required", [])
        if not isinstance(nested_required, list) or not all(
            isinstance(item, str) for item in nested_required
        ):
            raise MemoSightSchemaError(
                f"Field {name!r} 'required' must be a list of field names"
            )
        unknown_nested = [item for item in nested_required if item not in nested]
        if unknown_nested:
            raise MemoSightSchemaError(
                f"Field {name!r} 'required' names unknown nested fields: "
                f"{', '.join(unknown_nested)}"
            )
        for child_name, child_spec in nested.items():
            _validate_field_spec(f"{name}.{child_name}", child_spec, object_depth=child_depth)
