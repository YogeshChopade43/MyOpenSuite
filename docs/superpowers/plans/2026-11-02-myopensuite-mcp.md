# MyOpenSuite MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code / Claude Desktop (on the owner's Claude Pro plan) can list, install, start and stop MyOpenSuite apps and drive VoiceStudio and ComfyUI through one MCP endpoint at `http://localhost:8080/mcp`.

**Architecture:** App lifecycle logic moves out of `api.py`'s closures into a `Suite` class shared by the HTTP API and a new MCP server (MCP Python SDK 2.x `MCPServer`, streamable HTTP, mounted in the same FastAPI app). App-specific MCP actions live next to each app in `catalog/<id>/mcp.py` and get a small context object (ensure the app is running, read its secrets, save outputs). Outputs are saved under `/data/outputs` and served at `/files/…`.

**Tech Stack:** as before, plus `mcp==2.3.0` (`from mcp.server.mcpserver import MCPServer, Image`).

**Spec:** `docs/superpowers/specs/2026-11-02-myopensuite-design.md` §8 (milestone 5). The LLM gateway (milestone 4) is deferred by the owner — see `docs/superpowers/plans/2026-11-02-myopensuite-gateway.md`.

**Spec deviations (decided here):**
- **Draw.io uses its upstream MCP server** (`@next-ai-drawio/mcp-server`: live canvas, reads hand edits back, works offline). No wrapper; the README tells the owner how to add it. Cost: one more MCP entry in the client.
- **ComfyUI exposes `comfy_list_checkpoints` + `comfy_txt2img`** (a built-in text-to-image graph) instead of `comfy_list_workflows`/`comfy_run(workflow)`. Saved-workflow support can follow once the owner has workflows worth exposing.
- **sd-webui and open-notebook actions** move to milestone 6, with those apps.
- **Outputs live in `/data/outputs` on `mos-state`**, not a separate `mos-outputs` volume (no other container needs them).
- **`start_app` over MCP stops conflicting GPU apps without asking** — the tool call is the owner's instruction — and reports what it stopped.
- **`/mcp` is exempt from the `X-MOS` header** (MCP clients cannot add it). It stays protected by the allowed-clients check, `TrustedHostMiddleware`, and MCP's JSON content type (forces a CORS preflight from browsers).

## Global Constraints

- All earlier Global Constraints hold (localhost binds; allowed clients = gateway IP + 127.0.0.1; `X-MOS: 1` on non-MCP mutations; CDI GPU; secrets never in `GET /api/apps` and never in MCP tool output or logs).
- MCP endpoint, exactly: `http://localhost:8080/mcp` (streamable HTTP, POST without redirect).
- `uninstall_app` over MCP never deletes data (`down --rmi all`, no `-v`).
- Tool errors are returned as plain text that tells Claude the next step (e.g. `"comfyui is not installed — call install_app('comfyui')"`), never a stack trace.
- Long actions wait at most 600 s.
- VoiceStudio calls use `Authorization: Bearer <OMNIVOICE_API_KEY>` (traffic over `mos-net` is non-loopback, so the key is required).

## Review Focus

1. **VoiceStudio's model licence not yet accepted** (true on this machine today: `model_licence_required`) → `voice_speak` returns "Accept the model licence in VoiceStudio → Model Catalogue, then try again", not a raw 403 body. Test: `test_voice_speak_licence_message` (Task 4).
2. **ComfyUI has no checkpoint installed** (true today) → `comfy_txt2img` returns "No checkpoints installed — open ComfyUI → Manager → Model Manager and install one". Test: `test_comfy_no_checkpoints_message` (Task 5).
3. **Claude asks for an image while VoiceStudio holds the GPU** → ComfyUI is started, VoiceStudio stopped, and the reply says so. Test: `test_ensure_running_stops_gpu_conflict` (Task 1).
4. **Output file names from user text** (e.g. a voice called `../../etc`) → names are generated server-side; `/files/` refuses paths outside the outputs folder. Test: `test_files_rejects_traversal` (Task 2).
5. **App never becomes healthy while an action waits** → the action returns "still starting after N s — check app_logs('id')" instead of hanging. Test: `test_ensure_running_times_out` (Task 1).

---

### Task 1: Extract `Suite` from the API

**Files:**
- Create: `backend/suite.py`
- Modify: `backend/api.py`, `backend/main.py`
- Test: `tests/test_suite.py` (new), `tests/test_api.py` (must pass unchanged)

**Interfaces:**
- Produces:
  - `class SuiteError(Exception)`: `.status: int`, `.detail: str | dict`. Subclasses: `NotFound` (404), `Busy` (409, detail `"A job is already running for {id}"`), `Conflict` (409, detail `{"conflicts": [...]}`), `RuntimeDown` (503, detail `RUNTIME_DOWN_MSG`).
  - `RUNTIME_DOWN_MSG` moves to `suite.py` (re-exported from `api.py` for existing imports).
  - `class Suite(apps, compose, probe, clock=time.time, secrets=None)` with methods returning plain data:
    - `get(app_id) -> App` (raises `NotFound`)
    - `check_runtime() -> None` (raises `RuntimeDown`)
    - `list_apps(show_dev: bool) -> list[dict]` — the exact item shape `GET /api/apps` returns today (including `has_secrets`, `job`).
    - `status(app_id) -> str`
    - `install(app_id) -> dict`, `update(app_id) -> dict` — start jobs exactly as today (GPU `--no-start` rules unchanged).
    - `start(app_id, confirm: bool) -> list[str]` — returns stopped app ids; raises `Busy`/`Conflict` as today.
    - `stop(app_id)`, `uninstall(app_id, delete_data: bool)`, `logs(app_id, lines=50) -> str`, `job(app_id) -> dict | None`, `secrets_for(app_id) -> list[dict]`
    - `ensure_running(app_id, timeout: float = 600, poll: float = 3, sleep=time.sleep) -> list[str]` — not installed → `SuiteError(400, "{id} is not installed — call install_app('{id}')")`; running → `[]`; otherwise `start(app_id, confirm=True)` then poll `status` until `running` (returns stopped ids), `error` → `SuiteError(500, "{id} failed to start — check app_logs('{id}')")`, or timeout → `SuiteError(504, "{id} is still starting after {timeout:.0f} s — check app_logs('{id}')")`.
  - `create_app(...)` keeps its signature but builds a `Suite` internally and maps `SuiteError` → `HTTPException(status, detail)`; also accepts an existing `suite: Suite | None = None`.

- [ ] **Step 1: Write failing tests** in `tests/test_suite.py` (reuse the `Fake` runner pattern from `test_api.py`; move `Fake` and `APPS` into `tests/conftest.py` so both files share them):

```python
def test_ensure_running_not_installed():           # no project -> SuiteError status 400, message contains "install_app('sd')"
def test_ensure_running_already_running():         # mos-sd running + probe True -> [] and no compose calls
def test_ensure_running_stops_gpu_conflict():      # mos-comfy running, mos-sd exited; probe sd flips True after start -> returns ["comfy"]; calls: comfy stop, sd up -d
def test_ensure_running_times_out():               # sd running but probe always False, fake clock + sleep advancing 3 s; timeout=9 -> SuiteError 504 "still starting after 9 s"
def test_ensure_running_error_state():             # clock past start_timeout -> SuiteError 500 "failed to start"
```

- [ ] **Step 2: Run, verify FAIL** — `uv run pytest tests/test_suite.py -q`.
- [ ] **Step 3: Implement `backend/suite.py`; make `api.py` a thin layer over it.** No behaviour change for HTTP.
- [ ] **Step 4: Run full suite, verify PASS** — `uv run pytest -q` (all existing API tests unchanged and green).
- [ ] **Step 5: Commit** — `git commit -m "refactor: extract Suite from the HTTP API"`.

---

### Task 2: Outputs store and `/files`

**Files:**
- Create: `backend/outputs.py`
- Modify: `backend/api.py`, `backend/main.py`
- Test: `tests/test_outputs.py`, `tests/test_api.py`

**Interfaces:**
- Produces:
  - `class Outputs(root: Path, base_url: str = "http://localhost:8080/files")`:
    - `save(app_id: str, ext: str, data: bytes) -> tuple[Path, str]` — writes `root/<app_id>/<YYYYmmdd-HHMMSS>-<8 hex>.<ext>` (`ext` must match `^[a-z0-9]{1,5}$`), returns `(path, url)`.
    - `resolve(rel: str) -> Path` — raises `FileNotFoundError` if the resolved path is outside `root` or missing.
  - `GET /files/{rel:path}` → `FileResponse`; 404 on traversal or missing.
  - `main.py`: `Outputs(Path(os.environ.get("MOS_STATE", "state")) / "outputs")`.

- [ ] **Step 1: Write failing tests**

```python
def test_save_returns_url_and_writes(tmp_path):   # save("voicestudio", "wav", b"x") -> file exists with b"x"; url == f"http://localhost:8080/files/voicestudio/{path.name}"
def test_bad_ext_rejected(tmp_path):              # ext "../x" -> ValueError
def test_files_serves_saved(env):                 # api: GET /files/voicestudio/<name> -> 200 body b"x"
def test_files_rejects_traversal(env):            # GET /files/..%2F..%2Fsecrets.json and /files/../s.json -> 404
```

- [ ] **Step 2: FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: PASS** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `git commit -m "feat: outputs store served at /files"`.

---

### Task 3: MCP server with suite tools

**Files:**
- Create: `backend/mcp_server.py`
- Modify: `backend/api.py` (mount + `/mcp` header exemption), `backend/main.py`, `pyproject.toml` (`mcp==2.3.0`), `uv.lock`
- Test: `tests/test_mcp.py`, `tests/e2e/test_mcp_e2e.py`

**Interfaces:**
- Consumes: `Suite`, `SuiteError` (Task 1); `Outputs` (Task 2).
- Produces:
  - `build_mcp(suite: Suite, outputs: Outputs, catalog_root: Path) -> MCPServer` — name `"MyOpenSuite"`, instructions: one paragraph telling Claude what the suite is, that GPU apps are mutually exclusive, and that outputs come back as `http://localhost:8080/files/...` links it can download.
  - Suite tools (each catches `SuiteError` and returns its message as text):
    - `list_apps() -> list[dict]` — `[{"id","name","replaces","status","url","gpu"}]` (dev apps hidden)
    - `install_app(app_id: str) -> str` — `"Installing {name} — this can take several minutes; call list_apps to see when it is ready."`
    - `start_app(app_id: str) -> str` — uses `ensure_running`; `"{name} is running at {url}"` plus `" (stopped {names} to free the GPU)"` when applicable.
    - `stop_app(app_id: str) -> str`
    - `uninstall_app(app_id: str) -> str` — never `delete_data`.
    - `app_logs(app_id: str, lines: int = 50) -> str`
  - Mounting: `mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)`; its routes are added to the FastAPI app (no `Mount`, so `POST /mcp` has no redirect) and `mcp.session_manager.run()` runs inside the FastAPI lifespan. `transport_security` allows hosts `localhost:*` and `127.0.0.1:*`.
  - `require_header` middleware skips the `X-MOS` check for paths starting `/mcp` (allowed-clients check still applies).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mcp.py — call tools in-process: await server.call_tool(name, args) via asyncio.run / anyio
def test_tools_listed():                 # list_tools names ⊇ {"list_apps","install_app","start_app","stop_app","uninstall_app","app_logs"}
def test_list_apps_hides_dev():          # result has "comfy","sd", not "hello"
def test_start_app_reports_stopped():    # comfy running, sd exited, probe flips -> text contains "stopped comfy"
def test_unknown_app_message():          # start_app("nope") -> text "Unknown app nope"
def test_uninstall_never_deletes_data(): # compose args == ["down", "--rmi", "all"]
def test_mcp_post_needs_no_header(env):  # TestClient POST /mcp initialize JSON-RPC without X-MOS -> 200 (not 403, not 307)
```

```python
# tests/e2e/test_mcp_e2e.py (MOS_E2E=1) — real client over HTTP
# from mcp.client.streamable_http import streamable_http_client ; from mcp import ClientSession
def test_mcp_lists_apps():               # initialize; list_tools contains "list_apps"; call list_apps -> includes "voicestudio"
```

- [ ] **Step 2: FAIL.**  - [ ] **Step 3: `uv add mcp==2.3.0`; implement.** (Confirm the 2.x client import path with `uv run python -c "import mcp.client.streamable_http as m; print(dir(m))"` and use what it exposes.)
- [ ] **Step 4: PASS** — `uv run pytest -q`; rebuild (`$env:MOS_DEV='1'; podman compose up -d --build`); `$env:MOS_E2E='1'; uv run pytest tests/e2e -v`.
- [ ] **Step 5: Commit** — `git commit -m "feat: MCP server with suite tools"`.

---

### Task 4: Catalog action loader + VoiceStudio actions

**Files:**
- Create: `backend/actions.py`, `catalog/voicestudio/mcp.py`
- Modify: `backend/mcp_server.py`, `Dockerfile` (no change needed if `catalog/` is already copied — verify), `tests/test_catalog_lint.py` (lint skips non-yml files — verify)
- Test: `tests/test_actions.py`, `tests/test_voicestudio_mcp.py`

**Interfaces:**
- Produces:
  - `@dataclass class ActionContext: suite: Suite; outputs: Outputs; http: httpx.Client` with:
    - `ensure_running(app_id) -> str` — calls `suite.ensure_running`, returns a note `""` or `" (stopped X to free the GPU)"`.
    - `base_url(app_id) -> str` — `f"http://{app.id}:{app.internal_port}"`.
    - `secret(app_id, name) -> str` — from `suite.secrets_for`.
  - `load_actions(server: MCPServer, ctx: ActionContext, catalog_root: Path) -> list[str]` — for each `catalog/*/mcp.py`, import it with `importlib.util.spec_from_file_location(f"mos_actions_{id}", path)` and call its `register(server, ctx)`; returns ids loaded. A module that fails to import is skipped and logged (the server still starts).
  - `catalog/voicestudio/mcp.py`: `register(server, ctx)` adds
    - `voice_list() -> list[dict]` — `GET /v1/audio/voices` → `[{"id","name","type"}]`
    - `voice_speak(text: str, voice: str = "alloy") -> str` — `POST /v1/audio/speech` `{"model": "tts-1", "voice": voice, "input": text, "response_format": "wav"}`, timeout 600; saves via `outputs.save("voicestudio", "wav", bytes)`; returns `"Saved {url}{note}"`. On `model_licence_required` → `"Accept the model licence in VoiceStudio → Model Catalogue (open http://localhost:7801), then try again."`; other non-2xx → `"VoiceStudio error {status}: {error.message}"`.

- [ ] **Step 1: Write failing tests** (VoiceStudio via `httpx.MockTransport`; suite stubbed so `ensure_running` returns `[]`)

```python
def test_loader_registers_voicestudio():    # load_actions(...) returns ["voicestudio", ...]; tools include voice_speak, voice_list
def test_loader_skips_broken_module(tmp_path):  # catalog with mcp.py raising ImportError -> other ids still loaded
def test_voice_speak_saves_wav():           # mock 200 b"RIFF..." -> text starts "Saved http://localhost:8080/files/voicestudio/"; request had Bearer header with the secret
def test_voice_speak_licence_message():     # mock 403 {"error":{"code":"model_licence_required",...}} -> "Accept the model licence in VoiceStudio"
def test_voice_list_shape():                # mock {"voices":[{"voice_id":"alloy","name":"Alloy","type":"openai_alias"}]} -> [{"id":"alloy","name":"Alloy","type":"openai_alias"}]
def test_secret_not_in_output():            # no tool text contains the secret value
```

- [ ] **Step 2: FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: PASS** — `uv run pytest -q`.
- [ ] **Step 5: E2E (MOS_E2E_APPS=1)** — add to `tests/e2e/test_mcp_e2e.py`: `voice_list` returns `alloy`; `voice_speak("Hello from MyOpenSuite.")` returns either a `Saved http://…` link whose download is a WAV (`RIFF`), or the licence message — in the latter case `pytest.skip("accept VoiceStudio licence to finish this check")`.
- [ ] **Step 6: Commit** — `git commit -m "feat: VoiceStudio MCP actions"`.

---

### Task 5: ComfyUI actions

**Files:**
- Create: `catalog/comfyui/mcp.py`
- Test: `tests/test_comfyui_mcp.py`, `tests/e2e/test_mcp_e2e.py`

**Interfaces:**
- `catalog/comfyui/mcp.py`: `register(server, ctx)` adds
  - `comfy_list_checkpoints() -> list[str]` — `GET /models/checkpoints`.
  - `comfy_txt2img(prompt: str, negative: str = "", width: int = 1024, height: int = 1024, steps: int = 25, cfg: float = 7.0, seed: int | None = None, checkpoint: str | None = None) -> list` — builds the standard graph (`CheckpointLoaderSimple` → `CLIPTextEncode` ×2 → `EmptyLatentImage` → `KSampler` (`euler`, `normal`, denoise 1.0) → `VAEDecode` → `SaveImage` prefix `mos`), `POST /prompt` `{"prompt": graph, "client_id": uuid4}`, polls `GET /history/{prompt_id}` every 2 s (max 600 s), downloads each image via `GET /view?filename=&subfolder=&type=output`, saves with `outputs.save("comfyui", "png", bytes)`, returns `[Image(data=bytes, format="png"), f"Saved {url}{note}"]`.
  - No checkpoint installed → `"No checkpoints installed — open ComfyUI (http://localhost:7802) → Manager → Model Manager and install one (SD 1.5 or SDXL fit 6 GB VRAM)."`
  - `checkpoint` not in the list → `"Unknown checkpoint X. Installed: a, b"`.
  - `/prompt` returns `node_errors` → `"ComfyUI rejected the workflow: {first error message}"`.
  - Width/height clamped to multiples of 8 in 256–2048; steps 1–100.

- [ ] **Step 1: Write failing tests** (MockTransport scripting `/models/checkpoints`, `/prompt`, `/history/<id>` (first empty, then outputs), `/view`)

```python
def test_comfy_no_checkpoints_message():
def test_comfy_unknown_checkpoint():
def test_comfy_txt2img_happy_path():   # returns Image + "Saved http://localhost:8080/files/comfyui/...png"; graph sent has KSampler steps 25, seed int, ckpt_name == first checkpoint
def test_comfy_node_errors():
def test_comfy_size_clamped():         # width 1000 -> 1000; width 3000 -> 2048; width 250 -> 256; width 1001 -> 1000
```

- [ ] **Step 2: FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: PASS** — `uv run pytest -q`.
- [ ] **Step 5: E2E (MOS_E2E_APPS=1)** — `comfy_list_checkpoints` via MCP; if empty, assert `comfy_txt2img` returns the "No checkpoints installed" message and `pytest.skip("install a checkpoint to finish this check")`; else generate 512×512, 10 steps, and assert an image comes back. Also assert VoiceStudio was reported stopped if it was running (GPU rule via MCP).
- [ ] **Step 6: Commit** — `git commit -m "feat: ComfyUI MCP actions"`.

---

### Task 6: Connect Claude + docs

**Files:**
- Modify: `README.md`, `catalog/next-ai-draw-io/NOTES.md`, `catalog/voicestudio/NOTES.md`, `catalog/comfyui/NOTES.md`

- [ ] **Step 1: README "Use with Claude" section** with exact snippets:
  - Claude Code: `claude mcp add --scope user --transport http mos http://localhost:8080/mcp`
  - Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`): `{"mcpServers": {"mos": {"command": "npx", "args": ["-y", "mcp-remote", "http://localhost:8080/mcp"]}}}` — note that Claude Desktop's "custom connector" UI goes through Anthropic's cloud and cannot reach `localhost`, so use the config file.
  - Draw.io: `claude mcp add --scope user drawio -- npx @next-ai-drawio/mcp-server@latest` (and the Desktop JSON equivalent).
  - Tool list with one example prompt each; outputs are links under `http://localhost:8080/files/`.
  - First-time steps: accept the VoiceStudio model licence; install a ComfyUI checkpoint.

- [ ] **Step 2: Verify the Claude Code snippet against the running stack without changing the owner's config** — `claude mcp add --scope local --transport http mos-check http://localhost:8080/mcp` in a scratch directory, `claude mcp list` shows `mos-check ... ✓ Connected`, then `claude mcp remove mos-check --scope local`. (The owner adds the real user-scope entry themselves.)

- [ ] **Step 3: Commit** — `git commit -m "docs: connect Claude to MyOpenSuite"`.
