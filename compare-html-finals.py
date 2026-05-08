#!/usr/bin/env python3
import argparse
import difflib
import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULT_ROOT = ROOT / "quality-bench" / "results"


def resolve_dir(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = RESULT_ROOT / value
    if not path.exists():
        raise SystemExit(f"Missing result folder: {path}")
    return path


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def normalize(text):
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def style_block(text):
    match = re.search(r"<style[^>]*>(.*?)</style>", text, flags=re.I | re.S)
    return match.group(1).strip() if match else ""


def body_block(text):
    match = re.search(r"<body[^>]*>(.*?)</body>", text, flags=re.I | re.S)
    return match.group(1).strip() if match else ""


def headings(text):
    found = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", text, flags=re.I | re.S)
    result = []
    for item in found:
        item = re.sub(r"<[^>]+>", "", item)
        item = re.sub(r"\s+", " ", item).strip()
        if item:
            result.append(item)
    return result


def css_vars(css):
    return sorted(set(re.findall(r"--[a-zA-Z0-9_-]+\s*:\s*[^;]+", css)))


def class_names(text):
    classes = []
    for value in re.findall(r'class="([^"]+)"', text):
        classes.extend(value.split())
    return sorted(set(classes))


def similarity(a, b):
    a = normalize(a)
    b = normalize(b)
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def sha(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:12]


def collect(folder):
    rows = []
    for final in sorted(folder.glob("*__code_html_final.html")):
        profile = final.name.split("__", 1)[0]
        visual = folder / f"{profile}__code_html_visual.html"
        copy = folder / f"{profile}__copy_allroundwebsite.md"
        text = read(final)
        css = style_block(text)
        body = body_block(text)
        original_text = read(visual) if visual.exists() else ""
        original_css = style_block(original_text)
        rows.append(
            {
                "folder": folder.name,
                "profile": profile,
                "final": final,
                "visual": visual if visual.exists() else None,
                "copy": copy if copy.exists() else None,
                "text": text,
                "css": css,
                "body": body,
                "original_text": original_text,
                "original_css": original_css,
                "headings": headings(text),
                "classes": class_names(text),
                "vars": css_vars(css),
            }
        )
    return rows


def print_summary(rows):
    print("| Folder | Profile | Final KB | Original KB | CSS hash | Body hash | Headings | Classes |")
    print("|---|---|---:|---:|---|---|---:|---:|")
    for row in rows:
        print(
            f"| {row['folder']} | {row['profile']} | "
            f"{row['final'].stat().st_size / 1024:.1f} | "
            f"{(row['visual'].stat().st_size / 1024 if row['visual'] else 0):.1f} | "
            f"{sha(row['css'])} | {sha(row['body'])} | "
            f"{len(row['headings'])} | {len(row['classes'])} |"
        )


def print_pairwise(rows, label, key):
    print(f"\n## Pairwise {label} Similarity")
    print("| A | B | Similarity |")
    print("|---|---|---:|")
    for idx, a in enumerate(rows):
        for b in rows[idx + 1 :]:
            sim = similarity(a[key], b[key])
            print(f"| {a['folder']}/{a['profile']} | {b['folder']}/{b['profile']} | {sim:.3f} |")


def print_headings(rows):
    print("\n## Headline/Section Sample")
    for row in rows:
        print(f"\n### {row['folder']}/{row['profile']}")
        for heading in row["headings"][:8]:
            print(f"- {heading}")


def main():
    parser = argparse.ArgumentParser(description="Compare finalized HTML benchmark artifacts across result folders.")
    parser.add_argument("folders", nargs="+", help="Result folder names or paths.")
    args = parser.parse_args()

    rows = []
    for folder_arg in args.folders:
        rows.extend(collect(resolve_dir(folder_arg)))
    if not rows:
        raise SystemExit("No *__code_html_final.html files found.")

    print_summary(rows)
    print_pairwise(rows, "final body", "body")
    print_pairwise(rows, "model/original CSS", "original_css")
    print_headings(rows)


if __name__ == "__main__":
    main()
