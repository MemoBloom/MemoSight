#!/usr/bin/env bash
# Helper for the MemoSight skill.
# Usage: memosight-helper.sh [doctor|analyze IMAGE|serve]
set -euo pipefail

cmd="${1:-}"
shift || true

case "$cmd" in
  doctor)
    exec memosight doctor "$@"
    ;;
  analyze)
    exec memosight analyze "$@"
    ;;
  serve)
    exec memosight serve "$@"
    ;;
  *)
    echo "Usage: memosight-helper.sh [doctor|analyze IMAGE|serve]" >&2
    exit 2
    ;;
esac
