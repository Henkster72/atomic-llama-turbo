# Setup Guide

This is the recipe for Atomic Llama Turbo: a clean, container-first way to run big GGUF models locally with CUDA acceleration.

The guide uses Podman first because it fits Bazzite/Fedora Atomic well. Docker can work too. The important part is not the logo on the runtime; the important part is that the NVIDIA GPU is visible inside a container.

## 0. The Shape Of The Thing

The stack looks like this:

```text
host NVIDIA driver
        |
container GPU access
        |
CUDA llama-server image
        |
GGUF model from Hugging Face
        |
localhost OpenAI-compatible API
        |
curl, chat-atomic.sh, the web UI, an SSH tunnel, or another client
```

The host does not need a CUDA toolkit. The host does need a working NVIDIA driver.

## 1. Pick A Workspace

Use a folder with enough room for the source tree, image layers, and model cache:

```bash
export WORKDIR="$HOME/AI/llama-turboquant"
mkdir -p "$WORKDIR"
cd "$WORKDIR"
```

Expect tens of GB once model weights and image layers are present. Large local AI is not weightless; we are just keeping the mess in predictable places.

## 2. Check The Host

Host GPU:

```bash
nvidia-smi
```

Runtime:

```bash
podman --version
```

or:

```bash
docker --version
```

Memory:

```bash
free -h
```

Disk:

```bash
df -h "$HOME"
```

If `nvidia-smi` fails on the host, stop here. Fix the driver first. Containers cannot borrow a GPU the host cannot see.

## 3. Check GPU Access Inside A Container

Podman with NVIDIA CDI:

```bash
ls -l /etc/cdi/nvidia.yaml
podman run --rm \
  --device nvidia.com/gpu=all \
  --security-opt=label=disable \
  docker.io/nvidia/cuda:12.4.1-base-ubuntu22.04 \
  nvidia-smi
```

Docker with NVIDIA Container Toolkit:

```bash
docker run --rm --gpus all \
  docker.io/nvidia/cuda:12.4.1-base-ubuntu22.04 \
  nvidia-smi
```

Do not build llama.cpp until this works. A broken GPU container path will only become a more expensive broken GPU container path later.

## 4. Clone TurboQuant llama.cpp

```bash
git clone --depth 1 \
  --branch feature/turboquant-kv-cache \
  https://github.com/TheTom/llama-cpp-turboquant.git \
  "$WORKDIR/src"
```

This fork/branch is used for the TurboQuant KV cache flags:

```text
--cache-type-k turbo4
--cache-type-v turbo3
```

## 5. Choose CUDA Architecture

Set `CUDA_DOCKER_ARCH` to your GPU compute capability without the dot:

```text
RTX 2060 / Turing      75
RTX 3060 / Ampere      86
RTX 3090 / Ampere      86
RTX 4090 / Ada         89
```

For the validated RTX 2060 Max-Q:

```bash
export CUDA_DOCKER_ARCH=75
```

If you are not sure, look up your exact GPU compute capability. Guessing may still build, but it is a poor hobby.

## 6. Build The CUDA Server Image

Podman:

```bash
cd "$WORKDIR/src"
podman build --target server \
  --build-arg CUDA_DOCKER_ARCH="$CUDA_DOCKER_ARCH" \
  --build-arg BASE_CUDA_DEV_CONTAINER=docker.io/nvidia/cuda:12.8.1-devel-ubuntu24.04 \
  --build-arg BASE_CUDA_RUN_CONTAINER=docker.io/nvidia/cuda:12.8.1-runtime-ubuntu24.04 \
  -t llama-turboquant-cuda \
  -f .devops/cuda.Dockerfile .
```

Docker:

```bash
cd "$WORKDIR/src"
docker build --target server \
  --build-arg CUDA_DOCKER_ARCH="$CUDA_DOCKER_ARCH" \
  --build-arg BASE_CUDA_DEV_CONTAINER=docker.io/nvidia/cuda:12.8.1-devel-ubuntu24.04 \
  --build-arg BASE_CUDA_RUN_CONTAINER=docker.io/nvidia/cuda:12.8.1-runtime-ubuntu24.04 \
  -t llama-turboquant-cuda \
  -f .devops/cuda.Dockerfile .
```

Verify the binary has the flags this setup expects:

```bash
podman run --rm llama-turboquant-cuda --help | grep -E 'cache-type|n-cpu-moe|hf-repo|flash-attn'
```

With Docker, replace `podman` with `docker`.

## 7. Add The Helper Scripts

This repository includes:

```text
run-atomic.sh
test-atomic.sh
chat-atomic.sh
chat-atomic.py
install-models.sh
download-bench-models.sh
doctor.sh
recommend-profile.sh
chat_store.py
atomic-chat-web.sh
atomic-chat-web.py
bench-copy.sh
bench-code.sh
bench/run-bench.py
profiles/*.env
static/atomic-llama-turbo.svg
static/popicon.css
static/popicon.woff2
```

Make them executable if needed:

```bash
chmod +x "$WORKDIR"/run-atomic.sh \
  "$WORKDIR"/test-atomic.sh \
  "$WORKDIR"/chat-atomic.sh \
  "$WORKDIR"/install-models.sh \
  "$WORKDIR"/download-bench-models.sh \
  "$WORKDIR"/doctor.sh \
  "$WORKDIR"/recommend-profile.sh \
  "$WORKDIR"/chat-atomic.py \
  "$WORKDIR"/atomic-chat-web.sh \
  "$WORKDIR"/atomic-chat-web.py \
  "$WORKDIR"/bench-copy.sh \
  "$WORKDIR"/bench-code.sh \
  "$WORKDIR"/bench/run-bench.py
```

The run script can load a profile:

```bash
PROFILE=qwen36-coder-q4 "$WORKDIR/run-atomic.sh"
PROFILE=profiles/gemma4-copy-e4b.env "$WORKDIR/run-atomic.sh"
```

Profiles are plain env files:

```text
CONTAINER_RUNTIME=podman
IMAGE=llama-turboquant-cuda
PROFILE_NAME=qwen36-coder-q4
PROFILE_ROLE=coding
MODEL=unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M
MODEL_ALIAS=qwen
CTX_SIZE=131072
N_CPU_MOE=36
CACHE_K=turbo4
CACHE_V=turbo3
GPU_LAYERS=99
HOST_BIND=127.0.0.1
PORT=8080
```

Docker users can start with:

```bash
CONTAINER_RUNTIME=docker PROFILE=qwen36-coder-q4 "$WORKDIR/run-atomic.sh"
```

## 8. Diagnose And Pick A Profile

Run the doctor:

```bash
"$WORKDIR/doctor.sh"
```

Then ask for a conservative starting profile:

```bash
"$WORKDIR/recommend-profile.sh"
```

The doctor checks OS, runtime, host GPU, RAM/swap, disk, NVIDIA CDI for Podman, and NVIDIA access inside a CUDA container. It does not install drivers or mutate host config.

For Docker:

```bash
CONTAINER_RUNTIME=docker "$WORKDIR/doctor.sh"
```

## 9. Prefetch Models

The first server run can download the selected GGUF automatically. If you want to download models deliberately, use the installer.

Validated profile only:

```bash
"$WORKDIR/install-models.sh"
```

All curated candidates:

```bash
"$WORKDIR/install-models.sh" --all
```

The exact benchmark manifest in `MODEL_LIST.md`:

```bash
"$WORKDIR/download-bench-models.sh" --dry-run --all
"$WORKDIR/download-bench-models.sh"
```

Preview first:

```bash
"$WORKDIR/install-models.sh" --dry-run --all
```

One profile:

```bash
"$WORKDIR/install-models.sh" --profile gemma4-copy-e4b
```

The curated set matches [MODELS.md](MODELS.md):

```text
qwen36-coder-q4     main coding, validated
qwen36-coder-q3     fallback coding candidate
gemma4-copy-e4b     copywriting / fast assistant candidate
gemma4-fast-e2b     smoke test / ultra fast candidate
qwen36-coder-27b    coding comparison candidate
qwopus36-q4         Qwen3.6 A3B fine-tune, Q4 same-recipe candidate
qwopus36-q5         Qwen3.6 A3B fine-tune, Q5 stress-test candidate
caveman-qwen36-q4   terse Qwen3.6 A3B fine-tune, Q4 same-recipe candidate
caveman-qwen36-q5   terse Qwen3.6 A3B fine-tune, Q5 stress-test candidate
```

This can download many GB. Files are cached under:

```text
$HOME/.cache/huggingface
```

## 10. Start The Server

```bash
"$WORKDIR/run-atomic.sh"
```

The first run downloads the model into:

```text
$HOME/.cache/huggingface
```

Wait for:

```text
main: model loaded
main: server is listening on http://0.0.0.0:8080
srv  update_slots: all slots are idle
```

That `0.0.0.0` is inside the container. The host binding defaults to:

```text
127.0.0.1:8080
```

So the server is open to your own machine, not to the whole LAN.

## 11. Test The API

Health:

```bash
curl http://127.0.0.1:8080/health
```

Chat:

```bash
"$WORKDIR/test-atomic.sh"
```

A good response includes generated text and timing data. A bad response usually comes with useful server logs: CUDA OOM, model still loading, missing model file, or broken GPU runtime.

## 12. Use The Console Agent

```bash
"$WORKDIR/chat-atomic.sh"
```

The client prints:

- server status
- model alias
- load split
- GPU memory
- RAM and swap
- transcript path

It also shows a small loading indicator while waiting for a response and prints timing afterward.

Transcripts are saved in:

```text
$WORKDIR/chats/
```

The server does not write those transcript files. The Python console and web clients do.

New JSON-backed chats produce both:

```text
$WORKDIR/chats/YYYYMMDD-HHMMSS.json
$WORKDIR/chats/YYYYMMDD-HHMMSS.md
```

The sidebar title comes from the first useful words of the assistant's first response.

Console archive commands:

```text
/chats       list saved console and web chats
/open ID     reopen a saved JSON-backed chat
/where       show the Markdown path
```

## 13. Use The Integrated Web Chat

The raw llama-server page is not the archive. It is better to keep the model API and the chat UI separate:

```text
8080  llama-server API
8090  Atomic Llama Turbo web chat
```

Start the local web chat:

```bash
"$WORKDIR/atomic-chat-web.sh"
```

Open:

```text
http://127.0.0.1:8090/
```

For a persistent user service:

```bash
systemd-run --user \
  --unit=atomic-llama-chat \
  --working-directory="$WORKDIR" \
  "$WORKDIR/atomic-chat-web.sh"
```

Check it:

```bash
systemctl --user status atomic-llama-chat --no-pager
curl http://127.0.0.1:8090/api/health
```

## 14. Use Web Lookup

Inside the console:

```text
/search weather albufeira
/fetch https://example.com/page
/web what is happening with a topic today?
```

The model is still local. The client fetches pages, trims text, and gives the model snippets. This is simple retrieval, not a full browser automation system.

## 15. Remote Use Over SSH

Best default:

```bash
ssh -N -L 8080:127.0.0.1:8080 user@your-llm-host
```

Then from your remote machine:

```bash
curl http://127.0.0.1:8080/health
```

Run the TUI-ish console remotely:

```bash
ssh -t user@your-llm-host '$HOME/AI/llama-turboquant/chat-atomic.sh'
```

Direct LAN exposure:

```bash
HOST_BIND=0.0.0.0 "$WORKDIR/run-atomic.sh"
```

Only do that on a trusted network or behind your own access control. The default llama-server endpoint is not a hardened public service.

## 16. Publish Inside Tailscale

Tailnet-only model API:

```bash
tailscale serve --bg --https=8080 http://127.0.0.1:8080
```

Tailnet-only integrated web chat:

```bash
tailscale serve --bg --https=8090 http://127.0.0.1:8090
```

Then use:

```text
https://bazzite.smelt-sun.ts.net:8080/v1
https://bazzite.smelt-sun.ts.net:8090/
```

The first URL is for API clients. The second URL is for humans.

## 17. Try Another Model

See [MODELS.md](MODELS.md). The short version:

```bash
MODEL=some/GGUF-repo:some-quant CTX_SIZE=65536 N_CPU_MOE= ./run-atomic.sh
```

Then test:

```bash
./test-atomic.sh
./chat-atomic.sh
```

For a different model family, you may need different chat-template behavior, context size, or multimodal flags. Treat the Qwen profile as a strong pattern, not a magic universal incantation.

## 18. Benchmark The Current Server

Run copywriting prompts:

```bash
./bench-copy.sh --profile profiles/qwen36-coder-q4.env
```

Run coding prompts:

```bash
./bench-code.sh --profile profiles/qwen36-coder-q4.env
```

Results go to:

```text
bench/results/
```

## 19. Stop

Press `Ctrl-C` in the server terminal.

Or:

```bash
"${CONTAINER_RUNTIME:-podman}" stop atomic-llama-turbo
```

Stop the web chat user service:

```bash
systemctl --user stop atomic-llama-chat
```

Disable Tailscale Serve endpoints:

```bash
tailscale serve --https=8080 off
tailscale serve --https=8090 off
```
