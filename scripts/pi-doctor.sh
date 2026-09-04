#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail=0

check_file() {
  local path="$1"
  if [[ -e "$path" ]]; then
    printf '[ok]   %s\n' "$path"
  else
    printf '[fail] %s missing\n' "$path"
    fail=1
  fi
}

check_cmd() {
  local name="$1"
  shift
  if "$@" >/tmp/memosight-pi-doctor.out 2>/tmp/memosight-pi-doctor.err; then
    printf '[ok]   %s\n' "$name"
  else
    printf '[fail] %s\n' "$name"
    sed 's/^/       /' /tmp/memosight-pi-doctor.err
    fail=1
  fi
}

check_file ".pi/settings.json"
check_file ".pi/prompts/plan.md"
check_file ".pi/prompts/fix.md"
check_file ".pi/prompts/review.md"
check_file ".pi/prompts/test.md"
check_file "skills/memosight/SKILL.md"
check_file "memosight-skill/skill/SKILL.md"
check_file "AGENTS.md"

check_cmd "pi settings json" node -e "JSON.parse(require('fs').readFileSync('.pi/settings.json','utf8'))"
check_cmd "pi settings resources" node -e "const s=JSON.parse(require('fs').readFileSync('.pi/settings.json','utf8')); if(!s.packages.includes('../memosight-skill')) process.exit(1); if(!s.prompts.includes('prompts')) process.exit(1)"
check_cmd "memosight-skill package json" node -e "const p=JSON.parse(require('fs').readFileSync('memosight-skill/package.json','utf8')); if (!p.pi || !Array.isArray(p.pi.skills) || !p.pi.skills.includes('./skill')) process.exit(1)"
check_cmd "pi command" pi --version

if command -v uv >/dev/null 2>&1; then
  check_cmd "uv command" uv --version
else
  printf '[warn] uv is not on PATH; install uv or use a prepared Python environment for tests.\n'
fi

if python -c "import pytest_asyncio" >/dev/null 2>&1; then
  printf '[ok]   pytest-asyncio import\n'
else
  printf '[warn] pytest-asyncio is not importable; async pytest cases will fail until dev extras are installed.\n'
fi

printf '[info] Run these from your shell to verify provider auth:\n'
printf '       pi auth check --model dashscope/qwen3-coder-480b-a35b-instruct\n'
printf '       pi auth check --model dashscope/qwen3.7-max-preview\n'
printf '       pi auth check --model huggingface/openai/gpt-oss-120b\n'
printf '       (This pi build returns `invalid` for auth checks launched from a bash script.)\n'

if command -v memosight >/dev/null 2>&1; then
  check_cmd "memosight CLI" memosight --version
else
  printf '[warn] memosight CLI is not on PATH; use `uv run memosight ...` from source or install it separately.\n'
fi

exit "$fail"
