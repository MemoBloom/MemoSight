"""Tests for memosight.validator — structured output validation."""
from __future__ import annotations

from memosight.validator import (
    MemoSightValidationIssue,
    MemoSightValidationResult,
    MemoSightValidator,
)


def _valid_payload() -> dict:
    return {
        "caption": "室内婚礼现场中，新娘站在暖光下与宾客互动，桌面有红色装饰和餐具，氛围温馨热闹。",
        "scene_labels": ["婚礼", "室内"],
        "people": ["穿白色婚纱的新娘", "背景宾客"],
        "actions": ["站立", "互动"],
        "objects": ["餐桌", "红色装饰", "餐具"],
        "lighting": ["暖光"],
        "mood": ["温馨", "热闹"],
        "search_tags": ["婚礼", "新娘", "室内", "暖光"],
    }


def test_validator_accepts_valid_payload():
    issues = MemoSightValidator().validate_payload(_valid_payload(), source="asset:test")

    assert issues == []


def test_validator_reports_missing_caption_and_non_array_field():
    payload = _valid_payload()
    payload["people"] = "新娘"
    payload.pop("caption")

    issues = MemoSightValidator().validate_payload(payload)

    messages = [issue.message for issue in issues]
    assert "Missing field: caption" in messages
    assert "Field people must be an array" in messages


def test_validator_reports_too_many_items():
    payload = _valid_payload()
    payload["search_tags"] = [f"tag{i}" for i in range(8)]

    issues = MemoSightValidator().validate_payload(payload)

    assert any(
        "Field search_tags has 8 items; maximum is 6" == issue.message
        for issue in issues
    )


def test_validator_reports_non_string_items():
    payload = _valid_payload()
    payload["objects"] = ["餐桌", 3, None]

    issues = MemoSightValidator().validate_payload(payload)

    assert any("Field objects must contain only strings" in issue.message for issue in issues)


def test_validator_reports_empty_caption():
    payload = _valid_payload()
    payload["caption"] = "   "

    issues = MemoSightValidator().validate_payload(payload)

    assert any(issue.message == "Field caption must not be empty" for issue in issues)


def test_validator_non_strict_mode_returns_no_issues():
    issues = MemoSightValidator().validate_payload({"garbage": True}, strict=False)

    assert issues == []


def test_validator_finds_nested_structured_payload():
    payload = {"result": {"caption_fields": _valid_payload()}}

    issues = MemoSightValidator().validate_payload(payload)

    assert issues == []


def test_validator_flags_payload_without_caption_fields():
    issues = MemoSightValidator().validate_payload({"unrelated": 1}, source="x.json")

    assert len(issues) == 1
    assert "No caption structured payload found" in issues[0].message
    assert issues[0].source == "x.json"


def test_validate_json_text_reports_syntax_location():
    result = MemoSightValidator().validate_json_text(
        '{"caption": "broken", "scene_labels": [}',
        "broken.json",
    )

    assert not result.ok
    issue = result.issues[0]
    assert isinstance(issue, MemoSightValidationIssue)
    assert issue.source == "broken.json"
    assert issue.line == 1
    assert issue.column is not None
    assert "Invalid JSON syntax" in issue.message
    assert issue.snippet is not None and "^" in issue.snippet


def test_validation_result_ok_and_failed_properties():
    result = MemoSightValidationResult(checked=1, valid=1)
    assert result.ok
    assert result.failed == 0

    result.issues.append(
        MemoSightValidationIssue(source="a.json", message="bad", severity="error")
    )
    result.issues.append(
        MemoSightValidationIssue(source="b.json", message="meh", severity="warning")
    )
    assert not result.ok
    assert result.failed == 1  # distinct sources with error severity


def test_validation_result_extend_aggregates():
    left = MemoSightValidationResult(checked=1, valid=1)
    right = MemoSightValidationResult(
        checked=2,
        issues=[MemoSightValidationIssue(source="b.json", message="bad")],
    )

    left.extend(right)

    assert left.checked == 3
    assert left.valid == 1
    assert len(left.issues) == 1


CUSTOM_SCHEMA = {
    "type": "object",
    "properties": {
        "product_type": {"type": "string"},
        "brand_visible": {"type": "boolean"},
        "rating": {"type": "integer"},
        "dominant_colors": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 2,
        },
        "size": {"type": "string", "enum": ["S", "M", "L"]},
        "dimensions": {
            "type": "object",
            "properties": {"width_cm": {"type": "number"}},
            "required": ["width_cm"],
        },
    },
    "required": ["product_type", "brand_visible"],
}


def test_validate_custom_accepts_valid_payload():
    payload = {
        "product_type": "watch",
        "brand_visible": True,
        "rating": 4,
        "dominant_colors": ["black"],
        "size": "M",
        "dimensions": {"width_cm": 4.2},
    }

    issues = MemoSightValidator().validate_custom(payload, CUSTOM_SCHEMA)

    assert issues == []


def test_validate_custom_flags_missing_required_and_bad_types():
    payload = {
        "brand_visible": "yes",  # not a boolean
        "rating": 4.5,  # not an integer
        "dominant_colors": ["black", 42, "white"],  # bad item + over maxItems
        "size": "XL",  # outside enum
        "dimensions": {},  # missing required nested field
    }

    issues = MemoSightValidator().validate_custom(
        payload, CUSTOM_SCHEMA, source="payload.json"
    )
    messages = "\n".join(issue.message for issue in issues)

    assert "Missing required field: product_type" in messages
    assert "a boolean" in messages
    assert "an integer" in messages
    assert "maximum is 2" in messages
    assert "bad indexes: 1" in messages
    assert "not one of the allowed enum choices" in messages
    assert "Missing required field: width_cm" in messages
    assert all(issue.source.startswith("payload.json") for issue in issues)


def test_validate_custom_rejects_non_object_payload_and_honors_non_strict():
    validator = MemoSightValidator()

    issues = validator.validate_custom([1, 2], CUSTOM_SCHEMA)
    assert len(issues) == 1
    assert "must be a JSON object" in issues[0].message

    assert validator.validate_custom({"anything": 1}, CUSTOM_SCHEMA, strict=False) == []


def test_validate_custom_enforces_default_array_cap_without_maxitems():
    schema = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
    }
    payload = {"tags": [f"tag_{index}" for index in range(21)]}

    issues = MemoSightValidator().validate_custom(payload, schema)

    assert len(issues) == 1
    assert "maximum is 20" in issues[0].message

    payload["tags"] = payload["tags"][:20]
    assert MemoSightValidator().validate_custom(payload, schema) == []
