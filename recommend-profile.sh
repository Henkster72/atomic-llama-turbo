#!/usr/bin/env bash
set -euo pipefail

vram_mib=0
ram_mib=0
gpu_name="unknown"

if command -v nvidia-smi >/dev/null 2>&1; then
  gpu_csv="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1 || true)"
  if [[ -n "$gpu_csv" ]]; then
    gpu_name="$(awk -F, '{gsub(/^ +| +$/, "", $1); print $1}' <<< "$gpu_csv")"
    vram_mib="$(awk -F, '{gsub(/^ +| +$/, "", $2); print int($2)}' <<< "$gpu_csv")"
  fi
fi

if command -v free >/dev/null 2>&1; then
  ram_mib="$(free -m | awk '/^Mem:/ {print int($2)}')"
fi

vram_gib=$(( (vram_mib + 1023) / 1024 ))
ram_gib=$(( (ram_mib + 1023) / 1024 ))

echo "Atomic Llama Turbo profile recommendation"
echo
echo "Detected:"
echo "  GPU:  $gpu_name"
echo "  VRAM: ${vram_gib} GiB class (${vram_mib} MiB)"
echo "  RAM:  ${ram_gib} GiB class (${ram_mib} MiB)"
echo

recommend="gemma4-fast-e2b"
reason="safe smoke-test profile for unknown or very constrained machines"
optional=()

if (( vram_mib >= 11000 && ram_mib >= 30000 )); then
  recommend="qwen36-coder-q4"
  reason="12GB-class VRAM and 32GB-class RAM should start with the main coding profile; then test higher context"
  optional=("gemma4-copy-e4b" "qwen36-coder-q3" "qwen36-coder-27b")
elif (( vram_mib >= 7500 && ram_mib >= 24000 )); then
  recommend="qwen36-coder-q4"
  reason="8GB-class VRAM and 24GB+ RAM should try the main coding profile first"
  optional=("qwen36-coder-q3" "gemma4-copy-e4b")
elif (( vram_mib >= 5500 && ram_mib >= 22000 )); then
  recommend="qwen36-coder-q4"
  reason="matches the validated 6GB/24GB-class baseline most closely"
  optional=("qwen36-coder-q3" "gemma4-copy-e4b" "gemma4-fast-e2b")
elif (( vram_mib >= 5500 && ram_mib >= 16000 )); then
  recommend="qwen36-coder-q3"
  reason="6GB VRAM but lower RAM; prefer lower-memory fallback before Q4"
  optional=("gemma4-copy-e4b" "gemma4-fast-e2b")
elif (( vram_mib >= 3500 && ram_mib >= 12000 )); then
  recommend="gemma4-copy-e4b"
  reason="small GPU/RAM profile; start with fast copywriting assistant candidate"
  optional=("gemma4-fast-e2b")
fi

echo "Recommended:"
echo "  PROFILE=$recommend"
echo "  Reason: $reason"
echo

if [[ ${#optional[@]} -gt 0 ]]; then
  echo "Optional next tests:"
  for profile in "${optional[@]}"; do
    echo "  - $profile"
  done
  echo
fi

echo "Commands:"
echo "  ./install-models.sh --profile $recommend"
echo "  PROFILE=$recommend ./run-atomic.sh"
echo
echo "After it loads:"
echo "  ./test-atomic.sh"
echo "  ./bench-code.sh --profile profiles/$recommend.env"
echo "  ./bench-copy.sh --profile profiles/$recommend.env"
