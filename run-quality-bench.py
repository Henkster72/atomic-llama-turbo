#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROMPT_DIR = ROOT / "quality-bench" / "prompts"
RESULT_ROOT = ROOT / "quality-bench" / "results"
BENCHABLE_STATUSES = {"validated", "fit_candidate", "fit_selected"}
CANDIDATE_STATUSES = {"load_validated", "smoke_validated"}

TASKS = [
    {
        "id": "copy_allroundwebsite",
        "kind": "copy",
        "prompt": PROMPT_DIR / "copy_allroundwebsite.md",
        "extension": "md",
        "max_tokens": 2800,
        "temperature": 0.55,
    },
    {
        "id": "code_python_logic",
        "kind": "code",
        "prompt": PROMPT_DIR / "code_python_logic.md",
        "extension": "py",
        "max_tokens": 1200,
        "temperature": 0.25,
    },
    {
        "id": "code_html_visual",
        "kind": "html",
        "prompt": PROMPT_DIR / "code_html_visual.md",
        "extension": "html",
        "max_tokens": 2600,
        "temperature": 0.35,
    },
]

SMOKE_TASKS = {"code_python_logic"}


def load_dotenv():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def load_env(path):
    data = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def slug(value):
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "unknown"


def strip_markdown_fence(text, extension):
    stripped = text.strip()
    fence = re.match(r"^```(?:[a-zA-Z0-9_+-]+)?\s*\n(?P<body>.*)\n```\s*$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group("body").strip()
    if extension == "html":
        idx = stripped.lower().find("<!doctype html")
        if idx >= 0:
            stripped = stripped[idx:]
    if extension == "py":
        idx = stripped.find("from ")
        alt = stripped.find("import ")
        candidates = [value for value in (idx, alt) if value >= 0]
        if candidates:
            stripped = stripped[min(candidates):]
    return stripped


def extract_copy_lines(markdown, limit=12):
    lines = [line.strip() for line in markdown.splitlines()]
    picked = []
    want_next = False
    for line in lines:
        if not line:
            continue
        if line.startswith("#"):
            want_next = True
            continue
        if want_next:
            cleaned = re.sub(r"^[>*.\s0-9-]+", "", line).strip(" *`")
            if cleaned and not cleaned.lower().startswith(("model:", "task:")):
                picked.append(cleaned)
            want_next = False
        if len(picked) >= limit:
            break
    if len(picked) < 5:
        for line in lines:
            cleaned = re.sub(r"^[>*.\s0-9-]+", "", line).strip(" *`")
            if 8 <= len(cleaned) <= 100 and cleaned not in picked and not cleaned.startswith("#"):
                picked.append(cleaned)
            if len(picked) >= limit:
                break
    return picked[:limit]


def prompt_for_task(task, base_prompt, profile_outputs):
    if task["id"] != "code_html_visual":
        return base_prompt
    copy_text = profile_outputs.get("copy_allroundwebsite", "")
    copy_lines = extract_copy_lines(copy_text)
    if not copy_lines:
        return base_prompt
    injected = "\n".join(f"- {line}" for line in copy_lines)
    return (
        base_prompt
        + "\n\nBenchmark-provided copy lines from this same model's copywriting result:\n"
        + injected
        + "\n\nUse several of these lines visibly in the HTML so the visual result connects to the model's own copy direction.\n"
    )


def run(args, *, check=True, capture=False, env=None):
    if capture:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, env=env).strip()
    return subprocess.run(args, check=check, env=env)


def profile_map():
    mapped = {}
    for base in (ROOT / "profiles", ROOT / "quality-bench" / "tmp-profiles" / "model-list"):
        for path in sorted(base.glob("*.env")):
            env = load_env(path)
            model = env.get("MODEL")
            if model:
                mapped[model] = {"path": path, "env": env}
    return mapped


def named_profile_map():
    mapped = {}
    for base in (ROOT / "profiles", ROOT / "quality-bench" / "tmp-profiles" / "model-list"):
        for path in sorted(base.glob("*.env")):
            env = load_env(path)
            name = env.get("PROFILE_NAME", path.stem)
            mapped[name] = {"path": path, "env": env}
    return mapped


def manifest_profile_paths(include_not_downloaded=False, include_untuned=False, include_candidates=False):
    rows = []
    with (ROOT / "MODEL_LIST.md").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            profile = row.get("Profile", "").strip()
            downloaded = row.get("Downloaded", "").strip().lower()
            status = row.get("Tuning_Status", "").strip()
            if not profile:
                continue
            if not include_not_downloaded and downloaded != "yes":
                continue
            allowed_statuses = set(BENCHABLE_STATUSES)
            if include_candidates:
                allowed_statuses.update(CANDIDATE_STATUSES)
            if not include_untuned and status not in allowed_statuses:
                print(
                    f"skip not selected: {profile} ({status or 'no status'}); run ./fit-profile.sh {profile} --auto-plan --apply-best",
                    file=sys.stderr,
                )
                continue
            if profile:
                rows.append(ROOT / "quality-bench" / "tmp-profiles" / "model-list" / f"{profile}.env")
    return rows


def gpu_snapshot():
    query = "name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"
    try:
        out = run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"], capture=True)
    except Exception:
        return {}
    if not out:
        return {}
    parts = [p.strip() for p in out.splitlines()[0].split(",")]
    if len(parts) < 6:
        return {"gpu_raw": out}
    return {
        "gpu_name": parts[0],
        "vram_used_mib": int(float(parts[1])),
        "vram_total_mib": int(float(parts[2])),
        "gpu_util_pct": int(float(parts[3])),
        "gpu_temp_c": int(float(parts[4])),
        "gpu_power_w": float(parts[5]),
    }


def ram_snapshot():
    try:
        out = run(["free", "-b"], capture=True)
    except Exception:
        return {}
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


def complete(base_url, model_alias, prompt, max_tokens, temperature):
    payload = {
        "model": model_alias,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=1800) as response:
        body = json.loads(response.read().decode("utf-8"))
    elapsed = time.monotonic() - started
    answer = body["choices"][0]["message"].get("content", "")
    return answer, body, elapsed


def write_artifact(path, task, profile_name, model, answer):
    answer = strip_markdown_fence(answer, task["extension"])
    if task["extension"] == "md":
        text = (
            f"# {task['id']} - {profile_name}\n\n"
            f"- Model: `{model}`\n"
            f"- Task: `{task['id']}`\n\n"
            f"{answer.strip()}\n"
        )
    else:
        text = answer.strip() + "\n"
    path.write_text(text, encoding="utf-8")


def switch_profile(profile_ref, port, host_bind, name):
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST_BIND"] = host_bind
    env["NAME"] = name
    env.setdefault("READY_TIMEOUT", "900")
    print(f"\n==> switching to {profile_ref} on http://{host_bind}:{port}", flush=True)
    run([str(ROOT / "atomic-server.sh"), "switch", str(profile_ref)], env=env)


def stop_server(port, host_bind, name):
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST_BIND"] = host_bind
    env["NAME"] = name
    run([str(ROOT / "atomic-server.sh"), "stop"], check=False, env=env)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run local quality/speed comparisons across downloaded Atomic Llama Turbo profiles.")
    parser.add_argument("--profiles", nargs="*", help="Profile names to test. Default: all MODEL_LIST rows marked yes.")
    parser.add_argument("--tasks", nargs="*", choices=[task["id"] for task in TASKS], help="Task ids to run. Overrides --stage.")
    parser.add_argument("--stage", choices=["smoke", "full"], default=os.environ.get("QUALITY_BENCH_STAGE", "smoke"), help="Default smoke runs only the cheap Python task; full runs all tasks.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("QUALITY_BENCH_PORT", "18082")))
    parser.add_argument("--host-bind", default=os.environ.get("QUALITY_BENCH_HOST", "127.0.0.1"))
    parser.add_argument("--name", default=os.environ.get("QUALITY_BENCH_CONTAINER", "atomic-quality-bench"))
    parser.add_argument("--keep-server", action="store_true", help="Leave the last tested server running.")
    parser.add_argument("--no-switch", action="store_true", help="Use the currently running server; only valid with one profile.")
    parser.add_argument("--include-untuned", action="store_true", help="Also benchmark MODEL_LIST rows whose Tuning_Status still needs fitting.")
    parser.add_argument("--include-candidates", action="store_true", help="Also benchmark load_validated/smoke_validated candidate rows.")
    parser.add_argument("--result-dir", help="Reuse/write a specific result directory. Useful after an interrupted run.")
    parser.add_argument("--resume", action="store_true", help="Skip task outputs that already exist in the result directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned matrix without switching or prompting.")
    args = parser.parse_args()

    selected = []
    if args.profiles:
        run([str(ROOT / "materialize-model-list-profiles.sh")], capture=True)
        by_name = named_profile_map()
        for name in args.profiles:
            path = Path(name)
            if path.exists():
                if not path.is_absolute():
                    path = (Path.cwd() / path).resolve()
                selected.append({"path": path, "env": load_env(path)})
            elif name not in by_name:
                raise SystemExit(f"Profile not found: {name}")
            else:
                selected.append(by_name[name])
    else:
        run([str(ROOT / "materialize-model-list-profiles.sh")], capture=True)
        for path in manifest_profile_paths(include_untuned=args.include_untuned, include_candidates=args.include_candidates):
            if path.exists():
                selected.append({"path": path, "env": load_env(path)})
            else:
                print(f"warning: materialized profile missing: {path}", file=sys.stderr)

    if args.tasks:
        wanted_tasks = [task for task in TASKS if task["id"] in set(args.tasks)]
    elif args.stage == "smoke":
        wanted_tasks = [task for task in TASKS if task["id"] in SMOKE_TASKS]
    else:
        wanted_tasks = TASKS
    effective_stage = "custom" if args.tasks else args.stage
    print(f"Planned benchmark matrix ({effective_stage} stage):", flush=True)
    for item in selected:
        profile_name = item["env"].get("PROFILE_NAME", item["path"].stem)
        tasks_label = ", ".join(task["id"] for task in wanted_tasks)
        print(f"  - {profile_name}: {tasks_label}", flush=True)

    missing = [str(task["prompt"]) for task in wanted_tasks if not task["prompt"].exists()]
    if missing:
        raise SystemExit("Missing prompt files:\n" + "\n".join(missing))

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    result_dir = Path(args.result_dir).expanduser() if args.result_dir else RESULT_ROOT / stamp
    if not result_dir.is_absolute():
        result_dir = (Path.cwd() / result_dir).resolve()
    stamp = result_dir.name
    if args.dry_run:
        print(f"Result directory: {result_dir}")
        for item in selected:
            profile_name = item["env"].get("PROFILE_NAME", item["path"].stem)
            print(f"{profile_name}:")
            for task in wanted_tasks:
                print(f"  - {task['id']} -> {profile_name}__{task['id']}.{task['extension']}")
        if effective_stage == "smoke":
            profiles = " ".join(item["env"].get("PROFILE_NAME", item["path"].stem) for item in selected)
            print("\nSmoke stage only runs the cheap Python task.")
            print(f"Next full run for these profiles: ./run-quality-bench.sh --stage full --profiles {profiles}")
        return

    result_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = result_dir / "metrics.jsonl"
    summary_path = result_dir / "SUMMARY.md"
    base_url = f"http://{args.host_bind}:{args.port}"
    rows = []

    try:
        with jsonl_path.open("w", encoding="utf-8") as jsonl:
            for item in selected:
                env_data = item["env"]
                profile_name = env_data.get("PROFILE_NAME", item["path"].stem)
                model = env_data.get("MODEL", "")
                model_alias = env_data.get("MODEL_ALIAS", profile_name)
                if not args.no_switch:
                    try:
                        switch_profile(item["path"], args.port, args.host_bind, args.name)
                    except subprocess.CalledProcessError as exc:
                        row = {
                            "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                            "profile": profile_name,
                            "model": model,
                            "ctx_size": env_data.get("CTX_SIZE"),
                            "gpu_layers": env_data.get("GPU_LAYERS"),
                            "cache_k": env_data.get("CACHE_K"),
                            "cache_v": env_data.get("CACHE_V"),
                            "n_cpu_moe": env_data.get("N_CPU_MOE"),
                            "task": "load",
                            "kind": "load",
                            "output_file": "",
                            "elapsed_sec": None,
                            "prompt_tokens": None,
                            "completion_tokens": None,
                            "prompt_tps": None,
                            "generation_tps": None,
                            "vram_used_mib": None,
                            "vram_total_mib": None,
                            "ram_used_gib": None,
                            "ram_available_gib": None,
                            "swap_used_gib": None,
                            "human_quality_score": None,
                            "notes": f"server switch/load failed: {exc.returncode}",
                        }
                        rows.append(row)
                        jsonl.write(json.dumps(row, ensure_ascii=False) + "\n")
                        jsonl.flush()
                        print(f"{profile_name}: load failed; continuing", flush=True)
                        continue
                elif len(selected) != 1:
                    raise SystemExit("--no-switch requires exactly one profile")

                profile_outputs = {}
                for task in wanted_tasks:
                    output_name = f"{slug(profile_name)}__{task['id']}.{task['extension']}"
                    output_path = result_dir / output_name
                    if args.resume and output_path.exists():
                        existing = output_path.read_text(encoding="utf-8")
                        profile_outputs[task["id"]] = existing
                        row = {
                            "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                            "profile": profile_name,
                            "model": model,
                            "ctx_size": env_data.get("CTX_SIZE"),
                            "gpu_layers": env_data.get("GPU_LAYERS"),
                            "cache_k": env_data.get("CACHE_K"),
                            "cache_v": env_data.get("CACHE_V"),
                            "n_cpu_moe": env_data.get("N_CPU_MOE"),
                            "task": task["id"],
                            "kind": task["kind"],
                            "output_file": output_name,
                            "elapsed_sec": 0,
                            "prompt_tokens": None,
                            "completion_tokens": None,
                            "prompt_tps": None,
                            "generation_tps": None,
                            "vram_used_mib": None,
                            "vram_total_mib": None,
                            "ram_used_gib": None,
                            "ram_available_gib": None,
                            "swap_used_gib": None,
                            "human_quality_score": None,
                            "notes": "resumed: existing artifact reused",
                        }
                        rows.append(row)
                        jsonl.write(json.dumps(row, ensure_ascii=False) + "\n")
                        jsonl.flush()
                        print(f"{profile_name}/{task['id']}: reused existing -> {output_name}", flush=True)
                        continue
                    base_prompt = task["prompt"].read_text(encoding="utf-8")
                    prompt = prompt_for_task(task, base_prompt, profile_outputs)
                    before = {**gpu_snapshot(), **ram_snapshot()}
                    answer, body, elapsed = complete(base_url, model_alias, prompt, task["max_tokens"], task["temperature"])
                    after = {**gpu_snapshot(), **ram_snapshot()}
                    timings = body.get("timings", {})
                    usage = body.get("usage", {})
                    completion_tokens = usage.get("completion_tokens", timings.get("predicted_n"))
                    notes = ""
                    if completion_tokens == task["max_tokens"]:
                        notes = "hit max_tokens; output may be incomplete and speed is not a clean comparison"
                    write_artifact(output_path, task, profile_name, model, answer)
                    profile_outputs[task["id"]] = strip_markdown_fence(answer, task["extension"])
                    row = {
                        "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                        "profile": profile_name,
                        "model": model,
                        "ctx_size": env_data.get("CTX_SIZE"),
                        "gpu_layers": env_data.get("GPU_LAYERS"),
                        "cache_k": env_data.get("CACHE_K"),
                        "cache_v": env_data.get("CACHE_V"),
                        "n_cpu_moe": env_data.get("N_CPU_MOE"),
                        "task": task["id"],
                        "kind": task["kind"],
                        "output_file": output_name,
                        "elapsed_sec": round(elapsed, 3),
                        "prompt_tokens": usage.get("prompt_tokens", timings.get("prompt_n")),
                        "completion_tokens": completion_tokens,
                        "prompt_tps": timings.get("prompt_per_second"),
                        "generation_tps": timings.get("predicted_per_second"),
                        "vram_used_mib": after.get("vram_used_mib"),
                        "vram_total_mib": after.get("vram_total_mib"),
                        "ram_used_gib": after.get("ram_used_gib"),
                        "ram_available_gib": after.get("ram_available_gib"),
                        "swap_used_gib": after.get("swap_used_gib"),
                        "human_quality_score": None,
                        "notes": notes,
                    }
                    rows.append(row)
                    jsonl.write(json.dumps(row, ensure_ascii=False) + "\n")
                    jsonl.flush()
                    print(f"{profile_name}/{task['id']}: {row['elapsed_sec']}s, gen {row['generation_tps']} tok/s -> {output_name}")
    finally:
        if not args.keep_server:
            stop_server(args.port, args.host_bind, args.name)

    lines = [
        "# Quality Benchmark Summary",
        "",
        f"- Run: `{stamp}`",
        f"- Stage: `{effective_stage}`",
        f"- Base URL: `{base_url}`",
        f"- Metrics: `{jsonl_path.name}`",
        "",
        "| Profile | Task | Output | Prompt tok/s | Gen tok/s | Elapsed | VRAM | RAM | Swap | Quality | Notes |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['profile']} | {row['task']} | `{row['output_file']}` | "
            f"{row.get('prompt_tps') or ''} | {row.get('generation_tps') or ''} | {row['elapsed_sec']} | "
            f"{row.get('vram_used_mib') or ''} MiB | {row.get('ram_used_gib') or ''} GiB | "
            f"{row.get('swap_used_gib') or ''} GiB |  | {row.get('notes') or ''} |"
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {summary_path}")
    print(f"Wrote {jsonl_path}")
    if effective_stage == "smoke":
        profiles = " ".join(item["env"].get("PROFILE_NAME", item["path"].stem) for item in selected)
        print("Smoke stage complete: copy and HTML were intentionally skipped.")
        print(f"Run full copy/Python/HTML for this shortlist with: ./run-quality-bench.sh --stage full --profiles {profiles}")


if __name__ == "__main__":
    main()
