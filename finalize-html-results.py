#!/usr/bin/env python3
import argparse
import html
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULT_ROOT = ROOT / "quality-bench" / "results"


SECTION_ALIASES = {
    "headlines": ("homepage hero headline", "hero headline"),
    "subheads": ("subheadline",),
    "one_liners": ("one-liner", "one liners", "ads", "banners"),
    "ctas": ("cta", "button"),
    "problem": ("problem agitation", "problem"),
    "why": ("why allroundwebsite", "why allround", "why choose"),
    "pricing": ("pricing", "value"),
    "comparison": ("comparison", "beats website builders"),
    "microcopy": ("micro-copy", "microcopy"),
}


def resolve_result_dir(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        if path.exists():
            path = path.resolve()
        else:
            path = RESULT_ROOT / value
    if not path.exists() or not path.is_dir():
        raise SystemExit(f"Result folder not found: {path}")
    return path


def strip_inline_markdown(value):
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    value = value.replace("•", " ").strip()
    return re.sub(r"\s+", " ", value).strip()


def clean_line(line):
    line = line.strip()
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"^\s*[-*+]\s+", "", line)
    line = re.sub(r"^\s*\d+[.)]\s+", "", line)
    line = re.sub(r"^\s*>+\s*", "", line)
    line = re.sub(r"^\s*(Headline|Subheadline|Primary CTA|Secondary CTA|Trust Line|Small trust/value line|CTA)\s*:\s*", "", line, flags=re.I)
    return strip_inline_markdown(line).strip(" -:")


def section_key(heading):
    normalized = heading.lower()
    for key, aliases in SECTION_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return key
    return None


def parse_copy(markdown):
    sections = {key: [] for key in SECTION_ALIASES}
    current = None
    model = ""
    title = ""
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("- model:"):
            model = clean_line(line.split(":", 1)[1])
            continue
        if line.startswith("#"):
            heading = clean_line(line)
            if not title:
                title = heading
            current = section_key(heading)
            continue
        if current:
            cleaned = clean_line(line)
            if not cleaned:
                continue
            lower = cleaned.lower()
            if lower.startswith(("model:", "task:", "here is", "output", "ready-to-paste")):
                continue
            if len(cleaned) > 220:
                cleaned = cleaned[:217].rstrip() + "..."
            sections[current].append(cleaned)
    return {
        "model": model,
        "title": title,
        "headlines": sections["headlines"][:10],
        "subheads": sections["subheads"][:10],
        "one_liners": sections["one_liners"][:10],
        "ctas": sections["ctas"][:8],
        "problem": sections["problem"][:8],
        "why": sections["why"][:10],
        "pricing": sections["pricing"][:10],
        "comparison": sections["comparison"][:10],
        "microcopy": sections["microcopy"][:12],
    }


def first(items, fallback):
    for item in items:
        if item:
            return item
    return fallback


def many(items, fallback, count):
    values = [item for item in items if item]
    values.extend(fallback)
    result = []
    for item in values:
        if item not in result:
            result.append(item)
        if len(result) >= count:
            break
    return result


def extract_model_css(text):
    match = re.search(r"<style[^>]*>(.*?)(?:</style>|$)", text, flags=re.I | re.S)
    if match:
        return match.group(1).strip()
    before_body = re.split(r"<body[^>]*>", text, flags=re.I, maxsplit=1)[0]
    css_like = []
    for line in before_body.splitlines():
        if "{" in line or "}" in line or line.strip().startswith((".", "#", "@", ":root", "body", "*", "h1", "h2", "p", "a")):
            css_like.append(line)
    return "\n".join(css_like).strip()


def sanitize_css(css):
    lines = css.splitlines()
    while lines and lines[-1].strip() and "{" not in lines[-1] and "}" not in lines[-1] and lines[-1].lstrip().startswith((".", "#", "@", ":")):
        lines.pop()
    css = "\n".join(lines).strip()
    opens = css.count("{")
    closes = css.count("}")
    if opens > closes:
        css += "\n" + ("\n".join("}" for _ in range(opens - closes)))
    return css


def fallback_css():
    return r"""
/* Finalizer safety layer: keeps repaired artifacts reviewable in a browser. */
:root {
  --final-bg: #0b1020;
  --final-panel: rgba(255,255,255,0.08);
  --final-ink: #f8fafc;
  --final-muted: rgba(248,250,252,0.72);
  --final-accent: #38d9c7;
  --final-hot: #ff6b6b;
  --final-line: rgba(255,255,255,0.16);
}
body { min-height: 100vh; }
.alt-final-page { background: radial-gradient(circle at top right, rgba(56,217,199,.2), transparent 32rem), var(--final-bg); color: var(--final-ink); }
.alt-final-page .container { max-width: 1180px; margin: 0 auto; padding: 0 22px; }
.alt-final-page .hero { min-height: 78vh; display: flex; align-items: center; padding: 72px 0 44px; }
.alt-final-page .hero-content { display: grid; grid-template-columns: minmax(0,1fr) minmax(320px,.9fr); gap: 42px; align-items: center; width: 100%; }
.alt-final-page .hero-text h1 { font-size: clamp(2.6rem, 6vw, 5rem); line-height: 1.02; letter-spacing: 0; margin: 0 0 22px; color: inherit; }
.alt-final-page .hero-text p { font-size: clamp(1.05rem, 2vw, 1.35rem); color: var(--final-muted); max-width: 640px; margin: 0 0 26px; }
.alt-final-page .cta-button, .alt-final-page .cta-btn { display: inline-flex; align-items: center; justify-content: center; min-height: 48px; padding: 0 24px; border-radius: 999px; background: var(--final-accent); color: #051014; font-weight: 800; text-decoration: none; box-shadow: 0 12px 34px rgba(56,217,199,.22); }
.alt-final-page .secondary-cta { margin-left: 12px; color: var(--final-ink); border: 1px solid var(--final-line); background: transparent; }
.alt-final-page .browser-window, .alt-final-page .browser { min-height: 360px; background: #f8fafc; color: #111827; border-radius: 18px; overflow: hidden; box-shadow: 0 28px 70px rgba(0,0,0,.34); border: 1px solid rgba(255,255,255,.15); }
.alt-final-page .browser-header, .alt-final-page .browser-bar { height: 42px; display: flex; align-items: center; gap: 8px; padding: 0 16px; background: #e5e7eb; }
.alt-final-page .dot { width: 11px; height: 11px; border-radius: 50%; background: #9ca3af; }
.alt-final-page .dot:nth-child(1), .alt-final-page .dot.red { background: #ff5f56; }
.alt-final-page .dot:nth-child(2), .alt-final-page .dot.yellow { background: #ffbd2e; }
.alt-final-page .dot:nth-child(3), .alt-final-page .dot.green { background: #27c93f; }
.alt-final-page .browser-content { min-height: 318px; padding: 28px; background: linear-gradient(135deg,#ffffff,#e0f7f4); }
.alt-final-page .browser-content h2 { color: #111827; font-size: clamp(1.8rem, 4vw, 3rem); margin: 0 0 18px; }
.alt-final-page .mock-row { height: 16px; border-radius: 999px; background: rgba(17,24,39,.14); margin: 12px 0; }
.alt-final-page .mock-row.short { width: 56%; }
.alt-final-page .mock-card-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; margin-top: 22px; }
.alt-final-page .mock-card { min-height: 78px; border-radius: 14px; background: rgba(255,255,255,.78); border: 1px solid rgba(17,24,39,.08); padding: 14px; font-weight: 800; }
.alt-final-page .services, .alt-final-page .story-section, .alt-final-page .comparison-section, .alt-final-page .cta-section { padding: 72px 0; }
.alt-final-page .section-heading { max-width: 760px; margin: 0 auto 32px; text-align: center; }
.alt-final-page .section-heading h2 { font-size: clamp(2rem, 4vw, 3.2rem); margin: 0 0 14px; }
.alt-final-page .section-heading p { margin: 0 auto; color: var(--final-muted); }
.alt-final-page .services-grid { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 18px; }
.alt-final-page .service-card, .alt-final-page .card, .alt-final-page .story-card { background: var(--final-panel); border: 1px solid var(--final-line); border-radius: 18px; padding: 24px; box-shadow: 0 18px 42px rgba(0,0,0,.18); }
.alt-final-page .service-icon, .alt-final-page .card-icon { width: 48px; height: 48px; border-radius: 14px; display: grid; place-items: center; background: rgba(56,217,199,.16); margin-bottom: 16px; font-size: 1.5rem; }
.alt-final-page .story-grid { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 18px; }
.alt-final-page .compare-list { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 18px; }
.alt-final-page .compare-list ul { margin: 12px 0 0 18px; color: var(--final-muted); }
.alt-final-page .microcopy { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 24px; }
.alt-final-page .microcopy span { border: 1px solid var(--final-line); border-radius: 999px; padding: 8px 12px; color: var(--final-muted); }
.alt-final-page .final-meta { position: fixed; right: 14px; bottom: 14px; z-index: 20; max-width: min(420px, calc(100vw - 28px)); padding: 10px 12px; border-radius: 12px; background: rgba(0,0,0,.68); color: rgba(255,255,255,.78); font: 12px/1.4 system-ui, sans-serif; backdrop-filter: blur(12px); }
@media (max-width: 900px) {
  .alt-final-page .hero-content, .alt-final-page .story-grid, .alt-final-page .compare-list { grid-template-columns: 1fr; }
  .alt-final-page .services-grid { grid-template-columns: repeat(2, minmax(0,1fr)); }
}
@media (max-width: 560px) {
  .alt-final-page .services-grid { grid-template-columns: 1fr; }
  .alt-final-page .secondary-cta { margin: 12px 0 0; }
}
"""


def esc(value):
    return html.escape(value or "", quote=True)


def service_cards(copy):
    titles = many(
        copy["one_liners"] + copy["headlines"],
        ["Bespoke websites", "Fast. Clear. Yours.", "Design + build + hosting", "No template traps"],
        4,
    )
    body = many(
        copy["subheads"] + copy["why"],
        [
            "Tailored to your brand, not squeezed into a rented platform box.",
            "Built for performance, clarity, and conversion.",
            "Design, development, hosting, SEO, and practical support in one place.",
            "A business asset that looks trustworthy and loads fast.",
        ],
        4,
    )
    icons = ["✦", "⚡", "◎", "↗"]
    html_parts = []
    for idx, title in enumerate(titles[:4]):
        html_parts.append(
            f"""<article class="service-card card">
              <div class="service-icon card-icon">{icons[idx]}</div>
              <h3>{esc(title)}</h3>
              <p>{esc(body[idx])}</p>
            </article>"""
        )
    return "\n".join(html_parts)


def list_items(items, fallback, count=5):
    return "\n".join(f"<li>{esc(item)}</li>" for item in many(items, fallback, count))


def build_final_html(model_name, model_css, copy):
    headline = first(copy["headlines"], "Your Business Deserves Better Than a Template.")
    subhead = first(copy["subheads"], "Bespoke websites built for speed, clarity, ownership, and real business results.")
    cta_primary = first(copy["ctas"], "Build My Website")
    cta_secondary = copy["ctas"][1] if len(copy["ctas"]) > 1 else "See Plans"
    browser_title = first(copy["one_liners"], "Your website should be a sales tool, not a brochure.")
    trust = first(copy["microcopy"] + copy["pricing"], "Fast, custom business websites from €199.")
    problem_title = first(copy["problem"], "Your Business Deserves Better Than a Website Builder")
    why_title = first(copy["why"], "The Smart Middle Ground")
    pricing_title = first(copy["pricing"], "Transparent Pricing. No Hidden Fees.")
    comparison_title = first(copy["comparison"], "Why Choose Allroundwebsite Over DIY Builders?")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(model_name)} - Allround Website Final HTML</title>
  <style>
{model_css}

{fallback_css()}
  </style>
</head>
<body class="alt-final-page">
  <main>
    <section class="hero">
      <div class="container">
        <div class="hero-content">
          <div class="hero-text hero-copy">
            <h1>{esc(headline)}</h1>
            <p>{esc(subhead)}</p>
            <a href="#contact" class="cta-button cta-btn">{esc(cta_primary)}</a>
            <a href="#pricing" class="cta-button cta-btn secondary-cta">{esc(cta_secondary)}</a>
            <p class="fine-print">{esc(trust)}</p>
          </div>
          <div class="browser-mockup hero-visual">
            <div class="browser-window browser">
              <div class="browser-header browser-bar">
                <span class="dot red"></span>
                <span class="dot yellow"></span>
                <span class="dot green"></span>
              </div>
              <div class="browser-content">
                <h2>{esc(browser_title)}</h2>
                <div class="mock-row"></div>
                <div class="mock-row short"></div>
                <div class="mock-card-grid">
                  <div class="mock-card">Bespoke</div>
                  <div class="mock-card">Fast</div>
                  <div class="mock-card">Owned</div>
                  <div class="mock-card">Supported</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="services" aria-labelledby="services-title">
      <div class="container">
        <div class="section-heading">
          <h2 id="services-title">{esc(first(copy["headlines"][1:], "Fast. Flexible. Built for You."))}</h2>
          <p>{esc(first(copy["subheads"][1:], "Custom business websites with less bloat, more ownership, and a clearer path to conversion."))}</p>
        </div>
        <div class="services-grid grid-3">
          {service_cards(copy)}
        </div>
      </div>
    </section>

    <section class="story-section transformation" aria-labelledby="problem-title">
      <div class="container">
        <div class="story-grid">
          <article class="story-card">
            <h2 id="problem-title">{esc(problem_title)}</h2>
            <p>{esc(first(copy["problem"][1:], "Generic builders often leave serious businesses with slow pages, familiar templates, and awkward platform restrictions."))}</p>
          </article>
          <article class="story-card">
            <h2>{esc(why_title)}</h2>
            <p>{esc(first(copy["why"][1:], "Allroundwebsite is the practical middle ground: custom enough to fit, lean enough to move fast, and personal enough to make sense."))}</p>
          </article>
          <article class="story-card" id="pricing">
            <h2>{esc(pricing_title)}</h2>
            <p>{esc(first(copy["pricing"][1:], "Start with a focused €199 website and add SEO, branding, hosting, domains, photography, or custom widgets when they actually help."))}</p>
          </article>
        </div>
      </div>
    </section>

    <section class="comparison-section" aria-labelledby="compare-title">
      <div class="container">
        <div class="section-heading">
          <h2 id="compare-title">{esc(comparison_title)}</h2>
          <p>{esc(first(copy["comparison"][1:], "DIY builders can be useful, but serious small businesses often need a faster, more tailored site they can actually own."))}</p>
        </div>
        <div class="compare-list">
          <article class="story-card">
            <h3>Template builder drag</h3>
            <ul>
              {list_items(copy["problem"][1:], ["Rigid layouts", "Platform restrictions", "Slow pages", "Generic positioning"], 4)}
            </ul>
          </article>
          <article class="story-card">
            <h3>Allround Website lift</h3>
            <ul>
              {list_items(copy["why"][1:] + copy["comparison"][2:], ["Custom design", "Clean performance", "Practical support", "Clear ownership"], 4)}
            </ul>
          </article>
        </div>
        <div class="microcopy">
          {"".join(f"<span>{esc(item)}</span>" for item in many(copy["microcopy"] + copy["one_liners"], ["No fluff", "Fast. Clear. Yours.", "Tailored to your brand"], 10))}
        </div>
      </div>
    </section>

    <section class="cta-section" id="contact">
      <div class="container text-center">
        <h2>{esc(first(copy["headlines"][2:], "Stop fighting templates. Start building business."))}</h2>
        <p>{esc(first(copy["subheads"][2:], "Pick the practical next step: start small, go custom, and keep the site yours."))}</p>
        <a href="#pricing" class="cta-button cta-btn">{esc(cta_primary)}</a>
        <p class="fine-print">{esc(trust)}</p>
      </div>
    </section>
  </main>
  <aside class="final-meta">
    Finalized from <strong>{esc(model_name)}</strong>. CSS preserved from model artifact; visible copy pulled from that same model's copy benchmark.
  </aside>
</body>
</html>
"""


def original_is_complete(text):
    lower = text.lower()
    return "<!doctype html" in lower and "<body" in lower and "</style>" in lower and "</html>" in lower


def inject_meta_before_body_end(text, model_name):
    meta = (
        '\n  <aside class="final-meta">'
        f"\n    Preserved original complete HTML from <strong>{esc(model_name)}</strong>; no scaffold finalizer layout applied."
        "\n  </aside>\n"
    )
    css = "\n.final-meta{position:fixed;right:14px;bottom:14px;z-index:20;max-width:min(420px,calc(100vw - 28px));padding:10px 12px;border-radius:12px;background:rgba(0,0,0,.68);color:rgba(255,255,255,.78);font:12px/1.4 system-ui,sans-serif;backdrop-filter:blur(12px)}\n"
    if "</style>" in text.lower():
        text = re.sub(r"</style>", css + "</style>", text, count=1, flags=re.I)
    if "</body>" in text.lower():
        text = re.sub(r"</body>", meta + "</body>", text, count=1, flags=re.I)
    return text


def finalize_one(html_path, preserve_complete=True):
    model_name = html_path.name.split("__", 1)[0]
    copy_path = html_path.with_name(f"{model_name}__copy_allroundwebsite.md")
    if not copy_path.exists():
        return None, f"missing copy file: {copy_path.name}"
    original = html_path.read_text(encoding="utf-8", errors="replace")
    out_path = html_path.with_name(f"{model_name}__code_html_final.html")
    if preserve_complete and original_is_complete(original):
        out_path.write_text(inject_meta_before_body_end(original, model_name), encoding="utf-8")
        return out_path, "preserved complete original"
    model_css = sanitize_css(extract_model_css(original))
    copy = parse_copy(copy_path.read_text(encoding="utf-8", errors="replace"))
    final = build_final_html(model_name, model_css, copy)
    out_path.write_text(final, encoding="utf-8")
    return out_path, "scaffolded incomplete original"


def main():
    parser = argparse.ArgumentParser(description="Finalize incomplete model HTML benchmark artifacts into browser-reviewable pages.")
    parser.add_argument("result_folder", help="Result folder name such as 20260507-163842, or a path to a result folder.")
    parser.add_argument("--scaffold-all", action="store_true", help="Force the same repair scaffold even for complete original HTML files.")
    args = parser.parse_args()

    result_dir = resolve_result_dir(args.result_folder)
    html_files = sorted(result_dir.glob("*__code_html_visual.html"))
    if not html_files:
        raise SystemExit(f"No *__code_html_visual.html files found in {result_dir}")

    written = []
    for html_path in html_files:
        out_path, status = finalize_one(html_path, preserve_complete=not args.scaffold_all)
        if out_path:
            written.append(out_path)
            print(f"finalized: {out_path} ({status})")
        else:
            print(f"skip: {html_path.name}: {status}")
    print(f"Done. Wrote {len(written)} final HTML file(s) in {result_dir}")


if __name__ == "__main__":
    main()
