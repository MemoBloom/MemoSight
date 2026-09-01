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
