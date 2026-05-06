#!/usr/bin/env bash
set -euo pipefail

CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-podman}"
IMAGE="${IMAGE:-docker.io/nvidia/cuda:12.4.1-base-ubuntu22.04}"

ok() { printf 'OK   %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*"; }
info() { printf 'INFO %s\n' "$*"; }

runtime_name="${CONTAINER_RUNTIME##*/}"

gpu_args() {
  if [[ "$runtime_name" == "docker" ]]; then
    printf '%s\n' --gpus all
  else
    printf '%s\n' --device nvidia.com/gpu=all --security-opt=label=disable
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

if command -v "$CONTAINER_RUNTIME" >/dev/null 2>&1; then
  ok "container runtime: $("$CONTAINER_RUNTIME" --version 2>/dev/null || echo "$CONTAINER_RUNTIME")"
else
  fail "container runtime not found: $CONTAINER_RUNTIME"
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  gpu_line="$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>/dev/null | head -n 1 || true)"
  if [[ -n "$gpu_line" ]]; then
    ok "host NVIDIA GPU: $gpu_line"
  else
    fail "nvidia-smi exists but did not return GPU data"
  fi
else
  fail "nvidia-smi not found"
fi

if command -v free >/dev/null 2>&1; then
  mem_line="$(free -h | awk '/^Mem:/ {print "RAM used "$3"/"$2", available "$7} /^Swap:/ {print "Swap used "$3"/"$2}')"
  while IFS= read -r line; do
    info "$line"
  done <<< "$mem_line"
else
  warn "free not found"
fi

if command -v df >/dev/null 2>&1; then
  info "home disk: $(df -h "$HOME" | awk 'NR==2 {print $4" free on "$1}')"
fi

if [[ "$runtime_name" == "podman" ]]; then
  if [[ -f /etc/cdi/nvidia.yaml ]]; then
    ok "NVIDIA CDI file: /etc/cdi/nvidia.yaml"
  else
    warn "NVIDIA CDI file not found at /etc/cdi/nvidia.yaml"
  fi
fi

if command -v "$CONTAINER_RUNTIME" >/dev/null 2>&1; then
  info "checking NVIDIA GPU inside container with $CONTAINER_RUNTIME"
  mapfile -t args < <(gpu_args)
  set +e
  "$CONTAINER_RUNTIME" run --rm "${args[@]}" "$IMAGE" nvidia-smi >/tmp/atomic-llama-doctor-nvidia.txt 2>&1
  status=$?
  set -e
  if [[ "$status" -eq 0 ]]; then
    ok "container NVIDIA access works"
    sed -n '1,12p' /tmp/atomic-llama-doctor-nvidia.txt | sed 's/^/     /'
  else
    fail "container NVIDIA access failed"
    sed -n '1,20p' /tmp/atomic-llama-doctor-nvidia.txt | sed 's/^/     /'
  fi
fi

echo
echo "Next:"
echo "  ./recommend-profile.sh"
