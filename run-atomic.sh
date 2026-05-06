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

IMAGE="${IMAGE:-llama-turboquant-cuda}"
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-podman}"
NAME="${NAME:-atomic-llama-turbo}"
PORT="${PORT:-8080}"
HOST_BIND="${HOST_BIND:-127.0.0.1}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
MODEL="${MODEL:-unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M}"
CTX_SIZE="${CTX_SIZE:-131072}"
if [[ "${N_CPU_MOE+x}" != "x" ]]; then
  N_CPU_MOE=36
fi
CACHE_K="${CACHE_K:-turbo4}"
CACHE_V="${CACHE_V:-turbo3}"
GPU_LAYERS="${GPU_LAYERS:-99}"
NO_MMPROJ="${NO_MMPROJ:-1}"
REASONING="${REASONING:-off}"
FLASH_ATTN="${FLASH_ATTN:-on}"
MLCK="${MLCK:-1}"
NO_MMAP="${NO_MMAP:-1}"

mkdir -p "$HF_CACHE"

RUNTIME_NAME="${CONTAINER_RUNTIME##*/}"
GPU_ARGS=(--device nvidia.com/gpu=all --security-opt=label=disable)
VOLUME_SUFFIX=":Z"

case "$RUNTIME_NAME" in
  docker)
    GPU_ARGS=(--gpus all)
    VOLUME_SUFFIX=""
    ;;
esac

SERVER_ARGS=(
  -hf "$MODEL"
  --host 0.0.0.0
  --port 8080
  -ngl "$GPU_LAYERS"
  -fa "$FLASH_ATTN"
  --reasoning "$REASONING"
  -c "$CTX_SIZE"
  --cache-type-k "$CACHE_K"
  --cache-type-v "$CACHE_V"
)

if [[ -n "$N_CPU_MOE" ]]; then
  SERVER_ARGS+=(--n-cpu-moe "$N_CPU_MOE")
fi
if [[ "$NO_MMPROJ" == "1" ]]; then
  SERVER_ARGS+=(--no-mmproj)
fi
if [[ "$NO_MMAP" == "1" ]]; then
  SERVER_ARGS+=(--no-mmap)
fi
if [[ "$MLCK" == "1" ]]; then
  SERVER_ARGS+=(--mlock)
fi

exec "$CONTAINER_RUNTIME" run --rm \
  --name "$NAME" \
  "${GPU_ARGS[@]}" \
  --cap-add=IPC_LOCK \
  --ulimit memlock=-1:-1 \
  -p "$HOST_BIND:$PORT:8080" \
  -v "$HF_CACHE:/root/.cache/huggingface$VOLUME_SUFFIX" \
  "$IMAGE" \
  "${SERVER_ARGS[@]}" \
  "$@"
