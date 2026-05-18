#!/usr/bin/env python3
import datetime as dt
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CHAT_DIR = ROOT / "chats"
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "you", "your", "are", "was", "were", "will", "would",
    "could", "should", "about", "into", "onto", "over", "under", "then", "than", "what", "when", "where", "why",
    "how", "can", "cannot", "cant", "have", "has", "had", "not", "but", "all", "any", "some", "just", "reply",
    "exactly", "please", "using", "use", "used", "does", "did", "doing", "write", "make", "give", "tell", "say",
    "web", "based", "according", "today", "short",
    "een", "het", "deze", "dit", "dat", "wat", "waar", "waarom", "hoe", "kan", "met", "voor", "van", "naar",
}


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def chat_id():
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def clean_title(text, fallback="New chat"):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^0-9A-Za-zÀ-ÿ._-]+", " ", text)
    words = []
    seen = set()
    for raw in text.split():
        word = raw.strip("._-").lower()
        if len(word) < 3 or word in STOPWORDS or word in seen:
            continue
        if word.isdigit():
            continue
        seen.add(word)
        words.append(raw.strip("._-"))
        if len(words) >= 5:
            break
    if not words:
        return fallback
    title = " ".join(words).strip()
    return title[:42]


def title_from_messages(messages, fallback="New chat"):
    chunks = []
    for role in ("user", "assistant"):
        for item in messages:
            if item.get("role") == role and item.get("content"):
                chunks.append(item["content"])
                break
    return clean_title(" ".join(chunks), fallback=fallback)


def json_path(chat):
    return CHAT_DIR / f"{chat}.json"


def md_path(chat):
    return CHAT_DIR / f"{chat}.md"


def create_chat(base_url, model, system, status_lines=None, source="console"):
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    ident = chat_id()
    data = {
        "id": ident,
        "title": "New chat",
        "source": source,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "base_url": base_url,
        "model": model,
        "system": system,
        "status": status_lines or [],
        "messages": [],
    }
    save_chat(data)
    return data


def load_chat(ident):
    path = json_path(ident)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    legacy = md_path(ident)
    if legacy.exists():
        return parse_legacy_markdown(legacy)
    raise FileNotFoundError(ident)


def save_chat(data):
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now_iso()
    json_path(data["id"]).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown(data)


def append_message(ident, role, content, timings=None, meta=None):
    data = load_chat(ident)
    data.setdefault("messages", []).append(
        {
            "role": role,
            "content": content.strip(),
            "created_at": now_iso(),
            "timings": timings or {},
            "meta": meta or {},
        }
    )
    if data.get("title") in {"", "New chat"} and role == "assistant":
        data["title"] = title_from_messages(data.get("messages", []))
    save_chat(data)
    return data


def update_status(ident, status_lines):
    data = load_chat(ident)
    data["status"] = status_lines
    save_chat(data)
    return data


def delete_if_empty(ident):
    try:
        data = load_chat(ident)
    except FileNotFoundError:
        return False
    if data.get("messages"):
        return False
    for path in (json_path(ident), md_path(ident)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return True


def delete_chat(ident):
    removed = False
    for path in (json_path(ident), md_path(ident)):
        try:
            path.unlink()
            removed = True
        except FileNotFoundError:
            pass
    return removed


def rename_chat(ident, title):
    data = load_chat(ident)
    title = (title or "").strip()
    if not title:
        raise ValueError("title cannot be empty")
    data["title"] = title
    save_chat(data)
    return data


def to_llm_messages(data):
    messages = []
    system = data.get("system")
    if system:
        messages.append({"role": "system", "content": system})
    for item in data.get("messages", []):
        role = item.get("role")
        if role in {"user", "assistant", "system"}:
            messages.append({"role": role, "content": item.get("content", "")})
    return messages


def list_chats():
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    items = {}
    for path in CHAT_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = data.get("title") or "New chat"
        if title in {"", "New chat"}:
            title = title_from_messages(data.get("messages", []), title)
        items[data["id"]] = {
            "id": data["id"],
            "title": title,
            "source": data.get("source", "unknown"),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "md_path": str(md_path(data["id"])),
            "md_name": md_path(data["id"]).name,
            "model": data.get("model") or "",
            "message_count": len(data.get("messages", [])),
        }
    for path in CHAT_DIR.glob("*.md"):
        ident = path.stem
        if ident in items:
            continue
        data = parse_legacy_markdown(path)
        items[ident] = {
            "id": ident,
            "title": title_from_messages(data.get("messages", []), data.get("title") or ident),
            "source": "legacy-md",
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "md_path": str(path),
            "md_name": path.name,
            "model": data.get("model") or "",
            "message_count": len(data.get("messages", [])),
        }
    return sorted(
        items.values(),
        key=lambda item: (item.get("updated_at") or item.get("created_at") or "", item.get("id") or ""),
        reverse=True,
    )


def write_markdown(data):
    lines = [
        f"# {data.get('title') or 'New chat'}",
        "",
        f"- Chat ID: `{data['id']}`",
        f"- Source: `{data.get('source', 'unknown')}`",
        f"- Created: `{data.get('created_at', '')}`",
        f"- Updated: `{data.get('updated_at', '')}`",
        f"- Base URL: `{data.get('base_url', '')}`",
        f"- Model alias: `{data.get('model', '')}`",
        f"- System: {data.get('system', '')}",
        "",
    ]
    status = data.get("status") or []
    if status:
        lines.extend(["## Startup Status", ""])
        lines.extend(f"- {line}" for line in status)
        lines.append("")
    lines.extend(["## Transcript", ""])
    for item in data.get("messages", []):
        role = item.get("role", "message").replace("_", " ").title()
        lines.extend([f"### {role}", "", item.get("content", "").strip(), ""])
        timings = item.get("timings") or {}
        prompt_tps = timings.get("prompt_per_second")
        pred_tps = timings.get("predicted_per_second")
        prompt_n = timings.get("prompt_n")
        pred_n = timings.get("predicted_n")
        if prompt_tps and pred_tps:
            lines.extend(
                [
                    f"_timing: prompt {prompt_tps:.2f} tok/s ({prompt_n} tok), "
                    f"generation {pred_tps:.2f} tok/s ({pred_n} tok)_",
                    "",
                ]
            )
    md_path(data["id"]).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_legacy_markdown(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    first_heading = re.search(r"^#\s+(.+)$", text, flags=re.M)
    if first_heading:
        title = first_heading.group(1).strip()
    model = ""
    model_match = re.search(r"^- Model alias:\s+`?([^`\n]+)`?\s*$", text, flags=re.M)
    if model_match:
        model = model_match.group(1).strip()
    messages = []
    matches = list(re.finditer(r"^###\s+(.+?)\s*$", text, flags=re.M))
    for idx, match in enumerate(matches):
        role_name = match.group(1).strip().lower().replace(" ", "_")
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        content = re.sub(r"\n?_timing:.*?_\s*$", "", content, flags=re.S).strip()
        if role_name in {"user", "assistant", "system", "web_context", "web_search", "web_fetch"} and content:
            messages.append(
                {
                    "role": role_name,
                    "content": content,
                    "created_at": "",
                    "timings": {},
                    "meta": {},
                }
            )
    return {
        "id": path.stem,
        "title": title_from_messages(messages, title),
        "source": "legacy-md",
        "created_at": "",
        "updated_at": dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        "base_url": "",
        "model": model,
        "system": "",
        "status": [],
        "messages": messages,
    }
