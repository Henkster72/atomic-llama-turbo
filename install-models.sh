#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
IMAGE="${IMAGE:-llama-turboquant-cuda}"
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-podman}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-7200}"
PREFETCH_PORT="${PREFETCH_PORT:-18080}"

usage() {
  cat <<'EOF'
Atomic Llama Turbo model prefetcher

Usage:
  ./install-models.sh                  download validated profile only
  ./install-models.sh --all            download all curated profiles
  ./install-models.sh --profile NAME   download one profile
  ./install-models.sh --list           list profiles
  ./install-models.sh --dry-run --all  show what would be downloaded

Profiles:
  qwen36-coder-q4     Qwen3.6-35B-A3B Q4, main coding, validated
  qwen36-coder-q3     Qwen3.6-35B-A3B Q3, fallback coding candidate
  gemma4-copy-e4b     Gemma 4 E4B Q4, copywriting / fast assistant candidate
  gemma4-fast-e2b     Gemma 4 E2B Q4, smoke test / ultra fast candidate
  qwen36-coder-27b    Qwen3.6 27B Q4, coding comparison candidate

Environment:
  HF_CACHE            host Hugging Face cache, default $HOME/.cache/huggingface
  IMAGE               container image, default llama-turboquant-cuda
  CONTAINER_RUNTIME   podman or docker, default podman
  TIMEOUT_SECONDS     timeout per model server prefetch attempt, default 180
  HF_TOKEN            optional Hugging Face token
  PREFETCH_PORT       temporary container server port, default 18080
EOF
}

profiles_default=(qwen36-coder-q4)
profiles_all=(qwen36-coder-q4 qwen36-coder-q3 gemma4-copy-e4b gemma4-fast-e2b qwen36-coder-27b)
selected=()
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      selected=("${profiles_all[@]}")
      shift
      ;;
    --profile)
      selected+=("$2")
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --list)
      usage
      exit 0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ${#selected[@]} -eq 0 ]]; then
  selected=("${profiles_default[@]}")
fi

mkdir -p "$HF_CACHE"

load_profile() {
  local name="$1"
  local path="$name"
  if [[ ! -f "$path" && -f "$SCRIPT_DIR/profiles/$name.env" ]]; then
    path="$SCRIPT_DIR/profiles/$name.env"
  elif [[ ! -f "$path" && -f "$SCRIPT_DIR/$name" ]]; then
    path="$SCRIPT_DIR/$name"
  fi
  if [[ ! -f "$path" ]]; then
    echo "Profile not found: $name" >&2
    return 1
  fi
  # shellcheck source=/dev/null
  source "$path"
}

runtime_args() {
  if [[ "${CONTAINER_RUNTIME##*/}" == "docker" ]]; then
    printf '%s\n' --gpus all
  else
    printf '%s\n' --device nvidia.com/gpu=all --security-opt=label=disable
  fi
}

volume_spec() {
  if [[ "${CONTAINER_RUNTIME##*/}" == "docker" ]]; then
    printf '%s' "$HF_CACHE:/root/.cache/huggingface"
  else
    printf '%s' "$HF_CACHE:/root/.cache/huggingface:Z"
  fi
}

download_one() {
  local profile="$1"
  MODEL=
  PROFILE_NAME=
  PROFILE_ROLE=
  load_profile "$profile"
  if [[ -z "${MODEL:-}" ]]; then
    echo "Profile $profile does not define MODEL" >&2
    return 1
  fi

  echo
  echo "==> $PROFILE_NAME"
  echo "    role:  ${PROFILE_ROLE:-unknown}"
  echo "    model: $MODEL"
  echo "    cache: $HF_CACHE"

  local args=()
  mapfile -t args < <(runtime_args)
  local volume
  volume="$(volume_spec)"

  local cmd=(
    "$CONTAINER_RUNTIME" run --rm
    "${args[@]}"
    -v "$volume"
  )
  if [[ -n "${HF_TOKEN:-}" ]]; then
    cmd+=(-e HF_TOKEN="$HF_TOKEN")
  fi
  cmd+=(
    "$IMAGE"
    -hf "$MODEL"
    --no-mmproj
    --host 127.0.0.1
    --port "$PREFETCH_PORT"
    -ngl 0
    -c 128
    --no-warmup
    --cache-type-k f16
    --cache-type-v f16
    --mmap
  )

  if [[ "$dry_run" == "1" ]]; then
    printf '    '
    printf '%q ' "${cmd[@]}"
    printf '\n'
    return 0
  fi

  set +e
  timeout --foreground "$TIMEOUT_SECONDS" "${cmd[@]}"
  local status=$?
  set -e

  case "$status" in
    0)
      echo "    downloaded and loaded successfully"
      ;;
    124)
      echo "    timeout after ${TIMEOUT_SECONDS}s; download may still have completed or partially resumed" >&2
      ;;
    *)
      echo "    prefetch exited with status $status; inspect output above" >&2
      return "$status"
      ;;
  esac
}

echo "Atomic Llama Turbo model prefetch"
echo "Selected profiles: ${selected[*]}"
echo "This can download many GB. Use --dry-run first if unsure."

for profile in "${selected[@]}"; do
  download_one "$profile"
done

echo
echo "Done. Cached files live under:"
echo "  $HF_CACHE"
