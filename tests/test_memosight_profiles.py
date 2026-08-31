"""Tests for memosight.profiles — registry, resolution, schema validation."""
from __future__ import annotations

import pytest

from memosight.errors import MemoSightSchemaError
from memosight.profiles import (
    MAX_ENUM_CHOICES,
    MAX_SCHEMA_JSON_BYTES,
    MAX_TOP_LEVEL_FIELDS,
    MemoSightProfile,
    get_profile,
    list_profiles,
    resolve_profile,
    validate_output_schema,
)

CUSTOM_SCHEMA = {
    "type": "object",
    "properties": {
        "product_type": {
            "type": "string",
            "description": "Visible product category.",
        },
        "brand_visible": {
            "type": "boolean",
            "description": "Whether a brand logo or brand name is visible.",
        },
        "dominant_colors": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
        },
        "defects": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
    },
    "required": ["product_type", "brand_visible"],
}


def test_default_profile_resolves_correctly():
    profile = resolve_profile()

    assert profile.name == "photography_default"
    assert profile.schema_name == "photography_default"
    assert profile.schema_version == "1.0.0"

    properties = profile.output_schema["properties"]
    assert list(properties) == [
        "caption",
        "scene_labels",
        "people",
        "actions",
        "objects",
        "lighting",
        "mood",
        "search_tags",
    ]
    assert properties["caption"]["type"] == "string"
    for key in ("scene_labels", "people", "actions", "objects", "lighting", "mood", "search_tags"):
        assert properties[key]["type"] == "array"
        assert properties[key]["items"] == {"type": "string"}
        assert properties[key]["maxItems"] == 6


def test_named_profiles_resolve():
    for name in (
        "photography_default",
        "wedding_selection",
        "portrait_review",
        "product_catalog",
        "event_coverage",
    ):
        profile = resolve_profile(profile=name)
        assert profile.name == name
        assert profile.output_schema["type"] == "object"
        assert profile.output_schema["properties"]
    assert "custom" in list_profiles()


def test_output_schema_overrides_profile():
    profile = resolve_profile(output_schema=CUSTOM_SCHEMA, profile="wedding_selection")

    assert profile.name == "custom"
    assert profile.schema_name == "custom"
    assert profile.output_schema == CUSTOM_SCHEMA


def test_unknown_profile_raises_schema_error():
    with pytest.raises(MemoSightSchemaError):
        resolve_profile(profile="does_not_exist")


def test_custom_profile_without_schema_raises():
    with pytest.raises(MemoSightSchemaError):
        get_profile("custom")


def test_schema_with_too_many_fields_is_rejected():
    schema = {
        "type": "object",
        "properties": {f"field_{index}": {"type": "string"} for index in range(MAX_TOP_LEVEL_FIELDS + 1)},
    }
    with pytest.raises(MemoSightSchemaError, match="top-level fields"):
        validate_output_schema(schema)

    schema["properties"].popitem()
    validate_output_schema(schema)  # exactly at the limit is fine


def test_schema_nesting_deeper_than_three_is_rejected():
    level3 = {"type": "object", "properties": {"leaf": {"type": "string"}}}
    level2 = {"type": "object", "properties": {"child": level3}}

    # Root object + 2 nested objects = depth 3, allowed.
    validate_output_schema({"type": "object", "properties": {"child": level2}})

    # Root + 3 nested objects = depth 4, rejected.
    level1 = {"type": "object", "properties": {"child": level2}}
    schema = {"type": "object", "properties": {"child": level1}}
    with pytest.raises(MemoSightSchemaError, match="depth"):
        validate_output_schema(schema)


def test_schema_array_max_items_capped_at_20():
    schema = {
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 21}
        },
    }
    with pytest.raises(MemoSightSchemaError, match="maxItems"):
        validate_output_schema(schema)


def test_schema_array_items_must_be_scalar():
    schema = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "object"}}},
    }
    with pytest.raises(MemoSightSchemaError, match="items"):
        validate_output_schema(schema)


def test_schema_enum_limit_is_enforced():
    schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": [str(i) for i in range(MAX_ENUM_CHOICES + 1)]}
        },
    }
    with pytest.raises(MemoSightSchemaError, match="enum"):
        validate_output_schema(schema)


def test_schema_size_limit_is_enforced():
    schema = {
        "type": "object",
        "properties": {
            "blob": {"type": "string", "description": "x" * MAX_SCHEMA_JSON_BYTES}
        },
    }
    with pytest.raises(MemoSightSchemaError, match="bytes"):
        validate_output_schema(schema)


def test_schema_rejects_non_object_top_level_and_bad_types():
    with pytest.raises(MemoSightSchemaError, match="object"):
        validate_output_schema({"type": "array", "items": {"type": "string"}})
    with pytest.raises(MemoSightSchemaError, match="unsupported type"):
        validate_output_schema({"type": "object", "properties": {"x": {"type": "null"}}})
    with pytest.raises(MemoSightSchemaError, match="required"):
        validate_output_schema(
            {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["nope"]}
        )


def test_resolve_custom_profile_carries_instructions():
    profile = resolve_profile(
        output_schema=CUSTOM_SCHEMA,
        instructions_zh="关注包装",
        instructions_en="Focus on packaging",
    )

    assert isinstance(profile, MemoSightProfile)
    assert profile.instructions_for("zh") == "关注包装"
    assert profile.instructions_for("en") == "Focus on packaging"


def test_profile_instructions_fall_back_to_zh():
    profile = resolve_profile(output_schema=CUSTOM_SCHEMA, instructions_zh="只写中文")

    assert profile.instructions_for("en") == "只写中文"


def test_nested_object_required_is_schema_validated():
    base = {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "object",
                "properties": {"width_cm": {"type": "number"}},
            }
        },
    }
    validate_output_schema(base)  # no nested required is fine

    bad_names = {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "object",
                "properties": {"width_cm": {"type": "number"}},
                "required": ["height_cm"],
            }
        },
    }
    with pytest.raises(MemoSightSchemaError, match="unknown nested fields"):
        validate_output_schema(bad_names)

    bad_shape = {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "object",
                "properties": {"width_cm": {"type": "number"}},
                "required": "width_cm",
            }
        },
    }
    with pytest.raises(MemoSightSchemaError, match="list of field names"):
        validate_output_schema(bad_shape)
