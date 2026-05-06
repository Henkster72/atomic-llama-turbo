# Why Atomic Llama Turbo Exists

Because local AI should not require sacrificing the host OS on a pile of mismatched CUDA packages.

This project is a pattern:

```text
keep the host boring
put CUDA build/runtime pieces in a container
run GGUF through llama-server
compress the KV cache
offload what the small GPU cannot hold
measure instead of guessing
```

That is the entire philosophy. Modest hardware, practical settings, repeatable steps.

The narrowed mission is:

```text
small-VRAM TurboQuant recipes for copywriting and coding with local GGUF models
```

## Why Atomic?

Atomic and immutable Linux systems are excellent daily-driver systems, but they do not enjoy random low-level package layering. That is a feature, not a flaw.

Atomic Llama Turbo respects that:

- no host CUDA toolkit
- no system driver replacement
- no surprise service manager edits
- no Ollama changes
- no permanent host mutation beyond normal files in your home directory and container images

If the experiment fails, remove the workspace and image. The host remains boring. Boring hosts are good hosts.

## Why A Local HTTP Server?

`llama-server` speaks HTTP because that makes it easy to use from many clients:

- curl
- the included terminal chat client
- OpenAI-compatible SDKs
- editor plugins
- remote machines through SSH tunnels
- small scripts

The helper script binds the host side to:

```text
127.0.0.1:8080
```

That means "this machine only." It is open locally so your tools can talk to it, but it is not advertised to the LAN by default.

Inside the container, llama-server logs:

```text
server is listening on http://0.0.0.0:8080
```

That line is normal. The container listens on all container interfaces; Podman/Docker then maps it to localhost on the host.

## Where Chat Memory Lives

There are four layers people often mix up:

```text
model weights: cached in Hugging Face cache
server context: temporary in-memory prompt/session state
chat state: JSON file written by the console/web clients
chat transcript: Markdown file written beside the JSON
```

The durable archive is saved here:

```text
./chats/YYYYMMDD-HHMMSS.json
./chats/YYYYMMDD-HHMMSS.md
```

The server itself is not a diary. The console and web clients are the diary. The web sidebar uses the JSON state when available and can still show older Markdown-only console transcripts as legacy chats.

## Why A Separate Web Chat?

The llama-server page is useful, but it is not the product here. The integrated web chat exists so the archive has one home:

```text
console chat -> ./chats
web chat     -> ./chats
```

The model API stays on `8080`. The human web chat uses `8090`. That keeps automation and chat history from stepping on each other.

## Why TurboQuant KV Cache?

Long context is expensive because the model has to remember keys and values for many tokens. At 128K or 262K context, KV cache can become the wall you hit before the model weights are the problem.

TurboQuant KV cache reduces that pressure:

```text
--cache-type-k turbo4
--cache-type-v turbo3
```

On the tested 6 GiB GPU, this helped make 131K context practical.

## Why CPU MoE Offload?

Qwen3.6 35B A3B is a mixture-of-experts model. It has many parameters, but only a smaller active slice per token. That makes it a good candidate for careful CPU/GPU splitting.

The tested profile uses:

```text
--n-cpu-moe 36
```

That keeps many MoE expert weights in host RAM while still using CUDA for the parts that fit and matter. It is not the fastest possible setup. It is the setup that lets a 6 GiB GPU punch above its weight without falling over.

Other models may not support or need this flag. The generic launcher only adds `--n-cpu-moe` when `N_CPU_MOE` is non-empty.

## Why 131K Context?

The model supports 262K context. The tested laptop did not fit Q4 at 262K with enough CUDA headroom.

So the stable default is:

```text
CTX_SIZE=131072
```

That is still a huge working window. It is also the difference between "impressive and usable" and "almost loaded, then died dramatically."

Larger GPUs should try:

```bash
CTX_SIZE=262144 ./run-atomic.sh
```

Smaller systems should try:

```bash
CTX_SIZE=65536 ./run-atomic.sh
```

## Why Text-Only By Default?

Some GGUF repos include multimodal projector files. That is useful when you are doing vision. It is wasteful when you are trying to squeeze text inference onto a small GPU.

The default run uses:

```text
--no-mmproj
```

For this project, the first target is a strong local text/code/chat setup. Multimodal can come later, after the memory budget stops screaming.

## Why Reasoning Off?

Qwen-style reasoning can be useful, but it can also eat the whole response budget before giving you the answer. For a terminal agent, smoke tests, and quick coding help, direct answers are usually better.

The default run uses:

```text
--reasoning off
```

You can change that once the baseline is stable.

## Will This Work On Other Machines?

Yes, if the machine passes the actual checks. This is not tied to one laptop. It depends on measurable resources:

- NVIDIA GPU visible inside a container
- enough VRAM for model layers, KV cache, recurrent state, and compute buffers
- enough RAM for CPU-resident weights
- enough swap if RAM is tight
- enough disk for model files and image layers

Use:

```bash
./doctor.sh
./recommend-profile.sh
```

The first script checks the machine and container GPU path. The second suggests a conservative profile based on VRAM/RAM class.

The exact best settings change with hardware. That is why the run script exposes the main knobs:

```bash
MODEL=...
CTX_SIZE=...
N_CPU_MOE=...
CACHE_K=...
CACHE_V=...
GPU_LAYERS=...
```

## How To Test Fit

Start conservative:

```bash
PROFILE=qwen36-coder-q4 ./run-atomic.sh
```

In another terminal:

```bash
nvidia-smi
free -h
curl http://127.0.0.1:8080/health
```

Then:

```bash
./test-atomic.sh
```

If the server reaches `main: model loaded`, you have a working baseline. If it fails, the log usually tells you which budget ran out.

Then run practical benchmarks:

```bash
./bench-code.sh --profile profiles/qwen36-coder-q4.env
./bench-copy.sh --profile profiles/qwen36-coder-q4.env
```

## Reading Failure Signals

CUDA OOM:

- reduce `CTX_SIZE`
- try a smaller quant
- increase `N_CPU_MOE`
- close other GPU programs

Host RAM pressure:

- use a smaller quant
- reduce context
- add/check swap
- close memory-heavy apps

HTTP 503 from the chat client:

- the server is probably still loading
- wait for `main: model loaded`

Bad answers after changing models:

- check chat template support
- check whether the model expects reasoning flags
- check whether the selected GGUF quant is healthy
- test with a smaller prompt first

## What "Best" Means

Here, best means:

```text
stable
useful
repeatable
low host pollution
high context for the resources available
```

It does not mean maximum benchmark throughput. A 6 GiB laptop GPU will not behave like a workstation card. Atomic Llama Turbo is about finding the cleanest stable lane for the machine you actually have.
