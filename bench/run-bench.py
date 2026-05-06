#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench"
PROMPTS = BENCH / "prompts"
RESULTS = BENCH / "results"


def load_env(path):
    data = {}
    if not path:
        return data
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def run_text(args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def gpu_snapshot():
    query = "name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"
    out = run_text(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"])
    if not out:
        return {}
    parts = [p.strip() for p in out.splitlines()[0].split(",")]
    if len(parts) < 6:
        return {"raw": out}
    return {
        "gpu_name": parts[0],
        "vram_used_mib": int(float(parts[1])),
        "vram_total_mib": int(float(parts[2])),
        "gpu_util_pct": int(float(parts[3])),
        "gpu_temp_c": int(float(parts[4])),
        "gpu_power_w": float(parts[5]),
    }


def ram_snapshot():
    out = run_text(["free", "-b"])
    lines = out.splitlines()
    if len(lines) < 3:
        return {}
    mem = lines[1].split()
    swap = lines[2].split()
    return {
        "ram_total_gib": round(int(mem[1]) / 1024**3, 2),
        "ram_used_gib": round(int(mem[2]) / 1024**3, 2),
        "ram_available_gib": round(int(mem[6]) / 1024**3, 2) if len(mem) > 6 else None,
        "swap_total_gib": round(int(swap[1]) / 1024**3, 2),
        "swap_used_gib": round(int(swap[2]) / 1024**3, 2),
    }


def complete(base_url, model_alias, prompt):
    payload = {
        "model": model_alias,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 700,
        "temperature": 0.4,
    }
    request = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=900) as response:
        body = json.loads(response.read().decode("utf-8"))
    elapsed = time.monotonic() - started
    answer = body["choices"][0]["message"].get("content", "")
    return answer, body, elapsed


def prompt_files(kind):
    if kind == "all":
        files = sorted(PROMPTS.glob("*/*.md"))
    else:
        files = sorted((PROMPTS / kind).glob("*.md"))
    return files


def main():
    parser = argparse.ArgumentParser(description="Run practical Atomic Llama Turbo benchmarks against the current server.")
    parser.add_argument("--kind", choices=["copy", "code", "all"], default="all")
    parser.add_argument("--profile", default=os.environ.get("PROFILE", "profiles/qwen36-coder-q4.env"))
    parser.add_argument("--base-url", default=os.environ.get("ATOMIC_BASE_URL", os.environ.get("QWEN_BASE_URL", "http://127.0.0.1:8080")))
    parser.add_argument("--model-alias", default=os.environ.get("MODEL_ALIAS", os.environ.get("ATOMIC_MODEL", os.environ.get("QWEN_MODEL", "qwen"))))
    args = parser.parse_args()

    profile_path = Path(args.profile)
    if not profile_path.is_absolute():
        profile_path = ROOT / profile_path
    profile = load_env(profile_path) if profile_path.exists() else {}
    profile_name = profile.get("PROFILE_NAME", profile_path.stem if profile_path.exists() else "ad-hoc")
    model_alias = profile.get("MODEL_ALIAS", args.model_alias)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    jsonl_path = RESULTS / f"{args.kind}-{profile_name}-{stamp}.jsonl"
    md_path = RESULTS / f"{args.kind}-{profile_name}-{stamp}.md"

    rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for prompt_path in prompt_files(args.kind):
            task_kind = prompt_path.parent.name
            task = prompt_path.stem
            prompt = prompt_path.read_text(encoding="utf-8")
            before_gpu = gpu_snapshot()
            before_ram = ram_snapshot()
            answer, body, elapsed = complete(args.base_url, model_alias, prompt)
            after_gpu = gpu_snapshot()
            after_ram = ram_snapshot()
            timings = body.get("timings", {})
            usage = body.get("usage", {})
            row = {
                "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "profile": profile_name,
                "role": profile.get("PROFILE_ROLE", task_kind),
                "task": task,
                "kind": task_kind,
                "model": profile.get("MODEL", body.get("model", "")),
                "model_alias": model_alias,
                "ctx_size": int(profile["CTX_SIZE"]) if profile.get("CTX_SIZE", "").isdigit() else profile.get("CTX_SIZE"),
                "cache_k": profile.get("CACHE_K"),
                "cache_v": profile.get("CACHE_V"),
                "n_cpu_moe": profile.get("N_CPU_MOE"),
                "prompt_tokens": usage.get("prompt_tokens", timings.get("prompt_n")),
                "completion_tokens": usage.get("completion_tokens", timings.get("predicted_n")),
                "prompt_tps": timings.get("prompt_per_second"),
                "generation_tps": timings.get("predicted_per_second"),
                "elapsed_sec": round(elapsed, 3),
                **{f"before_{k}": v for k, v in before_gpu.items()},
                **{f"after_{k}": v for k, v in after_gpu.items()},
                **{f"before_{k}": v for k, v in before_ram.items()},
                **{f"after_{k}": v for k, v in after_ram.items()},
                "human_score": None,
                "answer_preview": answer[:500],
            }
            rows.append(row)
            jsonl.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{task_kind}/{task}: {row['elapsed_sec']}s, gen {row.get('generation_tps')} tok/s")

    lines = [
        f"# Benchmark: {profile_name}",
        "",
        f"- Date: `{stamp}`",
        f"- Profile: `{args.profile}`",
        f"- Base URL: `{args.base_url}`",
        f"- JSONL: `{jsonl_path.name}`",
        "",
        "| Kind | Task | Prompt tok/s | Gen tok/s | Elapsed | VRAM after | RAM after | Score |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['kind']} | {row['task']} | {row.get('prompt_tps') or ''} | "
            f"{row.get('generation_tps') or ''} | {row['elapsed_sec']} | "
            f"{row.get('after_vram_used_mib', '')} MiB | {row.get('after_ram_used_gib', '')} GiB |  |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {jsonl_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
