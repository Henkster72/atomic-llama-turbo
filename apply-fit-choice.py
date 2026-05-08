#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODEL_LIST = ROOT / "MODEL_LIST.md"


COLUMNS = [
    "MODELS",
    "Downloaded",
    "Profile",
    "Role",
    "CTX_SIZE",
    "GPU_LAYERS",
    "CACHE_K",
    "CACHE_V",
    "N_CPU_MOE",
    "REASONING",
    "NO_MMPROJ",
    "Tuning_Status",
    "Notes",
]


def load_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in COLUMNS})


def main():
    parser = argparse.ArgumentParser(description="Apply the best fit-profile result back into MODEL_LIST.md tuning columns.")
    parser.add_argument("fit_jsonl", help="quality-bench/tuning/.../fit-results.jsonl")
    parser.add_argument("--rank", type=int, default=1, help="1-based ranked loaded candidate by fit score")
    parser.add_argument("--model-list", default=str(MODEL_LIST))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fit_rows = [row for row in load_jsonl(args.fit_jsonl) if row.get("loaded")]
    if not fit_rows:
        raise SystemExit("No loaded fit rows found")
    fit_rows.sort(key=lambda row: row.get("score", -10**9), reverse=True)
    if args.rank < 1 or args.rank > len(fit_rows):
        raise SystemExit(f"Rank out of range: {args.rank}; loaded rows: {len(fit_rows)}")
    choice = fit_rows[args.rank - 1]

    rows = load_csv(args.model_list)
    updated = False
    for row in rows:
        if row.get("Profile") == choice.get("base_profile"):
            row["CTX_SIZE"] = str(choice.get("CTX_SIZE", ""))
            row["GPU_LAYERS"] = str(choice.get("GPU_LAYERS", ""))
            row["CACHE_K"] = str(choice.get("CACHE_K", ""))
            row["CACHE_V"] = str(choice.get("CACHE_V", ""))
            row["N_CPU_MOE"] = str(choice.get("N_CPU_MOE", ""))
            row["Tuning_Status"] = "fit_selected"
            note = (
                f"Selected from {Path(args.fit_jsonl).parent.name}: "
                f"headroom {choice.get('vram_headroom_mib')} MiB, "
                f"VRAM {choice.get('vram_used_mib')} MiB, score {choice.get('score')}."
            )
            row["Notes"] = note
            updated = True
            break
    if not updated:
        raise SystemExit(f"No MODEL_LIST row found for profile {choice.get('base_profile')}")

    print("Selected fit candidate:")
    print(json.dumps(choice, indent=2, ensure_ascii=False))
    if args.dry_run:
        print("Dry run: MODEL_LIST.md unchanged")
        return
    write_csv(args.model_list, rows)
    print(f"Updated {args.model_list}")


if __name__ == "__main__":
    main()
