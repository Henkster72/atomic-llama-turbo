#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROMPT_DIR = ROOT / "quality-bench" / "prompts"
RESULT_ROOT = ROOT / "quality-bench" / "results"

DEFAULT_COPY_PROMPT = """You are an expert conversion copywriter.

Write practical, persuasive website copy for a small business website service called Example Custom Websites.

Offer:
- custom websites for small businesses, freelancers, and local service providers
- fast static sites where appropriate
- optional hosting, domain setup, email, SEO, branding, and maintenance
- a clear middle ground between generic DIY builders and expensive agencies

Tone:
Clear, specific, confident, lightly cheeky, not generic SaaS.

Output:
1. Five homepage hero headlines.
2. Five subheadlines.
3. Five CTA labels.
4. One short problem section about generic website builders.
5. One short value section explaining why a bespoke website can be a better business asset.
"""

DEFAULT_HTML_PROMPT = """Create one complete single-file HTML document with embedded CSS only.

Use case:
A custom website design service for small businesses.

Goal:
Create a polished landing-page visual concept that communicates bespoke design, speed, practical support, and a move from generic templates to a website made for the business.

Requirements:
- semantic HTML
- embedded CSS
- responsive layout
- no JavaScript
- no external libraries
- no external images
- a header, hero, visual website/mockup metaphor, at least four service cards, pricing/value strip, and footer CTA
- use the copy deck provided by the benchmark where it fits
- output only the complete HTML file, no Markdown fences
"""

DEFAULT_THEME_TEXT = """{
  "name": "generic-alt-benchmark-theme",
  "style": "modern, high contrast, polished, business-friendly",
  "colors": ["#101820", "#f2aa4c", "#2ec4b6", "#ffffff"],
  "notes": "Use this as loose inspiration, not as a rigid design system."
}
"""


@dataclass
class Target:
    name: str
    backend: str
    model: str
    profile: str | None = None
    base_url: str | None = None
    keep_alive: str = "30m"


def slug(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "unknown"


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_optional(path_value: str | None, fallback: str) -> str:
    if not path_value:
        return fallback
    path = Path(path_value).expanduser()
    if path.exists():
        return read(path)
    raise FileNotFoundError(path)


def strip_fence(text: str, extension: str) -> str:
    stripped = text.strip()
    fence = re.match(r"^```(?:[a-zA-Z0-9_+-]+)?\s*\n(?P<body>.*)\n```\s*$", stripped, re.S)
    if fence:
        stripped = fence.group("body").strip()
    if extension == "html":
        idx = stripped.lower().find("<!doctype html")
        if idx >= 0:
            stripped = stripped[idx:]
    return stripped.strip() + "\n"


def count_words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def run_cmd(args: list[str], env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, env=env, check=check)


def wait_http(url: str, timeout: int = 900) -> None:
    start = time.monotonic()
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return
        except Exception:
            pass
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            raise TimeoutError(f"Timed out waiting for {url}")
        print(f"waiting for server... {int(elapsed)}s elapsed", end="\r", flush=True)
        time.sleep(2)


def ollama_generate(
    base_url: str,
    model: str,
    prompt: str,
    *,
    temperature: float,
    max_tokens: int,
    keep_alive: str,
    timeout: int,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": keep_alive,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    first_token = None
    chunks: list[str] = []
    final: dict[str, Any] = {}
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            if not raw.strip():
                continue
            msg = json.loads(raw.decode("utf-8", errors="replace"))
            piece = msg.get("response") or ""
            if piece and first_token is None:
                first_token = time.monotonic() - started
            if piece:
                chunks.append(piece)
            if msg.get("done"):
                final = msg
                break
    elapsed = time.monotonic() - started
    eval_count = final.get("eval_count")
    eval_duration = final.get("eval_duration")
    prompt_eval_count = final.get("prompt_eval_count")
    prompt_eval_duration = final.get("prompt_eval_duration")
    gen_tps = None
    prompt_tps = None
    if eval_count and eval_duration:
        gen_tps = eval_count / (eval_duration / 1_000_000_000)
    if prompt_eval_count and prompt_eval_duration:
        prompt_tps = prompt_eval_count / (prompt_eval_duration / 1_000_000_000)
    return "".join(chunks), {
        "elapsed_sec": elapsed,
        "first_token_sec": first_token,
        "prompt_tokens": prompt_eval_count,
        "completion_tokens": eval_count,
        "prompt_tps": prompt_tps,
        "generation_tps": gen_tps,
        "backend_raw": final,
    }


def openai_chat(
    base_url: str,
    model: str,
    prompt: str,
    *,
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    first_token = None
    chunks: list[str] = []
    usage: dict[str, Any] = {}
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            msg = json.loads(data)
            if msg.get("usage"):
                usage = msg["usage"]
            for choice in msg.get("choices", []):
                delta = choice.get("delta") or {}
                piece = delta.get("content") or ""
                if piece and first_token is None:
                    first_token = time.monotonic() - started
                if piece:
                    chunks.append(piece)
    elapsed = time.monotonic() - started
    completion_tokens = usage.get("completion_tokens")
    prompt_tokens = usage.get("prompt_tokens")
    return "".join(chunks), {
        "elapsed_sec": elapsed,
        "first_token_sec": first_token,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "prompt_tps": None,
        "generation_tps": completion_tokens / elapsed if completion_tokens and elapsed else None,
        "backend_raw": {"usage": usage},
    }


def ollama_unload(base_url: str, model: str) -> None:
    payload = {"model": model, "keep_alive": 0}
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=30).read()
    except Exception:
        pass


def build_html_prompt(base_prompt: str, theme_text: str, copy_text: str) -> str:
    return (
        base_prompt
        + "\n\n---\nSAME-MODEL COPY RESULT TO USE AS THE COPY DECK\n\n"
        + copy_text.strip()
        + "\n\n---\nEXTERNAL THEME FILE: Theme candy.json\n\n"
        + theme_text.strip()
        + "\n\n---\nNow produce one complete browser-reviewable HTML file using the copy deck and Theme candy.json. "
        "Do not output notes, Markdown fences, or CSS-only content.\n"
    )


def write_artifact(path: Path, title: str, model: str, task: str, content: str, extension: str) -> None:
    content = strip_fence(content, extension)
    if extension == "md":
        text = f"# {task} - {title}\n\n- Model: `{model}`\n- Task: `{task}`\n\n{content}"
    else:
        text = content
    path.write_text(text, encoding="utf-8")


def record_row(target: Target, task: str, output_file: str, text: str, stats: dict[str, Any]) -> dict[str, Any]:
    row = {
        "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "profile": target.name,
        "backend": target.backend,
        "model": target.model,
        "task": task,
        "output_file": output_file,
        "elapsed_sec": round(float(stats.get("elapsed_sec") or 0), 3),
        "first_token_sec": round(float(stats["first_token_sec"]), 3) if stats.get("first_token_sec") is not None else None,
        "prompt_tokens": stats.get("prompt_tokens"),
        "completion_tokens": stats.get("completion_tokens"),
        "prompt_tps": stats.get("prompt_tps"),
        "generation_tps": stats.get("generation_tps"),
        "output_chars": len(text),
        "output_words": count_words(text),
        "notes": "",
    }
    return row


def default_targets(ollama_url: str, llama_url: str) -> list[Target]:
    return [
        Target(name="ollama-gemma3-1b", backend="ollama", model="gemma3:1b", base_url=ollama_url),
        Target(name="ollama-gemma3-4b", backend="ollama", model="gemma3:4b", base_url=ollama_url),
        Target(name="qwen36-coder-q4", backend="llamacpp", model="qwen", profile="qwen36-coder-q4", base_url=llama_url),
    ]


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Compare Ollama small models and Atomic Llama Turbo profiles on generic copy + HTML prompts.")
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--llama-url", default=os.environ.get("MIXED_LLAMA_URL", "http://127.0.0.1:18083"))
    parser.add_argument("--llama-port", type=int, default=int(os.environ.get("MIXED_LLAMA_PORT", "18083")))
    parser.add_argument("--llama-container", default=os.environ.get("MIXED_LLAMA_CONTAINER", "atomic-mixed-bench"))
    parser.add_argument("--copy-prompt", help="Optional copy prompt file. Uses a generic built-in prompt by default.")
    parser.add_argument("--html-prompt", help="Optional HTML/CSS prompt file. Uses a generic built-in prompt by default.")
    parser.add_argument("--theme-file", help="Optional theme/reference file. Uses a generic built-in theme by default.")
    parser.add_argument("--result-dir", help="Optional result directory. Defaults to quality-bench/results/<timestamp>__mixed.")
    parser.add_argument("--copy-max-tokens", type=int, default=2600)
    parser.add_argument("--html-max-tokens", type=int, default=3200)
    parser.add_argument("--copy-temperature", type=float, default=0.55)
    parser.add_argument("--html-temperature", type=float, default=0.35)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-llama-server", action="store_true")
    parser.add_argument("--keep-ollama-loaded", action="store_true")
    args = parser.parse_args()

    copy_prompt = read_optional(args.copy_prompt, DEFAULT_COPY_PROMPT)
    html_prompt_base = read_optional(args.html_prompt, DEFAULT_HTML_PROMPT)
    theme_text = read_optional(args.theme_file, DEFAULT_THEME_TEXT)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    result_dir = Path(args.result_dir).expanduser() if args.result_dir else RESULT_ROOT / f"{stamp}__mixed"
    if not result_dir.is_absolute():
        result_dir = (Path.cwd() / result_dir).resolve()

    targets = default_targets(args.ollama_url, args.llama_url)
    print("Mixed benchmark plan:")
    for target in targets:
        print(f"  - {target.name}: {target.backend} {target.model} -> copy_generic, html_visual_generic")
    print(f"Result directory: {result_dir}")
    if args.dry_run:
        return

    result_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = result_dir / "metrics.jsonl"
    summary_path = result_dir / "SUMMARY.md"
    rows: list[dict[str, Any]] = []

    try:
        with metrics_path.open("w", encoding="utf-8") as metrics:
            for target in targets:
                print(f"\n==> {target.name}", flush=True)
                if target.backend == "llamacpp":
                    env = os.environ.copy()
                    env["PORT"] = str(args.llama_port)
                    env["HOST_BIND"] = "127.0.0.1"
                    env["NAME"] = args.llama_container
                    env.setdefault("READY_TIMEOUT", "900")
                    run_cmd([str(ROOT / "atomic-server.sh"), "switch", target.profile or target.name], env=env)
                    wait_http(f"{target.base_url}/health", timeout=args.timeout)

                copy_answer, copy_stats = (
                    ollama_generate(target.base_url or args.ollama_url, target.model, copy_prompt, temperature=args.copy_temperature, max_tokens=args.copy_max_tokens, keep_alive=target.keep_alive, timeout=args.timeout)
                    if target.backend == "ollama"
                    else openai_chat(target.base_url or args.llama_url, target.model, copy_prompt, temperature=args.copy_temperature, max_tokens=args.copy_max_tokens, timeout=args.timeout)
                )
                copy_name = f"{target.name}__copy_generic.md"
                write_artifact(result_dir / copy_name, target.name, target.model, "copy_generic", copy_answer, "md")
                row = record_row(target, "copy_generic", copy_name, copy_answer, copy_stats)
                rows.append(row)
                metrics.write(json.dumps(row, ensure_ascii=False) + "\n")
                metrics.flush()
                print(f"{target.name}/copy: {row['elapsed_sec']}s, gen {row['generation_tps']} tok/s -> {copy_name}", flush=True)

                html_prompt = build_html_prompt(html_prompt_base, theme_text, copy_answer)
                html_answer, html_stats = (
                    ollama_generate(target.base_url or args.ollama_url, target.model, html_prompt, temperature=args.html_temperature, max_tokens=args.html_max_tokens, keep_alive=target.keep_alive, timeout=args.timeout)
                    if target.backend == "ollama"
                    else openai_chat(target.base_url or args.llama_url, target.model, html_prompt, temperature=args.html_temperature, max_tokens=args.html_max_tokens, timeout=args.timeout)
                )
                html_name = f"{target.name}__html_visual_generic.html"
                write_artifact(result_dir / html_name, target.name, target.model, "html_visual_generic", html_answer, "html")
                row = record_row(target, "html_visual_generic", html_name, html_answer, html_stats)
                rows.append(row)
                metrics.write(json.dumps(row, ensure_ascii=False) + "\n")
                metrics.flush()
                print(f"{target.name}/html: {row['elapsed_sec']}s, gen {row['generation_tps']} tok/s -> {html_name}", flush=True)

                if target.backend == "ollama" and not args.keep_ollama_loaded:
                    ollama_unload(target.base_url or args.ollama_url, target.model)
    finally:
        if not args.keep_llama_server:
            env = os.environ.copy()
            env["PORT"] = str(args.llama_port)
            env["HOST_BIND"] = "127.0.0.1"
            env["NAME"] = args.llama_container
            run_cmd([str(ROOT / "atomic-server.sh"), "stop"], env=env, check=False)

    lines = [
        "# Mixed Benchmark",
        "",
        f"- Run: `{result_dir.name}`",
        f"- Ollama URL: `{args.ollama_url}`",
        f"- llama.cpp URL: `{args.llama_url}`",
        f"- Copy prompt: `{Path(args.copy_prompt).name if args.copy_prompt else 'built-in generic copy prompt'}`",
        f"- HTML prompt: `{Path(args.html_prompt).name if args.html_prompt else 'built-in generic HTML prompt'}`",
        f"- Theme file: `{Path(args.theme_file).name if args.theme_file else 'built-in generic theme'}`",
        "",
        "| Profile | Backend | Task | Output | First token | Total | Gen tok/s | Words | Notes |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['profile']} | {row['backend']} | {row['task']} | `{row['output_file']}` | "
            f"{row.get('first_token_sec') or ''} | {row['elapsed_sec']} | {row.get('generation_tps') or ''} | "
            f"{row['output_words']} | {row.get('notes') or ''} |"
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {summary_path}")
    print(f"Wrote {metrics_path}")


if __name__ == "__main__":
    main()
