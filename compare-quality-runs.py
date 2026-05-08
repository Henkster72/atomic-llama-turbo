#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load_run(run_id):
    path = ROOT / "quality-bench" / "results" / run_id / "metrics.jsonl"
    if not path.exists():
        raise SystemExit(f"Missing run metrics: {path}")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def key(row):
    return row["profile"], row["task"]


def fmt(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def main():
    parser = argparse.ArgumentParser(description="Compare two quality-bench metrics.jsonl runs.")
    parser.add_argument("old_run")
    parser.add_argument("new_run")
    args = parser.parse_args()

    old = {key(row): row for row in load_run(args.old_run)}
    new = {key(row): row for row in load_run(args.new_run)}
    keys = sorted(set(old) | set(new))

    print(f"# Compare {args.old_run} -> {args.new_run}\n")
    print("| Profile | Task | Old gen tok/s | New gen tok/s | Delta | Old swap | New swap | Settings changed |")
    print("|---|---|---:|---:|---:|---:|---:|---|")
    for item in keys:
        a = old.get(item)
        b = new.get(item)
        if not a or not b:
            present = "new only" if b else "old only"
            row = b or a
            print(f"| {item[0]} | {item[1]} |  | {fmt(row.get('generation_tps'))} |  |  | {fmt(row.get('swap_used_gib'))} | {present} |")
            continue
        delta = (b.get("generation_tps") or 0) - (a.get("generation_tps") or 0)
        changed = []
        for field in ("ctx_size", "gpu_layers", "cache_k", "cache_v", "n_cpu_moe"):
            if str(a.get(field, "")) != str(b.get(field, "")):
                changed.append(f"{field}: {a.get(field)}->{b.get(field)}")
        print(
            f"| {item[0]} | {item[1]} | {fmt(a.get('generation_tps'))} | {fmt(b.get('generation_tps'))} | "
            f"{delta:.2f} | {fmt(a.get('swap_used_gib'))} | {fmt(b.get('swap_used_gib'))} | "
            f"{'; '.join(changed) or 'no'} |"
        )


if __name__ == "__main__":
    main()
