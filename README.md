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

## Test

```powershell
uv run pytest                                   # unit tests
$env:MOS_DEV='1'; podman compose up -d --build  # stack with hello app
$env:MOS_E2E='1'; uv run pytest tests/e2e -v    # end-to-end against the running stack
```

## Adding an app

Create `catalog/<id>/` with `app.yml` and `docker-compose.yml` following the conventions in the spec (§5).
`uv run pytest tests/test_catalog_lint.py` checks them.
