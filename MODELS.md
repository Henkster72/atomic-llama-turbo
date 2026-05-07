# Models To Try

Atomic Llama Turbo started with Qwen3.6 35B A3B because it is a useful stress test: large total parameter count, small active parameter count, huge context, and GGUF availability.

The setup is not married to Qwen. Any llama.cpp-compatible GGUF model can be tested if the server supports its architecture and the machine has enough RAM/VRAM.

## Tested Stable

### Qwen3.6 35B A3B

```text
PROFILE=profiles/qwen36-coder-q4.env
MODEL=unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M
CTX_SIZE=131072
N_CPU_MOE=36
CACHE_K=turbo4
CACHE_V=turbo3
```

Validated on a 6 GiB NVIDIA laptop GPU with about 24 GiB system RAM.

What worked:

- loaded successfully
- answered through `/v1/chat/completions`
- ran the terminal chat client
- web lookup worked through the Python client
- generated around low-to-mid 20 tokens/sec on short tests

What did not fit on the validated machine:

- Q4 at 262K context

## Good Candidates To Test Next

These are candidates, not validated profiles. Start with lower context, confirm the server loads, then increase ambition.

The profile files are the preferred way to test them:

```bash
PROFILE=gemma4-copy-e4b ./run-atomic.sh
```

On a new machine, start with:

```bash
./doctor.sh
./recommend-profile.sh
```

To prefetch models into the Hugging Face cache:

```bash
./install-models.sh --dry-run --all
./install-models.sh --all
```

Default installer behavior downloads only the validated Qwen Q4 profile.

## Curated Role Matrix

| Profile | Model | Role | Status |
|---|---|---|---|
| `qwen36-coder-q4` | Qwen3.6-35B-A3B Q4 | main coding | validated |
| `qwen36-coder-q3` | Qwen3.6-35B-A3B Q3 | fallback coding | candidate |
| `gemma4-copy-e4b` | Gemma 4 E4B | copywriting / fast assistant | candidate |
| `gemma4-fast-e2b` | Gemma 4 E2B | smoke test / ultra fast | candidate |
| `qwen36-coder-27b` | Qwen3.6 27B | coding comparison | candidate |
| `qwopus36-q4` | Qwopus3.6-35B-A3B Q4 | reasoning/coding comparison | candidate, same Q4 recipe |
| `qwopus36-q5` | Qwopus3.6-35B-A3B Q5 | heavier reasoning/coding comparison | stress-test |
| `caveman-qwen36-q4` | caveman-qwen3.6 Q4 | terse coding comparison | candidate, same Q4 recipe |
| `caveman-qwen36-q5` | caveman-qwen3.6 Q5 | heavier terse coding comparison | stress-test |

## Benchmark Download List

`MODEL_LIST.md` is a small CSV-style manifest of models selected for local testing. Use the wrapper when you want to fetch that exact list:

```bash
./download-bench-models.sh --dry-run --all
./download-bench-models.sh
```

Default behavior skips rows marked `Downloaded=yes`. Use `--all` when you want the script to include those too.

Suitability on the validated 6GB VRAM / 24GB RAM machine:

| Profile | Fit notes |
|---|---|
| `qwen36-coder-q4` | known stable baseline at 131K context |
| `qwen36-coder-q3` | lower-memory fallback with the same MoE/TurboKV pattern |
| `qwopus36-q4` | Qwen3.6-35B-A3B derivative, should use the same Q4 recipe |
| `caveman-qwen36-q4` | Qwen3.6-35B-A3B derivative, should use the same Q4 recipe |
| `qwopus36-q5` | heavier Q5 test; start at 64K and watch RAM/swap |
| `caveman-qwen36-q5` | heavier Q5 test; start at 64K and watch RAM/swap |
| `gemma4-copy-e4b` | smaller non-Qwen profile; no CPU MoE flag |
| `gemma4-fast-e2b` | smallest non-Qwen smoke test; no CPU MoE flag |

The Q4 Qwen-derived fine-tunes are the closest matches to the original validated recipe. The Q5 fine-tunes are not impossible, but they are likely to spend more time leaning on system RAM and swap on 24GB-class machines.

### Qwen3.6 27B GGUF

```bash
MODEL=unsloth/Qwen3.6-27B-GGUF:UD-Q4_K_M \
CTX_SIZE=131072 \
./run-atomic.sh
```

Why try it:

- likely easier to fit than 35B A3B
- same broad Qwen3.6 family
- promising for coding and agent-style workflows

### Qwen3.6 35B A3B Q3

```bash
MODEL=unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q3_K_XL \
CTX_SIZE=131072 \
./run-atomic.sh
```

Why try it:

- lower memory pressure than Q4
- useful fallback if Q4 is too close to the edge
- may allow more headroom for longer prompts or other GPU activity

### Gemma 4 E2B / E4B GGUF

```bash
MODEL=unsloth/gemma-4-E4B-it-GGUF:UD-Q4_K_M \
CTX_SIZE=65536 \
N_CPU_MOE= \
./run-atomic.sh
```

Why try it:

- much smaller than the 25B/31B candidates
- good first Gemma 4 compatibility check
- likely friendlier to small GPUs

Also try:

```bash
MODEL=unsloth/gemma-4-E2B-it-GGUF:UD-Q4_K_M \
CTX_SIZE=65536 \
N_CPU_MOE= \
./run-atomic.sh
```

### Gemma 4 26B A4B GGUF

```bash
MODEL=unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q4_K_M \
CTX_SIZE=65536 \
N_CPU_MOE= \
./run-atomic.sh
```

Why try it:

- MoE-style candidate
- potentially interesting quality/resource tradeoff
- should be tested carefully before raising context

### Gemma 4 31B GGUF

```bash
MODEL=unsloth/gemma-4-31B-it-GGUF:UD-Q3_K_XL \
CTX_SIZE=65536 \
N_CPU_MOE= \
./run-atomic.sh
```

Why try it:

- larger dense-style candidate
- likely heavier than the small Gemma variants
- may need lower quant or lower context on small GPUs

## Testing Pattern

For every new model:

```bash
MODEL=repo/name:quant CTX_SIZE=65536 N_CPU_MOE= ./run-atomic.sh
```

Then:

```bash
curl http://127.0.0.1:8080/health
./test-atomic.sh
./chat-atomic.sh
```

Benchmark:

```bash
./bench-copy.sh --profile profiles/gemma4-copy-e4b.env
./bench-code.sh --profile profiles/qwen36-coder-q4.env
```

Watch:

```bash
nvidia-smi
free -h
```

Record:

- model repo and quant
- context size
- CPU MoE setting if relevant
- VRAM use
- RAM/swap use
- prompt tok/s
- generation tok/s
- whether the answer quality looks sane

## Important Caveats

Model aliases in `MODEL=repo:quant` depend on the Hugging Face repository filenames. If a quant name fails with a 404, check the repo's file list and use the exact quant label available there.

Some models need different flags, chat templates, or multimodal projector handling. This setup defaults to text-only:

```text
--no-mmproj
```

That is intentional for small-GPU testing. If you want image input later, treat that as a separate memory budget.

## Pointers

- Qwen3.6 35B A3B GGUF: https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF
- Unsloth model list: https://huggingface.co/unsloth
- Gemma 4 E4B GGUF: https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF
- Gemma 4 collection: https://huggingface.co/collections/unsloth/gemma-4
