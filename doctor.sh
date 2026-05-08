#!/usr/bin/env bash
set -uo pipefail

CUDA_TEST_IMAGE="${CUDA_TEST_IMAGE:-docker.io/nvidia/cuda:12.4.1-base-ubuntu22.04}"
SERVER_IMAGE="${SERVER_IMAGE:-llama-turboquant-cuda}"
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-}"
TMP_LOG="/tmp/atomic-llama-doctor-nvidia.$$"

failures=0
warnings=0

cleanup() {
  rm -f "$TMP_LOG"
}
trap cleanup EXIT

ok() { printf 'OK   %s\n' "$*"; }
warn() {
  warnings=$((warnings + 1))
  printf 'WARN %s\n' "$*"
}
fail() {
  failures=$((failures + 1))
  printf 'FAIL %s\n' "$*"
}
info() { printf 'INFO %s\n' "$*"; }
advice() { printf '     advice: %s\n' "$*"; }

runtime_name() {
  basename "$CONTAINER_RUNTIME"
}

gpu_args() {
  if [[ "$(runtime_name)" == "docker" ]]; then
    printf '%s\n' --gpus all
  else
    printf '%s\n' --device nvidia.com/gpu=all --security-opt=label=disable
  fi
}

image_exists() {
  local image="$1"
  if [[ "$(runtime_name)" == "docker" ]]; then
    "$CONTAINER_RUNTIME" image inspect "$image" >/dev/null 2>&1
  else
    "$CONTAINER_RUNTIME" image exists "$image" >/dev/null 2>&1
  fi
}

require_cmd() {
  local cmd="$1"
  local hint="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "dependency: $cmd"
  else
    fail "missing dependency: $cmd"
    advice "$hint"
  fi
}

echo "Atomic Llama Turbo doctor"
echo

if [[ -r /etc/os-release ]]; then
  # shellcheck source=/dev/null
  source /etc/os-release
  info "OS: ${PRETTY_NAME:-unknown}"
else
  warn "OS: /etc/os-release unavailable"
fi

require_cmd python3 "Install Python 3 from your distro packages."
require_cmd curl "Install curl from your distro packages."

if [[ -z "$CONTAINER_RUNTIME" ]]; then
  if command -v podman >/dev/null 2>&1; then
    CONTAINER_RUNTIME="podman"
  elif command -v docker >/dev/null 2>&1; then
    CONTAINER_RUNTIME="docker"
  else
    fail "no container runtime found"
    advice "Install Podman or Docker. On Bazzite/Fedora Atomic, prefer Podman."
  fi
fi

if [[ -n "$CONTAINER_RUNTIME" ]]; then
  if command -v "$CONTAINER_RUNTIME" >/dev/null 2>&1; then
    ok "container runtime: $("$CONTAINER_RUNTIME" --version 2>/dev/null || printf '%s' "$CONTAINER_RUNTIME")"
  else
    fail "container runtime not found: $CONTAINER_RUNTIME"
    advice "Install it, or set CONTAINER_RUNTIME=podman or CONTAINER_RUNTIME=docker."
  fi
fi

gpu_ready=0
if command -v nvidia-smi >/dev/null 2>&1; then
  if nvidia-smi >/dev/null 2>&1; then
    gpu_line="$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>/dev/null | head -n 1 || true)"
    if [[ -n "$gpu_line" ]]; then
      ok "host NVIDIA GPU: $gpu_line"
      gpu_ready=1
    else
      fail "nvidia-smi exists but did not return GPU data"
      advice "Fix the NVIDIA driver first. Containers cannot use a GPU the host cannot see."
    fi
  else
    fail "nvidia-smi is installed but cannot communicate with the NVIDIA driver"
    advice "Fix the NVIDIA driver first. Containers cannot use a GPU the host cannot see."
  fi
else
  fail "nvidia-smi not found"
  advice "Install or repair the NVIDIA driver, reboot if needed, then rerun nvidia-smi."
fi

if command -v free >/dev/null 2>&1; then
  while IFS= read -r line; do
    [[ -n "$line" ]] && info "$line"
  done < <(free -h | awk '/^Mem:/ {print "RAM used "$3"/"$2", available "$7} /^Swap:/ {print "Swap used "$3"/"$2}')
else
  warn "free not found; RAM/swap summary skipped"
fi

if command -v df >/dev/null 2>&1; then
  info "home disk: $(df -h "$HOME" | awk 'NR==2 {print $4" free on "$1}')"
else
  warn "df not found; disk summary skipped"
fi

if [[ -n "$CONTAINER_RUNTIME" ]] && command -v "$CONTAINER_RUNTIME" >/dev/null 2>&1; then
  if [[ "$(runtime_name)" == "podman" ]]; then
    if [[ -f /etc/cdi/nvidia.yaml ]]; then
      ok "NVIDIA CDI file: /etc/cdi/nvidia.yaml"
    else
      fail "NVIDIA CDI file not found at /etc/cdi/nvidia.yaml"
      advice "Fix NVIDIA CDI/container-toolkit setup. On Bazzite, prefer the distro-provided NVIDIA container workflow."
    fi
  fi

  if image_exists "$SERVER_IMAGE"; then
    ok "server image available: $SERVER_IMAGE"
  else
    warn "server image not found yet: $SERVER_IMAGE"
    advice "Build or provide this image before running ./run-atomic.sh."
  fi
fi

if [[ -n "$CONTAINER_RUNTIME" ]] && command -v "$CONTAINER_RUNTIME" >/dev/null 2>&1 && [[ "$gpu_ready" -eq 1 ]]; then
  info "checking NVIDIA GPU inside container with $CONTAINER_RUNTIME"
  mapfile -t args < <(gpu_args)
  if "$CONTAINER_RUNTIME" run --rm "${args[@]}" "$CUDA_TEST_IMAGE" nvidia-smi >"$TMP_LOG" 2>&1; then
    ok "container NVIDIA access works"
    sed -n '1,12p' "$TMP_LOG" | sed 's/^/     /'
  else
    fail "container NVIDIA access failed"
    sed -n '1,24p' "$TMP_LOG" | sed 's/^/     /'
    if [[ "$(runtime_name)" == "docker" ]]; then
      advice "Install or repair NVIDIA Container Toolkit, then test Docker with --gpus all."
    else
      advice "Fix Podman NVIDIA CDI/container GPU access before changing model settings."
    fi
    advice "If the image pull failed, check network access or pre-pull $CUDA_TEST_IMAGE."
  fi
fi

echo
if [[ "$failures" -gt 0 ]]; then
  printf 'Doctor found %d blocking issue(s) and %d warning(s).\n' "$failures" "$warnings"
  echo "Fix the failures above, then rerun ./doctor.sh."
  exit 1
fi

printf 'Doctor passed with %d warning(s).\n' "$warnings"
echo
echo "Next:"
echo "  ./download-bench-models.sh --dry-run"
echo "  PROFILE=qwen36-coder-q4 ./run-atomic.sh"
