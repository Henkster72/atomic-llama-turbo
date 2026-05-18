#!/usr/bin/env python3
import datetime as dt
import html.parser
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import chat_store

try:
    import readline
except ImportError:  # pragma: no cover - readline is platform-dependent
    readline = None


BASE_URL = os.environ.get("ATOMIC_BASE_URL", os.environ.get("QWEN_BASE_URL", "http://127.0.0.1:8080"))
API_URL = f"{BASE_URL}/v1/chat/completions"
HEALTH_URL = f"{BASE_URL}/health"
MODELS_URL = f"{BASE_URL}/v1/models"
MODEL = os.environ.get("ATOMIC_MODEL", os.environ.get("QWEN_MODEL", "qwen"))
SYSTEM = os.environ.get("ATOMIC_SYSTEM", os.environ.get("QWEN_SYSTEM", "You are a concise, practical coding assistant."))
MAX_TOKENS = int(os.environ.get("ATOMIC_MAX_TOKENS", "4096"))
ROOT = Path(__file__).resolve().parent
LOG_DIR = chat_store.CHAT_DIR
STABLE_SPLIT = "Load split: CUDA model 3845 MiB, TurboKV+RS+compute 1334 MiB, host model 17253 MiB"
COMMANDS = {
    "/": "show command palette",
    "/help": "show commands",
    "/status": "show server, model, VRAM, RAM and swap",
    "/models": "list models exposed by llama-server",
    "/chats": "list saved console and web chats",
    "/open": "open a saved chat, example: /open 20260506-201500",
    "/search": "search the web, example: /search weather London",
    "/fetch": "fetch a URL and show extracted text",
    "/web": "search, fetch context, then ask the model",
    "/reset": "clear this chat context",
    "/where": "show transcript path",
    "/exit": "quit",
}


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    BLUE = "\033[34m"


def color(text, style):
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{style}{text}{Style.RESET}"


def http_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_text(url, timeout=20):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "atomic-llama-turbo/1.0 (+https://github.com/ggml-org/llama.cpp)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(2_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def wait_until_ready(timeout=900):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=5) as response:
                if response.status == 200:
                    return True
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except urllib.error.URLError as exc:
            last_error = str(exc.reason)
        except TimeoutError:
            last_error = "timeout"
        print(color("  waiting for llama-server...", Style.DIM))
        time.sleep(2)
    print(f"Server was not ready after {timeout}s; last error: {last_error}", file=sys.stderr)
    return False


def setup_readline():
    if readline is None:
        return

    commands = sorted(COMMANDS)

    def complete_command(text, state):
        matches = [cmd for cmd in commands if cmd.startswith(text)]
        try:
            return matches[state]
        except IndexError:
            return None

    readline.set_completer(complete_command)
    readline.parse_and_bind("tab: complete")


def run_text(args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def model_ids():
    try:
        body = http_json(MODELS_URL)
    except Exception:
        return []
    return [item.get("id", "") for item in body.get("data", []) if item.get("id")]


def gpu_status():
    query = "name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"
    out = run_text(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"])
    if not out:
        return "GPU: unavailable"
    parts = [p.strip() for p in out.splitlines()[0].split(",")]
    if len(parts) < 6:
        return f"GPU: {out}"
    name, used, total, util, temp, power = parts[:6]
    return f"GPU: {name} | VRAM {used}/{total} MiB | util {util}% | {temp}C | {power} W"


def ram_status():
    out = run_text(["free", "-h"])
    if not out:
        return "RAM: unavailable"
    lines = out.splitlines()
    mem = lines[1].split() if len(lines) > 1 else []
    swap = lines[2].split() if len(lines) > 2 else []
    if len(mem) >= 4 and len(swap) >= 4:
        return f"RAM: used {mem[2]}/{mem[1]}, available {mem[6] if len(mem) > 6 else '?'} | swap {swap[2]}/{swap[1]}"
    return "RAM: " + " ".join(lines)


def server_status():
    health = "unknown"
    try:
        health = http_json(HEALTH_URL).get("status", "unknown")
    except Exception as exc:
        health = f"unreachable ({exc})"
    models = model_ids()
    model_line = ", ".join(models) if models else MODEL
    return [
        f"Server: {BASE_URL} | health {health}",
        f"Model: {model_line}",
        STABLE_SPLIT,
        gpu_status(),
        ram_status(),
    ]


def print_status():
    labels = {
        "Server": Style.GREEN,
        "Model": Style.CYAN,
        "Load split": Style.YELLOW,
        "GPU": Style.MAGENTA,
        "RAM": Style.BLUE,
    }
    for line in server_status():
        label = line.split(":", 1)[0]
        style = labels.get(label, Style.RESET)
        print(color(line, style))


def write_transcript_header(path):
    chat_store.update_status(path, server_status())


def append_turn(path, role, content, timings=None, meta=None):
    role_key = role.strip().lower().replace(" ", "_")
    chat_store.append_message(path, role_key, content, timings=timings, meta=meta)


def append_meta(path, timings):
    return


class Progress:
    def __init__(self, label):
        self.label = label
        self.started = time.monotonic()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.enabled = sys.stdout.isatty()

    def __enter__(self):
        if self.enabled:
            self.thread.start()
        else:
            print(f"{self.label}...")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.done.set()
        if self.enabled:
            self.thread.join(timeout=1)
            elapsed = time.monotonic() - self.started
            sys.stdout.write("\r" + " " * 72 + "\r")
            sys.stdout.flush()

    def _run(self):
        frames = "|/-\\"
        idx = 0
        while not self.done.wait(0.25):
            elapsed = time.monotonic() - self.started
            sys.stdout.write(f"\r{color(frames[idx % len(frames)], Style.CYAN)} {self.label}... {elapsed:4.1f}s")
            sys.stdout.flush()
            idx += 1


class DuckDuckGoParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.in_link = False
        self.href = ""
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        if tag == "a" and "result__a" in classes:
            self.in_link = True
            self.href = attrs.get("href", "")
            self.text = []

    def handle_data(self, data):
        if self.in_link:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.in_link:
            title = " ".join("".join(self.text).split())
            url = normalize_ddg_url(self.href)
            if title and url:
                self.results.append({"title": title, "url": url})
            self.in_link = False


class TextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
        elif tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1
        elif tag == "title":
            self.in_title = False

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self.in_title:
            self.title = f"{self.title} {text}".strip()
        elif self.skip == 0:
            self.parts.append(text)


def normalize_ddg_url(url):
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    if parsed.path.startswith("/l/"):
        params = urllib.parse.parse_qs(parsed.query)
        if params.get("uddg"):
            return params["uddg"][0]
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://duckduckgo.com" + url
    return url


def search_web(query, limit=5):
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    parser = DuckDuckGoParser()
    parser.feed(http_text(url))
    seen = set()
    results = []
    for result in parser.results:
        if result["url"] in seen:
            continue
        seen.add(result["url"])
        results.append(result)
        if len(results) >= limit:
            break
    return results


def fetch_page(url, max_chars=3500):
    html = http_text(url)
    parser = TextExtractor()
    parser.feed(html)
    text = " ".join(parser.parts)
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "title": parser.title or url,
        "url": url,
        "text": text[:max_chars],
    }


def print_search_results(results):
    if not results:
        print(color("No search results.", Style.YELLOW))
        return
    for idx, result in enumerate(results, 1):
        print(color(f"{idx}. {result['title']}", Style.GREEN))
        print(color(f"   {result['url']}", Style.DIM))


def build_web_context(question):
    results = search_web(question, limit=5)
    pages = []
    for result in results[:3]:
        try:
            page = fetch_page(result["url"], max_chars=2200)
        except Exception as exc:
            page = {"title": result["title"], "url": result["url"], "text": f"[fetch failed: {exc}]"}
        pages.append(page)
    lines = ["Web lookup results:", ""]
    for idx, page in enumerate(pages, 1):
        lines.extend(
            [
                f"[{idx}] {page['title']}",
                page["url"],
                page["text"],
                "",
            ]
        )
    return results, "\n".join(lines).strip()


def complete(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": 0.4,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                body = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 503 and attempt == 0:
                print(color("Server is still loading; waiting for readiness...", Style.YELLOW))
                wait_until_ready()
                continue
            raise
    message = body["choices"][0]["message"]
    return message.get("content", ""), body.get("timings", {}), body.get("usage", {})


def ask_model(messages, label="thinking"):
    started = time.monotonic()
    with Progress(label):
        answer, timings, usage = complete(messages)
    return answer, timings, usage, time.monotonic() - started


def print_timing(elapsed, timings, usage):
    prompt_tps = timings.get("prompt_per_second")
    pred_tps = timings.get("predicted_per_second")
    prompt_n = timings.get("prompt_n", usage.get("prompt_tokens", "?"))
    pred_n = timings.get("predicted_n", usage.get("completion_tokens", "?"))
    if prompt_tps and pred_tps:
        print(color(f"\n[{elapsed:.1f}s | prompt {prompt_tps:.1f} tok/s ({prompt_n}) | gen {pred_tps:.1f} tok/s ({pred_n})]", Style.DIM))
    else:
        print(color(f"\n[{elapsed:.1f}s]", Style.DIM))


def print_commands():
    print(color("\nCommand Palette", Style.BOLD + Style.CYAN))
    for cmd, desc in COMMANDS.items():
        print(f"  {color(cmd.ljust(9), Style.GREEN)} {desc}")
    print(color("\nTip: type / then Enter to show this palette. Tab completes slash commands.", Style.DIM))


def print_usage(command):
    usages = {
        "/search": "/search <query>",
        "/fetch": "/fetch <url>",
        "/web": "/web <question>",
        "/open": "/open <chat-id>",
    }
    print(color(f"Usage: {usages[command]}", Style.YELLOW))


def print_banner(transcript):
    print(color("╭────────────────────────────────────────────╮", Style.CYAN))
    print(color("│ Atomic Llama Turbo                         │", Style.BOLD + Style.CYAN))
    print(color("╰────────────────────────────────────────────╯", Style.CYAN))
    print(color("OpenAI-compatible llama-server console. Type / for commands.", Style.DIM))
    print(color(f"Transcript: {transcript}", Style.DIM))


def main():
    setup_readline()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    chat = chat_store.create_chat(BASE_URL, MODEL, SYSTEM, [], source="console")
    transcript = chat["id"]
    initial_transcript = transcript
    messages = [{"role": "system", "content": SYSTEM}]

    print_banner(chat_store.md_path(transcript))
    print(color("Waiting for server readiness...", Style.DIM))
    if not wait_until_ready():
        return 1
    write_transcript_header(transcript)
    print(color("Ready.", Style.GREEN))
    print_status()

    while True:
        try:
            user = input(color("\natomic> ", Style.CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            chat_store.delete_if_empty(initial_transcript)
            return 0
        if not user:
            continue
        if user in {"/exit", "/quit"}:
            chat_store.delete_if_empty(initial_transcript)
            return 0
        command, _, arg = user.partition(" ")
        if user in {"/", "/help"}:
            print_commands()
            continue
        if user == "/status":
            print_status()
            continue
        if user == "/models":
            models = model_ids()
            print("\n".join(models) if models else "No models endpoint data.")
            continue
        if user == "/chats":
            chats = chat_store.list_chats()[:20]
            if not chats:
                print("No saved chats.")
                continue
            for item in chats:
                current = "*" if item["id"] == transcript else " "
                print(f"{current} {item['id']}  {item['title']}  ({item['source']}, {item['message_count']} msgs)")
            continue
        if command == "/open":
            if not arg:
                print_usage("/open")
                continue
            try:
                data = chat_store.load_chat(arg.strip())
            except FileNotFoundError:
                print(color(f"Chat not found: {arg}", Style.RED))
                continue
            transcript = data["id"]
            messages = chat_store.to_llm_messages(data)
            if not messages or messages[0].get("role") != "system":
                messages.insert(0, {"role": "system", "content": SYSTEM})
            print(color(f"Opened: {data.get('title', transcript)}", Style.GREEN))
            print(color(f"Transcript: {chat_store.md_path(transcript)}", Style.DIM))
            continue
        if user == "/where":
            print(chat_store.md_path(transcript))
            continue
        if command == "/search":
            if not arg:
                print_usage("/search")
                continue
            try:
                results = search_web(arg)
            except Exception as exc:
                print(color(f"Search failed: {exc}", Style.RED))
                continue
            append_turn(transcript, "Web Search", f"Query: {arg}\n\n" + "\n".join(f"- {r['title']}: {r['url']}" for r in results))
            print_search_results(results)
            continue
        if command == "/fetch":
            if not arg:
                print_usage("/fetch")
                continue
            try:
                page = fetch_page(arg)
            except Exception as exc:
                print(color(f"Fetch failed: {exc}", Style.RED))
                continue
            excerpt = page["text"][:1800]
            append_turn(transcript, "Web Fetch", f"{page['title']}\n{page['url']}\n\n{excerpt}")
            print(color(page["title"], Style.GREEN))
            print(color(page["url"], Style.DIM))
            print(excerpt)
            continue
        if command == "/web":
            if not arg:
                print_usage("/web")
                continue
            try:
                results, context = build_web_context(arg)
            except Exception as exc:
                print(color(f"Web lookup failed: {exc}", Style.RED))
                continue
            print_search_results(results)
            web_prompt = (
                f"{context}\n\n"
                f"Question: {arg}\n\n"
                "Answer using the web lookup results above. Cite sources by number. "
                "If the lookup results are weak or contradictory, say so."
            )
            messages.append({"role": "user", "content": web_prompt})
            append_turn(transcript, "User", f"/web {arg}")
            append_turn(transcript, "Web Context", context)
            try:
                answer, timings, usage, elapsed = ask_model(messages, "answering with web context")
            except urllib.error.URLError as exc:
                print(color(f"Request failed: {exc}", Style.RED), file=sys.stderr)
                continue
            messages.append({"role": "assistant", "content": answer})
            append_turn(transcript, "Assistant", answer, timings=timings, meta={"usage": usage})
            print()
            print(answer)
            print_timing(elapsed, timings, usage)
            continue
        if user == "/reset":
            messages = [{"role": "system", "content": SYSTEM}]
            append_turn(transcript, "System", "[context reset]")
            print(color("Context cleared.", Style.GREEN))
            continue
        if user.startswith("/"):
            print(color(f"Unknown command: {user}", Style.RED))
            print_commands()
            continue

        messages.append({"role": "user", "content": user})
        append_turn(transcript, "User", user)
        try:
            answer, timings, usage, elapsed = ask_model(messages, "thinking")
        except urllib.error.URLError as exc:
            print(color(f"Request failed: {exc}", Style.RED), file=sys.stderr)
            continue
        messages.append({"role": "assistant", "content": answer})
        append_turn(transcript, "Assistant", answer, timings=timings, meta={"usage": usage})
        print()
        print(answer)
        print_timing(elapsed, timings, usage)


if __name__ == "__main__":
    raise SystemExit(main())
