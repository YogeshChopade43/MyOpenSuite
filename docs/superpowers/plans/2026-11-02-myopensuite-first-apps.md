# MyOpenSuite First Apps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** next-ai-draw-io, VoiceStudio and ComfyUI install, run and open from the dashboard, with per-app generated secrets and the GPU rule proven on real GPU apps.

**Architecture:** Each app is a catalog folder (`app.yml` + `docker-compose.yml` + `icon.png`) following spec §5. A new secret store generates per-app secrets once, persists them in the `mos-state` volume, and injects them as environment into every compose call for that app; the dashboard shows them in a Credentials dialog. Job hardening from the core review lands first because real installs are long.

**Tech Stack:** as the core plan (FastAPI, docker compose CLI on Podman, React + Vite). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-02-myopensuite-design.md` — milestone 3 (§3 rows voicestudio, comfyui, next-ai-draw-io; §5; §6). Core plan: `docs/superpowers/plans/2026-11-02-myopensuite-core.md` (already merged).

**Spec additions and deviations (decided here):**
- **Per-app secrets (addition).** VoiceStudio refuses to start without `OMNIVOICE_API_KEY`, and its web UI asks for that key. `app.yml` gains `secrets: {VAR: description}`. Values are generated once (`secrets.token_urlsafe(32)`), stored in `/data/secrets.json` on the new `mos-state` volume, injected into every compose call for that app, and shown in the dashboard's Credentials dialog.
- **ComfyUI keeps its own model volume** instead of the shared `mos-models` volume (spec §5). sd-webui uses a different model folder layout; sharing is decided when sd-webui is added (milestone 6). Cost: models downloaded twice if both apps are used.
- **No LLM injection yet.** next-ai-draw-io gets no `llm:` block; users set an AI provider in the app's own Settings until the gateway plan (milestone 4) adds injection.
- **Host ports:** hello 7800, voicestudio 7801, comfyui 7802, next-ai-draw-io 7803.

## Global Constraints

- All core-plan Global Constraints still hold (localhost binds, `mos-<id>` projects, `mos-net`, named volumes only, statuses, runtime-down message, 180 s, `uv run pytest`).
- Mutating API calls need header `X-MOS: 1`; only Host `localhost`/`127.0.0.1` is accepted.
- GPU form is CDI: `devices: ["nvidia.com/gpu=all"]` (see `docs/podman-gpu.md`). Never `deploy.resources`.
- No `container_name:` in any catalog compose file (it breaks `mos-<id>` project isolation).
- Secrets are never logged and never included in `GET /api/apps`.

## Review Focus

1. **Backend restarts or the container is rebuilt** → secrets survive (same value after `podman compose up -d --build`), so VoiceStudio's key never silently changes. Test: `test_secret_persists_across_instances` (Task 1) and e2e `test_secret_survives_rebuild` step (Task 3).
2. **secrets.json missing, empty or corrupt** → regenerated without crashing the API; a corrupt file is not silently overwritten without a backup. Test: `test_corrupt_store_is_backed_up` (Task 1).
3. **User clicks Uninstall while an install is still running** (second tab, or MCP later) → 409, no `down` racing `up`. Test: `test_mutation_during_job_returns_409` (Task 2).
4. **Huge install log** (multi-GB pulls) → the job log is capped so the 1 s poll stays small. Test: `test_job_log_is_capped` (Task 2).
5. **Starting VoiceStudio while ComfyUI runs** → asks first; on confirm, ComfyUI stops and VoiceStudio starts. Test: e2e `test_gpu_rule_between_real_apps` (Task 6).

---

### Task 1: Secret store and compose env hook

**Files:**
- Create: `backend/secrets_store.py`
- Modify: `backend/catalog.py` (field `secrets`, lint rule), `backend/compose.py` (env hook), `backend/api.py` (secrets endpoint, `has_secrets`), `backend/main.py` (wiring)
- Test: `tests/test_secrets_store.py`, `tests/test_catalog.py`, `tests/test_catalog_lint.py`, `tests/test_compose.py`, `tests/test_api.py`

**Interfaces:**
- Produces:
  - `App.secrets: dict[str, str]` (var → human description; default `{}`); loader rejects var names not matching `^[A-Z][A-Z0-9_]*$` with message containing `secrets`.
  - `lint_compose`: every secret var must appear in the compose file as `${VAR}` or `${VAR:` → problem string contains `secret VAR is not used`.
  - `class SecretStore(path: Path)`: `env_for(app: App) -> dict[str, str]` — returns all of the app's secrets, generating and persisting missing ones (`secrets.token_urlsafe(32)`); writes atomically (temp file + `os.replace`); one `threading.Lock`. If the file exists but is not valid JSON, renames it to `secrets.json.corrupt-<unix-ts>` and starts empty.
  - `Compose(runner=..., streamer=..., env_for: Callable[[App], dict[str, str]] = lambda app: {})` — `run`, `stream` and `logs` merge `env_for(app)` under any explicit `env` (explicit wins).
  - `GET /api/apps/{id}/secrets` → `[{"name": VAR, "description": str, "value": str}]` (empty list if none). `create_app` gains parameter `secrets: SecretStore`.
  - `GET /api/apps` items gain `"has_secrets": bool`.
  - `backend/main.py`: `store = SecretStore(Path(os.environ.get("MOS_STATE", "state")) / "secrets.json")`; `Compose(env_for=store.env_for)`; `create_app(..., secrets=store)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_secrets_store.py
def test_generates_and_persists(tmp_path):        # env_for(app with secrets {"K": "d"}) -> {"K": v}, len(v) >= 40; file contains v
def test_stable_across_calls(tmp_path):            # two env_for calls -> same value
def test_secret_persists_across_instances(tmp_path):  # new SecretStore(same path).env_for -> same value
def test_no_secrets_no_file(tmp_path):             # app without secrets -> {}; file not created
def test_corrupt_store_is_backed_up(tmp_path):     # file "{nope" -> env_for works; a secrets.json.corrupt-* file exists with "{nope"

# tests/test_catalog.py
def test_load_rejects_bad_secret_name(tmp_path):   # secrets: {"bad-name": "x"} -> CatalogError match "secrets"

# tests/test_catalog_lint.py
def test_lint_secret_not_used(tmp_path):            # App(secrets={"K": "d"}), GOOD compose -> "secret K is not used"
def test_lint_secret_used(tmp_path):                # compose service env "K: ${K}" -> []

# tests/test_compose.py
def test_env_hook_merged_into_run():                # Compose(runner=r, env_for=lambda a: {"K": "v"}).run(hello, "up") -> runner got env {"K": "v"}
def test_explicit_env_wins():                       # .run(hello, "up", env={"K": "x"}) -> env {"K": "x"}

# tests/test_api.py  (create_app now needs secrets=SecretStore(tmp_path / "s.json"); APPS["sd"] gets secrets={"SD_KEY": "Admin key"})
def test_secrets_endpoint(env):                     # GET /api/apps/sd/secrets -> [{"name":"SD_KEY","description":"Admin key","value": <non-empty>}]; second GET same value
def test_apps_never_include_secret_values(env):     # GET /api/apps text does not contain the SD_KEY value; sd has_secrets True, comfy False
```
The `FakeRunner` in `test_compose.py` must record `env` alongside `cmd`.

- [ ] **Step 2: Run, verify FAIL** — `uv run pytest -q` → new tests fail (import/attribute errors), existing pass.
- [ ] **Step 3: Implement** the Interfaces above. File mode: create the store file with `os.open(..., 0o600)` semantics via writing the temp file then `os.chmod(tmp, 0o600)` before `os.replace`.
- [ ] **Step 4: Run, verify PASS** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `git commit -m "feat: per-app generated secrets"`.

---

### Task 2: Job hardening

**Files:**
- Modify: `backend/jobs.py`, `backend/api.py`
- Test: `tests/test_jobs.py`, `tests/test_api.py`

**Interfaces:**
- Produces:
  - `MAX_LOG_LINES = 2000` in `jobs.py`; `Job.log` keeps only the last `MAX_LOG_LINES` lines (use `collections.deque(maxlen=MAX_LOG_LINES)`; `GET .../job` still returns a JSON list).
  - `start`, `stop`, `DELETE` and `update` return 409 `{"detail": "A job is already running for {id}"}` while that app has a running job (install already does).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_jobs.py
def test_job_log_is_capped():                 # work logs 2500 lines -> len(job.log) == 2000, last item "line 2499"

# tests/test_api.py
@pytest.mark.parametrize("method,path", [("post", "/api/apps/sd/start?confirm=true"), ("post", "/api/apps/sd/stop"), ("delete", "/api/apps/sd"), ("post", "/api/apps/sd/update")])
def test_mutation_during_job_returns_409(env, method, path):  # fake.gate set; POST install; then method/path -> 409; no extra commands recorded; release gate
```

- [ ] **Step 2: Run, verify FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run, verify PASS** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `git commit -m "fix: cap job logs and block mutations during jobs"`.

---

### Task 3: State volume, hello secret, Credentials dialog

**Files:**
- Modify: `docker-compose.yml` (root), `catalog/hello/app.yml`, `catalog/hello/docker-compose.yml`, `tests/e2e/test_smoke.py`
- Modify: `frontend/src/api.ts`, `frontend/src/Tile.tsx`
- Create: `frontend/src/Credentials.tsx`

**Interfaces:**
- Consumes: `GET /api/apps/{id}/secrets`, `has_secrets` (Task 1).
- Produces: root service `myopensuite` mounts named volume `mos-state` at `/data` and sets `MOS_STATE: /data`; top-level `volumes: { mos-state: { name: mos-state } }`.

- [ ] **Step 1: Give hello a secret** — `app.yml`: `secrets: { HELLO_TOKEN: "Test secret" }`; compose service `hello`: `environment: { HELLO_TOKEN: "${HELLO_TOKEN}" }`. Run `uv run pytest tests/test_catalog_lint.py -q` → PASS.

- [ ] **Step 2: Extend the e2e smoke test (write first)** — after hello is running:

```python
token = API.get("/api/apps/hello/secrets").json()[0]["value"]
assert token and token == API.get("/api/apps/hello/secrets").json()[0]["value"]
out = subprocess.run(["podman", "exec", "mos-hello-hello-1", "printenv", "HELLO_TOKEN"], capture_output=True, text=True).stdout.strip()
assert out == token
```
Add `def test_secret_survives_rebuild():` — read token, run `podman compose up -d --build` (cwd = repo root, `env MOS_DEV=1`), wait for `/api/health`, read token again → equal.

- [ ] **Step 3: Run e2e against the current image, verify FAIL** — `$env:MOS_E2E='1'; uv run pytest tests/e2e -v` → fails (no secrets endpoint in the running image).

- [ ] **Step 4: Root compose** — add the `mos-state` volume and `MOS_STATE` per Interfaces.

- [ ] **Step 5: UI** — `api.ts`: `AppInfo.has_secrets: boolean`; `getSecrets(id) -> {name, description, value}[]`. `Credentials.tsx`: native `<dialog>` listing each secret: description, value in a read-only monospace `<input>` (masked by default, a Show toggle), and a Copy button (`navigator.clipboard.writeText`, button text changes to "Copied" for 2 s). `Tile.tsx`: a ghost **Credentials** button whenever `has_secrets` and status is not `not_installed`.

- [ ] **Step 6: Rebuild and run e2e, verify PASS** — `$env:MOS_DEV='1'; podman compose up -d --build`; `$env:MOS_E2E='1'; uv run pytest tests/e2e -v` → all pass. Check in the browser: Hello tile → Credentials shows a masked value; Show reveals it; Copy works.

- [ ] **Step 7: Commit** — `git commit -m "feat: persistent state volume and credentials dialog"`.

---

### Task 4: next-ai-draw-io

**Files:**
- Create: `catalog/next-ai-draw-io/app.yml`, `catalog/next-ai-draw-io/docker-compose.yml`, `catalog/next-ai-draw-io/icon.png`, `catalog/next-ai-draw-io/NOTES.md`
- Create: `tests/e2e/test_apps.py`

**Interfaces:**
- Produces: `tests/e2e/test_apps.py` with helpers reused by Tasks 5–6: `install_and_wait(id, timeout=1800)`, `status(id)`, `wait(cond, what, timeout)`; module skipped unless `MOS_E2E_APPS=1` (real downloads). Uses `X-MOS: 1`.

- [ ] **Step 1: Write the e2e test (first)**

```python
def test_next_ai_draw_io():
    install_and_wait("next-ai-draw-io")          # install -> job done -> status running
    r = httpx.get("http://localhost:7803/")
    assert r.status_code == 200 and "draw" in r.text.lower()
```

- [ ] **Step 2: Run, verify FAIL** — `$env:MOS_E2E_APPS='1'; uv run pytest tests/e2e/test_apps.py -v` → fails: app not in catalog (404).

- [ ] **Step 3: Catalog entry**

`app.yml`: `id: next-ai-draw-io`, `name: Next AI Draw.io`, `replaces: Napkin.ai / Lucid AI`, `description: Describe a diagram in words and get an editable draw.io diagram. Set your AI provider in the app's Settings.`, `repo: https://github.com/DayuanJiang/next-ai-draw-io`, `port: 7803`, `internal_port: 3000`, `size_gb: 1`.
Compose: service `next-ai-draw-io`, image `ghcr.io/dayuanjiang/next-ai-draw-io:latest`, ports `["127.0.0.1:7803:3000"]`, volume `drawio-data:/app/data`, network `mos-net`, `restart: unless-stopped`; top-level `drawio-data: {}` and external `mos-net`.
`icon.png`: the repo's app icon (look under `public/` for a PNG favicon/logo, ≥ 64 px); if none exists, omit the file (letter fallback).
`NOTES.md`: how to set an AI provider in the app until the gateway lands; manual check = "open the app, ask for a flowchart, diagram appears".

- [ ] **Step 4: Lint, rebuild, run e2e, verify PASS** — `uv run pytest -q`; `$env:MOS_DEV='1'; podman compose up -d --build`; `$env:MOS_E2E_APPS='1'; uv run pytest tests/e2e/test_apps.py -v -k draw`.
- [ ] **Step 5: Commit** — `git commit -m "feat: next-ai-draw-io catalog entry"`.

---

### Task 5: VoiceStudio

**Files:**
- Create: `catalog/voicestudio/app.yml`, `catalog/voicestudio/docker-compose.yml`, `catalog/voicestudio/icon.png`, `catalog/voicestudio/NOTES.md`
- Modify: `tests/e2e/test_apps.py`

- [ ] **Step 1: Write the e2e test (first)**

```python
def test_voicestudio():
    install_and_wait("voicestudio")               # GPU app: install leaves it stopped
    assert status("voicestudio") == "stopped"
    API.post("/api/apps/voicestudio/start?confirm=true").raise_for_status()
    wait(lambda: status("voicestudio") == "running", "voicestudio running", timeout=900)
    assert httpx.get("http://localhost:7801/health").status_code == 200
    gpu = subprocess.run(["podman", "exec", "mos-voicestudio-voicestudio-1", "nvidia-smi", "-L"], capture_output=True, text=True)
    assert "RTX 4050" in gpu.stdout
    key = API.get("/api/apps/voicestudio/secrets").json()[0]
    assert key["name"] == "OMNIVOICE_API_KEY" and key["value"]
```
`install_and_wait` for GPU apps waits for job `done` and status `stopped` (not `running`).

- [ ] **Step 2: Run, verify FAIL** (404, not in catalog).

- [ ] **Step 3: Catalog entry**

`app.yml`: `id: voicestudio`, `name: VoiceStudio`, `replaces: ElevenLabs`, `description: Voice cloning, text-to-speech, dictation and dubbing. First start downloads about 4 GB of models.`, `repo: https://github.com/debpalash/VoiceStudio`, `port: 7801`, `internal_port: 3900`, `gpu: true`, `size_gb: 14`, `secrets: { OMNIVOICE_API_KEY: "Admin key — VoiceStudio asks for it when you open it" }`.
Compose: service `voicestudio`, image `ghcr.io/debpalash/voicestudio:stable`, ports `["127.0.0.1:7801:3900"]`, `devices: ["nvidia.com/gpu=all"]`, volume `voicestudio-data:/app/omnivoice_data`, environment (copied from upstream `deploy/docker-compose.yml` GPU service): `HF_HOME=/app/omnivoice_data/huggingface`, `OMNIVOICE_DATA_DIR=/app/omnivoice_data`, `PYTHONPATH=/app/backend`, `PYTHONUNBUFFERED=1`, `OMNIVOICE_SERVER_MODE=1`, `OMNIVOICE_ANALYTICS_DISABLED=1`, `OMNIVOICE_API_KEY=${OMNIVOICE_API_KEY}`; `restart: unless-stopped`; network `mos-net`. No `container_name`, no `deploy:`.
`icon.png`: from the repo (e.g. `frontend/public` or `.github/assets`), or omit.
`NOTES.md`: open → paste the key from Credentials; manual check = clone a voice from a 10 s sample and speak a sentence.

- [ ] **Step 4: Lint, rebuild, run e2e, verify PASS** — `uv run pytest -q`; rebuild; `uv run pytest tests/e2e/test_apps.py -v -k voicestudio` (allow ~30 min for first pull + model download).
- [ ] **Step 5: Commit** — `git commit -m "feat: VoiceStudio catalog entry"`.

---

### Task 6: ComfyUI and the GPU rule on real apps

**Files:**
- Create: `catalog/comfyui/app.yml`, `catalog/comfyui/docker-compose.yml`, `catalog/comfyui/icon.png`, `catalog/comfyui/NOTES.md`
- Modify: `tests/e2e/test_apps.py`, `README.md`

- [ ] **Step 1: Write the e2e tests (first)**

```python
def test_comfyui():
    install_and_wait("comfyui")                    # GPU: ends stopped
    API.post("/api/apps/comfyui/start?confirm=true").raise_for_status()
    wait(lambda: status("comfyui") == "running", "comfyui running", timeout=600)
    assert httpx.get("http://localhost:7802/system_stats").json()["devices"][0]["type"] == "cuda"

def test_gpu_rule_between_real_apps():             # runs after test_comfyui (comfyui running, voicestudio installed)
    r = API.post("/api/apps/voicestudio/start")
    assert r.status_code == 409 and r.json()["detail"] == {"conflicts": ["comfyui"]}
    assert API.post("/api/apps/voicestudio/start?confirm=true").json() == {"stopped": ["comfyui"]}
    wait(lambda: status("comfyui") == "stopped", "comfyui stopped")
    wait(lambda: status("voicestudio") == "running", "voicestudio running", timeout=900)
```

- [ ] **Step 2: Run, verify FAIL** (404, not in catalog).

- [ ] **Step 3: Catalog entry**

`app.yml`: `id: comfyui`, `name: ComfyUI`, `replaces: Midjourney / Runway`, `description: Node-based image and video generation. Download models from the Manager menu inside ComfyUI.`, `repo: https://github.com/Comfy-Org/ComfyUI`, `port: 7802`, `internal_port: 8188`, `gpu: true`, `size_gb: 12`.
Compose: service `comfyui`, image `docker.io/yanwk/comfyui-boot:cu130-slim-v2`, ports `["127.0.0.1:7802:8188"]`, `devices: ["nvidia.com/gpu=all"]`, `security_opt: ["label=disable"]`, `environment: { CLI_ARGS: "--fast" }`, `restart: unless-stopped`, network `mos-net`, named volumes (all top-level `{}`): `comfyui-cache:/root/.cache`, `comfyui-config:/root/.config`, `comfyui-local:/root/.local`, `comfyui-nodes:/root/ComfyUI/custom_nodes`, `comfyui-models:/root/ComfyUI/models`, `comfyui-input:/root/ComfyUI/input`, `comfyui-output:/root/ComfyUI/output`, `comfyui-user:/root/ComfyUI/user`.
`icon.png`: from the ComfyUI repo or Comfy-Org assets, or omit.
`NOTES.md`: first model (e.g. an SDXL or SD1.5 checkpoint via Manager → Model Manager); 6 GB VRAM guidance (SD1.5/SDXL fine, Flux needs GGUF/quantised); manual check = default workflow renders an image.

- [ ] **Step 4: Lint, rebuild, run e2e, verify PASS** — `uv run pytest -q`; rebuild; `$env:MOS_E2E_APPS='1'; uv run pytest tests/e2e/test_apps.py -v` (all four tests, in file order).

- [ ] **Step 5: README** — add an "Apps" table (name, replaces, port, GPU, notes link) and the `MOS_E2E_APPS=1` test command (warns: downloads ~25 GB).

- [ ] **Step 6: Browser check** — Marketplace shows three real tiles with icons (or letters); VoiceStudio → Credentials → copy key → Open → paste key → UI loads; ComfyUI → Open → UI loads.

- [ ] **Step 7: Commit** — `git commit -m "feat: ComfyUI catalog entry and GPU rule e2e"`.
