# Setup

Atomic Llama Turbo is designed for a clean host and a CUDA-enabled container.

It answers one practical question:

> What model/quant/context combination is actually usable on my machine?

You do not need a datacenter GPU. You need the right cursed incantation of llama.cpp flags. :-)

This repository is not a Python package. Do not install it with `pip install .`; there is no `setup.py` or `pyproject.toml`. Run the shell and Python helper scripts directly from the checked-out folder.

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
./doctor.sh
```

`doctor.sh` is the dependency gate. It checks:

- `python3` and `curl`
- Podman or Docker
- host NVIDIA visibility through `nvidia-smi`
- NVIDIA CDI when using Podman
- CUDA/NVIDIA access from inside a container
- RAM, swap, and home disk space

If a required dependency is missing, the doctor exits non-zero and prints short advice. Fix those blockers before downloading models or starting a server.

Common fixes:

- If `nvidia-smi` fails, fix the NVIDIA driver first. Containers cannot use a GPU the host cannot see.
- If no runtime is found, install Podman or Docker. On Bazzite/Fedora Atomic systems, prefer Podman.
- If Podman cannot see the GPU, fix NVIDIA CDI/container-toolkit setup before changing model flags.
- If Docker cannot see the GPU, install or repair NVIDIA Container Toolkit.

Docker users can set:

```bash
CONTAINER_RUNTIME=docker ./doctor.sh
```

## 2. Build Or Provide The CUDA Image

This project expects an image named:

```text
llama-turboquant-cuda
```

It should contain the TurboQuant-capable `llama-server` binary. The original local build used TheTom's TurboQuant llama.cpp fork.

The host does not need a CUDA toolkit. CUDA lives in the container.

## 3. Download Bench Models

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

## 4. Start A Profile

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

## 5. Retune For Another Machine

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

## 6. What Is Ignored

The following are intentionally not committed:

- Hugging Face/Ollama model caches
- generated benchmark outputs
- raw local prompts used during experiments
- chat transcripts
- generated temp profiles
- secrets in `.env`
