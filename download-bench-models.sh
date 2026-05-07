#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MODEL_LIST="${MODEL_LIST:-$SCRIPT_DIR/MODEL_LIST.md}"
INSTALLER="${INSTALLER:-$SCRIPT_DIR/install-models.sh}"
INCLUDE_DOWNLOADED=0
DRY_RUN=0
LIST_ONLY=0
MARK_DOWNLOADED=1

usage() {
  cat <<'EOF'
Atomic Llama Turbo benchmark model downloader

Usage:
  ./download-bench-models.sh             download MODEL_LIST.md rows marked Downloaded=no
  ./download-bench-models.sh --all       include rows already marked Downloaded=yes
  ./download-bench-models.sh --dry-run   show fit notes and prefetch commands only
  ./download-bench-models.sh --list      show model/profile mapping only
  ./download-bench-models.sh --no-mark   do not change Downloaded=no to yes after prefetch

Environment:
  MODEL_LIST          CSV-style manifest, default ./MODEL_LIST.md
  HF_CACHE            Hugging Face cache, default inherited by install-models.sh
  CONTAINER_RUNTIME   podman or docker, default inherited by install-models.sh
  IMAGE               llama-server container image, default inherited by install-models.sh
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all|--include-downloaded)
      INCLUDE_DOWNLOADED=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --list)
      LIST_ONLY=1
      shift
      ;;
    --no-mark)
      MARK_DOWNLOADED=0
      shift
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

if [[ "$LIST_ONLY" == "1" ]]; then
  INCLUDE_DOWNLOADED=1
fi

if [[ ! -f "$MODEL_LIST" ]]; then
  echo "Model list not found: $MODEL_LIST" >&2
  exit 1
fi
if [[ ! -x "$INSTALLER" ]]; then
  echo "Installer not executable: $INSTALLER" >&2
  exit 1
fi

model_rows() {
  awk -F, '
    NR == 1 { next }
    NF >= 1 {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
      if ($1 != "") print $1 "," tolower($2)
    }
  ' "$MODEL_LIST"
}

profile_for_model() {
  local model="$1"
  local profile
  for profile in "$SCRIPT_DIR"/profiles/*.env; do
    [[ -f "$profile" ]] || continue
    (
      PROFILE_NAME=
      MODEL=
      # shellcheck source=/dev/null
      source "$profile"
      if [[ "$MODEL" == "$model" ]]; then
        printf '%s\n' "${PROFILE_NAME:-$(basename "$profile" .env)}"
      fi
    )
  done | head -n 1
}

load_profile() {
  local profile_name="$1"
  local path="$SCRIPT_DIR/profiles/$profile_name.env"
  if [[ ! -f "$path" ]]; then
    echo "Profile not found for $profile_name" >&2
    return 1
  fi
  PROFILE_NAME=
  PROFILE_ROLE=
  MODEL=
  CTX_SIZE=
  N_CPU_MOE=
  CACHE_K=
  CACHE_V=
  # shellcheck source=/dev/null
  source "$path"
}

mark_downloaded() {
  local model="$1"
  local tmp
  tmp="$(mktemp)"
  awk -F, -v target="$model" '
    BEGIN { OFS = "," }
    NR == 1 { print; next }
    {
      left = $1
      right = $2
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", left)
      if (left == target) {
        print $1, "yes"
      } else {
        print
      }
    }
  ' "$MODEL_LIST" > "$tmp"
  mv "$tmp" "$MODEL_LIST"
}

fit_note() {
  local profile="$1"
  case "$profile" in
    qwen36-coder-q4)
      echo "validated baseline on 6GB VRAM / 24GB RAM: Q4, 131K, TurboKV, CPU MoE 36"
      ;;
    qwen36-coder-q3)
      echo "same Qwen MoE recipe with lower quant pressure: good fallback if Q4 is tight"
      ;;
    qwopus36-q4|caveman-qwen36-q4)
      echo "Qwen3.6-35B-A3B derivative: should use the same Q4 small-VRAM recipe as the baseline"
      ;;
    qwopus36-q5|caveman-qwen36-q5)
      echo "Qwen3.6-35B-A3B derivative but Q5: downloadable, test at 64K first, expect RAM/swap pressure on 24GB systems"
      ;;
    gemma4-copy-e4b)
      echo "smaller Gemma profile: no CPU MoE flag, useful for fast copywriting and compatibility tests"
      ;;
    gemma4-fast-e2b)
      echo "smallest Gemma profile: no CPU MoE flag, good smoke test / quick assistant"
      ;;
    qwen36-coder-27b)
      echo "coding comparison candidate: no CPU MoE flag in this profile; watch RAM at high context"
      ;;
    *)
      echo "candidate profile: verify load, context, RAM/VRAM, and answer quality before treating as stable"
      ;;
  esac
}

print_disk_note() {
  local cache="${HF_CACHE:-$HOME/.cache/huggingface}"
  mkdir -p "$cache"
  echo "Cache: $cache"
  df -h "$cache" | awk 'NR == 1 || NR == 2 { print "Disk:  " $0 }'
}

cache_has_model() {
  local model="$1"
  local cache="${HF_CACHE:-$HOME/.cache/huggingface}"
  local repo="${model%%:*}"
  local quant=""
  local encoded="${repo//\//--}"
  local repo_path="$cache/hub/models--$encoded"
  if [[ "$model" == *:* ]]; then
    quant="${model#*:}"
  fi
  [[ -d "$repo_path/snapshots" ]] || return 1
  if [[ -n "$quant" ]]; then
    find -L "$repo_path/snapshots" -type f -iname "*.gguf" -iname "*${quant}*" -print -quit | grep -q .
  else
    find -L "$repo_path/snapshots" -type f -iname "*.gguf" -print -quit | grep -q .
  fi
}

echo "Atomic Llama Turbo benchmark model downloader"
echo "Manifest: $MODEL_LIST"
print_disk_note
echo

selected=0
while IFS=, read -r model downloaded; do
  profile="$(profile_for_model "$model")"
  if [[ -z "$profile" ]]; then
    echo "!! No profile maps to: $model" >&2
    echo "   Add profiles/<name>.env before this can be launched cleanly." >&2
    continue
  fi

  load_profile "$profile"

  if [[ "$INCLUDE_DOWNLOADED" != "1" && "$downloaded" == "yes" ]]; then
    echo "skip: $profile"
    echo "      $MODEL"
    echo "      marked Downloaded=yes in manifest; use --all to include it"
    continue
  fi

  selected=$((selected + 1))
  echo "model: $profile"
  echo "  repo:  $MODEL"
  echo "  role:  ${PROFILE_ROLE:-unknown}"
  echo "  fit:   $(fit_note "$profile")"
  echo "  run:   PROFILE=$profile ./run-atomic.sh"
  echo "  bench: ./bench-code.sh --profile profiles/$profile.env"

  if [[ "$LIST_ONLY" == "1" ]]; then
    continue
  fi

  if cache_has_model "$MODEL"; then
    echo "  cache: already present"
    if [[ "$DRY_RUN" == "1" && "$MARK_DOWNLOADED" == "1" && "$downloaded" != "yes" ]]; then
      echo "  manifest: would mark Downloaded=yes"
    elif [[ "$MARK_DOWNLOADED" == "1" && "$downloaded" != "yes" ]]; then
      mark_downloaded "$MODEL"
      echo "  manifest: marked Downloaded=yes"
    fi
    echo
    continue
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    "$INSTALLER" --dry-run --profile "$profile"
  else
    "$INSTALLER" --profile "$profile"
    if [[ "$MARK_DOWNLOADED" == "1" ]]; then
      mark_downloaded "$MODEL"
      echo "  manifest: marked Downloaded=yes"
    fi
  fi
  echo
done < <(model_rows)

if [[ "$selected" == "0" ]]; then
  echo "No models selected. Use --all to include rows already marked Downloaded=yes."
fi
