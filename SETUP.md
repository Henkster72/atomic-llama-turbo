# Setup

Atomic Llama Turbo is designed for a clean host and a CUDA-enabled container.

Reference machine:

```text
OS: Bazzite / Fedora Atomic style
GPU: RTX 2060 Max-Q, 6GB VRAM
RAM: 24GB
Runtime: Podman
```

Other Linux machines can use the same workflow, but model settings should be retuned.

## 1. Check The Host

```bash
nvidia-smi
podman --version
free -h
df -h "$HOME"
```

If `nvidia-smi` fails on the host, fix the NVIDIA driver first.

## 2. Check Container GPU Access

Podman with NVIDIA CDI:

```bash
podman run --rm \
  --device nvidia.com/gpu=all \
  --security-opt=label=disable \
  docker.io/nvidia/cuda:12.4.1-base-ubuntu22.04 \
  nvidia-smi
```

Docker users can use `--gpus all`.

## 3. Build Or Provide The CUDA Image

This project expects an image named:

```text
llama-turboquant-cuda
```

It should contain the TurboQuant-capable `llama-server` binary. The original local build used TheTom's TurboQuant llama.cpp fork.

The host does not need a CUDA toolkit. CUDA lives in the container.

## 4. Download Bench Models

The current bench models are in `MODEL_LIST.md`.

```bash
./download-bench-models.sh --dry-run
./download-bench-models.sh
```

Ollama rows are skipped by this downloader. Manage them with:

```bash
ollama pull gemma3:1b
ollama pull gemma3:4b
```

## 5. Start A Profile

```bash
PROFILE=qwen36-coder-q4 ./run-atomic.sh
```

or use the server helper:

```bash
./atomic-server.sh switch qwen36-coder-q4
```

Test:

```bash
./test-atomic.sh
```

## 6. Retune For Another Machine

The checked-in settings are tuned for 6GB VRAM / 24GB RAM. On larger or smaller systems, retune context, GPU layers, K/V cache type, and CPU MoE offload.

Start by regenerating local profiles:

```bash
./materialize-model-list-profiles.sh
```

Then smoke test one model at a time:

```bash
./run-quality-bench.sh --stage smoke --profiles qwen36-coder-q4
```

Useful tuning principles:

- reduce context when KV cache OOMs
- reduce GPU layers when model weights OOM
- use TurboQuant KV when long context is the memory wall
- prefer plain/q8 KV when the model fits and TurboQuant overhead slows it down
- keep RAM/swap under control; high swap can make results meaningless

## 7. What Is Ignored

The following are intentionally not committed:

- Hugging Face/Ollama model caches
- generated benchmark outputs
- raw local prompts used during experiments
- chat transcripts
- generated temp profiles
- secrets in `.env`
