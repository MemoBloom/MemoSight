#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODEL="dashscope/qwen3-coder-480b-a35b-instruct"
ARGS=()

while (($#)); do
  case "$1" in
    --model)
      if [[ $# -lt 2 ]]; then
        printf 'usage: %s [--model provider/model] [pi args...]\n' "$0" >&2
        exit 2
      fi
      MODEL="$2"
      shift 2
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

exec pi \
  --no-approve \
  --no-extensions \
  --no-skills \
  --skill memosight-skill/skill \
  --no-prompt-templates \
  --prompt-template .pi/prompts \
  --tools read,bash,edit,write,grep,find,ls \
  --session-dir .pi/sessions \
  --offline \
  --model "$MODEL" \
  "${ARGS[@]}"
