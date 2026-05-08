#!/usr/bin/env python3
import argparse
import datetime as dt
import itertools
import json
import os
import re
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIT_ROOT = ROOT / "quality-bench" / "tuning"


def load_env(path):
    data = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def resolve_profile(name):
    path = Path(name)
    if path.exists():
        return path.resolve()
    path = ROOT / "profiles" / f"{name}.env"
    if path.exists():
        return path
    path = ROOT / "quality-bench" / "tmp-profiles" / "model-list" / f"{name}.env"
    if path.exists():
        return path
    raise SystemExit(f"Profile not found: {name}")


def split_csv(values):
    if not values:
        return []
    out = []
    for value in values:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out


def model_kind(model):
    lowered = model.lower()
    return {
        "qwen_moe": "35b-a3b" in lowered or "qwopus3.6" in lowered or "caveman-qwen3.6" in lowered,
        "gemma4": "gemma-4" in lowered,
        "q5": "q5" in lowered,
        "q4": "q4" in lowered or "ud-q4" in lowered,
        "q3": "q3" in lowered or "ud-q3" in lowered,
        "bf16": "bf16" in lowered,
    }


def unique(values):
    out = []
    seen = set()
    for value in values:
        value = str(value).strip()
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def lower_context(ctx):
    try:
        value = int(ctx)
    except (TypeError, ValueError):
        return []
    lowers = []
    while value > 16384:
        value //= 2
        lowers.append(str(value))
        if len(lowers) >= 2:
            break
    return lowers


def auto_candidates(base):
    model = base.get("MODEL", "")
    kind = model_kind(model)
    base_ctx = base.get("CTX_SIZE", "65536") or "65536"
    base_cache = f"{base.get('CACHE_K', 'turbo4')}:{base.get('CACHE_V', 'turbo3')}"
    base_moe = base.get("N_CPU_MOE", "") or "-"

    # Start from calculated layer bands instead of a hand-entered sweep. `auto`
    # is useful for many GGUFs, but some fork/model combinations assert while
    # fitting; explicit bands keep the run deterministic and measurable.
    if kind["bf16"] and kind["gemma4"]:
        gpu_values = ["16", "12", "20", "8", "24", "4", "0"]
    elif kind["gemma4"]:
        gpu_values = ["99", "42", "32", "24", "16"]
    elif kind["qwen_moe"]:
        gpu_values = ["99", "auto", "36", "28", "20"]
    else:
        gpu_values = ["auto", base.get("GPU_LAYERS", "99")]

    if kind["qwen_moe"]:
        ctx_values = [base_ctx]
        if kind["q3"] or kind["q4"]:
            ctx_values += ["131072", "65536"]
        elif kind["q5"]:
            ctx_values += ["65536", "32768"]
        ctx_values += lower_context(base_ctx)
        cache_values = ["turbo4:turbo3", "turbo3:turbo3", base_cache]
        moe_values = [base_moe, "36", "41"]
    elif kind["gemma4"]:
        ctx_values = [base_ctx]
        if kind["bf16"]:
            ctx_values += ["32768", "16384"]
            cache_values = ["turbo4:turbo3", "turbo3:turbo3", base_cache]
        else:
            ctx_values += ["65536", "32768"]
            cache_values = ["turbo4:turbo3", "q8_0:q8_0", base_cache]
        moe_values = ["-"]
    else:
        ctx_values = [base_ctx] + lower_context(base_ctx)
        cache_values = [base_cache, "turbo4:turbo3"]
        moe_values = [base_moe]

    return unique(ctx_values), unique(gpu_values), unique(cache_values), unique(moe_values)


def write_profile(path, base, overrides):
    merged = dict(base)
    merged.update(overrides)
    order = [
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
    lines = ["# Generated fit profile. Local only; ignored by git."]
    for key in order:
        if key in merged:
            lines.append(f"{key}={merged[key]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args, *, check=True, capture=False, env=None):
    if capture:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, env=env).strip()
    return subprocess.run(args, check=check, env=env)


def snapshot():
    result = {}
    try:
        out = run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,power.draw", "--format=csv,noheader,nounits"],
            capture=True,
        )
        parts = [part.strip() for part in out.splitlines()[0].split(",")]
        result.update(
            {
                "vram_used_mib": int(float(parts[0])),
                "vram_total_mib": int(float(parts[1])),
                "vram_headroom_mib": int(float(parts[1])) - int(float(parts[0])),
                "gpu_util_pct": int(float(parts[2])),
                "gpu_power_w": float(parts[3]),
            }
        )
    except Exception as exc:
        result["gpu_error"] = str(exc)
    try:
        out = run(["free", "-b"], capture=True)
        lines = out.splitlines()
        mem = lines[1].split()
        swap = lines[2].split()
        result.update(
            {
                "ram_used_gib": round(int(mem[2]) / 1024**3, 2),
                "ram_available_gib": round(int(mem[6]) / 1024**3, 2) if len(mem) > 6 else None,
                "swap_used_gib": round(int(swap[2]) / 1024**3, 2),
            }
        )
    except Exception as exc:
        result["ram_error"] = str(exc)
    return result


def stop(name, port):
    env = os.environ.copy()
    env["NAME"] = name
    env["PORT"] = str(port)
    run([str(ROOT / "atomic-server.sh"), "stop"], check=False, env=env)


def server_logs(name, port, tail=220):
    runtime = os.environ.get("CONTAINER_RUNTIME", "podman")
    proc = subprocess.run(
        [runtime, "logs", "--tail", str(tail), name],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.stdout


def switch(profile_path, name, port, timeout):
    env = os.environ.copy()
    env["NAME"] = name
    env["PORT"] = str(port)
    env["READY_TIMEOUT"] = str(timeout)
    start = time.monotonic()
    proc = subprocess.run(
        [str(ROOT / "atomic-server.sh"), "switch", str(profile_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    elapsed = time.monotonic() - start
    return proc.returncode, elapsed, proc.stdout


def parse_load_log(output):
    parsed = {}
    match = re.search(r"offloaded\s+(\d+)/(\d+)\s+layers", output)
    if match:
        parsed["offloaded_layers"] = int(match.group(1))
        parsed["total_layers"] = int(match.group(2))
    for key, pattern in {
        "cuda_model_mib": r"CUDA0 model buffer size =\s+([0-9.]+)\s+MiB",
        "cuda_host_model_mib": r"CUDA_Host model buffer size =\s+([0-9.]+)\s+MiB",
        "cpu_mapped_model_mib": r"CPU_Mapped model buffer size =\s+([0-9.]+)\s+MiB",
        "cuda_kv_mib": r"CUDA0 KV buffer size =\s+([0-9.]+)\s+MiB",
        "cpu_kv_mib": r"CPU KV buffer size =\s+([0-9.]+)\s+MiB",
        "cuda_compute_mib": r"CUDA0 compute buffer size =\s+([0-9.]+)\s+MiB",
    }.items():
        match = re.search(pattern, output)
        if match:
            parsed[key] = round(float(match.group(1)), 2)
    return parsed


def fit_score(row, target_headroom):
    if not row["loaded"]:
        return -10**9
    headroom = row.get("vram_headroom_mib") or 0
    ctx_bonus = int(row.get("CTX_SIZE") or 0) / 256
    layer_bonus = (row.get("offloaded_layers") or 0) * 25
    kv_bonus = 400 if row.get("CACHE_K", "").startswith("turbo") or row.get("CACHE_V", "").startswith("turbo") else 0
    penalty = abs(headroom - target_headroom) * 0.1
    if headroom < 512:
        penalty += 10000
    swap = (row.get("swap_used_gib") or 0) * 50
    return (row.get("vram_used_mib") or 0) + ctx_bonus + layer_bonus + kv_bonus - penalty - swap


def main():
    parser = argparse.ArgumentParser(description="Load candidate profiles and score RAM/VRAM fit before quality prompting.")
    parser.add_argument("profile")
    parser.add_argument("--ctx", nargs="*")
    parser.add_argument("--gpu-layers", nargs="*")
    parser.add_argument("--cache-pair", nargs="*")
    parser.add_argument("--n-cpu-moe", nargs="*")
    parser.add_argument("--auto-plan", action="store_true", help="Generate candidates from model class and current machine fit rules.")
    parser.add_argument("--apply-best", action="store_true", help="Apply the best loaded fit back into MODEL_LIST.md.")
    parser.add_argument("--target-vram-headroom", type=int, default=900)
    parser.add_argument("--ready-timeout", type=int, default=900)
    parser.add_argument("--port", default=os.environ.get("QUALITY_FIT_PORT", "18083"))
    parser.add_argument("--name", default=os.environ.get("QUALITY_FIT_CONTAINER", "atomic-profile-fit"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base_path = resolve_profile(args.profile)
    base = load_env(base_path)
    base_name = base.get("PROFILE_NAME", base_path.stem)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = FIT_ROOT / f"{base_name}-{stamp}"
    profiles_dir = out_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    if args.auto_plan or not (args.ctx or args.gpu_layers or args.cache_pair or args.n_cpu_moe):
        ctx_values, gpu_values, cache_values, moe_values = auto_candidates(base)
    else:
        ctx_values = split_csv(args.ctx) or [base.get("CTX_SIZE", "65536")]
        gpu_values = split_csv(args.gpu_layers) or ["auto"]
        cache_values = split_csv(args.cache_pair) or [f"{base.get('CACHE_K', 'turbo4')}:{base.get('CACHE_V', 'turbo3')}"]
        moe_values = split_csv(args.n_cpu_moe) or [base.get("N_CPU_MOE", "-") or "-"]

    candidates = []
    for ctx, gpu_layers, cache_pair, moe in itertools.product(ctx_values, gpu_values, cache_values, moe_values):
        cache_k, cache_v = cache_pair.split(":", 1)
        profile_name = f"{base_name}-fit-ctx{ctx}-ngl{gpu_layers}-k{cache_k}-v{cache_v}-moe{moe}".replace("_", "-")
        path = profiles_dir / f"{profile_name}.env"
        overrides = {
            "PROFILE_NAME": profile_name,
            "CTX_SIZE": ctx,
            "GPU_LAYERS": gpu_layers,
            "CACHE_K": cache_k,
            "CACHE_V": cache_v,
            "N_CPU_MOE": "" if moe == "-" else moe,
        }
        write_profile(path, base, overrides)
        candidates.append((path, overrides))

    print(f"Generated {len(candidates)} fit candidates in {profiles_dir}")
    if args.dry_run:
        for path, _ in candidates:
            print(path)
        return

    jsonl = out_dir / "fit-results.jsonl"
    rows = []
    try:
        with jsonl.open("w", encoding="utf-8") as handle:
            for path, overrides in candidates:
                print(f"\n==> fitting {path.stem}", flush=True)
                code, load_elapsed, output = switch(path, args.name, args.port, args.ready_timeout)
                loaded = code == 0
                log_output = output
                if loaded:
                    try:
                        log_output = output + "\n" + server_logs(args.name, args.port)
                    except Exception as exc:
                        log_output = output + f"\nfailed to collect running server logs: {exc}"
                metrics = snapshot() if loaded else {}
                parsed_log = parse_load_log(log_output)
                row = {
                    "profile_file": str(path),
                    "profile": path.stem,
                    "base_profile": base_name,
                    "loaded": loaded,
                    "load_elapsed_sec": round(load_elapsed, 3),
                    **overrides,
                    **metrics,
                    **parsed_log,
                    "score": 0,
                }
                row["score"] = round(fit_score(row, args.target_vram_headroom), 3)
                row["log_tail"] = "\n".join(log_output.splitlines()[-80:])
                rows.append(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(
                    f"loaded={loaded} vram={row.get('vram_used_mib')} MiB "
                    f"headroom={row.get('vram_headroom_mib')} MiB layers={row.get('offloaded_layers')}/{row.get('total_layers')} "
                    f"ram={row.get('ram_used_gib')} GiB score={row['score']}",
                    flush=True,
                )
                stop(args.name, args.port)
    finally:
        stop(args.name, args.port)

    rows.sort(key=lambda item: item["score"], reverse=True)
    summary = out_dir / "FIT_SUMMARY.md"
    lines = [
        f"# Fit Summary: {base_name}",
        "",
        f"- Target VRAM headroom: `{args.target_vram_headroom} MiB`",
        f"- Results: `{jsonl.name}`",
        "",
        "| Rank | Loaded | Profile | CTX | NGL | K | V | MoE | VRAM | Headroom | RAM | Swap | Score |",
        "|---:|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"| {idx} | {row['loaded']} | `{Path(row['profile_file']).name}` | {row.get('CTX_SIZE')} | "
            f"{row.get('GPU_LAYERS')} | {row.get('CACHE_K')} | {row.get('CACHE_V')} | {row.get('N_CPU_MOE')} | "
            f"{row.get('vram_used_mib', '')} | {row.get('vram_headroom_mib', '')} | "
            f"{row.get('ram_used_gib', '')} | {row.get('swap_used_gib', '')} | {row['score']} |"
        )
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {summary}")
    print(f"Wrote {jsonl}")
    loaded_rows = [row for row in rows if row.get("loaded")]
    if loaded_rows:
        loaded_rows.sort(key=lambda item: item["score"], reverse=True)
        print(f"Best loaded candidate: {loaded_rows[0]['profile_file']}")
    else:
        print("No loaded candidates found.")
    if args.apply_best:
        if not loaded_rows:
            raise SystemExit("No loaded fit candidate to apply")
        run([str(ROOT / "apply-fit-choice.sh"), str(jsonl)])


if __name__ == "__main__":
    main()
