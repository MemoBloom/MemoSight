"""CLI tests for memosight.cli.

Run the real entry path (``python -m memosight.cli``) in a subprocess so the
console-script behavior, exit codes, and stdout JSON contract are exercised
exactly as end users see them.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import re

from memosight import (
    MemoSightImageSource,
    MemoSightPipeline,
    MemoSightRequest,
    MockMemoSightBackend,
)

DEAD_SERVER_URL = "http://127.0.0.1:59999"


def run_cli(*args: str, env: dict[str, str] | None = None, stdin: str | None = None):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "memosight.cli", *args],
        capture_output=True,
        text=True,
        env=full_env,
        input=stdin,
        timeout=60,
    )


def test_help_lists_commands():
    result = run_cli("--help")
    assert result.returncode == 0
    assert "analyze" in result.stdout
    assert "doctor" in result.stdout
    assert "Traceback" not in result.stderr


def test_version():
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip().startswith("memosight ")


def test_no_args_prints_help():
    result = run_cli()
    assert result.returncode == 0
    assert "analyze" in result.stdout


def test_doctor_without_server_reports_and_does_not_crash():
    result = run_cli("doctor", env={"MEMOSIGHT_MLX_SERVER_URL": DEAD_SERVER_URL})
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "server reachable" in result.stdout
    # Every failing check must come with remediation advice.
    assert "memosight serve --model" in result.stdout
    assert "Traceback" not in result.stderr


def test_analyze_with_mock_backend_outputs_valid_json(tmp_path: Path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8\xff")  # content is irrelevant for the mock
    result = run_cli("analyze", str(image), "--backend", "mock")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["observation"]["caption"] == "mock caption"
    assert payload["model_name"] == "mock"


def test_analyze_missing_file_fails_with_json(tmp_path: Path):
    missing = tmp_path / "nope.jpg"
    result = run_cli("analyze", str(missing), "--backend", "mock")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["error"]


def test_analyze_compact_is_single_line(tmp_path: Path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8\xff")
    result = run_cli("analyze", str(image), "--backend", "mock", "--compact")
    assert result.returncode == 0
    assert len(result.stdout.strip().splitlines()) == 1
    json.loads(result.stdout)


def test_cli_matches_library_api_output(tmp_path: Path):
    """Consistency acceptance: CLI JSON must match the direct pipeline call."""
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    cli = run_cli(
        "analyze", str(image), "--backend", "mock", "--language", "en"
    )
    assert cli.returncode == 0
    cli_payload = json.loads(cli.stdout)

    async def direct_call():
        pipeline = MemoSightPipeline(backend=MockMemoSightBackend())
        return await pipeline.analyze(
            MemoSightRequest(
                image=MemoSightImageSource(kind="path", image_path=str(image)),
                language="en",
                profile="photography_default",
            )
        )

    direct = asyncio.run(direct_call())
    assert cli_payload == direct.model_dump(mode="json")


def test_setup_mlx_declined_installs_nothing():
    result = run_cli("setup-mlx", stdin="n\n")
    if importlib.util.find_spec("mlx_vlm") is not None:
        # Already installed: command must succeed without prompting.
        assert result.returncode == 0
        assert "already installed" in result.stdout
    else:
        assert result.returncode == 1
        assert "Aborted" in result.stdout
    # Model weights are never downloaded by the CLI.
    assert "never downloads models" in result.stdout


def test_serve_requires_mlx_vlm():
    if importlib.util.find_spec("mlx_vlm") is not None:
        pytest.skip("mlx-vlm installed; serve would start a real server")
    result = run_cli("serve", "--model", "/tmp/nonexistent-model")
    assert result.returncode == 1
    assert "setup-mlx" in result.stderr


SQUAT_SCHEMA = {
    "type": "object",
    "properties": {
        "exercise_type": {
            "type": "string",
            "enum": ["squat", "other"],
            "description": "图片中可见的健身动作类型。",
        },
        "safety_risk": {"type": "boolean", "description": "是否存在明显可见的动作安全风险。"},
    },
    "required": ["exercise_type", "safety_risk"],
}

SQUAT_PLAN = {
    "task_summary": "根据目标 JSON schema 进行可见事实结构化抽取。",
    "field_guidance": {"exercise_type": "只能选择：squat/other。"},
    "negative_rules": ["不要推断图片中不可见的信息。"],
    "output_rules": ["只输出一个 JSON 对象。"],
    "final_prompt": "结合字段判断策略抽取可见事实。",
}


def _write_json(tmp_path: Path, name: str, payload) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False))
    return path


def test_prompt_renders_all_three_prompts(tmp_path: Path):
    schema = _write_json(tmp_path, "schema.json", SQUAT_SCHEMA)
    plan = _write_json(tmp_path, "plan.json", SQUAT_PLAN)
    result = run_cli(
        "prompt", "--schema", str(schema), "--plan", str(plan),
    )
    assert result.returncode == 0, result.stderr
    # One-stage + both two-stage prompts are rendered.
    headings = re.findall(r"^## ", result.stdout, re.M)
    assert len(headings) == 3
    assert "## One-Stage Prompt" in result.stdout
    assert "Two-Stage Prompt 1" in result.stdout
    assert "Two-Stage Prompt 2" in result.stdout
    # Schema-derived field definitions and plan content appear.
    assert '"exercise_type" (string, 必填)' in result.stdout
    assert "squat/other" in result.stdout
    assert "不要推断图片中不可见的信息。" in result.stdout
    # Caption placeholder is used in the stage-two prompt.
    assert "第一阶段生成的 caption" in result.stdout


def test_prompt_json_output_is_machine_readable(tmp_path: Path):
    schema = _write_json(tmp_path, "schema.json", SQUAT_SCHEMA)
    result = run_cli("prompt", "--schema", str(schema), "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == {"one_stage", "two_stage_caption", "two_stage_fields"}
    assert "exercise_type" in payload["one_stage"]["text"]
    assert payload["two_stage_caption"]["max_tokens"] is not None


def test_prompt_rejects_invalid_schema(tmp_path: Path):
    bad = _write_json(tmp_path, "bad.json", {"type": "array"})
    result = run_cli("prompt", "--schema", str(bad))
    assert result.returncode == 2
    assert "schema rejected" in result.stderr


def test_prompt_rejects_missing_file(tmp_path: Path):
    result = run_cli("prompt", "--schema", str(tmp_path / "nope.json"))
    assert result.returncode == 2
    assert "cannot read schema file" in result.stderr
