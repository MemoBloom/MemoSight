"""Unit tests for the deterministic frame sampling helpers."""
from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "extract_frames.py"
SPEC = importlib.util.spec_from_file_location("extract_frames", SCRIPT_PATH)
assert SPEC and SPEC.loader
extract_frames = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extract_frames)


def test_sample_indices_are_even_and_include_endpoints():
    assert extract_frames._sample_indices(113, 20) == [
        0, 6, 12, 18, 24, 29, 35, 41, 47, 53,
        59, 65, 71, 77, 83, 88, 94, 100, 106, 112,
    ]


def test_sample_indices_do_not_duplicate_when_request_exceeds_frames():
    assert extract_frames._sample_indices(3, 20) == [0, 1, 2]


def test_sample_indices_support_single_sample():
    assert extract_frames._sample_indices(10, 1) == [0]
