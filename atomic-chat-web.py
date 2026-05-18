#!/usr/bin/env python3
import json
import mimetypes
import os
import re
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import html.parser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import chat_store


BASE_URL = os.environ.get("ATOMIC_BASE_URL", os.environ.get("QWEN_BASE_URL", "http://127.0.0.1:8080"))
API_URL = f"{BASE_URL}/v1/chat/completions"
HEALTH_URL = f"{BASE_URL}/health"
MODEL = os.environ.get("ATOMIC_MODEL", os.environ.get("QWEN_MODEL", "qwen"))
SYSTEM = os.environ.get("ATOMIC_SYSTEM", os.environ.get("QWEN_SYSTEM", "You are a concise, practical coding assistant."))
HOST = os.environ.get("ATOMIC_CHAT_HOST", "127.0.0.1")
PORT = int(os.environ.get("ATOMIC_CHAT_PORT", "8090"))
MAX_TOKENS = int(os.environ.get("ATOMIC_MAX_TOKENS", "4096"))
STATIC_DIR = Path(__file__).resolve().parent / "static"


def llama_complete(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": 0.4,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["choices"][0]["message"].get("content", ""), body.get("timings", {}), body.get("usage", {})


def health():
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as response:
            return {"ok": response.status == 200, "status": response.read().decode("utf-8")}
    except Exception as exc:
        return {"ok": False, "status": str(exc)}


def ensure_model_ready():
    with urllib.request.urlopen(HEALTH_URL, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"model health endpoint returned HTTP {response.status}")


def api_error(message, exc=None):
    if exc is not None:
        print(f"[atomic-chat-web] {message}: {exc!r}")
        traceback.print_exc()
    return {"error": message, "detail": str(exc) if exc is not None else ""}


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


def direct_targets(question):
    targets = []
    for match in re.finditer(r"https?://[^\s)>\"]+|www\.[^\s)>\"]+|[a-z0-9-]+\.[a-z]{2,}(?:/[^\s)>\"]*)?", question, re.I):
        raw = match.group(0).rstrip(".,;:")
        url = raw if raw.startswith(("http://", "https://")) else "https://" + raw.removeprefix("www.")
        if url not in targets:
            targets.append(url)
    return targets[:2]


def fetch_direct_target(url):
    try:
        return fetch_page(url, max_chars=2600)
    except Exception as exc:
        if url.startswith("https://"):
            try:
                return fetch_page("http://" + url.removeprefix("https://"), max_chars=2600)
            except Exception:
                pass
        return {"title": url, "url": url, "text": f"[direct fetch failed: {exc}]"}


def build_web_context(question):
    pages = [fetch_direct_target(url) for url in direct_targets(question)]
    seen_urls = {page["url"] for page in pages}
    try:
        results = search_web(question, limit=5)
    except Exception as exc:
        results = []
        pages.append({"title": "Search failed", "url": "", "text": f"[search failed: {exc}]"})
    for result in results[:3]:
        if result["url"] in seen_urls:
            continue
        try:
            page = fetch_page(result["url"], max_chars=2200)
        except Exception as exc:
            page = {"title": result["title"], "url": result["url"], "text": f"[fetch failed: {exc}]"}
        pages.append(page)
        seen_urls.add(page["url"])
        if len(pages) >= 4:
            break
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
    if not pages:
        lines.extend(["[1] No web context", "", "No direct page or search result text could be fetched.", ""])
    return results, "\n".join(lines).strip()


def should_search_web(content):
    text = (content or "").strip().lower()
    if not text:
        return False
    retry_phrases = {
        "again", "try again", "please try again", "retry", "continue", "go on", "same question",
        "answer again", "redo", "regenerate", "what about it", "and then", "ok", "yes", "no",
    }
    if text in retry_phrases:
        return False
    if re.search(r"https?://|www\.|[a-z0-9-]+\.[a-z]{2,}(?:/|\b)", text):
        return True
    if text.startswith(("/web ", "web ", "search ", "lookup ", "look up ", "browse ", "fetch ")):
        return True
    fresh_terms = {
        "current", "latest", "today", "recent", "news", "site", "website", "domain", "url",
        "internet", "online", "web", "page",
    }
    return any(term in text.split() for term in fresh_terms)


def compact_query_for_storage(query, max_chars=500):
    query = re.sub(r"\s+", " ", (query or "")).strip()
    if len(query) <= max_chars:
        return query
    return query[: max_chars - 1].rstrip() + "…"


def llm_messages_with_web_context(data):
    messages = []
    system = data.get("system") or SYSTEM
    if system:
        messages.append({"role": "system", "content": system})
    stored_messages = data.get("messages", [])
    latest_web_context_index = next(
        (idx for idx in range(len(stored_messages) - 1, -1, -1) if stored_messages[idx].get("role") == "web_context"),
        -1,
    )
    for idx, item in enumerate(stored_messages):
        role = item.get("role")
        content = item.get("content", "")
        if role in {"user", "assistant", "system"}:
            messages.append({"role": role, "content": content})
        elif role == "web_context" and idx == latest_web_context_index:
            messages.append({"role": "user", "content": "Prior web lookup context:\n" + content})
    return messages


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Atomic Llama Turbo</title>
  <link rel="stylesheet" href="/static/popicon.css">
  <link rel="icon" href="/static/atomic-llama-turbo.svg">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/markdown-it/13.0.1/markdown-it.min.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b0f14;
      --panel: #11161d;
      --panel-2: #171d26;
      --panel-3: #1d2430;
      --line: #263041;
      --line-2: #334155;
      --text: #edf2f7;
      --muted: #94a3b8;
      --accent: #10a37f;
      --accent-2: #2dd4bf;
      --danger: #ef4444;
      --bubble-user: #19212b;
      --bubble-assistant: #111822;
      --shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(16, 163, 127, 0.12), transparent 28%),
        radial-gradient(circle at 80% 0%, rgba(45, 212, 191, 0.08), transparent 22%),
        var(--bg);
      color: var(--text);
      font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app {
      height: 100vh;
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr);
      overflow: hidden;
      position: relative;
    }
    aside {
      background: linear-gradient(180deg, rgba(17, 22, 29, 0.98), rgba(13, 18, 24, 0.98));
      border-right: 1px solid rgba(255, 255, 255, 0.05);
      display: grid;
      grid-template-rows: auto auto auto minmax(0, 1fr);
      min-width: 0;
      min-height: 0;
      overflow: hidden;
    }
    .brand {
      display: flex;
      gap: 12px;
      align-items: center;
      padding: 18px 16px 12px;
      min-width: 0;
    }
    .brand img {
      width: calc(2rem + .8vw);
      height: calc(2rem + .8vw);
      flex: 0 0 auto;
      object-fit: contain;
      filter: brightness(0) invert(1);
    }
    .brand-title {
      font-weight: 700;
      letter-spacing: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .brand-sub, .panel-hint, .sub, .status, .chat-meta, .empty, .thinking {
      color: var(--muted);
    }
    .brand-sub {
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .side-actions {
      padding: 0 14px 12px;
      display: grid;
      gap: 10px;
    }
    .mode-actions {
      padding: 0 14px 6px;
      display: flex;
      justify-content: flex-start;
      align-items: center;
      width: 100%;
      align-self: start;
    }
    button {
      border: 1px solid var(--line);
      background: rgba(23, 29, 38, 0.9);
      color: var(--text);
      border-radius: 14px;
      padding: 10px 12px;
      cursor: pointer;
      font: inherit;
      transition: background 120ms ease, border-color 120ms ease, transform 120ms ease, opacity 120ms ease;
    }
    button:hover { border-color: var(--line-2); }
    button:active { transform: translateY(1px); }
    .new-btn {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      background: linear-gradient(180deg, rgba(16, 163, 127, 0.18), rgba(16, 163, 127, 0.09));
      border-color: rgba(16, 163, 127, 0.35);
    }
    .new-btn:hover { border-color: rgba(16, 163, 127, 0.65); }
    .panel-hint {
      font-size: 12px;
      line-height: 1.35;
      padding: 0 16px 8px;
    }
    .mode-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      background: rgba(255, 255, 255, 0.03);
      width: auto;
      min-height: 0;
      line-height: 1;
    }
    .mode-chip.active {
      border-color: rgba(16, 163, 127, 0.45);
      background: rgba(16, 163, 127, 0.14);
      color: #d8fff3;
    }
    .chat-list {
      overflow: auto;
      min-height: 0;
      padding: 4px 10px 14px;
      display: grid;
      align-content: start;
      gap: 6px;
      scrollbar-color: rgba(148, 163, 184, 0.55) transparent;
    }
    .chat-item {
      width: 100%;
      min-width: 0;
      border-radius: 16px;
      border: 1px solid transparent;
      background: transparent;
      padding: 10px 10px 10px 12px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: start;
      text-align: left;
    }
    .chat-item:hover {
      background: rgba(255, 255, 255, 0.03);
      border-color: rgba(255, 255, 255, 0.05);
    }
    .chat-item.active {
      background: rgba(255, 255, 255, 0.05);
      border-color: rgba(16, 163, 127, 0.25);
      box-shadow: inset 0 0 0 1px rgba(16, 163, 127, 0.08);
    }
    .chat-main {
      min-width: 0;
      display: grid;
      gap: 4px;
    }
    .chat-title {
      font-weight: 650;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      letter-spacing: 0;
    }
    .chat-meta {
      font-size: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px 10px;
      min-width: 0;
    }
    .chat-meta span {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .chat-actions {
      display: flex;
      gap: 4px;
      opacity: 0.22;
      transition: opacity 120ms ease;
    }
    .chat-item:hover .chat-actions,
    .chat-item.active .chat-actions { opacity: 1; }
    .icon-btn {
      width: 30px;
      height: 30px;
      border-radius: 10px;
      padding: 0;
      display: grid;
      place-items: center;
      background: rgba(255, 255, 255, 0.02);
    }
    .icon-btn:hover {
      background: rgba(255, 255, 255, 0.06);
      border-color: rgba(255, 255, 255, 0.08);
    }
    .icon-btn.danger:hover {
      border-color: rgba(239, 68, 68, 0.4);
      color: #fecaca;
      background: rgba(239, 68, 68, 0.12);
    }
    main {
      min-width: 0;
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.01), transparent 120px),
        var(--bg);
    }
    header {
      min-width: 0;
      min-height: 52px;
      padding: 8px 16px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      background: rgba(10, 14, 20, 0.72);
      backdrop-filter: blur(12px);
    }
    .mobile-menu {
      width: 36px;
      height: 36px;
      border-radius: 10px;
      padding: 0;
      display: none;
      place-items: center;
      flex: 0 0 auto;
    }
    .top-title { min-width: 0; display: grid; gap: 2px; }
    h1 {
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .sub {
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: min(60vw, 760px);
    }
    .status {
      flex: 0 0 auto;
      font-size: 12px;
      white-space: nowrap;
      padding: 5px 9px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .thinking {
      width: min(100%, 820px);
      margin: 10px auto 0;
      padding: 0 18px;
      display: none;
      align-items: center;
      gap: 10px;
      font-size: 12px;
    }
    .thinking.show { display: flex; }
    .thinking .dots {
      display: inline-flex;
      gap: 4px;
    }
    .thinking .dots span {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent-2);
      animation: pulse 1s infinite ease-in-out;
    }
    .thinking .dots span:nth-child(2) { animation-delay: 0.15s; }
    .thinking .dots span:nth-child(3) { animation-delay: 0.3s; }
    @keyframes pulse {
      0%, 80%, 100% { transform: translateY(0); opacity: 0.45; }
      40% { transform: translateY(-3px); opacity: 1; }
    }
    .messages-wrap {
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      scroll-behavior: smooth;
      scrollbar-color: rgba(148, 163, 184, 0.55) transparent;
    }
    .messages {
      width: min(100%, 820px);
      margin: 0 auto;
      padding: 18px 18px 24px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      min-height: min-content;
    }
    .msg {
      display: grid;
      grid-template-columns: 32px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
    }
    .avatar {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      overflow: hidden;
      background: #1a2230;
      color: var(--accent);
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.05);
    }
    .avatar img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: 100% 100%;
      transform: translate(50%, 137%) scale(3);
      transform-origin: 100% 100%;
      background: #ffffff;
      padding: 7px;
    }
    .bubble {
      position: relative;
      min-width: 0;
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 18px;
      padding: 14px 15px;
      background: rgba(255, 255, 255, 0.02);
      box-shadow: var(--shadow);
    }
    .user .bubble { background: var(--bubble-user); }
    .assistant .bubble { background: var(--bubble-assistant); }
    .system .bubble {
      background: rgba(255, 255, 255, 0.015);
      box-shadow: none;
      border-style: dashed;
    }
    .role {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.09em;
      color: var(--muted);
      margin-bottom: 8px;
    }
    .content {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: #e5e7eb;
    }
    .assistant .content {
      white-space: normal;
    }
    .assistant .content p {
      margin: 0 0 0.85em;
    }
    .assistant .content p:last-child {
      margin-bottom: 0;
    }
    .assistant .content ul,
    .assistant .content ol {
      margin: 0.5em 0 0.9em;
      padding-left: 1.35em;
    }
    .assistant .content li {
      margin: 0.25em 0;
    }
    .assistant .content a {
      color: #7dd3fc;
      text-decoration: none;
      border-bottom: 1px solid rgba(125, 211, 252, 0.45);
    }
    .assistant .content a:hover {
      border-bottom-color: currentColor;
    }
    .assistant .content blockquote {
      margin: 0.75em 0;
      padding-left: 0.9em;
      border-left: 3px solid rgba(148, 163, 184, 0.45);
      color: #cbd5e1;
    }
    .assistant .content pre {
      overflow: auto;
      padding: 12px;
      border-radius: 10px;
      background: rgba(0, 0, 0, 0.28);
    }
    .system .content {
      color: #aab4c3;
      font-size: 13px;
    }
    .copy-btn {
      position: absolute;
      top: 10px;
      right: 10px;
      width: 30px;
      height: 30px;
      border-radius: 10px;
      padding: 0;
      display: grid;
      place-items: center;
      opacity: 0;
      background: rgba(255, 255, 255, 0.03);
    }
    .assistant .bubble:hover .copy-btn,
    .copy-btn:focus {
      opacity: 1;
    }
    .timing {
      margin-top: 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .empty {
      margin: auto;
      text-align: center;
      max-width: 42rem;
      padding: 30px 22px;
    }
    .empty .empty-title {
      font-size: 18px;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 8px;
    }
    .composer-shell {
      padding: 10px 14px 12px;
      border-top: 1px solid rgba(255, 255, 255, 0.05);
      background: linear-gradient(180deg, rgba(11, 15, 20, 0.25), rgba(11, 15, 20, 0.98));
      backdrop-filter: blur(12px);
    }
    form {
      width: min(100%, 820px);
      margin: 0 auto;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
      background: rgba(23, 29, 38, 0.88);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 18px;
      padding: 8px;
      box-shadow: var(--shadow);
    }
    textarea {
      min-height: 42px;
      max-height: 240px;
      resize: vertical;
      border: 0;
      border-radius: 12px;
      background: transparent;
      color: var(--text);
      padding: 9px 10px 8px;
      font: inherit;
      outline: none;
    }
    textarea::placeholder { color: #7f8a9e; }
    textarea:focus { box-shadow: none; }
    .send-btn {
      width: 38px;
      height: 38px;
      border-radius: 12px;
      display: grid;
      place-items: center;
      color: #ffffff;
      background: transparent;
      border-color: transparent;
      font-size: 18px;
      align-self: end;
    }
    .send-btn:hover {
      background: rgba(255, 255, 255, 0.06);
      border-color: rgba(255, 255, 255, 0.08);
    }
    code {
      color: #d1d5db;
      background: rgba(255, 255, 255, 0.04);
      padding: 0.1rem 0.3rem;
      border-radius: 6px;
    }
    @media (max-width: 860px) {
      .app {
        grid-template-columns: 1fr;
      }
      aside {
        position: fixed;
        z-index: 20;
        inset: 0 auto 0 0;
        width: min(84vw, 320px);
        transform: translateX(-102%);
        transition: transform 180ms ease;
        grid-template-rows: auto auto auto minmax(0, 1fr);
        border-right: 1px solid rgba(255, 255, 255, 0.08);
        border-bottom: 0;
        max-height: none;
        box-shadow: 24px 0 60px rgba(0, 0, 0, 0.45);
      }
      body.sidebar-open aside {
        transform: translateX(0);
      }
      body.sidebar-open::after {
        content: "";
        position: fixed;
        inset: 0;
        z-index: 10;
        background: rgba(0, 0, 0, 0.5);
      }
      .mobile-menu {
        display: grid;
      }
      header {
        min-height: 46px;
        padding: 6px 10px;
      }
      h1 { font-size: 14px; }
      .sub { display: none; }
      .status {
        max-width: 38vw;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .messages {
        width: min(100%, 760px);
        padding: 12px 10px 18px;
        gap: 12px;
      }
      .msg {
        grid-template-columns: 28px minmax(0, 1fr);
        gap: 9px;
      }
      .avatar {
        width: 28px;
        height: 28px;
      }
      .bubble {
        border-radius: 14px;
        padding: 11px 12px;
      }
      .composer-shell { padding: 8px 8px 10px; }
      form { width: min(100%, 760px); }
      textarea {
        min-height: 38px;
        padding: 8px 9px;
      }
      .send-btn {
        width: 36px;
        height: 36px;
      }
    }
  </style>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand">
      <img src="/static/atomic-llama-turbo.svg" alt="">
      <div style="min-width:0">
        <div class="brand-title">Atomic Llama Turbo</div>
        <div class="brand-sub">local chats, local files</div>
      </div>
    </div>
    <div class="side-actions">
      <button id="newChat" class="new-btn" type="button"><span class="pi pi-edit"></span><span>New chat</span></button>
    </div>
    <div class="mode-actions">
      <button id="webMode" class="mode-chip" type="button" aria-pressed="false"><span class="pi pi-globe"></span><span>Web mode off</span></button>
    </div>
    <div id="chatList" class="chat-list"></div>
  </aside>
  <main>
    <header>
      <button id="sidebarToggle" class="mobile-menu" type="button" aria-label="Open chats" aria-expanded="false"><span class="pi pi-hamburger"></span></button>
      <div class="top-title">
        <h1 id="title">Atomic Llama Turbo</h1>
        <div class="sub" id="subtitle">Shared console + web chat archive</div>
      </div>
      <div class="status" id="status">checking...</div>
    </header>
    <div class="messages-wrap">
      <section id="messages" class="messages"></section>
      <div id="thinking" class="thinking"><span class="dots"><span></span><span></span><span></span></span><span id="thinkingText">Thinking...</span></div>
    </div>
    <div class="composer-shell">
      <form id="form">
        <textarea id="input" placeholder="Message the model..."></textarea>
        <button id="send" class="send-btn" type="submit" aria-label="Send"><span class="pi pi-send"></span></button>
      </form>
    </div>
  </main>
</div>
<script>
let current = null;
let currentChats = [];
let webMode = false;
let messageMarkdown = {};
const md = window.markdownit ? window.markdownit({html: false, linkify: true, breaks: true}) : null;
if (md) {
  const defaultLinkOpen = md.renderer.rules.link_open || function(tokens, idx, options, env, self) {
    return self.renderToken(tokens, idx, options);
  };
  md.renderer.rules.link_open = function(tokens, idx, options, env, self) {
    const targetIndex = tokens[idx].attrIndex('target');
    if (targetIndex < 0) tokens[idx].attrPush(['target', '_blank']);
    else tokens[idx].attrs[targetIndex][1] = '_blank';
    const relIndex = tokens[idx].attrIndex('rel');
    if (relIndex < 0) tokens[idx].attrPush(['rel', 'noopener noreferrer']);
    else tokens[idx].attrs[relIndex][1] = 'noopener noreferrer';
    return defaultLinkOpen(tokens, idx, options, env, self);
  };
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let payload = {};
    let raw = '';
    try {
      raw = await res.text();
      payload = raw ? JSON.parse(raw) : {};
    } catch (e) {
      payload = {error: raw || res.statusText};
    }
    const err = new Error(payload.error || res.statusText || 'Request failed');
    err.detail = payload.detail || '';
    err.status = res.status;
    throw err;
  }
  return await res.json();
}

function friendlyError(err) {
  const detail = err.detail || err.message || '';
  if (detail.includes('Connection refused') || detail.includes('Errno 111')) {
    return [
      'The web chat is running, but the local model server is not reachable.',
      '',
      'Start or restart the llama-server backend, then try again. The exact endpoint and traceback are printed in the terminal running atomic-chat-web.py.',
    ].join('\n');
  }
  if (err.status === 502) {
    return [
      err.message || 'The backend request failed.',
      detail ? `\nDetails: ${detail}` : '',
    ].join('\n');
  }
  return [err.message || 'Request failed.', detail ? `\nDetails: ${detail}` : ''].join('\n');
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function fallbackMarkdown(s) {
  const escaped = escapeHtml(s || "");
  return escaped
    .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\n/g, '<br>');
}

function extractSources(messages, uptoIndex) {
  const sources = {};
  for (let i = 0; i < uptoIndex; i++) {
    const msg = messages[i];
    if (msg.role !== 'web_context') continue;
    const lines = (msg.content || '').split('\n');
    for (let j = 0; j < lines.length - 1; j++) {
      const match = lines[j].match(/^\[(\d+)\]\s+(.+)$/);
      if (match && /^https?:\/\//.test(lines[j + 1].trim())) {
        sources[match[1]] = lines[j + 1].trim();
      }
    }
  }
  return sources;
}

function linkCitations(markdown, sources) {
  return (markdown || '').replace(/\[(\d+)\]/g, (full, n) => {
    if (!sources[n]) return full;
    return `[${n}](${sources[n]})`;
  });
}

function renderMarkdown(markdown, sources = {}) {
  const linked = linkCitations(markdown, sources);
  return md ? md.render(linked) : fallbackMarkdown(linked);
}

function visibleMessages(messages) {
  return (messages || []).filter(m => !['web_search', 'web_context', 'web_fetch'].includes(m.role));
}

function chatPreview(chat) {
  const count = chat.message_count || 0;
  const model = chat.model || 'model?';
  const updated = chat.updated_at ? new Date(chat.updated_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'unknown';
  return `${count} msg${count === 1 ? '' : 's'} · ${model} · ${updated}`;
}

function sortedChats(chats) {
  return [...chats].sort((a, b) => {
    if (a.id === current) return -1;
    if (b.id === current) return 1;
    const aKey = a.updated_at || a.created_at || a.id || '';
    const bKey = b.updated_at || b.created_at || b.id || '';
    return bKey.localeCompare(aKey);
  });
}

function setWebMode(next) {
  webMode = !!next;
  const button = document.getElementById('webMode');
  button.classList.toggle('active', webMode);
  button.setAttribute('aria-pressed', webMode ? 'true' : 'false');
  button.innerHTML = webMode
    ? '<span class="pi pi-globe"></span><span>Web mode on</span>'
    : '<span class="pi pi-globe"></span><span>Web mode off</span>';
}

function setSidebar(open) {
  document.body.classList.toggle('sidebar-open', open);
  const toggle = document.getElementById('sidebarToggle');
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  toggle.setAttribute('aria-label', open ? 'Close chats' : 'Open chats');
}

function setThinking(active, text = '') {
  const el = document.getElementById('thinking');
  const label = document.getElementById('thinkingText');
  if (active) {
    el.classList.add('show');
    label.textContent = text || (webMode ? 'Searching the web and drafting an answer...' : 'Generating an answer...');
  } else {
    el.classList.remove('show');
    label.textContent = '';
  }
}

function scrollMessages() {
  const scroller = document.querySelector('.messages-wrap');
  scroller.scrollTop = scroller.scrollHeight;
  requestAnimationFrame(() => {
    scroller.scrollTop = scroller.scrollHeight;
  });
}

function renderMessage(m, sources = {}, idx = null) {
  const role = escapeHtml(m.role || 'message');
  const assistantAvatar = '<img src="/static/atomic-llama-turbo.svg" alt="Assistant">';
  const userAvatar = '<span class="pi pi-profile"></span>';
  const copyId = idx === null ? '' : `msg-${idx}`;
  if (m.role === 'assistant' && copyId) {
    messageMarkdown[copyId] = m.content || '';
  }
  const body = m.role === 'assistant' ? renderMarkdown(m.content || '', sources) : escapeHtml(m.content || '');
  const copyButton = m.role === 'assistant' && copyId
    ? `<button class="copy-btn" type="button" title="Copy response" aria-label="Copy response as Markdown" data-copy-id="${copyId}" onclick="copyResponse('${copyId}')"><span class="pi pi-copy"></span></button>`
    : '';
  return `
    <article class="msg ${role}">
      <div class="avatar">${m.role === 'assistant' ? assistantAvatar : userAvatar}</div>
      <div class="bubble">
        ${copyButton}
        <div class="role">${role}</div>
        <div class="content">${body}</div>
        ${m.timings && m.timings.predicted_per_second ? `<div class="timing">Generation ${m.timings.predicted_per_second.toFixed(1)} tok/s</div>` : ''}
      </div>
    </article>
  `;
}

async function copyResponse(id) {
  const text = messageMarkdown[id] || '';
  if (!text) return;
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
  } else {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }
  const button = document.querySelector(`[data-copy-id="${id}"]`);
  if (!button) return;
  const original = button.innerHTML;
  button.innerHTML = '<span class="pi pi-checkmark"></span>';
  setTimeout(() => { button.innerHTML = original; }, 900);
}

function appendOptimisticUser(content) {
  const messagesBox = document.getElementById('messages');
  if (messagesBox.querySelector('.empty')) messagesBox.innerHTML = '';
  messagesBox.insertAdjacentHTML('beforeend', renderMessage({role: 'user', content}));
  scrollMessages();
}

function appendAssistantNotice(content) {
  const messagesBox = document.getElementById('messages');
  if (messagesBox.querySelector('.empty')) messagesBox.innerHTML = '';
  messagesBox.insertAdjacentHTML('beforeend', renderMessage({role: 'assistant', content}, {}, `notice-${Date.now()}`));
  scrollMessages();
}

function renderChatList(chats) {
  const box = document.getElementById('chatList');
  box.innerHTML = sortedChats(chats).map(c => `
    <div class="chat-item ${c.id === current ? 'active' : ''}" role="button" tabindex="0" onclick="openChat('${c.id}')"
      onkeydown="if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openChat('${c.id}'); }">
      <div class="chat-main">
        <div class="chat-title">${escapeHtml(c.title || 'New chat')}</div>
        <div class="chat-meta">
          <span>${escapeHtml(c.md_name || (c.id + '.md'))}</span>
          <span>${escapeHtml(chatPreview(c))}</span>
        </div>
      </div>
      <div class="chat-actions">
        <button class="icon-btn" type="button" aria-label="Rename chat" title="Rename"
          onclick="event.stopPropagation(); renameChat('${c.id}')"><span class="pi pi-edit"></span></button>
        <button class="icon-btn danger" type="button" aria-label="Delete chat" title="Delete"
          onclick="event.stopPropagation(); deleteChat('${c.id}')"><span class="pi pi-bin"></span></button>
      </div>
    </div>
  `).join('');
}

async function loadChats(preferId = null) {
  currentChats = await api('/api/chats');
  renderChatList(currentChats);
  if (preferId && currentChats.some(c => c.id === preferId)) {
    await openChat(preferId);
    return;
  }
  if (current && currentChats.some(c => c.id === current)) {
    renderChatList(currentChats);
    return;
  }
  if (currentChats[0]) {
    await openChat(currentChats[0].id);
    return;
  }
  current = null;
  document.getElementById('title').textContent = 'Atomic Llama Turbo';
  document.getElementById('subtitle').textContent = 'Start a new conversation';
  document.getElementById('messages').innerHTML = `
    <div class="empty">
      <div class="empty-title">No chats yet</div>
      <div>Start a conversation and it will be saved as a Markdown file automatically.</div>
    </div>`;
  renderChatList(currentChats);
}

async function openChat(id) {
  current = id;
  setSidebar(false);
  const chat = await api('/api/chats/' + id);
  document.getElementById('title').textContent = chat.title || 'New chat';
  document.getElementById('subtitle').textContent = `${chat.md_name || ''} · ${chat.model || 'qwen'}`;
  const messagesBox = document.getElementById('messages');
  const items = chat.messages || [];
  messageMarkdown = {};
  const rendered = visibleMessages(items).map((m, idx) => renderMessage(m, extractSources(items, items.indexOf(m)), idx));
  messagesBox.innerHTML = rendered.length ? rendered.join('') : `
    <div class="empty">
      <div class="empty-title">New chat</div>
      <div>Send the first message to create the transcript and title automatically.</div>
    </div>`;
  scrollMessages();
  renderChatList(currentChats.length ? currentChats : await api('/api/chats'));
}

async function newChat() {
  const chat = await api('/api/chats', { method: 'POST' });
  current = chat.id;
  await loadChats(chat.id);
  setSidebar(false);
}

async function deleteChat(id) {
  const target = currentChats.find(c => c.id === id);
  const label = target ? target.title || target.md_name || id : id;
  const wasCurrent = current === id;
  if (!confirm(`Delete "${label}"? This removes the chat JSON and Markdown files.`)) return;
  await api('/api/chats/' + id, { method: 'DELETE' });
  currentChats = currentChats.filter(c => c.id !== id);
  if (wasCurrent) current = null;
  renderChatList(currentChats);
  if (wasCurrent) {
    if (currentChats[0]) {
      await openChat(currentChats[0].id);
    } else {
      await loadChats();
    }
    return;
  }
  if (!current && currentChats[0]) await openChat(currentChats[0].id);
}

async function renameChat(id) {
  const target = currentChats.find(c => c.id === id);
  const currentTitle = target ? target.title || '' : '';
  const title = prompt('Rename chat', currentTitle);
  if (title === null) return;
  const nextTitle = title.trim();
  if (!nextTitle) return;
  await api('/api/chats/' + id, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: nextTitle })
  });
  await loadChats(id);
}

async function sendMessage(ev) {
  ev.preventDefault();
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text) return;
  if (!current) await newChat();
  input.value = '';
  appendOptimisticUser(text);
  const useWeb = webMode && shouldSearchWeb(text);
  const modeLabel = useWeb ? 'web search + answer' : 'thinking';
  document.getElementById('status').textContent = `${modeLabel}... 0.0s`;
  setThinking(true, useWeb ? 'Searching the web and drafting an answer...' : 'Generating an answer...');
  const start = performance.now();
  const tick = setInterval(() => {
    document.getElementById('status').textContent = `${modeLabel}... ${((performance.now() - start) / 1000).toFixed(1)}s`;
  }, 250);
  try {
    const endpoint = webMode ? '/api/chats/' + current + '/webmessage' : '/api/chats/' + current + '/message';
    await api(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: text })
    });
    await loadChats(current);
  } catch (err) {
    appendAssistantNotice(friendlyError(err));
    document.getElementById('status').textContent = 'request failed';
  } finally {
    clearInterval(tick);
    setThinking(false);
    if (document.getElementById('status').textContent !== 'request failed') {
      document.getElementById('status').textContent = 'ready';
    }
  }
}

function shouldSearchWeb(text) {
  const value = text.trim().toLowerCase();
  const retryPhrases = new Set([
    'again', 'try again', 'please try again', 'retry', 'continue', 'go on',
    'same question', 'answer again', 'redo', 'regenerate', 'what about it', 'ok', 'yes', 'no'
  ]);
  if (retryPhrases.has(value)) return false;
  if (/https?:\/\/|www\.|[a-z0-9-]+\.[a-z]{2,}(?:\/|\b)/i.test(value)) return true;
  if (/^(\/web|web|search|lookup|look up|browse|fetch)\b/i.test(value)) return true;
  const words = new Set(value.split(/\s+/));
  return ['current', 'latest', 'today', 'recent', 'news', 'site', 'website', 'domain', 'url', 'internet', 'online', 'web', 'page']
    .some(word => words.has(word));
}

async function refreshHealth() {
  try {
    const h = await api('/api/health');
    document.getElementById('status').textContent = h.ok ? 'ready' : 'llama unavailable';
  } catch (e) {
    document.getElementById('status').textContent = 'web backend error';
  }
}

document.getElementById('newChat').addEventListener('click', newChat);
document.getElementById('webMode').addEventListener('click', () => setWebMode(!webMode));
document.getElementById('sidebarToggle').addEventListener('click', ev => {
  ev.stopPropagation();
  setSidebar(!document.body.classList.contains('sidebar-open'));
});
document.addEventListener('click', ev => {
  if (!document.body.classList.contains('sidebar-open')) return;
  if (ev.target.closest('aside') || ev.target.closest('#sidebarToggle')) return;
  setSidebar(false);
});
document.getElementById('form').addEventListener('submit', sendMessage);
document.getElementById('input').addEventListener('keydown', ev => {
  if (ev.key === 'Enter' && !ev.shiftKey) {
    ev.preventDefault();
    document.getElementById('form').requestSubmit();
  }
});
setWebMode(true);
refreshHealth();
loadChats();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_html(self, include_body=True):
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, include_body=True):
        rel = self.path.removeprefix("/static/").split("?", 1)[0]
        path = (STATIC_DIR / rel).resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.is_file():
            self.send_response(404)
            self.end_headers()
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_HEAD(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_html(include_body=False)
            return
        if self.path.startswith("/static/"):
            self.send_static(include_body=False)
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_html()
            return
        if self.path.startswith("/static/"):
            self.send_static()
            return
        if self.path == "/api/health":
            self.send_json(health())
            return
        if self.path == "/api/chats":
            self.send_json(chat_store.list_chats())
            return
        if self.path.startswith("/api/chats/"):
            ident = self.path.rsplit("/", 1)[-1]
            try:
                data = chat_store.load_chat(ident)
                data["md_path"] = str(chat_store.md_path(ident))
                data["md_name"] = chat_store.md_path(ident).name
                title = data.get("title") or "New chat"
                if title in {"", "New chat"}:
                    title = chat_store.title_from_messages(data.get("messages", []), title)
                data["title"] = title
                data["model"] = data.get("model") or MODEL
            except FileNotFoundError:
                self.send_json({"error": "chat not found"}, 404)
                return
            self.send_json(data)
            return
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/chats":
            data = chat_store.create_chat(BASE_URL, MODEL, SYSTEM, [], source="web")
            self.send_json(data, 201)
            return
        if self.path.startswith("/api/chats/") and self.path.endswith("/message"):
            ident = self.path.split("/")[3]
            payload = self.read_json()
            content = (payload.get("content") or "").strip()
            if not content:
                self.send_json({"error": "empty message"}, 400)
                return
            try:
                ensure_model_ready()
            except Exception as exc:
                self.send_json(api_error("model server is not reachable", exc), 502)
                return
            chat_store.append_message(ident, "user", content)
            data = chat_store.load_chat(ident)
            started = time.monotonic()
            try:
                answer, timings, usage = llama_complete(chat_store.to_llm_messages(data))
            except urllib.error.HTTPError as exc:
                self.send_json(api_error(f"llama-server HTTP {exc.code}", exc), 502)
                return
            except Exception as exc:
                self.send_json(api_error("model server request failed", exc), 502)
                return
            timings = timings or {}
            timings["elapsed_seconds"] = round(time.monotonic() - started, 3)
            data = chat_store.append_message(ident, "assistant", answer, timings=timings, meta={"usage": usage})
            self.send_json(data)
            return
        if self.path.startswith("/api/chats/") and self.path.endswith("/webmessage"):
            ident = self.path.split("/")[3]
            payload = self.read_json()
            content = (payload.get("content") or "").strip()
            if not content:
                self.send_json({"error": "empty message"}, 400)
                return
            try:
                ensure_model_ready()
            except Exception as exc:
                self.send_json(api_error("model server is not reachable", exc), 502)
                return
            search_query = content if should_search_web(content) else ""
            if not search_query:
                chat_store.append_message(ident, "user", content)
                data = chat_store.load_chat(ident)
                started = time.monotonic()
                try:
                    answer, timings, usage = llama_complete(llm_messages_with_web_context(data))
                except urllib.error.HTTPError as exc:
                    self.send_json(api_error(f"llama-server HTTP {exc.code}", exc), 502)
                    return
                except Exception as exc:
                    self.send_json(api_error("model server request failed", exc), 502)
                    return
                timings = timings or {}
                timings["elapsed_seconds"] = round(time.monotonic() - started, 3)
                data = chat_store.append_message(ident, "assistant", answer, timings=timings, meta={"usage": usage})
                self.send_json(data)
                return
            try:
                results, context = build_web_context(search_query)
            except Exception as exc:
                self.send_json(api_error("web lookup failed", exc), 502)
                return
            chat_store.append_message(ident, "user", content)
            chat_store.append_message(
                ident,
                "web_search",
                "Query: " + compact_query_for_storage(search_query) + "\n\n" + "\n".join(f"- {r['title']}: {r['url']}" for r in results),
            )
            chat_store.append_message(ident, "web_context", context)
            data = chat_store.load_chat(ident)
            started = time.monotonic()
            web_prompt = (
                "Answer the user's latest question using the most recent web lookup context already provided in this conversation. "
                "Cite sources by number. "
                "Do not say you cannot browse; the lookup results are the browsed context. "
                "If the lookup results are weak, blocked, or contradictory, say exactly what was found or what failed."
            )
            try:
                answer, timings, usage = llama_complete(llm_messages_with_web_context(data) + [{"role": "user", "content": web_prompt}])
            except urllib.error.HTTPError as exc:
                self.send_json(api_error(f"llama-server HTTP {exc.code}", exc), 502)
                return
            except Exception as exc:
                self.send_json(api_error("model server request failed", exc), 502)
                return
            timings = timings or {}
            timings["elapsed_seconds"] = round(time.monotonic() - started, 3)
            data = chat_store.append_message(ident, "assistant", answer, timings=timings, meta={"usage": usage, "web_mode": True})
            self.send_json(data)
            return
        self.send_json({"error": "not found"}, 404)

    def do_PATCH(self):
        if self.path.startswith("/api/chats/") and not self.path.endswith("/message"):
            ident = self.path.rsplit("/", 1)[-1]
            payload = self.read_json()
            title = (payload.get("title") or "").strip()
            if not title:
                self.send_json({"error": "empty title"}, 400)
                return
            try:
                data = chat_store.rename_chat(ident, title)
            except FileNotFoundError:
                self.send_json({"error": "chat not found"}, 404)
                return
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 400)
                return
            self.send_json(data)
            return
        self.send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        if self.path.startswith("/api/chats/"):
            ident = self.path.rsplit("/", 1)[-1]
            removed = chat_store.delete_chat(ident)
            if not removed:
                self.send_json({"error": "chat not found"}, 404)
                return
            self.send_json({"ok": True})
            return
        self.send_json({"error": "not found"}, 404)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Atomic Llama Turbo web chat on http://{HOST}:{PORT}")
    print(f"Proxying model API at {BASE_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
