# Results

This file is the human-readable summary. Raw benchmark output belongs in `bench/results/`.

## Hardware

- GPU: NVIDIA RTX 2060 Max-Q
- VRAM: 6 GiB class
- RAM: 24 GiB class
- OS: Bazzite / Fedora Atomic style host
- Runtime: Podman with NVIDIA CDI

## Stable Profiles

| Profile | Role | Model | Context | KV cache | CPU MoE | VRAM | RAM | Copy speed | Code speed | Verdict |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---|
| `qwen36-coder-q4` | coding/copy | Qwen3.6-35B-A3B UD-Q4_K_M | 131K | turbo4/turbo3 | 36 | ~5.3 GiB | ~21-22 GiB used | 20.1-22.5 tok/s | low-mid 20 tok/s short gen | stable |

## Failed Profiles

| Profile | Failure | Fix / Next Test |
|---|---|---|
| `qwen36-coder-q4` at 262K | CUDA OOM on 6 GiB GPU | use 131K, try Q3, or test on 8/12 GiB VRAM |

## Candidate Profiles To Benchmark

| Profile | Role | Status |
|---|---|---|
| `qwen36-coder-q3` | fallback coding | candidate |
| `qwen36-coder-27b` | coding comparison | candidate |
| `gemma4-copy-e4b` | copywriting / fast assistant | candidate |
| `gemma4-fast-e2b` | smoke test / ultra fast | candidate |

## How To Add A Result

Run a profile, then benchmark the current server:

```bash
PROFILE=profiles/qwen36-coder-q4.env ./run-atomic.sh
```

In another terminal:

```bash
./bench-code.sh --profile profiles/qwen36-coder-q4.env
./bench-copy.sh --profile profiles/qwen36-coder-q4.env
```

Then summarize the generated `bench/results/*.md` files here.

## Latest Copy Benchmark

Profile: `qwen36-coder-q4`

| Task | Prompt tok/s | Gen tok/s | Elapsed | VRAM after | RAM after |
|---|---:|---:|---:|---:|---:|
| homepage_hero | 61.3 | 22.2 | 11.3s | 5330 MiB | 21.55 GiB |
| seo_titles | 52.5 | 20.1 | 29.3s | 5332 MiB | 21.43 GiB |
| service_page_rewrite | 63.8 | 22.5 | 12.5s | 5332 MiB | 21.69 GiB |
