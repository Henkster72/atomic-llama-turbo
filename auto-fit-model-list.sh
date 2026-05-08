#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ONLY_STATUS="${ONLY_STATUS:-needs_tuning,needs_fit,load_validated,smoke_validated}"

usage() {
  cat <<'EOF'
Atomic Llama Turbo model-list fitter

Usage:
  ./auto-fit-model-list.sh              fit non-selected candidate rows and apply best
  ./auto-fit-model-list.sh --dry-run    print commands only

Environment:
  ONLY_STATUS=needs_fit                 limit statuses

This measures model loading fit only. Run quality benchmarks after this.
EOF
}

dry_run=0
case "${1:-}" in
  --dry-run) dry_run=1 ;;
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac

"$SCRIPT_DIR/materialize-model-list-profiles.sh" >/dev/null
mapfile -t commands < <("$SCRIPT_DIR/plan-profile-tuning.sh" --only-status "$ONLY_STATUS" --apply-best)

if (( ${#commands[@]} == 0 )); then
  echo "No MODEL_LIST.md rows need fitting for status: $ONLY_STATUS"
  exit 0
fi

printf 'Planned fit commands:\n'
printf '  %s\n' "${commands[@]}"

if (( dry_run )); then
  exit 0
fi

for command in "${commands[@]}"; do
  echo
  echo "==> $command"
  (cd "$SCRIPT_DIR" && bash -lc "$command")
done

echo
echo "Fit pass complete. Review MODEL_LIST.md, then run:"
echo "  ./run-quality-bench.sh --dry-run"
