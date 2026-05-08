#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "quality-bench" / "tmp-profiles" / "model-list"


ORDER = [
    "PROFILE_NAME",
    "PROFILE_ROLE",
    "MODEL",
    "MODEL_ALIAS",
    "CTX_SIZE",
    "N_CPU_MOE",
    "CACHE_K",
    "CACHE_V",
    "GPU_LAYERS",
    "NO_MMPROJ",
    "REASONING",
]


def alias_for(profile, model):
    if "gemma4-e4b" in profile:
        return "gemma4-e4b"
    if "gemma4-e2b" in profile:
        return "gemma4-e2b"
    if "qwopus" in profile:
        return "qwopus"
    if "caveman" in profile:
        return "caveman"
    if "qwen" in profile:
        return "qwen"
    return profile


def row_to_env(row):
    profile = row.get("Profile", "").strip()
    model = row.get("MODELS", "").strip()
    env = {
        "PROFILE_NAME": profile,
        "PROFILE_ROLE": row.get("Role", "").strip(),
        "MODEL": model,
        "MODEL_ALIAS": alias_for(profile, model),
        "CTX_SIZE": row.get("CTX_SIZE", "").strip(),
        "N_CPU_MOE": row.get("N_CPU_MOE", "").strip(),
        "CACHE_K": row.get("CACHE_K", "").strip(),
        "CACHE_V": row.get("CACHE_V", "").strip(),
        "GPU_LAYERS": row.get("GPU_LAYERS", "").strip(),
        "NO_MMPROJ": row.get("NO_MMPROJ", "1").strip() or "1",
        "REASONING": row.get("REASONING", "off").strip() or "off",
    }
    return env


def write_env(path, env, note="Generated from MODEL_LIST.md. Local only; ignored by git."):
    lines = [f"# {note}"]
    for key in ORDER:
        if key in env:
            lines.append(f"{key}={env[key]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description="Create runnable profile env files from MODEL_LIST.md tuning columns.")
    parser.add_argument("--model-list", default=str(ROOT / "MODEL_LIST.md"))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--include-not-downloaded", action="store_true")
    args = parser.parse_args()

    rows = read_rows(Path(args.model_list))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for row in rows:
        if not args.include_not_downloaded and row.get("Downloaded", "").strip().lower() != "yes":
            continue
        profile = row.get("Profile", "").strip()
        model = row.get("MODELS", "").strip()
        if not profile or not model:
            continue
        env = row_to_env(row)
        path = out_dir / f"{profile}.env"
        write_env(path, env)
        written.append(path)

    for path in written:
        print(path)


if __name__ == "__main__":
    main()
