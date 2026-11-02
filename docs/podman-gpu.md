# GPU access through Podman

GPU_DEVICE form: CDI

Verified 2026-11-02 on Podman 5.8.5 (rootful WSL machine), RTX 4050 Laptop, nvidia-container-toolkit 1.20.1.

## One-time setup in the Podman machine

```powershell
podman machine ssh "sudo curl -fsSL https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo -o /etc/yum.repos.d/nvidia-container-toolkit.repo && sudo dnf install -y nvidia-container-toolkit && sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml && nvidia-ctk cdi list"
```

Rerun the `nvidia-ctk cdi generate` part after every NVIDIA driver update on Windows.

## Compose form for GPU apps

```yaml
services:
  myapp:
    devices: ["nvidia.com/gpu=all"]
```

## Check

```powershell
podman compose -f tests/gpu/docker-compose.yml run --rm gpu-check
# GPU 0: NVIDIA GeForce RTX 4050 Laptop GPU (...)
```
