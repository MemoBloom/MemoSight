"""MemoSight command-line interface.

Commands:

    memosight analyze IMAGE [--language zh|en] [--profile NAME] [--schema FILE]
    memosight doctor
    memosight serve --model /path/to/model [--port 8080]
    memosight setup-mlx [--yes]

``analyze`` writes the stable MemoSightResult JSON to stdout; diagnostics go
to stderr. ``doctor`` checks the local setup and prints remediation advice
for every failing check. Model weights are never downloaded by this CLI —
``setup-mlx`` only installs the mlx-vlm and jinja2 packages (after
confirmation) and prints preparation guidance.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

DEFAULT_SERVER_URL = "http://127.0.0.1:8080"
_DOCTOR_TIMEOUT_S = 5.0


def _version() -> str:
    try:
        return _pkg_version("memosight")
    except PackageNotFoundError:
        return "0.2.1"


def _server_url() -> str:
    return os.environ.get("MEMOSIGHT_MLX_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")


# ── analyze ──


async def _run_analyze(args: argparse.Namespace) -> int:
    from .backends import MlXVlmMemoSightBackend, MockMemoSightBackend
    from .pipeline import MemoSightPipeline
    from .schema import MemoSightImageSource, MemoSightRequest

    output_schema = None
    profile = args.profile
    if args.schema is not None:
        try:
            output_schema = json.loads(Path(args.schema).read_text())
        except OSError as exc:
            print(f"memosight: cannot read schema file: {exc}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"memosight: schema file is not valid JSON: {exc}", file=sys.stderr)
            return 2
        profile = "custom"

    backend = (
        MockMemoSightBackend() if args.backend == "mock" else MlXVlmMemoSightBackend()
    )
    pipeline = MemoSightPipeline(backend=backend)
    request = MemoSightRequest(
        image=MemoSightImageSource(kind="path", image_path=str(args.image)),
        language=args.language,
        profile=profile,
        output_schema=output_schema,
    )
    result = await pipeline.analyze(request)
    indent = None if args.compact else 2
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=indent))
    return 0 if result.status == "ok" else 1


# ── doctor ──


class _Check:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ok = False
        self.detail = ""
        self.advice = ""

    def passed(self, detail: str) -> "_Check":
        self.ok, self.detail = True, detail
        return self

    def failed(self, detail: str, advice: str) -> "_Check":
        self.ok, self.detail, self.advice = False, detail, advice
        return self


async def _run_doctor(_args: argparse.Namespace) -> int:
    checks: list[_Check] = []

    # 1. Package imports
    check = _Check("package imports")
    try:
        import pydantic  # noqa: F401

        from . import __name__ as _pkg  # noqa: F401

        check.passed(f"memosight {_version()}, pydantic {pydantic.VERSION}")
    except Exception as exc:  # pragma: no cover - defensive
        check.failed(
            str(exc),
            "Reinstall the package: `pip install -e .` or `brew reinstall memosight`.",
        )
    checks.append(check)

    # 2. httpx (needed by the MLX client)
    check = _Check("httpx available")
    if importlib.util.find_spec("httpx") is not None:
        check.passed("httpx importable")
    else:
        check.failed(
            "httpx is not installed",
            "Install it: `pip install httpx` (or reinstall memosight with its dependencies).",
        )
    checks.append(check)

    # 3. Server URL configuration (informational)
    url = _server_url()
    configured = "MEMOSIGHT_MLX_SERVER_URL" in os.environ
    check = _Check("server URL")
    check.passed(
        f"{url} (from MEMOSIGHT_MLX_SERVER_URL)"
        if configured
        else f"{url} (default; set MEMOSIGHT_MLX_SERVER_URL to override)"
    )
    checks.append(check)

    # 4/5. Server reachability and health/models
    reach = _Check("server reachable")
    health = _Check("health endpoint")
    model = _Check("model loaded")
    checks.extend([reach, health, model])

    try:
        import httpx
    except ImportError:
        httpx = None

    if httpx is None:
        advice = "Install httpx first: `pip install httpx`."
        reach.failed("skipped — httpx missing", advice)
        health.failed("skipped — httpx missing", advice)
        model.failed("skipped — httpx missing", advice)
    else:
        health_body: dict = {}
        model_ids: list[str] = []
        try:
            async with httpx.AsyncClient(
                timeout=_DOCTOR_TIMEOUT_S, trust_env=False
            ) as client:
                r = await client.get(f"{url}/health")
                reach.passed(f"{url} responded")
                if 200 <= r.status_code < 300:
                    try:
                        health_body = r.json()
                    except Exception:
                        health_body = {}
                    health.passed(f"GET /health -> {r.status_code}")
                else:
                    health.failed(
                        f"GET /health -> {r.status_code}",
                        "The server is running but unhealthy; check the "
                        "mlx_vlm.server logs and restart it.",
                    )
                try:
                    rm = await client.get(f"{url}/v1/models")
                    if 200 <= rm.status_code < 300:
                        model_ids = [
                            item.get("id")
                            for item in rm.json().get("data", [])
                            if isinstance(item, dict) and item.get("id")
                        ]
                except Exception:
                    pass
        except Exception as exc:
            advice = (
                "Start the local server: `memosight serve --model /path/to/model` "
                "or `mlx_vlm.server --model /path/to/model --port 8080`. "
                "If it runs elsewhere, set MEMOSIGHT_MLX_SERVER_URL."
            )
            reach.failed(f"{url} unreachable ({exc.__class__.__name__})", advice)
            health.failed("skipped — server unreachable", advice)
            model.failed("skipped — server unreachable", advice)

        if reach.ok:
            loaded = health_body.get("loaded_model")
            wanted = os.environ.get("MEMOSIGHT_MLX_MODEL_NAME", "")
            resolved = ""
            if wanted:
                resolved = next(
                    (m for m in model_ids if m == wanted or m.endswith(wanted)), ""
                )
                if not resolved and loaded and (loaded == wanted or loaded.endswith(wanted)):
                    resolved = loaded
                if resolved:
                    model.passed(f"{resolved} (matches MEMOSIGHT_MLX_MODEL_NAME)")
                else:
                    model.failed(
                        f"MEMOSIGHT_MLX_MODEL_NAME={wanted!r} not found on server "
                        f"(available: {', '.join(model_ids) or 'none'})",
                        "Fix MEMOSIGHT_MLX_MODEL_NAME to match a server model id, "
                        "or unset it to use the server's first model.",
                    )
            else:
                resolved = loaded or (model_ids[0] if model_ids else "")
                if resolved:
                    model.passed(f"{resolved}")
                else:
                    model.failed(
                        "no model reported by /health or /v1/models",
                        "Start the server with a model: "
                        "`memosight serve --model /path/to/model`.",
                    )

    print(f"memosight doctor — server {url}\n")
    all_ok = True
    for check in checks:
        mark = "ok " if check.ok else "FAIL"
        print(f"  [{mark}] {check.name}: {check.detail}")
        if not check.ok:
            all_ok = False
            print(f"         -> {check.advice}")
    print("\nAll checks passed." if all_ok else "\nSome checks failed; see advice above.")
    return 0 if all_ok else 1


# ── serve ──


def _run_serve(args: argparse.Namespace) -> int:
    executable = shutil.which("mlx_vlm.server")
    if executable is not None:
        cmd = [executable]
    elif importlib.util.find_spec("mlx_vlm") is not None:
        cmd = [sys.executable, "-m", "mlx_vlm.server"]
    else:
        print(
            "memosight: mlx-vlm is not installed.\n"
            "Run `memosight setup-mlx` first, or `pip install mlx-vlm`.",
            file=sys.stderr,
        )
        return 1
    cmd += ["--model", args.model, "--port", str(args.port)]
    cmd += args.extra or []
    print(f"memosight: starting {' '.join(cmd)}", file=sys.stderr)
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130


# ── setup-mlx ──


def _run_setup_mlx(args: argparse.Namespace) -> int:
    # mlx-vlm renders chat templates through jinja2 but does not declare it
    # as a dependency, so install/verify both together.
    missing = [
        pkg
        for pkg, module in (("mlx-vlm", "mlx_vlm"), ("jinja2", "jinja2"))
        if importlib.util.find_spec(module) is None
    ]
    if not missing:
        try:
            version = _pkg_version("mlx-vlm")
        except PackageNotFoundError:
            version = "unknown"
        print(f"mlx-vlm is already installed ({version}).")
    else:
        print(f"Missing packages: {', '.join(missing)}. mlx-vlm provides the")
        print("local VLM server (mlx_vlm.server) that memosight talks to;")
        print("jinja2 is required by mlx-vlm for chat template rendering.")
        print("Note: memosight never downloads models; model weights are")
        print("always prepared explicitly by you.")
        if not args.yes:
            answer = input(
                f"Install now via `pip install {' '.join(missing)}`? [y/N] "
            )
            if answer.strip().lower() not in {"y", "yes"}:
                print("Aborted; nothing was installed.")
                return 1
        rc = subprocess.call(
            [sys.executable, "-m", "pip", "install", *missing]
        )
        if rc != 0:
            print(
                f"memosight: installation failed ({', '.join(missing)}).",
                file=sys.stderr,
            )
            return rc

    print(
        """
Next steps:

  1. Prepare model weights yourself — memosight never downloads models.
     For example, pick an mlx-community VLM on Hugging Face and download it
     explicitly, e.g.:

       huggingface-cli download mlx-community/Qwen3.5-2B-MLX-4bit --local-dir ~/models/Qwen3.5-2B-MLX-4bit

  2. Start the local server:

       memosight serve --model ~/models/Qwen3.5-2B-MLX-4bit --port 8080

  3. Verify the setup:

       memosight doctor
""".strip()
    )
    return 0


# ── prompt ──

_CAPTION_PLACEHOLDER = {
    "zh": "这里替换为第一阶段生成的 caption。",
    "en": "(replaced by the stage-one caption at runtime).",
}


def _run_prompt(args: argparse.Namespace) -> int:
    """Render one-stage and two-stage prompts for a custom schema."""
    from .profiles import MemoSightProfile, validate_output_schema
    from .prompts import (
        build_caption_prompt,
        build_caption_structured_extraction_prompt,
        build_prompt,
    )

    try:
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"memosight: cannot read schema file: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"memosight: schema file is not valid JSON: {exc}", file=sys.stderr)
        return 2
    try:
        validate_output_schema(schema)
    except Exception as exc:
        print(f"memosight: schema rejected: {exc}", file=sys.stderr)
        return 2

    plan = None
    if args.plan is not None:
        try:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
        except OSError as exc:
            print(f"memosight: cannot read plan file: {exc}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"memosight: plan file is not valid JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(plan, dict):
            print("memosight: plan file must contain a JSON object", file=sys.stderr)
            return 2

    lang = "zh" if args.language == "zh" else "en"
    profile = MemoSightProfile(name="custom", schema_name="custom", output_schema=schema)
    caption = args.caption or _CAPTION_PLACEHOLDER[lang]

    one_stage = build_prompt(profile, language=lang, prompt_plan=plan)
    stage_one = build_caption_prompt(language=lang)
    stage_two = build_caption_structured_extraction_prompt(
        caption, profile, language=lang, prompt_plan=plan
    )

    if args.json:
        print(
            json.dumps(
                {
                    "one_stage": _prompt_payload(one_stage),
                    "two_stage_caption": _prompt_payload(stage_one),
                    "two_stage_fields": _prompt_payload(stage_two),
                },
                ensure_ascii=False,
                indent=None if args.compact else 2,
            )
        )
        return 0

    sections = [
        ("One-Stage Prompt", one_stage),
        ("Two-Stage Prompt 1: Image To Caption", stage_one),
        ("Two-Stage Prompt 2: Caption To JSON", stage_two),
    ]
    for title, prompt in sections:
        print(f"## {title}\n")
        print("### System\n")
        print("```text")
        print(prompt.system or "")
        print("```\n")
        print("### User\n")
        print("```text")
        print(prompt.text)
        print("```\n")
    return 0


def _prompt_payload(prompt) -> dict:
    return {
        "system": prompt.system,
        "text": prompt.text,
        "max_tokens": prompt.max_tokens,
        "schema_name": prompt.schema_name,
    }


# ── parser / entry point ──


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memosight",
        description="Local-first image-to-structured-visual-text CLI. "
        "Analyzes images through a local mlx-vlm server and prints validated "
        "JSON. No cloud API is called.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {_version()}"
    )
    sub = parser.add_subparsers(dest="command")

    p_analyze = sub.add_parser(
        "analyze", help="analyze one image and print the validated JSON result"
    )
    p_analyze.add_argument("image", type=Path, help="path to the image file")
    p_analyze.add_argument(
        "--language", default="zh", choices=["zh", "en"], help="prompt language"
    )
    p_analyze.add_argument(
        "--profile",
        default="photography_default",
        help="named output profile (see memosight.list_profiles())",
    )
    p_analyze.add_argument(
        "--schema",
        type=Path,
        default=None,
        metavar="FILE",
        help="custom output schema as a JSON file (implies --profile custom)",
    )
    p_analyze.add_argument(
        "--backend",
        default="mlx",
        choices=["mlx", "mock"],
        help="analysis backend; 'mock' is deterministic and offline (for tests)",
    )
    p_analyze.add_argument(
        "--compact", action="store_true", help="print single-line JSON"
    )
    p_analyze.set_defaults(func=_run_analyze, is_async=True)

    p_doctor = sub.add_parser(
        "doctor", help="check the local setup and print remediation advice"
    )
    p_doctor.set_defaults(func=_run_doctor, is_async=True)

    p_serve = sub.add_parser(
        "serve", help="start the local mlx_vlm.server (wraps mlx-vlm)"
    )
    p_serve.add_argument("--model", required=True, help="path to local model weights")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="additional arguments passed through to mlx_vlm.server",
    )
    p_serve.set_defaults(func=_run_serve, is_async=False)

    p_setup = sub.add_parser(
        "setup-mlx",
        help="install mlx-vlm and jinja2 (with confirmation) and print model setup guidance",
    )
    p_setup.add_argument(
        "--yes", action="store_true", help="do not prompt before pip install"
    )
    p_setup.set_defaults(func=_run_setup_mlx, is_async=False)

    p_prompt = sub.add_parser(
        "prompt",
        help="render one-stage and two-stage prompts for a custom output schema",
    )
    p_prompt.add_argument(
        "--schema", type=Path, required=True, metavar="FILE",
        help="custom output schema as a JSON file",
    )
    p_prompt.add_argument(
        "--plan", type=Path, default=None, metavar="FILE",
        help="prompt plan JSON (task_summary/field_guidance/negative_rules/"
        "output_rules/final_prompt), rendered into the prompts",
    )
    p_prompt.add_argument(
        "--language", default="zh", choices=["zh", "en"], help="prompt language"
    )
    p_prompt.add_argument(
        "--caption",
        default=None,
        help="caption text for the two-stage stage-two prompt "
        "(default: a placeholder)",
    )
    p_prompt.add_argument(
        "--json", action="store_true", help="print machine-readable JSON"
    )
    p_prompt.add_argument(
        "--compact", action="store_true", help="single-line JSON (with --json)"
    )
    p_prompt.set_defaults(func=_run_prompt, is_async=False)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    if getattr(args, "is_async", False):
        return asyncio.run(func(args))
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
