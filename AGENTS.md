# MemoSight Agent Instructions

## Project

MemoSight is a local-first Python package and CLI for turning images or video
frames into validated structured visual JSON. Keep the core package small:
`memosight/` should stay import-safe, side-effect-light, and free of storage,
database, indexing, or service ownership.

## Development Commands

- Run the full test suite with `uv run pytest` after installing dev extras.
- Run a focused test with `uv run pytest tests/test_name.py`.
- If `uv` is unavailable, `python -m pytest` can run synchronous tests, but
  async tests require `pytest-asyncio` from the dev extras.
- Exercise the CLI from source with `uv run memosight --help` or
  `uv run python -m memosight.cli --help`.
- Start a project-tuned pi session with `scripts/pi-dev.sh`.
- Check the pi setup with `scripts/pi-doctor.sh`.

## Coding Rules

- Prefer existing modules and helpers before adding new abstractions.
- Keep public output contracts stable; schema, parser, normalizer, and
  validator changes need focused tests.
- Treat backend model output as untrusted text until parsed, normalized, and
  validated.
- Do not add network calls, persistence, global config writes, package
  installs, service start/stop commands, or model downloads without explicit
  user approval.
- Local-first is the default. Do not route image content to a cloud endpoint
  unless the user explicitly asks for that backend.
- People fields describe visible roles or subjects only; never infer real
  identity from images.

## Pi Usage

Project-local pi settings live in `.pi/settings.json`. Use `pi --approve` from
the repository root, or run `scripts/pi-dev.sh`, so pi loads project settings,
prompt templates, and the MemoSight skill. To override the script defaults,
pass `--model <provider/model>` before the prompt text. The model cycle list is
configured in `.pi/settings.json` for normal trusted pi sessions.

The MemoSight skill is available as `/skill:memosight` after project trust.
Use it for image understanding, frame tagging, prompt preview, and CLI/API
guidance. Follow the skill boundary rules before installing packages, changing
environment variables, or starting local model services.
