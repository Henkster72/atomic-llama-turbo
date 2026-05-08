#!/usr/bin/env python3
import argparse
import datetime as dt
import itertools
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent


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
    raise SystemExit(f"Profile not found: {name}")


def split_csv(values):
    if not values:
        return []
    out = []
    for value in values:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out


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
    lines = ["# Generated tuning profile. Local only; ignored by git."]
    for key in order:
        if key in merged:
            lines.append(f"{key}={merged[key]}")
    for key in sorted(set(merged) - set(order)):
        lines.append(f"{key}={merged[key]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Create temporary profile variants and benchmark a small tuning matrix.")
    parser.add_argument("profile", help="Base profile name or path")
    parser.add_argument("--task", default="code_python_logic", choices=["copy_allroundwebsite", "code_python_logic", "code_html_visual"])
    parser.add_argument("--ctx", nargs="*", help="Context sizes to test. Default: base profile value")
    parser.add_argument("--gpu-layers", nargs="*", help="GPU layer counts to test. Default: base profile value")
    parser.add_argument("--cache-pair", nargs="*", help="K:V cache pairs. Example: turbo4:turbo3 q8_0:q8_0")
    parser.add_argument("--n-cpu-moe", nargs="*", help="MoE CPU expert values. Use empty string as '-' for no flag.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--port", default=os.environ.get("QUALITY_BENCH_PORT", "18082"))
    args = parser.parse_args()

    base_path = resolve_profile(args.profile)
    base = load_env(base_path)
    base_name = base.get("PROFILE_NAME", base_path.stem)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "quality-bench" / "tmp-profiles" / f"{base_name}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    ctx_values = split_csv(args.ctx) or [base.get("CTX_SIZE", "65536")]
    gpu_values = split_csv(args.gpu_layers) or [base.get("GPU_LAYERS", "99")]
    cache_values = split_csv(args.cache_pair) or [f"{base.get('CACHE_K', 'turbo4')}:{base.get('CACHE_V', 'turbo3')}"]
    moe_values = split_csv(args.n_cpu_moe)
    if not moe_values:
        moe_values = [base.get("N_CPU_MOE", "-") or "-"]

    temp_profiles = []
    for ctx, gpu_layers, cache_pair, moe in itertools.product(ctx_values, gpu_values, cache_values, moe_values):
        if ":" not in cache_pair:
            raise SystemExit(f"Invalid cache pair: {cache_pair}; expected K:V")
        cache_k, cache_v = cache_pair.split(":", 1)
        suffix = f"ctx{ctx}-ngl{gpu_layers}-k{cache_k}-v{cache_v}-moe{moe}"
        profile_name = f"{base_name}-{suffix}".replace("_", "-").replace(":", "-")
        path = out_dir / f"{profile_name}.env"
        overrides = {
            "PROFILE_NAME": profile_name,
            "CTX_SIZE": ctx,
            "GPU_LAYERS": gpu_layers,
            "CACHE_K": cache_k,
            "CACHE_V": cache_v,
        }
        if moe == "-":
            overrides["N_CPU_MOE"] = ""
        else:
            overrides["N_CPU_MOE"] = moe
        write_profile(path, base, overrides)
        temp_profiles.append(path)

    print("Generated tuning profiles:")
    for path in temp_profiles:
        print(f"  {path}")

    command = [
        str(ROOT / "run-quality-bench.sh"),
        "--profiles",
        *[str(path) for path in temp_profiles],
        "--tasks",
        args.task,
        "--port",
        str(args.port),
    ]
    if args.dry_run:
        print("Dry run command:")
        print(" ".join(command))
        return
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
