#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$SCRIPT_DIR/.alt-runtime"
WEB_PID_FILE="$STATE_DIR/atomic-chat-web.pid"
WEB_LOG_FILE="$STATE_DIR/atomic-chat-web.log"

PROFILE="${PROFILE:-qwen36-coder-q4}"
HOST_BIND="${HOST_BIND:-127.0.0.1}"
PORT="${PORT:-8080}"
ATOMIC_CHAT_HOST="${ATOMIC_CHAT_HOST:-127.0.0.1}"
ATOMIC_CHAT_PORT="${ATOMIC_CHAT_PORT:-8090}"
ATOMIC_BASE_URL="${ATOMIC_BASE_URL:-http://$HOST_BIND:$PORT}"

mkdir -p "$STATE_DIR"

usage() {
  cat <<EOF
Atomic Llama Turbo local starter

Usage:
  ./start-alt.sh                 start the default model server and web UI
  ./start-alt.sh start           same as above
  ./start-alt.sh stop            stop the web UI and model server
  ./start-alt.sh restart         restart both
  ./start-alt.sh status          show server and web UI status
  ./start-alt.sh model           print the active model
  ./start-alt.sh logs            follow the web UI log

Defaults:
  PROFILE=$PROFILE
  Model API: $ATOMIC_BASE_URL
  Web UI:    http://$ATOMIC_CHAT_HOST:$ATOMIC_CHAT_PORT

Overrides:
  PROFILE=gemma4-26b-a4b-q4 ./start-alt.sh
  PORT=18080 ATOMIC_CHAT_PORT=18090 ./start-alt.sh
EOF
}

profile_path() {
  local profile="${1:-$PROFILE}"
  if [[ -f "$profile" ]]; then
    printf '%s\n' "$profile"
  elif [[ -f "$SCRIPT_DIR/profiles/$profile.env" ]]; then
    printf '%s\n' "$SCRIPT_DIR/profiles/$profile.env"
  else
    return 1
  fi
}

profile_value() {
  local key="$1"
  local resolved
  resolved="$(profile_path 2>/dev/null)" || return 1
  (
    set -a
    # shellcheck source=/dev/null
    source "$resolved"
    eval 'printf "%s\n" "${'"$key"':-}"'
  )
}

web_url() {
  printf 'http://%s:%s\n' "$ATOMIC_CHAT_HOST" "$ATOMIC_CHAT_PORT"
}

web_pid() {
  [[ -f "$WEB_PID_FILE" ]] || return 1
  local pid
  pid="$(<"$WEB_PID_FILE")"
  [[ -n "$pid" ]] || return 1
  printf '%s\n' "$pid"
}

web_running() {
  local pid
  pid="$(web_pid)" || return 1
  kill -0 "$pid" 2>/dev/null
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local max_wait="${3:-30}"
  local elapsed=0

  while (( elapsed < max_wait )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  echo "$label did not become ready within ${max_wait}s" >&2
  return 1
}

live_model() {
  curl -fsS "$ATOMIC_BASE_URL/v1/models" 2>/dev/null | python3 -c '
import json, sys
try:
    body = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
items = body.get("data") or body.get("models") or []
for item in items:
    if isinstance(item, dict):
        model_id = item.get("id") or item.get("model") or item.get("name")
        if model_id:
            print(model_id)
            raise SystemExit(0)
raise SystemExit(1)
'
}

current_model() {
  live_model 2>/dev/null && return 0
  profile_value MODEL 2>/dev/null && return 0
  printf '%s\n' "unknown"
}

start_server() {
  echo "Starting model server with profile: $PROFILE"
  "$SCRIPT_DIR/atomic-server.sh" switch "$PROFILE"
}

start_web() {
  if web_running; then
    echo "Web UI already running at $(web_url)"
    return 0
  fi

  rm -f "$WEB_PID_FILE"
  echo "Starting web UI at $(web_url)"
  setsid bash -lc '
    cd "$1"
    echo $$ > "$2"
    exec env \
      ATOMIC_BASE_URL="$3" \
      ATOMIC_CHAT_HOST="$4" \
      ATOMIC_CHAT_PORT="$5" \
      python3 "$1/atomic-chat-web.py" >>"$6" 2>&1
  ' bash "$SCRIPT_DIR" "$WEB_PID_FILE" "$ATOMIC_BASE_URL" "$ATOMIC_CHAT_HOST" "$ATOMIC_CHAT_PORT" "$WEB_LOG_FILE" >/dev/null 2>&1 &

  if ! wait_for_http "$(web_url)/api/health" "Web UI" 20; then
    rm -f "$WEB_PID_FILE"
    echo "Recent web log:" >&2
    tail -n 60 "$WEB_LOG_FILE" >&2 || true
    return 1
  fi
}

stop_web() {
  if web_running; then
    local pid
    pid="$(web_pid)"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 10); do
      if kill -0 "$pid" 2>/dev/null; then
        sleep 1
      else
        break
      fi
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "Web UI still running, sending SIGKILL"
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$WEB_PID_FILE"
    echo "Stopped web UI"
  else
    rm -f "$WEB_PID_FILE"
    echo "Web UI not running"
  fi
}

status_all() {
  echo "Model server:"
  "$SCRIPT_DIR/atomic-server.sh" status || true
  echo "Loaded model: $(current_model)"
  echo
  if web_running; then
    if curl -fsS "$(web_url)/api/health" >/dev/null 2>&1; then
      echo "Web UI: running at $(web_url) (pid $(web_pid))"
    else
      echo "Web UI: process running but health check failed at $(web_url) (pid $(web_pid))"
    fi
  else
    echo "Web UI: not running"
  fi
  echo "Web log: $WEB_LOG_FILE"
}

start_all() {
  start_server
  start_web
  echo
  echo "Ready:"
  echo "  Model:     $(current_model)"
  echo "  Model API: $ATOMIC_BASE_URL"
  echo "  Web UI:    $(web_url)"
}

cmd="${1:-start}"
case "$cmd" in
  start)
    start_all
    ;;
  stop)
    stop_web
    "$SCRIPT_DIR/atomic-server.sh" stop
    ;;
  restart)
    stop_web
    "$SCRIPT_DIR/atomic-server.sh" stop
    start_all
    ;;
  status)
    status_all
    ;;
  model)
    current_model
    ;;
  logs)
    touch "$WEB_LOG_FILE"
    tail -n 120 -f "$WEB_LOG_FILE"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
