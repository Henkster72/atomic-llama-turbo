#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PROFILE="${PROFILE:-$SCRIPT_DIR/profiles/qwen36-coder-q4.env}"
exec "$SCRIPT_DIR/run-atomic.sh" "$@"
