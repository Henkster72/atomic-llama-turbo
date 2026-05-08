#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env"
  set +a
fi

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
N_PARALLEL="${N_PARALLEL:-1}"
BATCH_SIZE="${BATCH_SIZE:-2048}"
UBATCH_SIZE="${UBATCH_SIZE:-512}"
THREADS="${THREADS:-}"
THREADS_BATCH="${THREADS_BATCH:-}"
POLL="${POLL:-}"
CACHE_REUSE="${CACHE_REUSE:-}"
FIT_TARGET="${FIT_TARGET:-}"
NO_HOST="${NO_HOST:-0}"
MLCK="${MLCK:-1}"
NO_MMAP="${NO_MMAP:-1}"
DETACH="${DETACH:-0}"
REMOVE_ON_EXIT="${REMOVE_ON_EXIT:-1}"
LLAMA_EXTRA_ARGS="${LLAMA_EXTRA_ARGS:-}"

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
  -fa "$FLASH_ATTN"
  --reasoning "$REASONING"
  -np "$N_PARALLEL"
  -b "$BATCH_SIZE"
  -ub "$UBATCH_SIZE"
  -c "$CTX_SIZE"
  --cache-type-k "$CACHE_K"
  --cache-type-v "$CACHE_V"
)

if [[ -n "$THREADS" ]]; then
  SERVER_ARGS+=(-t "$THREADS")
fi
if [[ -n "$THREADS_BATCH" ]]; then
  SERVER_ARGS+=(-tb "$THREADS_BATCH")
fi
if [[ -n "$POLL" ]]; then
  SERVER_ARGS+=(--poll "$POLL")
fi
if [[ -n "$CACHE_REUSE" ]]; then
  SERVER_ARGS+=(--cache-reuse "$CACHE_REUSE")
fi
if [[ -n "$FIT_TARGET" ]]; then
  SERVER_ARGS+=(--fit-target "$FIT_TARGET")
fi
if [[ -n "$GPU_LAYERS" && "$GPU_LAYERS" != "auto" ]]; then
  SERVER_ARGS+=(-ngl "$GPU_LAYERS")
fi
if [[ -n "$N_CPU_MOE" ]]; then
  SERVER_ARGS+=(--n-cpu-moe "$N_CPU_MOE")
fi
if [[ "$NO_MMPROJ" == "1" ]]; then
  SERVER_ARGS+=(--no-mmproj)
fi
if [[ "$NO_MMAP" == "1" ]]; then
  SERVER_ARGS+=(--no-mmap)
fi
if [[ "$NO_HOST" == "1" ]]; then
  SERVER_ARGS+=(--no-host)
fi
if [[ "$MLCK" == "1" ]]; then
  SERVER_ARGS+=(--mlock)
fi
if [[ -n "$LLAMA_EXTRA_ARGS" ]]; then
  # shellcheck disable=SC2206
  EXTRA_ARGS=($LLAMA_EXTRA_ARGS)
  SERVER_ARGS+=("${EXTRA_ARGS[@]}")
fi

RUN_ARGS=(run)
if [[ "$REMOVE_ON_EXIT" == "1" ]]; then
  RUN_ARGS+=(--rm)
fi
if [[ "$DETACH" == "1" ]]; then
  RUN_ARGS+=(--detach)
fi

ENV_ARGS=()
if [[ -n "${HF_TOKEN:-}" ]]; then
  ENV_ARGS+=(-e HF_TOKEN="$HF_TOKEN")
fi

exec "$CONTAINER_RUNTIME" "${RUN_ARGS[@]}" \
  --name "$NAME" \
  "${GPU_ARGS[@]}" \
  "${ENV_ARGS[@]}" \
  --cap-add=IPC_LOCK \
  --ulimit memlock=-1:-1 \
  -p "$HOST_BIND:$PORT:8080" \
  -v "$HF_CACHE:/root/.cache/huggingface$VOLUME_SUFFIX" \
  "$IMAGE" \
  "${SERVER_ARGS[@]}" \
  "$@"
