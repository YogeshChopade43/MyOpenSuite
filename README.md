# MyOpenSuite

A personal, self-hosted marketplace of open-source alternatives to paid AI software.
Design: [docs/superpowers/specs/2026-11-02-myopensuite-design.md](docs/superpowers/specs/2026-11-02-myopensuite-design.md).

## Prerequisites

- Podman machine, **rootful**, VM disk on E: (`podman machine init --rootful`, then `wsl --manage podman-machine-default --move E:\podman`).
- For GPU apps: NVIDIA container toolkit + CDI in the machine — see [docs/podman-gpu.md](docs/podman-gpu.md).
- [uv](https://docs.astral.sh/uv/) for running tests (it fetches Python 3.12).

## Run

```powershell
podman compose up -d --build
```

Open http://localhost:8080. Everything binds to localhost only.

Set `MOS_DEV=1` before `up` to show the `hello` test app.

## Apps

| App | Replaces | Port | GPU | Notes |
|---|---|---|---|---|
| VoiceStudio | ElevenLabs | 7801 | yes | [notes](catalog/voicestudio/NOTES.md) — copy the admin key from **Credentials** |
| ComfyUI | Midjourney / Runway | 7802 | yes | [notes](catalog/comfyui/NOTES.md) — install a model from its Manager |
| Next AI Draw.io | Napkin.ai / Lucid AI | 7803 | no | [notes](catalog/next-ai-draw-io/NOTES.md) — set an AI provider in its Settings |
| Open Notebook | NotebookLM | 7804 | no | [notes](catalog/open-notebook/NOTES.md) — add a provider key in its Settings |
| bolt.diy | Bolt.new / v0 | 7805 | no | [notes](catalog/bolt-diy/NOTES.md) — pick a provider and paste its key in the app |
| OpenHands | Devin | 7806 | no | [notes](catalog/openhands/NOTES.md) — paste the key from **Credentials**, then add a provider |
| AppFlowy | Notion AI | 7807 | no | [notes](catalog/appflowy/NOTES.md) — "Sign up here" with your real email (one free seat) |

Approximate disk use once installed: VoiceStudio ~14 GB (with models), ComfyUI ~12 GB (plus checkpoints),
OpenHands ~3.5, AppFlowy ~2.5, bolt.diy ~2.4, Open Notebook ~1.5, Next AI Draw.io ~1 GB.

**Memory:** on a 16 GB PC, run 2–3 apps at a time. With everything running Windows ran out of memory
and WSL/Podman froze (`wsl --shutdown`, then `podman machine start`, recovers it; apps must be started
again). Dify was left out for this reason (16 containers, ~3 GB RAM).

Only one GPU app runs at a time; starting one asks to stop the other. GPU apps are installed stopped.
App secrets (like VoiceStudio's admin key) are generated once and kept in the `mos-state` volume.

## Disk space

All apps live inside the Podman VM disk (`E:\podman\ext4.vhdx`). Uninstalling an app frees space
*inside* the VM — new installs reuse it — but the `.vhdx` file on E: does not shrink by itself.
To give the space back to Windows:

```powershell
podman machine ssh sudo fstrim -av
podman machine stop
wsl --shutdown
wsl --manage podman-machine-default --set-sparse true   # one-time; lets the VHD shrink after trims
podman machine start
```

`podman image prune -f` removes unused image layers (old builds).

## Test

```powershell
uv run pytest                                   # unit tests
$env:MOS_DEV='1'; podman compose up -d --build  # stack with hello app
$env:MOS_E2E='1'; uv run pytest tests/e2e -v    # end-to-end against the running stack
$env:MOS_E2E_APPS='1'; uv run pytest tests/e2e/test_apps.py -v  # real apps — downloads ~25 GB, needs the GPU
```

## Adding an app

Create `catalog/<id>/` with `app.yml` and `docker-compose.yml` following the conventions in the spec (§5).
`uv run pytest tests/test_catalog_lint.py` checks them.
