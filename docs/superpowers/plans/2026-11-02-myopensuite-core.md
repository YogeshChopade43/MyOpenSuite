# MyOpenSuite Core Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running `myopensuite` container that shows a catalog of apps as tiles and can install, start, stop, update, open and uninstall them through Podman, with the one-GPU-app-at-a-time rule — proven end to end with a dummy `hello` app.

**Architecture:** Python FastAPI backend that shells out to `docker compose` (Compose v2 CLI) against Podman's Docker-compatible socket mounted at `/var/run/docker.sock`. App status is derived live from `docker compose ls` plus an HTTP probe; nothing is stored. A React + Vite frontend is built into the same image and served by FastAPI.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, PyYAML, httpx, pytest (via `uv`); React 18 + Vite + TypeScript; Podman 5.8.5 (rootful WSL machine); Docker CLI + Compose v2 inside the image.

**Spec:** `docs/superpowers/specs/2026-11-02-myopensuite-design.md` — this plan implements milestones 1–2 (spec §4, §5, §6, §9, §10, §11, §12). Gateway (§7), MCP (§8) and real apps (§3) get their own plans.

**Spec deviations (decided here):**
- `app.yml` gains `internal_port` (container port, used to probe `http://<id>:<internal_port><path>` over `mos-net`) and `dev: true` (hidden unless `MOS_DEV=1`). The main service in each app's compose file must be named exactly `<id>`.
- The dummy app is `catalog/hello/` with `dev: true` (not `_hello` — underscores are unsafe in DNS names).
- Install is one command: `up -d --build` (pulls missing images, builds git contexts, starts).
- Jobs are in-memory; after a backend restart there is no job record — the tile shows the derived status and Install/Update can be retried.

## Global Constraints

- Every published port binds `127.0.0.1` — dashboard is `127.0.0.1:8080`.
- Compose project name for an app is `mos-<id>`; shared network is the external network `mos-net`.
- Podman socket on the VM: `/run/podman/podman.sock`, mounted as `/var/run/docker.sock` with `security_opt: [label=disable]`.
- No Windows paths in any compose file; named volumes only (socket mount is the sole exception, only for apps with non-empty `warnings`).
- Runtime-down message, exactly: `Podman isn't running — run \`podman machine start\``
- Start timeout before status becomes `error`: 180 seconds. Log tail default: 50 lines.
- Statuses, exactly: `not_installed`, `stopped`, `starting`, `running`, `error`.
- Python runs via `uv` (host system Python is 3.9 — never use it). Run tests with `uv run pytest`.

## Review Focus

1. **Podman machine stopped while the dashboard is open** → every API call returns 503 with the runtime-down message and the UI shows a banner; nothing crashes. Test: `test_apps_503_when_runtime_down` (Task 6).
2. **Install clicked twice** → the second request gets 409 and no second `compose` process starts. Tests: `test_second_start_while_running_raises_busy` (Task 5), `test_install_twice_returns_409` (Task 6).
3. **Uninstall without "Also delete data"** → `down` without `-v`; shared `mos-*` volumes are external so even `-v` never deletes them. Tests: `test_uninstall_keeps_data_by_default` (Task 6), `test_lint_shared_volume_must_be_external` (Task 2).
4. **Container running but app never answers** (crash loop, wrong port) → `error` after 180 s, also when the backend restarted mid-start. Tests: `test_running_unprobed_after_timeout_is_error` (Task 4), `test_started_at_recorded_for_unprobed_app` (Task 6).
5. **Catalog typo** (bad YAML, id ≠ folder, duplicate port) → startup fails with a message naming the file. Tests: `test_load_rejects_*` (Task 2).

---

### Task 1: GPU access through Podman (gate)

Owner-assisted: needs commands inside the Podman machine. Decides the GPU compose form every GPU app will use.

**Files:**
- Create: `tests/gpu/docker-compose.yml`
- Create: `docs/podman-gpu.md`

**Interfaces:**
- Produces: the constant value `GPU_DEVICE` used by Task 2's lint — either the string `nvidia.com/gpu=all` under `devices:` (CDI form) or the `deploy.resources.reservations.devices` block (driver form), recorded in `docs/podman-gpu.md`.

- [ ] **Step 1: Install the NVIDIA container toolkit in the Podman machine**

```powershell
podman machine ssh "sudo curl -fsSL https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo -o /etc/yum.repos.d/nvidia-container-toolkit.repo && sudo dnf install -y nvidia-container-toolkit && sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml && nvidia-ctk cdi list"
```
Expected: output lists `nvidia.com/gpu=all`.

- [ ] **Step 2: Verify plain Podman sees the GPU**

Run: `podman run --rm --device nvidia.com/gpu=all docker.io/library/ubuntu:24.04 nvidia-smi -L`
Expected: `GPU 0: NVIDIA GeForce RTX 4050 Laptop GPU`

- [ ] **Step 3: Write `tests/gpu/docker-compose.yml` using the CDI form**

One service `gpu-check`, image `docker.io/library/ubuntu:24.04`, command `nvidia-smi -L`, `devices: ["nvidia.com/gpu=all"]`.

- [ ] **Step 4: Verify Compose → Podman API passes the GPU (the path the backend uses)**

Run: `podman compose -f tests/gpu/docker-compose.yml run --rm gpu-check`
Expected: `GPU 0: NVIDIA GeForce RTX 4050 Laptop GPU`.
If it fails, replace `devices:` with `deploy: { resources: { reservations: { devices: [{ driver: nvidia, count: all, capabilities: [gpu] }] } } }` and rerun. If both fail, stop and report — GPU apps are blocked.

- [ ] **Step 5: Record the working form in `docs/podman-gpu.md`**

Contents: the Step 1 commands, the working compose snippet, and the line `GPU_DEVICE form: CDI` or `GPU_DEVICE form: driver`. Note that `nvidia-ctk cdi generate` must be rerun after an NVIDIA driver update.

- [ ] **Step 6: Commit**

```bash
git add tests/gpu/docker-compose.yml docs/podman-gpu.md
git commit -m "test: verify GPU access through Podman compose"
```

---

### Task 2: Project skeleton, catalog loader and lint

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `backend/__init__.py`, `backend/catalog.py`
- Create: `catalog/hello/app.yml`, `catalog/hello/docker-compose.yml`
- Test: `tests/test_catalog.py`, `tests/test_catalog_lint.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class App: id: str; name: str; replaces: str; description: str; repo: str; port: int; internal_port: int; path: str = "/"; gpu: bool = False; size_gb: float = 0; llm: dict[str, str]; llm_manual: bool = False; warnings: list[str]; dev: bool = False; dir: Path` (dict/list fields default to empty via `field(default_factory=...)`)
  - `class CatalogError(Exception)` — message always contains the offending file path.
  - `load_catalog(root: Path) -> dict[str, App]` — reads every `root/*/app.yml`.
  - `lint_compose(app: App) -> list[str]` — human-readable problems, empty when clean.
  - `GPU_DEVICE` constant matching Task 1's decision.

- [ ] **Step 1: Create `pyproject.toml`**

Project `myopensuite`, `requires-python = ">=3.12"`, dependencies `fastapi>=0.115`, `uvicorn>=0.32`, `pyyaml>=6`, `httpx>=0.27`; dev dependency group `pytest>=8`; setuptools package `backend`. `.gitignore`: `.venv/`, `__pycache__/`, `frontend/node_modules/`, `frontend/dist/`.

Run: `uv sync`
Expected: creates `.venv` with Python 3.12.

- [ ] **Step 2: Create `catalog/hello/`**

`app.yml`: `id: hello`, `name: Hello`, `replaces: nothing`, `description: Test app`, `repo: https://hub.docker.com/_/nginx`, `port: 7800`, `internal_port: 80`, `dev: true`.
`docker-compose.yml`: service `hello`, image `docker.io/library/nginx:1.27-alpine`, ports `["127.0.0.1:7800:80"]`, networks `[mos-net]`; top-level `networks: { mos-net: { external: true } }`.

- [ ] **Step 3: Write failing loader tests in `tests/test_catalog.py`**

Each test builds a catalog in `tmp_path` with a helper `write_app(root, id, **overrides)` that writes a valid `app.yml` (defaults like hello's) plus a valid compose file.

```python
def test_load_reads_hello():
    apps = load_catalog(Path("catalog"))
    assert apps["hello"].port == 7800 and apps["hello"].internal_port == 80
    assert apps["hello"].dev is True and apps["hello"].gpu is False
    assert apps["hello"].dir == Path("catalog/hello")

def test_load_rejects_bad_yaml(tmp_path):        # app.yml = "id: [unclosed"
    with pytest.raises(CatalogError, match=r"app\.yml"): load_catalog(tmp_path)

def test_load_rejects_id_folder_mismatch(tmp_path):   # folder "a", id "b"
    with pytest.raises(CatalogError, match="does not match folder"): ...

def test_load_rejects_duplicate_port(tmp_path):  # two apps, port 7900
    with pytest.raises(CatalogError, match="port 7900"): ...

def test_load_rejects_missing_field(tmp_path):   # no internal_port
    with pytest.raises(CatalogError, match="internal_port"): ...

def test_load_rejects_bad_llm_value(tmp_path):   # llm: {OPENAI_API_KEY: "secret"}
    with pytest.raises(CatalogError, match="gateway_url, gateway_key or alias:"): ...
```

Validation rules: required `id, name, replaces, description, repo, port, internal_port`; id matches `^[a-z0-9][a-z0-9-]*$` and equals the folder name; ports are ints 1–65535 and `port` is unique across the catalog; `path` starts with `/`; each `llm` value is `gateway_url`, `gateway_key` or `alias:<name>`.

- [ ] **Step 4: Run, verify FAIL** — `uv run pytest tests/test_catalog.py -v` → import error.

- [ ] **Step 5: Implement `App`, `CatalogError`, `load_catalog` in `backend/catalog.py`.**

- [ ] **Step 6: Run, verify PASS** — `uv run pytest tests/test_catalog.py -v`.

- [ ] **Step 7: Write failing lint tests in `tests/test_catalog_lint.py`**

```python
@pytest.mark.parametrize("app", load_catalog(Path("catalog")).values(), ids=lambda a: a.id)
def test_catalog_entry_is_clean(app):
    assert lint_compose(app) == []

# each below writes one compose file into tmp_path and asserts the problem string appears
def test_lint_port_not_localhost(...):       # "7800:80"            -> "must bind 127.0.0.1"
def test_lint_missing_network(...):          # service without mos-net -> "mos-net"
def test_lint_network_not_external(...):     # mos-net without external -> "external"
def test_lint_host_bind_mount(...):          # "./data:/data"       -> "host bind mount"
def test_lint_socket_needs_warning(...):     # docker.sock, warnings=[] -> "warnings"
def test_lint_socket_allowed_with_warning(...)  # same with warnings=["x"] -> []
def test_lint_gpu_app_without_gpu(...):      # gpu: true, no GPU_DEVICE -> "GPU"
def test_lint_main_service_named_id(...):    # service "web" in app "a" -> "service named 'a'"
def test_lint_shared_volume_must_be_external(...):  # top-level volume mos-models without external -> "mos-models"
```

Lint rules (spec §5, plus deviations): every service joins `mos-net`; top-level `mos-net` has `external: true`; every `ports` entry starts with `127.0.0.1:`; a volume entry whose source starts with `.`, `/` or contains `\` is a host bind mount — only `/var/run/docker.sock` is allowed, and only when `app.warnings` is non-empty; `gpu: true` apps have at least one service using `GPU_DEVICE`; a service named `app.id` exists; every top-level volume whose name starts with `mos-` has `external: true`.

- [ ] **Step 8: Run, verify FAIL**, then **implement `lint_compose` and `GPU_DEVICE`**, then **run `uv run pytest -v`, verify all PASS.**

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock .gitignore backend catalog tests/test_catalog.py tests/test_catalog_lint.py
git commit -m "feat: catalog loader and compose lint"
```

---

### Task 3: Compose wrapper

**Files:**
- Create: `backend/compose.py`
- Test: `tests/test_compose.py`

**Interfaces:**
- Consumes: `App` (Task 2).
- Produces:
  - `class ComposeError(Exception)` — `.returncode: int`, message is the last 20 output lines.
  - `class Compose(runner: Callable[[list[str], dict[str, str] | None], tuple[int, str]] = run_subprocess, streamer: Callable[[list[str], dict[str, str] | None], Iterator[str]] = stream_subprocess)`
    - `cmd(app: App, *args: str) -> list[str]` → `["docker", "compose", "-p", f"mos-{app.id}", "-f", str(app.dir / "docker-compose.yml"), *args]`
    - `projects() -> dict[str, str]` — from `docker compose ls -a --format json`: `{"mos-hello": "running(1)"}`; only names starting `mos-`.
    - `runtime_ok() -> bool` — `docker info` exits 0.
    - `run(app: App, *args: str, env: dict[str, str] | None = None) -> str` — raises `ComposeError` on nonzero.
    - `stream(app: App, *args: str, env: dict[str, str] | None = None) -> Iterator[str]` — yields combined stdout/stderr lines; raises `ComposeError` after the last line if nonzero.
    - `logs(app: App, lines: int = 50) -> str` — `logs --no-color --tail <lines>`.
  - `run_subprocess` / `stream_subprocess`: real implementations; `env` is merged over `os.environ`; `run_subprocess` timeout 120 s.

- [ ] **Step 1: Write failing tests** using a fake runner that records commands and returns canned `(code, output)`:

```python
def test_cmd_uses_project_and_file(): assert Compose().cmd(hello, "up", "-d") == ["docker","compose","-p","mos-hello","-f",str(Path("catalog/hello/docker-compose.yml")),"up","-d"]
def test_projects_parses_ls_json():   # output '[{"Name":"mos-hello","Status":"running(1)"},{"Name":"other","Status":"exited(1)"}]'
    assert c.projects() == {"mos-hello": "running(1)"}
def test_projects_empty_output():      # output "" -> {}
def test_runtime_ok_false_on_error():  # code 1 -> False
def test_run_raises_with_tail():       # code 2, 30 lines -> ComposeError, returncode 2, message has line 30 not line 1
def test_stream_raises_after_lines():  # fake streamer yields "a","b" then signals code 1 -> collected ["a","b"] then ComposeError
def test_logs_tail():                  # cmd ends with ["logs","--no-color","--tail","50"]
```

For the streamer contract: `stream_subprocess` yields lines and finally raises `ComposeError` itself on nonzero exit; the fake streamer mimics that.

- [ ] **Step 2: Run, verify FAIL** — `uv run pytest tests/test_compose.py -v`.
- [ ] **Step 3: Implement `backend/compose.py`.** `stream_subprocess` uses `subprocess.Popen(..., stdout=PIPE, stderr=STDOUT, text=True, bufsize=1)`.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: docker compose wrapper"` (add `backend/compose.py tests/test_compose.py`).

---

### Task 4: GPU rule and status derivation

**Files:**
- Create: `backend/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: `App`.
- Produces:
  - `gpu_conflicts(target: App, apps: dict[str, App], running: set[str]) -> list[str]` — sorted ids of *other* `gpu: true` apps in `running`; `[]` if `target.gpu` is false.
  - `START_TIMEOUT = 180`
  - `derive_status(project_status: str | None, probe_ok: bool, started_at: float | None, now: float) -> str`

- [ ] **Step 1: Write failing tests**

```python
def test_gpu_conflicts_lists_other_running_gpu_apps():  # target comfyui(gpu), running {"sd","hello","comfyui"}, sd gpu, hello not
    assert gpu_conflicts(comfy, apps, {"sd","hello","comfyui"}) == ["sd"]
def test_gpu_conflicts_empty_for_non_gpu_target(): assert gpu_conflicts(hello, apps, {"sd"}) == []
def test_no_project_is_not_installed():   assert derive_status(None, False, None, 0) == "not_installed"
def test_exited_is_stopped():             assert derive_status("exited(1)", False, None, 0) == "stopped"
def test_running_and_probed():            assert derive_status("running(1)", True, 0, 500) == "running"
def test_running_unprobed_is_starting():  assert derive_status("running(1)", False, 100, 279) == "starting"
def test_running_unprobed_after_timeout_is_error(): assert derive_status("running(1)", False, 100, 281) == "error"
def test_partially_running_uses_probe():  assert derive_status("running(1), exited(1)", True, 0, 1) == "running"
def test_unprobed_without_started_at_is_starting(): assert derive_status("running(1)", False, None, 999) == "starting"
```

- [ ] **Step 2: Run, verify FAIL.** `uv run pytest tests/test_rules.py -v`
- [ ] **Step 3: Implement `backend/rules.py`.** "running" anywhere in `project_status` means the probe decides; anything else non-None is `stopped`.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: GPU exclusivity and status rules"`.

---

### Task 5: Background jobs

**Files:**
- Create: `backend/jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Produces:
  - `@dataclass class Job: app_id: str; kind: str; state: str = "running"; log: list[str]` — `state` ∈ `running | done | error`.
  - `class JobBusy(Exception)`
  - `class JobManager`: `start(app_id: str, kind: str, work: Callable[[Callable[[str], None]], None]) -> Job` runs `work(log)` in a daemon thread; on return → `done`; on exception → appends `str(exc)` to log, `error`. Raises `JobBusy` if that app has a `running` job. `get(app_id: str) -> Job | None` returns the latest job for the app. Uses one `threading.Lock` around the busy check + registration.

- [ ] **Step 1: Write failing tests**

```python
def test_job_completes():               # work logs "a","b" -> eventually state "done", log ["a","b"]
def test_job_error_keeps_log():         # work logs "a" then raises RuntimeError("boom") -> "error", log ["a","boom"]
def test_second_start_while_running_raises_busy():  # work waits on threading.Event; second start -> JobBusy; set event
def test_new_job_after_done_allowed():  # first done -> second start ok, get() returns second
```
Wait for completion with a small poll helper (`until(lambda: job.state != "running", timeout=2)`).

- [ ] **Step 2: Run, verify FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: per-app background jobs"`.

---

### Task 6: HTTP API

**Files:**
- Create: `backend/api.py`, `backend/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `load_catalog`, `App` (Task 2); `Compose`, `ComposeError` (Task 3); `gpu_conflicts`, `derive_status` (Task 4); `JobManager`, `JobBusy` (Task 5).
- Produces:
  - `RUNTIME_DOWN_MSG = "Podman isn't running — run `podman machine start`"`
  - `create_app(apps: dict[str, App], compose: Compose, probe: Callable[[App], bool], clock: Callable[[], float] = time.time, show_dev: bool = False) -> FastAPI`
  - `probe(app: App) -> bool` in `api.py` — `httpx.get(f"http://{app.id}:{app.internal_port}{app.path}", timeout=1)`; any HTTP response is `True`, any exception `False`.
  - `backend/main.py`: `app = create_app(load_catalog(Path(os.environ.get("MOS_CATALOG", "catalog"))), Compose(), probe, show_dev=os.environ.get("MOS_DEV") == "1")`, then mounts `frontend/dist` at `/` with `StaticFiles(html=True)` if that directory exists.
  - Endpoints (all return JSON; unknown id → 404; runtime down → 503 `{"detail": RUNTIME_DOWN_MSG}` on every `/api/apps*` route):

| Method & path | Behaviour | Response |
|---|---|---|
| `GET /api/health` | `compose.runtime_ok()` | `{"runtime": bool}` |
| `GET /api/apps` | non-dev apps (all if `show_dev`), status via `derive_status`; probe only apps whose project status contains `running`; record `started_at[id] = now` the first time an app is seen running-but-unprobed, clear it when probed or not running | `[{"id","name","replaces","description","gpu","size_gb","warnings","status","url","job"}]` — `url` = `http://localhost:{port}{path}`, `job` = `{"kind","state"}` or `null` |
| `POST /api/apps/{id}/install` | job `install`: `stream(app, "up", "-d", "--build")` | 202 `{"kind","state"}`; 409 `{"detail": "A job is already running for {id}"}` |
| `POST /api/apps/{id}/update` | job `update`: `stream(app, "pull", "--ignore-buildable")` then `stream(app, "up", "-d", "--build")` | as install |
| `POST /api/apps/{id}/start?confirm=false` | conflicts = `gpu_conflicts(app, apps, running ids)`; if conflicts and not confirm → 409 `{"detail": {"conflicts": [...]}}`; else `run(c, "stop")` for each conflict, then `run(app, "up", "-d")`, set `started_at[id] = now` | `{"stopped": [...]}` |
| `POST /api/apps/{id}/stop` | `run(app, "stop")` | `{}` |
| `DELETE /api/apps/{id}?delete_data=false` | `run(app, "down")`, plus `"-v"` only when `delete_data=true` | `{}` |
| `GET /api/apps/{id}/job` | latest job | `{"kind","state","log"}`; 404 if none |
| `GET /api/apps/{id}/logs?lines=50` | `compose.logs(app, lines)` | `{"logs": str}` |
| `GET /api/apps/{id}/icon` | `FileResponse(app.dir / "icon.png")` | 404 if missing |

`ComposeError` from synchronous endpoints → 500 `{"detail": str(error)}`.

- [ ] **Step 1: Write failing tests** with FastAPI `TestClient`, a `FakeCompose` (records commands; configurable `projects()` result, `runtime_ok()`, and `stream` that yields `["ok"]`), a probe dict `{id: bool}`, and a mutable clock. Catalog fixture: `hello` (dev), `sd` (gpu, port 7801), `comfy` (gpu, port 7802).

```python
def test_apps_hides_dev_by_default():            assert [a["id"] for a in get_apps()] == ["comfy","sd"]  # sorted by name
def test_apps_shows_dev_when_enabled():          # show_dev=True -> includes "hello"
def test_apps_503_when_runtime_down():           # runtime_ok False -> 503, detail == RUNTIME_DOWN_MSG
def test_apps_status_and_url():                  # projects {"mos-sd": "running(1)"}, probe sd True -> sd "running", url "http://localhost:7801/"; comfy "not_installed"
def test_started_at_recorded_for_unprobed_app(): # sd running, probe False; GET at t=0 -> "starting"; GET at t=181 -> "error"
def test_install_runs_up_build():                # POST install -> 202; job finishes; recorded cmd ends with ["up","-d","--build"]
def test_install_twice_returns_409():            # stream blocks on Event; second POST -> 409
def test_start_gpu_conflict_needs_confirm():     # sd running; POST comfy/start -> 409 {"detail": {"conflicts": ["sd"]}}; no "up" recorded
def test_start_gpu_conflict_confirmed_stops_others(): # ?confirm=true -> {"stopped": ["sd"]}; cmds: sd "stop" before comfy "up","-d"
def test_uninstall_keeps_data_by_default():      # DELETE -> cmd ends with ["down"]
def test_uninstall_delete_data():                # ?delete_data=true -> ["down","-v"]
def test_unknown_app_404():                      # POST /api/apps/nope/start -> 404
def test_logs_default_50():                      # GET logs -> compose.logs called with 50
```

- [ ] **Step 2: Run, verify FAIL.** `uv run pytest tests/test_api.py -v`
- [ ] **Step 3: Implement `backend/api.py` and `backend/main.py`.** Keep `started_at` as a dict inside `create_app`'s closure.
- [ ] **Step 4: Run full suite, verify PASS.** `uv run pytest -v`
- [ ] **Step 5: Commit** — `git commit -m "feat: app lifecycle HTTP API"`.

---

### Task 7: Container image, root compose and end-to-end smoke test

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `README.md`
- Test: `tests/e2e/test_smoke.py`

**Interfaces:**
- Consumes: `backend.main:app` (Task 6); frontend build output `frontend/dist` (Task 8 — until then the stage builds nothing; see Step 1).

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM docker.io/library/node:22-alpine AS ui
WORKDIR /ui
COPY frontend/ ./
RUN if [ -f package.json ]; then npm ci && npm run build; else mkdir -p dist; fi

FROM docker.io/library/python:3.12-slim
COPY --from=docker.io/library/docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker.io/docker/compose-bin:v2.29.7 /docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
WORKDIR /app
COPY pyproject.toml ./
COPY backend/ backend/
RUN pip install --no-cache-dir .
COPY catalog/ catalog/
COPY --from=ui /ui/dist frontend/dist
EXPOSE 8080
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
```
Create an empty `frontend/.gitkeep` so `COPY frontend/` works before Task 8. `.dockerignore`: `.venv`, `**/node_modules`, `frontend/dist`, `.git`.

- [ ] **Step 2: Write root `docker-compose.yml`**

```yaml
name: myopensuite
services:
  myopensuite:
    build: .
    image: localhost/myopensuite:dev
    ports: ["127.0.0.1:8080:8080"]
    volumes: ["/run/podman/podman.sock:/var/run/docker.sock"]
    security_opt: ["label=disable"]
    environment:
      MOS_DEV: "${MOS_DEV:-0}"
    networks: [mos-net]
networks:
  mos-net:
    name: mos-net
```

- [ ] **Step 3: Build and run**

Run: `$env:MOS_DEV='1'; podman compose up -d --build`
Then: `curl.exe -s http://localhost:8080/api/health`
Expected: `{"runtime":true}`. If `false`, check the socket mount with `podman compose exec myopensuite docker info` and fix before continuing.

- [ ] **Step 4: Write `tests/e2e/test_smoke.py`** — skipped unless `MOS_E2E=1`; talks to `http://localhost:8080` with httpx; each wait polls every 2 s up to 300 s.

```python
def test_hello_lifecycle():
    # precondition: hello is not_installed (DELETE first if needed)
    post("/api/apps/hello/install") -> 202; wait job state == "done"
    wait status("hello") == "running"
    assert httpx.get("http://localhost:7800/").status_code == 200
    post("/api/apps/hello/stop");   wait status == "stopped"
    post("/api/apps/hello/start");  wait status == "running"
    delete("/api/apps/hello");      wait status == "not_installed"
```

- [ ] **Step 5: Run e2e, verify PASS**

Run: `$env:MOS_E2E='1'; uv run pytest tests/e2e -v`
Expected: `test_hello_lifecycle PASSED`.

- [ ] **Step 6: Write `README.md`** — prerequisites (Podman machine rootful, disk on E:, `docs/podman-gpu.md`), `podman compose up -d --build`, open `http://localhost:8080`, `MOS_DEV=1` to show the `hello` app, how to run unit tests (`uv run pytest`) and e2e (`MOS_E2E=1`).

- [ ] **Step 7: Commit** — `git commit -m "feat: container image and e2e smoke test"` (add `Dockerfile docker-compose.yml .dockerignore README.md frontend/.gitkeep tests/e2e`).

---

### Task 8: Marketplace UI

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`
- Create: `frontend/src/main.tsx`, `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/Tile.tsx`, `frontend/src/JobLog.tsx`, `frontend/src/styles.css`
- Delete: `frontend/.gitkeep`

**Interfaces:**
- Consumes: the Task 6 endpoint table, exactly.
- Produces: `frontend/dist` (built by the Dockerfile `ui` stage).

- [ ] **Step 1: Scaffold** — `npm create vite@latest frontend -- --template react-ts` in a scratch dir, copy only the files listed above, remove demo assets. `vite.config.ts` proxies `/api` to `http://localhost:8080`.

- [ ] **Step 2: `src/api.ts`** — typed wrappers for every Task 6 endpoint. `AppInfo` type mirrors the `GET /api/apps` item. A 503 throws `RuntimeDown` (message from `detail`); a failed `fetch` (backend unreachable) throws `Unreachable` with message `Can't reach MyOpenSuite — is the container running?`; a 409 on start returns `{conflicts: string[]}` to the caller.

- [ ] **Step 3: `App.tsx` + `Tile.tsx`** — behaviour:
  - Polls `GET /api/apps` every 3 s. On `RuntimeDown` or `Unreachable`, shows a full-width banner with the error's message and keeps polling; the banner clears on the next successful poll.
  - Header "MyOpenSuite", tabs **Dashboard** (installed apps only) and **Marketplace** (all apps). The LLM Gateway tab is out of scope for this plan.
  - Responsive CSS grid of tiles: icon (`/api/apps/{id}/icon`, falls back to the first letter on error), name, "Replaces {replaces}", status pill, GPU badge, a warning badge per `warnings` entry.
  - Buttons by status: `not_installed` → Install (label shows `~{size_gb} GB`); `stopped` → Start, Update, Uninstall; `starting` → disabled "Starting…"; `running` → Open (new tab to `url`), Stop, Update, Uninstall; `error` → Logs, Start, Uninstall. Any app with `job.state == "running"` shows "Installing…"/"Updating…" and a View log button instead.
  - Start: on 409 conflicts, `window.confirm("This will stop {names}. Continue?")` → retry with `confirm=true`.
  - Uninstall: a native `<dialog>` with an unticked "Also delete data" checkbox → `DELETE ?delete_data=`.

- [ ] **Step 4: `JobLog.tsx`** — native `<dialog>` that polls `GET /api/apps/{id}/job` every 1 s while `state == "running"`, shows the log in a `<pre>` scrolled to the bottom, and a Retry button when `state == "error"`. The Logs button (error status) uses the same dialog with `GET /api/apps/{id}/logs`.

- [ ] **Step 5: Type-check and build** — `cd frontend; npm install; npm run build` → `dist/index.html` exists, no TypeScript errors.

- [ ] **Step 6: Rebuild the container and verify in a browser**

Run: `$env:MOS_DEV='1'; podman compose up -d --build`, open `http://localhost:8080`.
Check by hand: Hello tile in Marketplace → Install → log dialog streams → status Running → Open shows the nginx page → Stop → Uninstall dialog (box unticked) → tile back to Install. Then `podman machine stop` (this also stops the dashboard container, so the browser sees network errors, not a 503) → "Can't reach MyOpenSuite" banner within 3 s; `podman machine start` then `podman compose up -d` → banner clears. The 503 runtime-down banner is covered by `test_apps_503_when_runtime_down`.
Rerun `MOS_E2E=1 uv run pytest tests/e2e -v` → PASS.

- [ ] **Step 7: Commit** — `git add frontend; git rm frontend/.gitkeep; git commit -m "feat: marketplace UI"`.
