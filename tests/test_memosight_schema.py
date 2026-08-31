"""Tests for memosight.schema — public request/result models + purity guard."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from memosight.schema import (
    MemoSightImageSource,
    MemoSightObservation,
    MemoSightRequest,
    MemoSightResult,
)
from memosight.validator import MemoSightValidationResult


def test_image_source_defaults_to_path_kind():
    source = MemoSightImageSource(image_path="/tmp/a.jpg")

    assert source.kind == "path"
    assert source.data is None
    assert source.metadata == {}


def test_image_source_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        MemoSightImageSource(kind="url")


def test_request_defaults():
    request = MemoSightRequest(image=MemoSightImageSource(image_path="/tmp/a.jpg"))

    assert request.language == "zh"
    assert request.profile == "photography_default"
    assert request.output_schema is None
    assert request.options == {}


def test_observation_defaults_and_max_six_items():
    observation = MemoSightObservation(caption="新娘站在窗边")

    assert observation.scene_labels == []
    assert observation.search_tags == []

    with pytest.raises(ValidationError):
        MemoSightObservation(caption="x", mood=[str(i) for i in range(7)])


def test_result_carries_validation_and_default_observation():
    observation = MemoSightObservation(caption="暖光婚礼", mood=["温馨"])
    result = MemoSightResult(
        status="ok",
        observation=observation.model_dump(),
        default_observation=observation,
        raw_output='{"caption": "暖光婚礼"}',
        schema_name="photography_default",
        validation=MemoSightValidationResult(checked=1, valid=1),
    )

    assert result.schema_version == "1.0.0"
    assert result.validation.ok
    assert result.default_observation.mood == ["温馨"]
    assert result.error is None


def test_memosight_module_has_no_infra_dependencies():
    """MemoSight must stay pure at import time: no SQLAlchemy/FastAPI/Arq/Redis/app models.

    Only top-level import statements are checked. Function-level lazy
    imports (e.g. the MLX-VLM client in the backend adapter) and
    TYPE_CHECKING imports do not run at module import time, so they are
    allowed.
    """
    forbidden_prefixes = (
        "sqlalchemy",
        "fastapi",
        "arq",
        "redis",
        "app.models",
        "app.services",
        "app.workers",
        "app.api",
        "app.core",
        "app.db",
    )
    package_dir = Path(__file__).resolve().parents[1] / "memosight"

    for path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # Relative imports inside the package are fine.
                names = [] if node.level else [node.module or ""]
            else:
                continue
            for name in names:
                assert not name.startswith(forbidden_prefixes), (
                    f"{path.name} imports forbidden module {name}"
                )
