"""Tests for memosight.parser — untrusted model output parsing."""
from __future__ import annotations

from memosight.parser import parse_model_output


def test_parse_strict_json_object():
    raw = '{"caption": "新娘站在窗边", "scene_labels": ["婚礼", "室内"]}'

    result = parse_model_output(raw)

    assert result.ok
    assert result.strategy == "strict"
    assert result.error is None
    assert result.data["caption"] == "新娘站在窗边"
    assert result.data["scene_labels"] == ["婚礼", "室内"]
    assert result.raw_output == raw


def test_parse_fenced_json_block():
    raw = 'Here is the result:\n```json\n{"caption": "tea ceremony"}\n```\nThanks.'

    result = parse_model_output(raw)

    assert result.ok
    assert result.strategy == "fenced"
    assert result.data == {"caption": "tea ceremony"}


def test_parse_fenced_block_without_language_hint():
    raw = '```\n{"caption": "x"}\n```'

    result = parse_model_output(raw)

    assert result.ok
    assert result.strategy == "fenced"
    assert result.data == {"caption": "x"}


def test_parse_json_embedded_in_prose():
    raw = 'Analysis result:\n{"caption": "暖光婚礼", "mood": ["温馨"]}\nDone.'

    result = parse_model_output(raw)

    assert result.ok
    assert result.strategy == "embedded"
    assert result.data["caption"] == "暖光婚礼"
    assert result.data["mood"] == ["温馨"]


def test_parse_invalid_input_returns_structured_error():
    raw = "sorry, I cannot help with that"

    result = parse_model_output(raw)

    assert not result.ok
    assert result.data is None
    assert result.error is not None
    assert result.error.message
    assert result.raw_output == raw


def test_parse_broken_json_returns_structured_error_with_location():
    raw = '{"caption": "broken", "scene_labels": [}'

    result = parse_model_output(raw)

    assert not result.ok
    assert result.data is None
    assert result.error is not None
    assert result.error.line is not None
    assert result.error.column is not None
    assert result.raw_output == raw


def test_parse_non_object_json_returns_error():
    result = parse_model_output('["not", "an", "object"]')

    assert not result.ok
    assert result.data is None
    assert result.error is not None


def test_parse_empty_or_none_input_returns_error():
    for raw in (None, "", "   \n  "):
        result = parse_model_output(raw)

        assert not result.ok
        assert result.data is None
        assert result.error is not None


def test_parse_never_raises_on_arbitrary_garbage():
    for raw in ("}{][}{", "{", "}", "```json", "\x00\x01\xff"):
        result = parse_model_output(raw)

        assert not result.ok
        assert result.error is not None
        assert result.raw_output == raw
