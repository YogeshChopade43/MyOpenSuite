# ComfyUI

Upstream: https://github.com/Comfy-Org/ComfyUI · community image `docker.io/yanwk/comfyui-boot:cu130-slim-v2`
(https://github.com/YanWenKun/ComfyUI-Docker — ComfyUI + ComfyUI-Manager, CUDA 13; needs NVIDIA driver ≥ 580).

## First model

ComfyUI ships without models. Open it, then **Manager → Model Manager** and install a checkpoint, e.g.
an SD 1.5 or SDXL base model. Models live in the `comfyui-models` volume (deleted only by
Uninstall with "Also delete data").

## 6 GB VRAM

SD 1.5 and SDXL run fine. Flux and large video models need quantised (GGUF/FP8) variants; ComfyUI
offloads automatically when VRAM runs out, at the cost of speed.

## Manual check

Load the default workflow, pick the installed checkpoint, press **Queue** — an image appears.
