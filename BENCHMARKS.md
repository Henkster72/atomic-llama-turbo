# Benchmarks

ATL benchmarks practical usefulness, not leaderboard status.

The core question:

```text
On this machine, with this profile, is the model fast enough and good enough for real local work?
```

## Tasks

Current quality runs focus on:

- copywriting
- Python logic/helpers
- single-file HTML/CSS visual concepts

Use smoke first:

```bash
./run-quality-bench.sh --stage smoke --profiles qwen36-coder-q4 gemma4-26b-a4b-q4 qwen3-30b-a3b-2507-q4xl
```

Run the full set only after smoke results are worth the time:

```bash
./run-quality-bench.sh --stage full --profiles qwen36-coder-q4 gemma4-26b-a4b-q4 qwen3-30b-a3b-2507-q4xl
```

For Ollama comparison models:

```bash
python3 ./run-mixed-naomi-bench.py
```

## Metrics

Each run records:

- elapsed seconds
- prompt tokens/sec
- generation tokens/sec
- prompt/completion token counts
- VRAM/RAM/swap snapshots
- model/profile settings
- output file names

Outputs live in:

```text
quality-bench/results/
```

That folder is ignored by git. Keep summarized findings in Markdown, not raw generated artifacts.

## Human Quality Scoring

Use a simple 1-5 score:

```text
1 = unusable
2 = mostly wrong or generic
3 = usable with edits
4 = good
5 = strong, near-ready
```

Score copy for clarity, specificity, tone, and commercial usefulness.

Score code for correctness, restraint, readability, and whether it runs.

Score HTML/CSS for visual hierarchy, brand fit, browser usability, responsiveness, and whether the design is more than generic cards.
