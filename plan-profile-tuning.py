#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description="Print automatic fit commands for MODEL_LIST.md rows.")
    parser.add_argument("--model-list", default=str(ROOT / "MODEL_LIST.md"))
    parser.add_argument(
        "--only-status",
        default="needs_tuning,needs_fit,load_validated,smoke_validated",
        help="Comma-separated statuses to include; use all for every row.",
    )
    parser.add_argument("--apply-best", action="store_true", help="Include --apply-best in generated commands.")
    args = parser.parse_args()

    wanted = {part.strip() for part in args.only_status.split(",") if part.strip()}
    for row in read_rows(Path(args.model_list)):
        if row.get("Downloaded", "").strip().lower() != "yes":
            continue
        status = row.get("Tuning_Status", "").strip()
        if args.only_status != "all" and status not in wanted:
            continue
        profile = row["Profile"]
        cmd = ["./fit-profile.sh", profile, "--auto-plan"]
        if args.apply_best:
            cmd.append("--apply-best")
        print(" ".join(cmd))


if __name__ == "__main__":
    main()
