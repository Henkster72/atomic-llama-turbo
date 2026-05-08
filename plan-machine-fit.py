#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODEL_LIST = ROOT / "MODEL_LIST.md"
RESULT_ROOT = ROOT / "quality-bench" / "results"

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


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in COLUMNS})


def load_metrics():
    records = []
    for path in sorted(RESULT_ROOT.glob("*/metrics.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                row = json.loads(line)
                row["_run"] = path.parent.name
                records.append(row)
    return records


def median(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def observed_profile(records, profile):
    rows = [row for row in records if row.get("profile") == profile]
    if not rows:
        return {}
    return {
        "vram_used_mib": median([row.get("vram_used_mib") for row in rows]),
        "ram_used_gib": median([row.get("ram_used_gib") for row in rows]),
        "swap_used_gib": median([row.get("swap_used_gib") for row in rows]),
        "gen_tps": median([row.get("generation_tps") for row in rows]),
    }


def observed_code_tps(records, profile):
    values = [
        row.get("generation_tps")
        for row in records
        if row.get("profile") == profile and row.get("task") == "code_python_logic"
    ]
    return median(values)


def family(row):
    model = row["MODELS"].lower()
    profile = row["Profile"].lower()
    return {
        "qwen_moe": "35b-a3b" in model or "30b-a3b" in model or "qwopus3.6" in model or "caveman-qwen3.6" in model,
        "qwen30_a3b": "30b-a3b" in model,
        "qwen36_dense_27b": "qwen3.6-27b" in model,
        "qwen_dense_14b": ("qwen2.5-coder-14b" in model or "qwen3-14b" in model),
        "qwen25_coder_14b": "qwen2.5-coder-14b" in model,
        "qwen3_14b": "qwen3-14b" in model,
        "qwen_base_q4": profile == "qwen36-coder-q4",
        "qwen_q3": "q3" in model,
        "q4": "q4" in model or "ud-q4" in model,
        "q5": "q5" in model,
        "gemma": "gemma-4" in model,
        "gemma_e2b": "e2b" in model,
        "gemma_e4b": "e4b" in model,
        "bf16": "bf16" in model,
    }


def plan_row(row, obs, target_vram_mib, preserve_validated):
    info = family(row)
    profile = row["Profile"]
    code_tps = (obs.get(profile) or {}).get("code_tps")
    before = dict(row)
    note_parts = []

    if preserve_validated and row.get("Tuning_Status") == "validated":
        return row, "preserved validated baseline"

    row["REASONING"] = row.get("REASONING") or "off"
    row["NO_MMPROJ"] = row.get("NO_MMPROJ") or "1"

    if info["qwen_moe"]:
        row["GPU_LAYERS"] = "99"
        if info["qwen30_a3b"]:
            row["CTX_SIZE"] = "131072"
            row["CACHE_K"] = "turbo4"
            row["CACHE_V"] = "turbo3"
            row["N_CPU_MOE"] = "44"
            if code_tps is not None and code_tps < 14:
                row["Tuning_Status"] = "rejected_slow"
                note_parts.append("Rejected for default runs: Qwen 30B A3B candidate is below the validated Qwen3.6 35B A3B baseline on smoke.")
            else:
                row["Tuning_Status"] = "fit_candidate"
                note_parts.append("Qwen 30B A3B MoE candidate: 48 layers, 3.3B active, 262K context; start with extra CPU MoE offload versus the validated 40-layer Qwen3.6 A3B profile.")
        elif info["q5"]:
            row["CTX_SIZE"] = "65536"
            row["CACHE_K"] = "turbo4"
            row["CACHE_V"] = "turbo3"
            row["N_CPU_MOE"] = "41"
            row["Tuning_Status"] = "stress_candidate"
            note_parts.append("Q5 MoE stress profile: keep full GPU layer request, shorter context, more CPU MoE offload for 24GB RAM.")
        elif info["qwen_q3"]:
            row["CTX_SIZE"] = "131072"
            row["CACHE_K"] = "turbo4"
            row["CACHE_V"] = "turbo3"
            row["N_CPU_MOE"] = "36"
            row["Tuning_Status"] = "rejected_slow"
            note_parts.append("Rejected for default runs: Q3 stays around 8-9 tok/s on this machine despite spare VRAM; Q4 is much faster.")
        else:
            row["CTX_SIZE"] = "131072"
            row["CACHE_K"] = "turbo4"
            row["CACHE_V"] = "turbo3"
            row["N_CPU_MOE"] = "36"
            if code_tps is not None and code_tps < 14:
                row["Tuning_Status"] = "rejected_slow"
                note_parts.append("Rejected for default runs: Qwen A3B derivative is far below the validated Qwen Q4 baseline on smoke.")
            else:
                row["Tuning_Status"] = "fit_candidate"
                note_parts.append("Qwen A3B Q4-class profile: mirror validated Q4 split for derivative comparison.")
    elif info["qwen_dense_14b"]:
        row["CTX_SIZE"] = "32768"
        row["N_CPU_MOE"] = ""
        row["CACHE_K"] = "turbo4"
        row["CACHE_V"] = "turbo3"
        if code_tps is not None and code_tps < 8:
            row["Tuning_Status"] = "rejected_slow"
            note_parts.append(
                "Rejected for default runs: dense 14B partial GPU offload is too slow on this 6GB VRAM machine; "
                "the sparse Qwen3.6 A3B profile is the useful coding baseline here."
            )
        else:
            row["Tuning_Status"] = "fit_candidate"
        if info["qwen25_coder_14b"]:
            row["GPU_LAYERS"] = "24"
            note_parts.append("Dense Qwen2.5 Coder 14B Q4 candidate: start at 32K context with partial GPU offload on 6GB VRAM.")
        else:
            row["GPU_LAYERS"] = "20"
            row["REASONING"] = "off"
            note_parts.append("Dense Qwen3 14B Q4 candidate: start at 32K context, non-thinking mode, and partial GPU offload on 6GB VRAM.")
    elif info["qwen36_dense_27b"]:
        row["CTX_SIZE"] = "32768"
        row["GPU_LAYERS"] = "18"
        row["N_CPU_MOE"] = ""
        row["CACHE_K"] = "turbo4"
        row["CACHE_V"] = "turbo3"
        row["Tuning_Status"] = "stress_candidate"
        note_parts.append("Dense Qwen3.6 27B stress candidate: UD-Q4_K_XL is about 17.6GB, so 24GB RAM plus 6GB VRAM is tight; test load and smoke before full prompts.")
    elif info["gemma"]:
        row["N_CPU_MOE"] = ""
        if info["bf16"]:
            row["CTX_SIZE"] = "32768"
            row["GPU_LAYERS"] = "12"
            row["CACHE_K"] = "turbo4"
            row["CACHE_V"] = "turbo3"
            row["Tuning_Status"] = "quality_control"
            note_parts.append("BF16 E4B cannot fit all layers on 6GB; measured 12/43 layers loaded with about 2.2GB VRAM headroom.")
        elif info["gemma_e2b"]:
            row["CTX_SIZE"] = "32768"
            row["GPU_LAYERS"] = "99"
            row["CACHE_K"] = "q8_0"
            row["CACHE_V"] = "q8_0"
            row["Tuning_Status"] = "fit_candidate"
            note_parts.append("E2B leaves large VRAM headroom; use q8 KV to avoid TurboQuant overhead and benchmark fast-small behavior.")
        elif info["gemma_e4b"]:
            row["CTX_SIZE"] = "65536"
            row["GPU_LAYERS"] = "99"
            row["CACHE_K"] = "q8_0"
            row["CACHE_V"] = "q8_0"
            row["Tuning_Status"] = "fit_candidate"
            note_parts.append("E4B Q4 already fits all layers with spare VRAM; use q8 KV to reduce TurboQuant overhead for speed comparison.")
    else:
        row["GPU_LAYERS"] = row.get("GPU_LAYERS") or "99"
        row["CACHE_K"] = row.get("CACHE_K") or "turbo4"
        row["CACHE_V"] = row.get("CACHE_V") or "turbo3"
        row["Tuning_Status"] = "fit_candidate"
        note_parts.append("Generic fallback: keep existing model-list values.")

    measured = obs.get(profile, {})
    if measured and measured.get("ram_used_gib") is not None and measured.get("gen_tps") is not None:
        note_parts.append(
            "Observed previous median: "
            f"{measured.get('vram_used_mib')} MiB VRAM, "
            f"{float(measured.get('ram_used_gib')):.2f} GiB RAM, "
            f"{float(measured.get('gen_tps')):.2f} gen tok/s."
        )
    note_parts.append(f"Machine target: use up to about {target_vram_mib} MiB VRAM while avoiding swap-heavy Qwen RAM pressure.")
    row["Notes"] = " ".join(note_parts)

    changed = []
    for key in ("CTX_SIZE", "GPU_LAYERS", "CACHE_K", "CACHE_V", "N_CPU_MOE", "Tuning_Status"):
        if str(before.get(key, "")) != str(row.get(key, "")):
            changed.append(f"{key}:{before.get(key, '')}->{row.get(key, '')}")
    return row, ", ".join(changed) if changed else "no setting change"


def main():
    parser = argparse.ArgumentParser(description="Calculate machine-specific MODEL_LIST.md fit assumptions without launching models.")
    parser.add_argument("--model-list", default=str(MODEL_LIST))
    parser.add_argument("--target-vram-mib", type=int, default=5200)
    parser.add_argument("--preserve-validated", action="store_true", default=True)
    parser.add_argument("--include-validated", action="store_true", help="Also rewrite validated rows.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = read_rows(Path(args.model_list))
    records = load_metrics()
    obs = {}
    for row in rows:
        profile = row.get("Profile", "")
        obs[profile] = observed_profile(records, profile)
        obs[profile]["code_tps"] = observed_code_tps(records, profile)
    preserve = args.preserve_validated and not args.include_validated

    planned = []
    print("Machine fit plan:")
    for row in rows:
        if row.get("Downloaded", "").lower() != "yes":
            planned.append(row)
            continue
        updated, reason = plan_row(dict(row), obs, args.target_vram_mib, preserve)
        planned.append(updated)
        print(f"  {updated['Profile']}: {reason}")

    if args.dry_run:
        print("Dry run: MODEL_LIST.md unchanged")
        return
    write_rows(Path(args.model_list), planned)
    print(f"Updated {args.model_list}")


if __name__ == "__main__":
    main()
