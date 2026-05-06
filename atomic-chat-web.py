#!/usr/bin/env python3
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
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
STATIC_DIR = Path(__file__).resolve().parent / "static"


def llama_complete(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 700,
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


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Atomic Llama Turbo</title>
  <link rel="stylesheet" href="/static/popicon.css">
  <link rel="icon" href="/static/atomic-llama-turbo.svg">
  <style>
    :root { color-scheme: dark; --bg:#0f1117; --panel:#171923; --panel2:#1d202b; --line:#2d3140; --text:#f2f5f8; --muted:#9ba3b4; --accent:#ff8236; --accent2:#44d3a4; --bubble:#202431; --bubble2:#171a22; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font:14px/1.5 ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; }
    .app { display:grid; grid-template-columns:284px minmax(0,1fr); height:100vh; }
    aside { min-width:0; border-right:1px solid var(--line); background:var(--panel); display:grid; grid-template-rows:auto auto 1fr; overflow:hidden; }
    .brand { display:flex; align-items:center; gap:10px; padding:14px 14px 10px; min-width:0; }
    .brand img { width:36px; height:36px; flex:0 0 auto; }
    .brand-title { font-weight:760; font-size:15px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .brand-sub { color:var(--muted); font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .side-actions { padding:8px 12px 12px; }
    button { border:1px solid var(--line); background:var(--panel2); color:var(--text); border-radius:8px; padding:8px 10px; cursor:pointer; font:inherit; }
    button:hover { border-color:var(--accent); }
    .new-btn { width:100%; display:flex; align-items:center; justify-content:center; gap:8px; }
    .chat-list { overflow:auto; display:grid; align-content:start; gap:4px; padding:0 8px 12px; }
    .chat-item { width:100%; min-width:0; text-align:left; padding:9px 10px; border-radius:8px; border:1px solid transparent; background:transparent; }
    .chat-item:hover { background:#20232d; }
    .chat-item.active { background:#242835; border-color:#3a4052; }
    .chat-title { font-weight:650; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%; }
    .chat-meta { color:var(--muted); font-size:11px; margin-top:2px; display:flex; gap:6px; min-width:0; align-items:center; }
    .chat-meta span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    main { min-width:0; display:grid; grid-template-rows:58px 1fr auto; }
    header { border-bottom:1px solid var(--line); padding:10px 18px; display:flex; gap:16px; align-items:center; justify-content:space-between; background:#11141b; }
    .top-title { min-width:0; }
    h1 { font-size:16px; margin:0; letter-spacing:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .sub { color:var(--muted); font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:min(58vw, 820px); }
    .status { color:var(--muted); font-size:12px; white-space:nowrap; }
    .messages-wrap { overflow:auto; }
    .messages { width:min(100%, 920px); margin:0 auto; min-height:100%; padding:26px 18px 32px; display:flex; flex-direction:column; gap:18px; }
    .msg { display:grid; grid-template-columns:34px minmax(0,1fr); gap:12px; align-items:start; }
    .avatar { width:30px; height:30px; border-radius:50%; display:grid; place-items:center; background:#272b37; color:var(--accent); font-size:15px; overflow:hidden; }
    .avatar img { width:100%; height:100%; object-fit:cover; }
    .content { min-width:0; padding:2px 0; white-space:pre-wrap; overflow-wrap:anywhere; }
    .user .content { color:#f7f9fb; }
    .assistant .content { color:#e7ebf1; }
    .system .content, .web_context .content, .web_search .content, .web_fetch .content { color:var(--muted); font-size:13px; }
    .role { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; margin-bottom:4px; }
    .timing { color:var(--muted); font-size:12px; margin-top:8px; }
    .composer-shell { border-top:1px solid var(--line); background:#11141b; padding:14px 18px 18px; }
    form { width:min(100%, 920px); margin:0 auto; display:grid; grid-template-columns:1fr 42px; gap:10px; align-items:end; }
    textarea { min-height:56px; max-height:180px; resize:vertical; border:1px solid var(--line); border-radius:10px; background:#171a22; color:var(--text); padding:13px 14px; font:inherit; outline:none; }
    textarea:focus { border-color:var(--accent); box-shadow:0 0 0 2px rgba(255,130,54,.12); }
    .send-btn { width:42px; height:42px; border-radius:10px; display:grid; place-items:center; color:#11141b; background:var(--accent); border-color:var(--accent); font-size:19px; }
    .send-btn:hover { filter:brightness(1.05); }
    .empty { color:var(--muted); text-align:center; margin:auto; }
    code { color:#d7dce5; }
    @media (max-width:760px) {
      .app { grid-template-columns:1fr; grid-template-rows:210px 1fr; }
      aside { border-right:0; border-bottom:1px solid var(--line); }
      main { min-height:0; }
      .sub { max-width:60vw; }
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
      <button id="newChat" class="new-btn"><span class="pi pi-edit"></span><span>New chat</span></button>
    </div>
    <div id="chatList" class="chat-list"></div>
  </aside>
  <main>
    <header>
      <div class="top-title">
        <h1 id="title">Atomic Llama Turbo</h1>
        <div class="sub" id="subtitle">Shared console + web chat archive</div>
      </div>
      <div class="status" id="status">checking...</div>
    </header>
    <div class="messages-wrap"><section id="messages" class="messages"></section></div>
    <div class="composer-shell">
      <form id="form">
        <textarea id="input" placeholder="Message Qwen..."></textarea>
        <button id="send" class="send-btn" type="submit" aria-label="Send"><span class="pi pi-send"></span></button>
      </form>
    </div>
  </main>
</div>
<script>
let current = null;

async function api(path, opts={}) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function loadChats() {
  const chats = await api('/api/chats');
  const box = document.getElementById('chatList');
  box.innerHTML = chats.map(c => `
    <button class="chat-item ${c.id === current ? 'active' : ''}" onclick="openChat('${c.id}')">
      <div class="chat-title">${escapeHtml(c.title)}</div>
      <div class="chat-meta"><span>${escapeHtml(c.md_name || c.id + '.md')}</span><span>${escapeHtml(c.model || 'model?')}</span></div>
    </button>
  `).join('');
  if (!current && chats[0]) await openChat(chats[0].id);
}

async function openChat(id) {
  current = id;
  const chat = await api('/api/chats/' + id);
  document.getElementById('title').textContent = chat.title || 'New chat';
  document.getElementById('subtitle').textContent = `${chat.md_name || ''} · ${chat.model || 'qwen'}`;
  const messagesBox = document.getElementById('messages');
  const items = chat.messages || [];
  messagesBox.innerHTML = items.length ? items.map(m => `
    <article class="msg ${escapeHtml(m.role)}">
      <div class="avatar">${m.role === 'assistant' ? '<img src="/static/atomic-llama-turbo.svg" alt="">' : '<span class="pi pi-profile"></span>'}</div>
      <div class="content">
        <div class="role">${escapeHtml(m.role)}</div>
        <div>${escapeHtml(m.content)}</div>
        ${m.timings && m.timings.predicted_per_second ? `<div class="timing">gen ${m.timings.predicted_per_second.toFixed(1)} tok/s</div>` : ''}
      </div>
    </article>
  `).join('') : '<div class="empty">Start a new local chat. It will become a Markdown file automatically.</div>';
  document.querySelector('.messages-wrap').scrollTop = document.querySelector('.messages-wrap').scrollHeight;
  await loadChatButtonsOnly();
}

async function loadChatButtonsOnly() {
  const chats = await api('/api/chats');
  const box = document.getElementById('chatList');
  box.innerHTML = chats.map(c => `
    <button class="chat-item ${c.id === current ? 'active' : ''}" onclick="openChat('${c.id}')">
      <div class="chat-title">${escapeHtml(c.title)}</div>
      <div class="chat-meta"><span>${escapeHtml(c.md_name || c.id + '.md')}</span><span>${escapeHtml(c.model || 'model?')}</span></div>
    </button>
  `).join('');
}

async function newChat() {
  const chat = await api('/api/chats', {method:'POST'});
  current = chat.id;
  await openChat(current);
}

async function sendMessage(ev) {
  ev.preventDefault();
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text) return;
  if (!current) await newChat();
  input.value = '';
  document.getElementById('status').textContent = 'thinking... 0.0s';
  const start = performance.now();
  const tick = setInterval(() => {
    document.getElementById('status').textContent = 'thinking... ' + ((performance.now() - start) / 1000).toFixed(1) + 's';
  }, 250);
  try {
    await api('/api/chats/' + current + '/message', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({content:text})
    });
    await openChat(current);
  } finally {
    clearInterval(tick);
    document.getElementById('status').textContent = 'ready';
  }
}

async function refreshHealth() {
  try {
    const h = await api('/api/health');
    document.getElementById('status').textContent = h.ok ? 'ready' : 'llama unavailable';
  } catch(e) {
    document.getElementById('status').textContent = 'web backend error';
  }
}

document.getElementById('newChat').addEventListener('click', newChat);
document.getElementById('form').addEventListener('submit', sendMessage);
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
                data["title"] = chat_store.title_from_messages(data.get("messages", []), data.get("title") or "New chat")
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
            chat_store.append_message(ident, "user", content)
            data = chat_store.load_chat(ident)
            started = time.monotonic()
            try:
                answer, timings, usage = llama_complete(chat_store.to_llm_messages(data))
            except urllib.error.HTTPError as exc:
                self.send_json({"error": f"llama-server HTTP {exc.code}"}, 502)
                return
            except Exception as exc:
                self.send_json({"error": str(exc)}, 502)
                return
            timings = timings or {}
            timings["elapsed_seconds"] = round(time.monotonic() - started, 3)
            data = chat_store.append_message(ident, "assistant", answer, timings=timings, meta={"usage": usage})
            self.send_json(data)
            return
        self.send_json({"error": "not found"}, 404)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Atomic Llama Turbo web chat on http://{HOST}:{PORT}")
    print(f"Proxying model API at {BASE_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
