#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${PROFILE:-}"
if [[ -n "$PROFILE" ]]; then
  if [[ ! -f "$PROFILE" && -f "$SCRIPT_DIR/profiles/$PROFILE.env" ]]; then
    PROFILE="$SCRIPT_DIR/profiles/$PROFILE.env"
  elif [[ ! -f "$PROFILE" && -f "$SCRIPT_DIR/$PROFILE" ]]; then
    PROFILE="$SCRIPT_DIR/$PROFILE"
  fi
  # shellcheck source=/dev/null
  source "$PROFILE"
fi

PORT="${PORT:-8080}"
MODEL_ALIAS="${MODEL_ALIAS:-qwen}"
PROMPT="${PROMPT:-Write a short Python function that recursively lists files but skips .git and node_modules.}"
PAYLOAD="$(python3 -c 'import json,sys; print(json.dumps({"model":sys.argv[1],"messages":[{"role":"user","content":sys.argv[2]}],"max_tokens":300}))' "$MODEL_ALIAS" "$PROMPT")"

curl -sS "http://127.0.0.1:${PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD"
