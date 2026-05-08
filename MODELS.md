# Models

`MODEL_LIST.md` is the source of truth for benchmark candidates.

The current shortlist is deliberately small:

| Profile | Model | Why it stays |
|---|---|---|
| `qwen36-coder-q4` | `unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M` | Best validated all-round quality/speed baseline on 6GB VRAM / 24GB RAM. |
| `gemma4-26b-a4b-q4` | `unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q4_K_M` | Best observed HTML/CSS visual contender; good smoke speed for its size. |
| `qwen3-30b-a3b-2507-q4xl` | `unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:UD-Q4_K_XL` | Kept as the strongest Qwen-family challenger slot. |
| `ollama-gemma3-1b` | `ollama:gemma3:1b` | Tiny speed control through Ollama. |
| `ollama-gemma3-4b` | `ollama:gemma3:4b` | Small speed/quality control through Ollama. |

## Reference Settings

```text
qwen36-coder-q4:
  CTX_SIZE=131072
  GPU_LAYERS=99
  CACHE_K=turbo4
  CACHE_V=turbo3
  N_CPU_MOE=36

gemma4-26b-a4b-q4:
  CTX_SIZE=65536
  GPU_LAYERS=99
  CACHE_K=turbo3
  CACHE_V=turbo3
  N_CPU_MOE=32

qwen3-30b-a3b-2507-q4xl:
  CTX_SIZE=131072
  GPU_LAYERS=99
  CACHE_K=turbo4
  CACHE_V=turbo3
  N_CPU_MOE=44
```

These are not universal truth. They are the current reference settings for the tested laptop.

## Removed From The Active Set

The broader test matrix was useful, but several models were removed from the active manifest/cache because they were too slow, failed to fit cleanly, or duplicated stronger candidates:

- Qwen3.6 Q3
- Qwen2.5 Coder 14B Q4
- Qwen3 14B Q4
- Qwen3.6 27B dense Q4XL
- Qwen3 Coder 30B A3B duplicate slot
- DeepSeek-Coder-V2-Lite Q4
- Nemotron-3-Nano 30B A3B IQ4_XS
- Qwopus/Caveman Qwen3.6 derivatives
- older Gemma E2B/E4B HF experiments

They can be re-added later, but they should not distract from the current ATL bench set.
