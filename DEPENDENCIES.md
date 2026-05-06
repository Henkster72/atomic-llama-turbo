# Dependencies

Atomic Llama Turbo tries to keep the dependency story short:

```text
Linux
NVIDIA driver
container runtime
GPU visible inside container
enough RAM/VRAM/disk
```

That is the promise. Not "install half the CUDA universe on the host."

## Required

- Linux host
- NVIDIA GPU
- working NVIDIA driver
- `nvidia-smi`
- Podman or Docker
- Git
- Bash
- Python 3
- Curl
- disk space for model files and image layers

Check:

```bash
nvidia-smi
podman --version
git --version
python3 --version
curl --version
```

Docker users:

```bash
docker --version
```

## NVIDIA In Containers

This is the one dependency that matters most.

Use the project doctor:

```bash
./doctor.sh
```

For Docker:

```bash
CONTAINER_RUNTIME=docker ./doctor.sh
```

Podman with CDI:

```bash
ls -l /etc/cdi/nvidia.yaml
podman run --rm \
  --device nvidia.com/gpu=all \
  --security-opt=label=disable \
  docker.io/nvidia/cuda:12.4.1-base-ubuntu22.04 \
  nvidia-smi
```

Docker:

```bash
docker run --rm --gpus all \
  docker.io/nvidia/cuda:12.4.1-base-ubuntu22.04 \
  nvidia-smi
```

If the GPU does not show up there, fix that first. Everything else depends on it.

## Host CUDA Toolkit

Not required.

The build uses CUDA container images:

```text
docker.io/nvidia/cuda:12.8.1-devel-ubuntu24.04
docker.io/nvidia/cuda:12.8.1-runtime-ubuntu24.04
```

The host provides the driver. The container provides CUDA libraries and build tools.

## RAM And VRAM

Validated baseline:

```text
GPU: 6 GiB NVIDIA
RAM: about 24 GiB
Swap: useful
```

Observed with Qwen3.6 35B A3B Q4 at 131K context:

```text
VRAM: about 5.3 GiB used
Host model buffer: about 17 GiB
```

Practical guidance:

- 6 GiB VRAM can work with careful settings
- 8 to 12 GiB VRAM gives more comfort
- 24 GiB RAM is a good floor for this Q4 profile
- swap helps when the system gets tight
- bigger models and longer contexts cost real memory

If you are tight:

```bash
CTX_SIZE=65536 ./run-atomic.sh
```

or:

```bash
MODEL=unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q3_K_XL ./run-atomic.sh
```

For a first recommendation on a new machine:

```bash
./recommend-profile.sh
```

## Disk

Plan for:

- about 21 GB for the Q4 Qwen GGUF
- more if you test multiple quants
- several GB for CUDA image layers
- source checkout and build cache

The full curated installer set can be much larger than the validated Q4 baseline. Use:

```bash
./install-models.sh --dry-run --all
```

before downloading everything.

Having 40 to 60 GB free is sensible. More is nicer.

## Network

Needed during setup:

- GitHub for the TurboQuant fork
- container registry access for NVIDIA CUDA images
- Hugging Face for GGUF files
- optional web access for `/search`, `/fetch`, and `/web`

After images and models are cached, basic serving does not need to download again.

## Python

The console client uses only the Python standard library. No pip install is required.

It uses:

- `urllib`
- `html.parser`
- `json`
- `subprocess`
- `readline` when available

## Optional Comfort Tools

- `tmux` for keeping the server running in a session
- `nvtop` for GPU watching
- `htop` or `btop` for RAM/swap watching
- SSH tunnels, Tailscale, or WireGuard for remote access

## Security Posture

Default:

```text
127.0.0.1:8080
```

That is local-only. Good.

LAN mode:

```bash
HOST_BIND=0.0.0.0 ./run-atomic.sh
```

That is reachable by other machines. Use only on trusted networks or behind your own access control.
