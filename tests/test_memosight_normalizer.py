"""Tests for memosight.normalizer — default caption field normalization."""
from __future__ import annotations

from memosight.normalizer import (
    CAPTION_FIELD_KEYS,
    empty_caption_fields,
    normalize_caption_fields,
)


def test_caption_field_keys_match_default_contract():
    assert CAPTION_FIELD_KEYS == (
        "scene_labels",
        "people",
        "actions",
        "objects",
        "lighting",
        "mood",
        "search_tags",
    )


def test_empty_caption_fields_has_all_keys():
    fields = empty_caption_fields()

    assert set(fields) == set(CAPTION_FIELD_KEYS)
    assert all(value == [] for value in fields.values())


def test_normalize_string_value_becomes_single_item_array():
    result = normalize_caption_fields({"mood": "温馨", "actions": "walking"})

    assert result["mood"] == ["温馨"]
    assert result["actions"] == ["walking"]


def test_normalize_drops_unknown_keys():
    result = normalize_caption_fields({"unknown_field": ["x"], "scene_labels": ["婚礼"]})

    assert "unknown_field" not in result
    assert result["scene_labels"] == ["婚礼"]


def test_normalize_drops_null_empty_and_unknown_items():
    result = normalize_caption_fields(
        {"people": [None, "", "   ", "unknown", "UNKNOWN", "新娘"]}
    )

    assert result["people"] == ["新娘"]


def test_normalize_trims_whitespace():
    result = normalize_caption_fields({"objects": ["  餐桌 ", "\t红色装饰\n"]})

    assert result["objects"] == ["餐桌", "红色装饰"]


def test_normalize_dedupes_preserving_first_occurrence_order():
    result = normalize_caption_fields(
        {"scene_labels": ["婚礼", "婚礼", "室内", "婚礼", "室内"]}
    )

    assert result["scene_labels"] == ["婚礼", "室内"]


def test_normalize_enforces_max_six_items():
    result = normalize_caption_fields({"search_tags": [f"tag{i}" for i in range(10)]})

    assert result["search_tags"] == [f"tag{i}" for i in range(6)]


def test_normalize_coerces_non_list_non_string_values():
    result = normalize_caption_fields({"lighting": 42, "mood": None, "people": True})

    assert result["lighting"] == ["42"]
    assert result["mood"] == []
    assert result["people"] == ["True"]


def test_normalize_missing_keys_default_to_empty_lists():
    result = normalize_caption_fields({"caption": "ignored — not a field key"})

    assert result == empty_caption_fields()


def test_normalize_none_payload_returns_empty_fields():
    assert normalize_caption_fields(None) == empty_caption_fields()


def test_normalize_keeps_language_specific_text_intact():
    result = normalize_caption_fields({"scene_labels": ["婚礼", "wedding", "結婚式"]})

    assert result["scene_labels"] == ["婚礼", "wedding", "結婚式"]
