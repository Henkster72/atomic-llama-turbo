# Atomic Llama Turbo

<p align="center">
  <img src="static/atomic-llama-turbo.svg" alt="Atomic Llama Turbo" width="180">
</p>

**Useful local LLMs on modest NVIDIA hardware. Fast inference, practical quality, no host CUDA mess.**

Atomic Llama Turbo is a container-first recipe for running and comparing local GGUF models with `llama-server`, CUDA, TurboQuant KV cache, and CPU MoE offload. The current reference machine is a 6GB RTX 2060 Max-Q laptop with 24GB RAM.

The point is not to collect every model. The point is to find a small set of profiles that are actually useful for copywriting, HTML/CSS visuals, and Python coding.

The core question:

> What model/quant/context combination is actually usable on my machine?

You do not need a datacenter GPU. You need the right cursed incantation of llama.cpp flags. :-)

## Current Bench Set

These are the maintained benchmark choices in `MODEL_LIST.md`:

| Profile | Backend | Role | Reference settings |
|---|---|---|---|
| `qwen36-coder-q4` | llama.cpp | gold quality baseline | 131K ctx, `turbo4/turbo3`, `--n-cpu-moe 36` |
| `gemma4-26b-a4b-q4` | llama.cpp | best HTML/CSS contender | 64K ctx, `turbo3/turbo3`, `--n-cpu-moe 32` |
| `qwen3-30b-a3b-2507-q4xl` | llama.cpp | Qwen challenger | 131K ctx, `turbo4/turbo3`, `--n-cpu-moe 44` |
| `ollama-gemma3-1b` | Ollama | tiny speed control | managed by Ollama |
| `ollama-gemma3-4b` | Ollama | small speed/quality control | managed by Ollama |

Observed on the reference machine:

- Qwen3.6 35B A3B Q4 is still the best serious baseline: roughly 23-25 tok/s on clean copy/Python runs and 8-11 tok/s on long HTML/CSS generations.
- Gemma 4 26B-A4B loaded cleanly and gave about 15.5 tok/s on smoke testing, with strong observed HTML/CSS quality.
- Qwen3 30B A3B 2507 is slower than the Qwen3.6 baseline, but remains useful as a quality challenger.
- Ollama Gemma 1B/4B are speed controls, not replacements for the larger quality models.

Raw benchmark outputs, prompts, chats, model cache, and generated temp profiles are intentionally ignored by git.

## Quick Start

This is not a Python package and is not installed with `pip install .`. Use it from the checked-out folder as a script-driven container toolkit.

Check the machine:

```bash
./doctor.sh
```

Download/cache the listed Hugging Face models if needed:

```bash
./download-bench-models.sh --dry-run
./download-bench-models.sh
```

Start the validated Qwen profile:

```bash
PROFILE=qwen36-coder-q4 ./run-atomic.sh
```

In another terminal:

```bash
./test-atomic.sh
./chat-atomic.sh
```

For managed server switching:

```bash
./atomic-server.sh switch qwen36-coder-q4
./atomic-server.sh status
./atomic-server.sh stop
```

## Benchmark

Smoke test the llama.cpp bench set:

```bash
./run-quality-bench.sh --stage smoke --profiles qwen36-coder-q4 gemma4-26b-a4b-q4 qwen3-30b-a3b-2507-q4xl
```

Full copy/Python/HTML test:

```bash
./run-quality-bench.sh --stage full --profiles qwen36-coder-q4 gemma4-26b-a4b-q4 qwen3-30b-a3b-2507-q4xl
```

Mixed Ollama + llama.cpp comparison:

```bash
python3 ./run-mixed-bench.py
```

Benchmark results are written under `quality-bench/results/` and are not committed.

## Retuning On Another Machine

The checked-in parameters are a known-good starting point for the reference machine: 6GB VRAM / 24GB RAM. Other systems should retune instead of blindly copying the numbers.

The tuning loop is:

1. Check the machine:

```bash
./doctor.sh
```

2. Pick one candidate from `MODEL_LIST.md`.

3. Edit that row's tuning columns:

```text
CTX_SIZE      context window to allocate
GPU_LAYERS    requested GPU layer offload, or lower it when weights OOM
CACHE_K       K cache type, such as turbo4, turbo3, q8_0, f16
CACHE_V       V cache type, such as turbo4, turbo3, q8_0, f16
N_CPU_MOE     number of MoE expert layers kept on CPU; empty for dense models
```

4. Regenerate local profile env files:

```bash
./materialize-model-list-profiles.sh
```

5. Smoke test one profile:

```bash
./run-quality-bench.sh --stage smoke --profiles qwen36-coder-q4
```

6. Read the failure mode:

```text
KV cache OOM       lower CTX_SIZE or use more compressed CACHE_K/CACHE_V
model weight OOM   lower GPU_LAYERS or choose a smaller quant/model
very slow output    reduce CPU-heavy dense offload, lower context, or reject the model
high swap           lower context, use a smaller quant/model, or reduce CPU MoE pressure
```

7. When the smoke test is stable, run the full task set:

```bash
./run-quality-bench.sh --stage full --profiles qwen36-coder-q4
```

8. Keep the model only if it improves speed, quality, RAM/swap pressure, or a specific task such as HTML/CSS.

Practical rules of thumb:

- If a model already fits comfortably, try `q8_0/q8_0` KV before TurboQuant; compressed KV can be overhead.
- If long context causes VRAM OOM, lower context first, then use `turbo4/turbo4` or `turbo4/turbo3`.
- MoE models are usually better small-VRAM candidates than dense models because CPU expert offload can help.
- Dense models with partial GPU offload can become very slow on 6GB cards.
- Keep one gold baseline and make every new candidate justify itself by speed, quality, or lower RAM/swap.

## What This Project Is

Atomic Llama Turbo is a small-VRAM benchmark and launch recipe for useful local LLM work:

- copywriting that is good enough to edit, not throw away
- HTML/CSS visual concepts that can be reviewed in a browser
- Python helpers that are readable and runnable
- repeatable model/profile comparisons
- clean containerized CUDA instead of host package clutter

It is not a general AI dashboard, not a RAG stack, and not a leaderboard clone.
