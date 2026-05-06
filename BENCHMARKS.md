# Benchmarks

Atomic Llama Turbo benchmarks practical work, not leaderboard trophies.

The goal is to answer:

```text
On this machine, with this profile, is the model useful for coding or copywriting?
```

## What Gets Measured

- elapsed seconds
- prompt tokens/sec
- generation tokens/sec
- prompt tokens
- completion tokens
- VRAM before/after
- RAM/swap before/after
- profile settings
- model and quant
- human score placeholder

## Copywriting Tasks

Prompts live in:

```text
bench/prompts/copy/
```

Current tasks:

- homepage hero rewrite
- service page rewrite
- SEO titles/meta descriptions

Run:

```bash
./bench-copy.sh --profile profiles/qwen36-coder-q4.env
```

## Coding Tasks

Prompts live in:

```text
bench/prompts/code/
```

Current tasks:

- Bash script
- PHP bugfix
- JavaScript refactor
- Jinja explanation/rewrite

Run:

```bash
./bench-code.sh --profile profiles/qwen36-coder-q4.env
```

## Output

Each run writes:

```text
bench/results/<kind>-<profile>-YYYYMMDD-HHMMSS.jsonl
bench/results/<kind>-<profile>-YYYYMMDD-HHMMSS.md
```

The JSONL is for later analysis. The Markdown is for quick reading.

## Suggested Human Scoring

Use a simple 1-5 score:

```text
1 = wrong or unusable
2 = partially useful, needs heavy repair
3 = usable with edits
4 = good
5 = strong, near-ready
```

For coding, score:

- correctness
- instruction following
- runnable code
- restraint, no over-engineering

For copywriting, score:

- clarity
- tone fit
- specificity
- usefulness without major rewriting

## Why Practical Benchmarks

Formal benchmarks are useful, but they do not answer whether a profile is pleasant on a 6GB/8GB/12GB card. These tasks are intentionally ordinary: small scripts, PHP bugs, page copy, SEO snippets, and refactors.

That is the use case.
