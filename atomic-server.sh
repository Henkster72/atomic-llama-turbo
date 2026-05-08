#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env"
  set +a
fi

CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-podman}"
NAME="${NAME:-atomic-llama-turbo}"
HOST_BIND="${HOST_BIND:-127.0.0.1}"
PORT="${PORT:-8080}"
SERVER_URL="${SERVER_URL:-http://$HOST_BIND:$PORT}"
READY_TIMEOUT="${READY_TIMEOUT:-300}"

usage() {
  cat <<'EOF'
Atomic Llama Turbo server switcher

Usage:
  ./atomic-server.sh start PROFILE      start one profile in the background
  ./atomic-server.sh switch PROFILE     stop current server, start profile, wait ready
  ./atomic-server.sh restart PROFILE    alias for switch
  ./atomic-server.sh stop               stop the current server container
  ./atomic-server.sh status             show current container status
  ./atomic-server.sh logs               follow current server logs
  ./atomic-server.sh test               run ./test-atomic.sh against the current server
  ./atomic-server.sh bench PROFILE      switch profile, then run copy and code benches
  ./atomic-server.sh bench PROFILE copy switch profile, then run copy bench only
  ./atomic-server.sh bench PROFILE code switch profile, then run code bench only

Examples:
  ./atomic-server.sh switch qwen36-coder-q4
  ./atomic-server.sh switch gemma4-copy-e4b
  PORT=18081 ./atomic-server.sh start gemma4-copy-e4b

Profiles stay in profiles/*.env. This script only handles lifecycle.
EOF
}

runtime() {
  "$CONTAINER_RUNTIME" "$@"
}

container_exists() {
  runtime container exists "$NAME" >/dev/null 2>&1
}

container_running() {
  runtime ps --format '{{.Names}}' | grep -qx "$NAME"
}

profile_path() {
  local profile="$1"
  if [[ -f "$profile" ]]; then
    printf '%s\n' "$profile"
  elif [[ -f "$SCRIPT_DIR/profiles/$profile.env" ]]; then
    printf '%s\n' "$SCRIPT_DIR/profiles/$profile.env"
  else
    echo "Profile not found: $profile" >&2
    return 1
  fi
}

stop_server() {
  if container_running; then
    runtime stop "$NAME" >/dev/null
    echo "stopped: $NAME"
  elif container_exists; then
    runtime rm "$NAME" >/dev/null
    echo "removed stopped container: $NAME"
  else
    echo "not running: $NAME"
  fi
}

start_server() {
  local profile="$1"
  local resolved
  resolved="$(profile_path "$profile")"
  if container_running; then
    echo "already running: $NAME" >&2
    echo "use: ./atomic-server.sh switch $profile" >&2
    return 1
  fi
  if container_exists; then
    runtime rm "$NAME" >/dev/null
  fi
  PROFILE="$resolved" DETACH=1 REMOVE_ON_EXIT=0 "$SCRIPT_DIR/run-atomic.sh" >/dev/null
  echo "started: $NAME"
  echo "profile: $profile"
  wait_ready
}

wait_ready() {
  local start now elapsed state
  start="$(date +%s)"
  while true; do
    if curl -fsS "$SERVER_URL/health" >/dev/null 2>&1; then
      printf '\n'
      echo "ready: $SERVER_URL"
      return 0
    fi
    state="$(runtime inspect --format '{{.State.Status}}' "$NAME" 2>/dev/null || true)"
    if [[ -z "$state" ]]; then
      printf '\n'
      echo "server container disappeared before becoming ready: $NAME" >&2
      return 1
    fi
    if [[ "$state" == "exited" || "$state" == "dead" ]]; then
      printf '\n'
      echo "server container exited before becoming ready: $NAME" >&2
      runtime logs --tail 160 "$NAME" >&2 || true
      return 1
    fi
    now="$(date +%s)"
    elapsed=$((now - start))
    if (( elapsed >= READY_TIMEOUT )); then
      printf '\n'
      echo "server did not become ready within ${READY_TIMEOUT}s" >&2
      runtime logs --tail 120 "$NAME" >&2 || true
      return 1
    fi
    printf 'waiting for server... %ss elapsed\r' "$elapsed"
    sleep 2
  done
}

status_server() {
  runtime ps -a --filter "name=^${NAME}$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
}

logs_server() {
  runtime logs -f "$NAME"
}

test_server() {
  SERVER_URL="$SERVER_URL" ATOMIC_BASE_URL="$SERVER_URL" "$SCRIPT_DIR/test-atomic.sh"
}

bench_server() {
  local profile="$1"
  local kind="${2:-all}"
  local resolved
  resolved="$(profile_path "$profile")"
  stop_server
  start_server "$profile"
  case "$kind" in
    all)
      ATOMIC_BASE_URL="$SERVER_URL" "$SCRIPT_DIR/bench-copy.sh" --profile "$resolved"
      ATOMIC_BASE_URL="$SERVER_URL" "$SCRIPT_DIR/bench-code.sh" --profile "$resolved"
      ;;
    copy)
      ATOMIC_BASE_URL="$SERVER_URL" "$SCRIPT_DIR/bench-copy.sh" --profile "$resolved"
      ;;
    code)
      ATOMIC_BASE_URL="$SERVER_URL" "$SCRIPT_DIR/bench-code.sh" --profile "$resolved"
      ;;
    *)
      echo "Unknown bench kind: $kind" >&2
      return 2
      ;;
  esac
}

cmd="${1:-}"
case "$cmd" in
  start)
    [[ $# -ge 2 ]] || { usage >&2; exit 2; }
    start_server "$2"
    ;;
  switch|restart)
    [[ $# -ge 2 ]] || { usage >&2; exit 2; }
    stop_server
    start_server "$2"
    ;;
  stop)
    stop_server
    ;;
  status)
    status_server
    ;;
  logs)
    logs_server
    ;;
  test)
    test_server
    ;;
  bench)
    [[ $# -ge 2 ]] || { usage >&2; exit 2; }
    bench_server "$2" "${3:-all}"
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
