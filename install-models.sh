#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env"
  set +a
fi

HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
IMAGE="${IMAGE:-llama-turboquant-cuda}"
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-podman}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-7200}"
PREFETCH_PORT="${PREFETCH_PORT:-18080}"
PREFETCH_POLL_SECONDS="${PREFETCH_POLL_SECONDS:-5}"
DOWNLOAD_METHOD="${DOWNLOAD_METHOD:-auto}"

usage() {
  cat <<'EOF'
Atomic Llama Turbo model prefetcher

Usage:
  ./install-models.sh                  download validated profile only
  ./install-models.sh --all            download all profiles in profiles/*.env
  ./install-models.sh --profile NAME   download one profile
  ./install-models.sh --list           list profiles
  ./install-models.sh --dry-run --all  show what would be downloaded

Profiles:
  qwen36-coder-q4              Qwen3.6-35B-A3B Q4, gold ATL baseline
  gemma4-26b-a4b-q4            Gemma 4 26B-A4B Q4, HTML/CSS contender
  qwen3-30b-a3b-2507-q4xl      Qwen3 30B-A3B 2507 Q4XL, Qwen challenger

Environment:
  HF_CACHE            host Hugging Face cache, default $HOME/.cache/huggingface
  IMAGE               container image, default llama-turboquant-cuda
  CONTAINER_RUNTIME   podman or docker, default podman
  TIMEOUT_SECONDS     timeout per model server prefetch attempt, default 7200
  PREFETCH_POLL_SECONDS  seconds between temporary server log checks, default 5
  DOWNLOAD_METHOD     auto, hf, or server; default auto
  HF_TOKEN            optional Hugging Face token
  PREFETCH_PORT       temporary container server port, default 18080
EOF
}

profiles_default=(qwen36-coder-q4)
mapfile -t profiles_all < <(
  for file in "$SCRIPT_DIR"/profiles/*.env; do
    [[ -f "$file" ]] || continue
    (
      PROFILE_NAME=
      # shellcheck source=/dev/null
      source "$file"
      printf '%s\n' "${PROFILE_NAME:-$(basename "$file" .env)}"
    )
  done | sort
)
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

cache_path_for_model() {
  local model="$1"
  local repo="${model%%:*}"
  local encoded="${repo//\//--}"
  printf '%s/hub/models--%s\n' "$HF_CACHE" "$encoded"
}

cache_has_model() {
  local model="$1"
  local quant=""
  local repo_path
  if [[ "$model" == *:* ]]; then
    quant="${model#*:}"
  fi
  repo_path="$(cache_path_for_model "$model")"
  [[ -d "$repo_path/snapshots" ]] || return 1
  if [[ -n "$quant" ]]; then
    find -L "$repo_path/snapshots" -type f -iname "*.gguf" -iname "*${quant}*" -print -quit | grep -q .
  else
    find -L "$repo_path/snapshots" -type f -iname "*.gguf" -print -quit | grep -q .
  fi
}

hf_download_command() {
  local model="$1"
  local repo="${model%%:*}"
  local include="*.gguf"
  if [[ "$model" == *:* ]]; then
    include="*${model#*:}*.gguf"
  fi

  local cmd=(uvx --from huggingface_hub hf download "$repo" --include "$include" --exclude "mmproj*" --cache-dir "$HF_CACHE/hub")
  printf '%s\0' "${cmd[@]}"
}

download_with_hf_cli() {
  local model="$1"
  local cmd=()
  if ! command -v uv >/dev/null 2>&1; then
    return 127
  fi

  mapfile -d '' -t cmd < <(hf_download_command "$model")
  if [[ "$dry_run" == "1" ]]; then
    local redacted=()
    local hide_next=0
    local part
    for part in "${cmd[@]}"; do
      if [[ "$hide_next" == "1" ]]; then
        redacted+=("********")
        hide_next=0
        continue
      fi
      if [[ "$part" == "--token" ]]; then
        redacted+=("$part")
        hide_next=1
        continue
      fi
      redacted+=("$part")
    done
    printf '    '
    printf '%q ' "${redacted[@]}"
    printf '\n'
    return 0
  fi

  "${cmd[@]}"
  cache_has_model "$model"
}

stop_prefetch_container() {
  local name="$1"
  "$CONTAINER_RUNTIME" stop "$name" >/dev/null 2>&1 || true
}

wait_for_prefetch() {
  local name="$1"
  local start now elapsed status logs
  start="$(date +%s)"
  while true; do
    logs="$("$CONTAINER_RUNTIME" logs "$name" 2>&1 || true)"
    if grep -q "main: model loaded" <<< "$logs"; then
      echo "    model loaded; stopping temporary prefetch server"
      stop_prefetch_container "$name"
      return 0
    fi

    status="$("$CONTAINER_RUNTIME" inspect --format '{{.State.Status}}' "$name" 2>/dev/null || true)"
    if [[ "$status" == "exited" || "$status" == "dead" ]]; then
      echo "$logs" | tail -n 80 >&2
      echo "    prefetch container exited before model loaded" >&2
      return 1
    fi

    now="$(date +%s)"
    elapsed=$((now - start))
    if (( elapsed >= TIMEOUT_SECONDS )); then
      echo "$logs" | tail -n 80 >&2
      echo "    timeout after ${TIMEOUT_SECONDS}s; stopping temporary prefetch server" >&2
      stop_prefetch_container "$name"
      return 124
    fi

    printf '    waiting for model load... %ss elapsed\r' "$elapsed"
    sleep "$PREFETCH_POLL_SECONDS"
  done
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

  if cache_has_model "$MODEL"; then
    echo "    already present in cache"
    return 0
  fi

  case "$DOWNLOAD_METHOD" in
    auto|hf)
      set +e
      download_with_hf_cli "$MODEL"
      local hf_status=$?
      set -e
      if [[ "$hf_status" == "0" ]]; then
        if [[ "$dry_run" == "1" ]]; then
          echo "    would download with huggingface_hub"
        else
          echo "    downloaded with huggingface_hub"
        fi
        return 0
      fi
      if [[ "$DOWNLOAD_METHOD" == "hf" ]]; then
        echo "    huggingface_hub download failed or uv is unavailable" >&2
        return 1
      fi
      if [[ "$hf_status" != "127" ]]; then
        echo "    huggingface_hub download failed; not falling back to server prefetch" >&2
        return "$hf_status"
      fi
      echo "    huggingface_hub unavailable or failed; falling back to temporary llama-server prefetch" >&2
      ;;
    server)
      ;;
    *)
      echo "Unknown DOWNLOAD_METHOD: $DOWNLOAD_METHOD" >&2
      return 2
      ;;
  esac

  local args=()
  mapfile -t args < <(runtime_args)
  local volume
  volume="$(volume_spec)"
  local container_name
  container_name="atomic-prefetch-${PROFILE_NAME:-$profile}-$$"
  container_name="${container_name//[^a-zA-Z0-9_.-]/-}"

  local cmd=(
    "$CONTAINER_RUNTIME" run --detach --rm
    --name "$container_name"
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
  "${cmd[@]}" >/dev/null
  local status=$?
  if [[ "$status" == "0" ]]; then
    wait_for_prefetch "$container_name"
    status=$?
  fi
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
if [[ "$dry_run" == "1" ]]; then
  echo "Dry run complete. Cached files will live under:"
else
  echo "Done. Cached files live under:"
fi
echo "  $HF_CACHE"
