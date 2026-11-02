# MyOpenSuite More Apps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add open-notebook, bolt.diy, OpenHands, AppFlowy and Dify to the catalog within the owner's ~30 GB disk budget, with multi-container stacks supported safely.

**Architecture:** Same catalog model (`app.yml` + `docker-compose.yml` + `icon.png` + `NOTES.md`). Multi-container apps keep their internal services on the project's own default network; only the main service also joins `mos-net`, so generic service names (`db`, `redis`, `api`) from different apps never collide on the shared network. Config files that upstream bind-mounts are baked into tiny images built from the catalog folder.

**Tech Stack:** unchanged. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-02-myopensuite-design.md` milestone 6. Scope is marketplace-only (no Claude/MCP; gateway deferred) — AI apps get their model/key in their own settings.

**Owner decisions applied (2026-11-02):** disk budget ~30 GB. **Dropped:** SD WebUI (7–11 GB with models; ComfyUI already covers it), open-lovable (needs E2B/Vercel cloud sandboxes + Firecrawl key — not self-hostable), OpenManus (CLI only, no web UI).

**Measured budget:** E: free 31.2 GB; reclaimable 1.4 GB; reserved: VoiceStudio models ~4 GB, one SD 1.5 checkpoint ~2 GB, safety margin 5 GB → **~21 GB for this plan**. Estimated use (compressed download × ~2.3): open-notebook ~1.5, bolt.diy ~1.2, OpenHands ~3.5, AppFlowy ~2.5, Dify ~5.5 → **~14 GB**.

## Global Constraints

- All earlier constraints hold (localhost binds, `mos-<id>` projects, CDI GPU form, no `container_name`, secrets via `secrets:` + Credentials, mutations need `X-MOS`, allowed clients = gateway IP + 127.0.0.1).
- **Disk gate:** before and after every install, record `E:` free space and `podman system df`. If `E:` free would drop below **5 GB**, stop and report to the owner instead of installing.
- Host ports: open-notebook 7804, bolt-diy 7805, openhands 7806, appflowy 7807, dify 7808.
- Only the main service (named `<id>`) may join `mos-net`; other services stay on the project default network.
- No host bind mounts; upstream config files are baked via a build context inside `catalog/<id>/`.
- Images pinned to a release tag where upstream publishes one (record the tag in `NOTES.md`).

## Review Focus

1. **Two stacks both define `db`/`redis`/`nginx`** (Dify and AppFlowy do) → each resolves its own, never the other app's. Test: lint `test_lint_only_main_joins_mos_net` (Task 1) + e2e both stacks running at once (Task 6).
2. **Disk fills mid-install** → install job fails with Podman's "no space left" in the log, tile shows the error; nothing else breaks. Covered by the disk gate (manual) — the owner must never be left with a full E:.
3. **"Also delete data" on a multi-container app** → all of that app's named volumes are removed, no other app's. Test: e2e `test_uninstall_stack_removes_only_its_volumes` (Task 6).
4. **AppFlowy / Dify first boot takes minutes (migrations)** → tile stays "Starting…", not "Error". Test: `start_timeout` set from measured first-boot time (Tasks 5–6).
5. **Generated DB passwords change after first boot** → never: secrets are generated once and persisted (existing behaviour); Postgres would otherwise refuse the new password. Covered by `test_secret_survives_rebuild`.

---

### Task 1: Multi-container support and disk housekeeping

**Files:**
- Modify: `backend/catalog.py` (lint), `tests/test_catalog_lint.py`, `README.md`

**Interfaces:**
- `lint_compose` changes: the main service (`app.id`) must list `mos-net`; **any other service listing `mos-net` is a problem** (`"service X must not join mos-net (only the main service may)"`); the main service of a multi-service app must also list `default` (`"service X must also join the default network to reach its stack"`). Single-service apps unchanged.

- [ ] **Step 1: Write failing tests**

```python
def test_lint_only_main_joins_mos_net(tmp_path):     # services a (mos-net) + db (mos-net) -> "service db must not join mos-net"
def test_lint_stack_main_needs_default(tmp_path):    # services a (mos-net only) + db (no networks) -> "must also join the default network"
def test_lint_stack_ok(tmp_path):                    # a: [default, mos-net]; db: no networks key -> []
```
Existing `test_lint_missing_network` keeps passing for the main service.

- [ ] **Step 2: FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: PASS** — `uv run pytest -q`.
- [ ] **Step 5: Reclaim space** — `podman image prune -f`; record `E:` free before/after.
- [ ] **Step 6: README "Disk space" section** — Uninstall frees space inside the Podman VM, but Windows only gets it back after: `podman machine ssh sudo fstrim -av`, then `podman machine stop`, `wsl --shutdown`, `wsl --manage podman-machine-default --set-sparse true` (one-time; lets the VHD shrink). Note the app budget table from this plan.
- [ ] **Step 7: Commit** — `git commit -m "feat: multi-container catalog apps; disk housekeeping docs"`.

---

### Task 2: open-notebook

**Files:** Create `catalog/open-notebook/{app.yml,docker-compose.yml,icon.png,NOTES.md}`; modify `tests/e2e/test_apps.py`.

- [ ] **Step 1: Write the e2e test (first)**

```python
def test_open_notebook():
    install_and_wait("open-notebook", timeout=900)
    assert httpx.get("http://localhost:7804/", follow_redirects=True).status_code == 200
```
Run → FAIL (not in catalog).

- [ ] **Step 2: Catalog entry**
  - `app.yml`: `id: open-notebook`, `name: Open Notebook`, `replaces: NotebookLM`, `description: Research notebooks — add sources, chat with them, generate podcasts. Add an AI provider key in its Settings.`, `repo: https://github.com/lfnovo/open-notebook`, `port: 7804`, `internal_port: 8502`, `size_gb: 1.5`, `start_timeout: 300`, `secrets: { OPEN_NOTEBOOK_ENCRYPTION_KEY: "Encrypts provider keys stored in its database", SURREAL_PASSWORD: "Internal database password" }`.
  - Compose (from upstream `docker-compose.yml`): service `surrealdb` (`docker.io/surrealdb/surrealdb:v2`, command `["start","--log","info","--user","root","--pass","${SURREAL_PASSWORD}","rocksdb:/mydata/mydatabase.db"]`, `user: root`, volume `surreal-data:/mydata`, **no ports**, default network only); service `open-notebook` (`docker.io/lfnovo/open_notebook:v1-latest`, ports `["127.0.0.1:7804:8502"]`, env `OPEN_NOTEBOOK_ENCRYPTION_KEY=${…}`, `SURREAL_URL=ws://surrealdb:8000/rpc`, `SURREAL_USER=root`, `SURREAL_PASSWORD=${SURREAL_PASSWORD}`, `SURREAL_NAMESPACE=open_notebook`, `SURREAL_DATABASE=open_notebook`, volume `notebook-data:/app/data`, networks `[default, mos-net]`, `depends_on: [surrealdb]`); both `restart: unless-stopped`.
  - Verify whether the UI needs port 5055 published (open the UI, add a notebook; if the browser calls `:5055` directly, publish `127.0.0.1:7814:5055` and set the API URL env the upstream docs name — record the outcome in `NOTES.md`).
  - Icon: repo `logo.png` resized ≤ 256 px if large (or as is).
- [ ] **Step 3: Lint, rebuild, disk gate, e2e PASS** — `uv run pytest -q`; `$env:MOS_DEV='1'; podman compose up -d --build`; `$env:MOS_E2E_APPS='1'; uv run pytest tests/e2e/test_apps.py -v -k notebook`; record disk use.
- [ ] **Step 4: Browser check** — create a notebook, add a URL source (works without AI key); Settings shows where to add a provider key.
- [ ] **Step 5: Commit** — `git commit -m "feat: open-notebook catalog entry"`.

---

### Task 3: bolt.diy

**Files:** Create `catalog/bolt-diy/{app.yml,docker-compose.yml,icon.png,NOTES.md}`; modify `tests/e2e/test_apps.py`.

- [ ] **Step 1: e2e test (first)** — `install_and_wait("bolt-diy")`; `GET http://localhost:7805/` → 200. Run → FAIL.
- [ ] **Step 2: Catalog entry** — `id: bolt-diy`, `name: bolt.diy`, `replaces: Bolt.new / v0`, `description: Build full-stack web apps from a prompt in your browser. Pick a provider and paste its key in the app.`, `port: 7805`, `internal_port: 5173`, `size_gb: 1.2`. Compose: service `bolt-diy`, image `ghcr.io/stackblitz-labs/bolt.diy:latest` (use a release tag if one is published — check `ghcr.io/stackblitz-labs/bolt.diy` tags), env `NODE_ENV=production`, `PORT=5173`, `RUNNING_IN_DOCKER=true`; if the image's default command does not serve production, set `command: pnpm run dockerstart` (upstream). Network `mos-net`, `restart: unless-stopped`.
- [ ] **Step 3: Lint, rebuild, disk gate, e2e PASS.**
- [ ] **Step 4: Browser check** — the app loads, provider picker visible, the in-browser preview (WebContainers) initialises on `localhost`.
- [ ] **Step 5: Commit** — `git commit -m "feat: bolt.diy catalog entry"`.

---

### Task 4: OpenHands

**Files:** Create `catalog/openhands/{app.yml,docker-compose.yml,icon.png,NOTES.md}`; modify `tests/e2e/test_apps.py`.

- [ ] **Step 1: e2e test (first)** — `install_and_wait("openhands", timeout=1200)`; `GET http://localhost:7806/canvas` (follow redirects) → 200; `secrets` endpoint returns `LOCAL_BACKEND_API_KEY`. Run → FAIL.
- [ ] **Step 2: Catalog entry** — `id: openhands`, `name: OpenHands`, `replaces: Devin`, `description: AI software engineer that writes and runs code in its own sandbox. Paste the key from Credentials, then add an AI provider in its settings.`, `port: 7806`, `internal_port: 8000`, `path: /canvas`, `size_gb: 3.5`, `secrets: { LOCAL_BACKEND_API_KEY: "Login key — OpenHands asks for it when you open it" }`. Compose: service `openhands`, image `ghcr.io/openhands/agent-canvas:1.34.0`, ports `["127.0.0.1:7806:8000"]`, env `LOCAL_BACKEND_API_KEY=${LOCAL_BACKEND_API_KEY}` (no `AGENT_CANVAS_ALLOW_LAN_SESSION_KEY` — the key is not injected into HTML, so containers on `mos-net` cannot pick it up), volumes `openhands-state:/home/openhands/.openhands`, `openhands-projects:/projects`, network `mos-net`, `restart: unless-stopped`. No container socket (Option 2: the container itself is the sandbox).
- [ ] **Step 3: Lint, rebuild, disk gate, e2e PASS.**
- [ ] **Step 4: Browser check** — `/canvas` asks for the API key; pasting the Credentials value logs in.
- [ ] **Step 5: Commit** — `git commit -m "feat: OpenHands catalog entry"`.

---

### Task 5: AppFlowy (Cloud + Web)

**Files:** Create `catalog/appflowy/{app.yml,docker-compose.yml,icon.png,NOTES.md}` plus `catalog/appflowy/nginx/{Dockerfile,nginx.conf}` (baked config); modify `tests/e2e/test_apps.py`.

- [ ] **Step 1: Research (record in NOTES.md)** — from `AppFlowy-IO/AppFlowy-Cloud` at its latest release tag: `docker-compose.yml`, `deploy.env`, `nginx/nginx.conf`. List every service, the minimum env, and which services are optional (drop `ai`, `admin_frontend` if the web app works without them, to save disk). Target `APPFLOWY_BASE_URL`/`API_EXTERNAL_URL` = `http://localhost:7807`, sign-up without email (`GOTRUE_MAILER_AUTOCONFIRM=true`, an admin user from secrets).
- [ ] **Step 2: e2e test (first)** — `install_and_wait("appflowy", timeout=1800)`; `GET http://localhost:7807/` → 200 and the web app's HTML; `GET http://localhost:7807/api/health` (or the gotrue health route found in research) → 200. Run → FAIL.
- [ ] **Step 3: Catalog entry** — main service `appflowy` = the nginx entry point built from `catalog/appflowy/nginx/` (`build: {context: ./nginx}`; `FROM docker.io/library/nginx:<pinned>`, `COPY nginx.conf /etc/nginx/nginx.conf`) with networks `[default, mos-net]` and ports `["127.0.0.1:7807:80"]`; every other service on the default network only; all state in named volumes; generated `secrets:` for Postgres password, GoTrue JWT secret, MinIO root password, admin password (description says which one to log in with). `size_gb: 2.5`; `start_timeout` = measured first boot + 50 %.
- [ ] **Step 4: Lint, rebuild, disk gate, e2e PASS.** Measure first-boot time; set `start_timeout`.
- [ ] **Step 5: Browser check** — sign in with the admin credentials from Credentials, create a page.
- [ ] **Step 6: Commit** — `git commit -m "feat: AppFlowy catalog entry"`.

---

### Task 6: Dify

**Files:** Create `catalog/dify/{app.yml,docker-compose.yml,icon.png,NOTES.md}` plus baked-config build contexts `catalog/dify/nginx/` and `catalog/dify/ssrf-proxy/` (and `catalog/dify/sandbox/` if upstream bind-mounts sandbox config); modify `tests/e2e/test_apps.py`.

- [ ] **Step 1: Research (record in NOTES.md)** — from `langgenius/dify` at its latest release tag, `docker/docker-compose.yaml` + `docker/.env.example` + the nginx, ssrf_proxy and sandbox config files. Keep the default stack (api, worker, web, db=Postgres, redis, sandbox, plugin_daemon, ssrf_proxy, nginx, vector store = weaviate) and drop optional profiles. List every env var that must be set; generate secrets for `SECRET_KEY`, DB password, Redis password, `SANDBOX_API_KEY`, `PLUGIN_DAEMON_KEY`, `PLUGIN_DIFY_INNER_API_KEY`, weaviate API key.
- [ ] **Step 2: e2e tests (first)**

```python
def test_dify():
    install_and_wait("dify", timeout=2400)
    assert httpx.get("http://localhost:7808/install", follow_redirects=True).status_code == 200
    assert httpx.get("http://localhost:7808/console/api/setup").status_code == 200

def test_two_stacks_coexist():           # appflowy and dify both running: both health checks 200

def test_uninstall_stack_removes_only_its_volumes():
    # uninstall open-notebook with delete_data=true; `podman volume ls` has no mos-open-notebook_* volumes
    # and still has mos-dify_* and mos-appflowy_* volumes; reinstall open-notebook afterwards
```
Run → FAIL.

- [ ] **Step 3: Catalog entry** — main service `dify` = baked nginx (`[default, mos-net]`, `127.0.0.1:7808:80`); all others default network only; named volumes for db, redis, weaviate, storage, plugin data; env from research with `${SECRET}` references; `size_gb: 5.5`; `start_timeout` = measured first boot + 50 %. Description: `Build AI apps, agents and workflows visually. Create the admin account on first open, then add a model provider in Settings → Model Provider.`
- [ ] **Step 4: Lint, rebuild, disk gate, e2e PASS** — all of `tests/e2e/test_apps.py`.
- [ ] **Step 5: Browser check** — first-open setup page → create admin → Studio loads.
- [ ] **Step 6: README Apps table** — add all five rows (port, GPU no, notes link) and the updated disk budget with measured sizes.
- [ ] **Step 7: Commit** — `git commit -m "feat: Dify catalog entry"`.
