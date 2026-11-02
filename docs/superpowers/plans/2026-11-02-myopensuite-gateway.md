# MyOpenSuite LLM Gateway Implementation Plan

> **Status: deferred (2026-11-02, owner's call).** The owner uses Claude Pro through MCP; AI apps are configured in their own settings for now. Pick this plan up if managing per-app keys becomes a burden.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A LiteLLM gateway the owner configures from a new **LLM Gateway** page (providers + model aliases + test), whose URL, key and model are injected into apps automatically — starting with Next AI Draw.io.

**Architecture:** A `litellm` service joins the root stack on `mos-net` as container `mos-litellm`. The dashboard keeps gateway state (providers, aliases, master key) in `/data/gateway.json` on `mos-state`, renders LiteLLM's `config.yaml` into a separate `mos-gateway` volume (mounted read-only by LiteLLM), and restarts `mos-litellm` after every change. Apps declare an `llm:` block in `app.yml`; the existing compose env hook resolves it from gateway state.

**Tech Stack:** as before; LiteLLM proxy image `docker.litellm.ai/berriai/litellm:main-stable` (no database).

**Spec:** `docs/superpowers/specs/2026-11-02-myopensuite-design.md` §7 (milestone 4).

**Spec additions and deviations (decided here):**
- **Keys live in the config file, not a `.env`.** LiteLLM reads `.env` only at container start through compose, which the dashboard cannot rewrite from inside a volume; `config.yaml` holds provider keys and the master key literally. It sits in its own `mos-gateway` volume so LiteLLM never sees other apps' secrets.
- **`llm:` values gain `const:<value>`** (e.g. `AI_PROVIDER: const:openai`), injected together with the gateway values.
- **All-or-nothing injection:** an app's `llm:` env is injected only when every `alias:` it references exists; otherwise nothing is injected and the tile shows "AI: not connected". The app then falls back to its own settings.
- **Running apps keep old values until restarted.** Start runs `up -d`, which recreates a container whose env changed; the Gateway page says so after each save.
- **Provider kinds:** `openrouter`, `anthropic`, `openai`, `gemini`, `custom` (OpenAI-compatible, needs `base_url`). LiteLLM model string = `<prefix>/<model>`, prefix = kind, except `custom` → `openai` plus `api_base`.

## Global Constraints

- All earlier Global Constraints hold (localhost binds, `X-MOS: 1` on mutations, allowed clients = gateway IP + 127.0.0.1, CDI GPU, no `container_name` in catalog files, secrets never in `GET /api/apps`).
- Gateway endpoint for apps, exactly: `http://litellm:4000/v1`. Container name: `mos-litellm`. LiteLLM health: `GET http://litellm:4000/health/liveliness`.
- Provider keys and the master key are never returned to the browser; the UI sees `key_hint` = last 4 characters.
- Master key format: `"sk-" + secrets.token_urlsafe(32)`, generated once.
- No database, no virtual keys, no budgets (spec §15).

## Review Focus

1. **A provider key is pasted with surrounding whitespace or a newline** → stored trimmed; LiteLLM gets the clean key. Test: `test_provider_key_trimmed` (Task 1).
2. **Removing a provider that an alias still uses** → 409 naming the aliases; nothing written. Test: `test_delete_provider_in_use_409` (Task 3).
3. **Gateway container down or restarting when the user presses Test** → a clear error ("Gateway is not running — …"), not a 500. Test: `test_gateway_test_when_down` (Task 3).
4. **gateway.json missing on first run** → master key generated, empty config rendered, LiteLLM starts with no models. Test: `test_fresh_state_renders_empty_config` (Task 1); e2e `test_gateway_running` (Task 4).
5. **App references alias `default` but only `fast` exists** → no partial env; tile shows not connected. Test: `test_llm_env_all_or_nothing` (Task 2).

---

### Task 1: Gateway state and LiteLLM config rendering

**Files:**
- Create: `backend/gateway.py`
- Test: `tests/test_gateway.py`

**Interfaces:**
- Produces:
  - `PROVIDER_KINDS = ("openrouter", "anthropic", "openai", "gemini", "custom")`
  - `class GatewayError(ValueError)` — message is user-facing.
  - `class GatewayStore(state_path: Path, config_path: Path)`:
    - `state() -> dict` — `{"master_key": str, "providers": {id: {"kind", "api_key", "base_url"?}}, "aliases": {name: {"provider", "model"}}}`; creates and persists a master key on first read (same atomic write + 0600 + corrupt-backup behaviour as `SecretStore`).
    - `set_provider(id: str, kind: str, api_key: str, base_url: str | None = None) -> None` — id matches `^[a-z0-9][a-z0-9-]*$`; kind in `PROVIDER_KINDS`; `api_key` stripped and non-empty; `custom` requires `base_url` starting `http://` or `https://`.
    - `delete_provider(id: str) -> None` — raises `GatewayError` listing alias names if any alias uses it.
    - `set_alias(name: str, provider: str, model: str) -> None` — name matches `^[a-z0-9][a-z0-9._-]*$`; provider must exist; model stripped, non-empty.
    - `delete_alias(name: str) -> None`
    - `public() -> dict` — `{"providers": [{"id","kind","base_url","key_hint"}], "aliases": [{"name","provider","model"}]}` sorted by id/name; no keys.
    - every mutating method persists state and calls `write_config()`.
    - `write_config() -> None` — writes `render_config(self.state())` as YAML to `config_path` (atomic, 0600).
  - `render_config(state: dict) -> dict`:
    ```python
    {"model_list": [{"model_name": alias, "litellm_params": {"model": f"{prefix}/{model}", "api_key": key, **({"api_base": base_url} if custom)}}],
     "general_settings": {"master_key": state["master_key"]}}
    ```

- [ ] **Step 1: Write failing tests**

```python
def test_fresh_state_renders_empty_config(tmp_path):   # GatewayStore(s, c).write_config(); yaml.safe_load(c) == {"model_list": [], "general_settings": {"master_key": <starts "sk-">}}
def test_master_key_stable(tmp_path):                   # two stores on same path -> same master_key
def test_provider_key_trimmed(tmp_path):                # set_provider("or", "openrouter", "  sk-or-x \n") -> state key "sk-or-x"
def test_custom_requires_base_url(tmp_path):            # set_provider("lm", "custom", "k") -> GatewayError match "base_url"
def test_unknown_kind_rejected(tmp_path):               # kind "foo" -> GatewayError
def test_alias_needs_existing_provider(tmp_path):       # set_alias("default", "nope", "m") -> GatewayError match "nope"
def test_render_prefixes(tmp_path):                     # openrouter alias default model "anthropic/claude-x" -> "openrouter/anthropic/claude-x"; custom -> "openai/m" + api_base
def test_public_hides_keys(tmp_path):                   # public() json has key_hint "ab12", no full key anywhere in json.dumps
def test_delete_provider_in_use(tmp_path):              # alias uses provider -> GatewayError match alias name; provider still present
def test_config_written_on_change(tmp_path):            # after set_alias, config file lists the alias
```

- [ ] **Step 2: Run, verify FAIL** — `uv run pytest tests/test_gateway.py -q`.
- [ ] **Step 3: Implement `backend/gateway.py`.** Reuse the atomic-write/corrupt-backup logic by extracting `read_json(path) -> dict` and `write_private(path, text) -> None` from `secrets_store.py` into `backend/files.py` and using them in both.
- [ ] **Step 4: Run full suite, verify PASS** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `git commit -m "feat: gateway state and LiteLLM config rendering"`.

---

### Task 2: LLM env resolution for apps

**Files:**
- Modify: `backend/catalog.py`, `backend/gateway.py`, `backend/main.py`
- Test: `tests/test_catalog.py`, `tests/test_catalog_lint.py`, `tests/test_gateway.py`

**Interfaces:**
- Produces:
  - `LLM_RE` accepts `gateway_url`, `gateway_key`, `alias:<name>`, `const:<value>`.
  - `lint_compose`: every `llm:` var must be referenced as `${VAR}` or `${VAR:` → problem `llm var VAR is not used`.
  - `GATEWAY_URL = "http://litellm:4000/v1"` in `gateway.py`.
  - `GatewayStore.llm_env(app: App) -> dict[str, str]` — `{}` if `app.llm` is empty or any `alias:` target is missing; otherwise each var resolved (`gateway_url` → `GATEWAY_URL`, `gateway_key` → master key, `alias:x` → `"x"`, `const:v` → `"v"`).
  - `GatewayStore.llm_status(app: App) -> str | None` — `None` if no `llm:`; `"connected"` if `llm_env` non-empty; else `"not_connected"`.
  - `backend/main.py`: `Compose(env_for=lambda a: {**store.env_for(a), **gateway.llm_env(a)})`.

- [ ] **Step 1: Write failing tests**

```python
# test_catalog.py
def test_load_accepts_const_llm(tmp_path):     # llm: {AI_PROVIDER: "const:openai"} loads
# test_catalog_lint.py
def test_lint_llm_var_not_used(tmp_path):      # App(llm={"X": "gateway_url"}), GOOD compose -> "llm var X is not used"
# test_gateway.py
def test_llm_env_resolves(tmp_path):           # alias default exists; app llm {U: gateway_url, K: gateway_key, M: alias:default, P: const:openai} -> {"U": "http://litellm:4000/v1", "K": <master>, "M": "default", "P": "openai"}
def test_llm_env_all_or_nothing(tmp_path):     # only alias "fast"; app references alias:default -> {} and llm_status "not_connected"
def test_llm_status_none_without_llm(tmp_path):
```

- [ ] **Step 2: Run, verify FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run, verify PASS** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `git commit -m "feat: resolve app llm env from the gateway"`.

---

### Task 3: Gateway API

**Files:**
- Modify: `backend/api.py`, `backend/compose.py`, `backend/main.py`
- Test: `tests/test_api.py`, `tests/test_compose.py`

**Interfaces:**
- Consumes: `GatewayStore`, `GatewayError`, `GATEWAY_URL` (Tasks 1–2).
- Produces:
  - `Compose.restart_container(name: str) -> None` — runs `["docker", "restart", name]`, raises `ComposeError` on failure.
  - `create_app(..., gateway: GatewayStore | None = None, gateway_up: Callable[[], bool] = lambda: False, llm_call: Callable[[str, str], tuple[bool, str]] = ...)`
  - `gateway_up()` in `api.py`: `httpx.get("http://litellm:4000/health/liveliness", timeout=2).status_code == 200`, `False` on error.
  - `llm_call(alias, master_key) -> (ok, text)` in `api.py`: `POST http://litellm:4000/v1/chat/completions`, bearer master key, `{"model": alias, "messages": [{"role": "user", "content": "Reply with the single word OK."}], "max_tokens": 10}`, timeout 60; ok → first choice content; not ok → the response's `error.message` (or HTTP status text).
  - Endpoints (mutations need `X-MOS`; each mutation persists, re-renders config, then `restart_container("mos-litellm")`; `GatewayError` → 400 with its message):

| Method & path | Body | Response |
|---|---|---|
| `GET /api/gateway` | — | `{"running": gateway_up(), "endpoint": GATEWAY_URL, **gateway.public()}` |
| `PUT /api/gateway/providers/{id}` | `{"kind", "api_key", "base_url"?}` | `public()` |
| `DELETE /api/gateway/providers/{id}` | — | `public()`; 409 if in use |
| `PUT /api/gateway/aliases/{name}` | `{"provider", "model"}` | `public()` |
| `DELETE /api/gateway/aliases/{name}` | — | `public()` |
| `POST /api/gateway/test/{name}` | — | `{"ok": bool, "reply"?: str, "error"?: str}`; if not `gateway_up()` → `{"ok": false, "error": "Gateway is not running — check the litellm container logs"}` |

  - `GET /api/apps` items gain `"llm": gateway.llm_status(app)` (`None` when no gateway).

- [ ] **Step 1: Write failing tests** (gateway fixture: `GatewayStore(tmp_path/"g.json", tmp_path/"c.yaml")`; fake `gateway_up`, fake `llm_call` recording calls)

```python
def test_get_gateway_public(env):                 # PUT provider then GET -> providers[0].key_hint, no full key in text, endpoint == GATEWAY_URL
def test_put_provider_restarts_litellm(env):      # fake.calls contains ["docker", "restart", "mos-litellm"]
def test_bad_provider_400(env):                   # kind "foo" -> 400, no restart recorded
def test_delete_provider_in_use_409(env):         # alias uses it -> 409, detail mentions alias name
def test_gateway_test_ok(env):                    # gateway_up True, llm_call -> (True, "OK") -> {"ok": True, "reply": "OK"}; llm_call got ("default", master_key)
def test_gateway_test_when_down(env):             # gateway_up False -> {"ok": False, "error": startswith "Gateway is not running"}; llm_call not called
def test_gateway_mutation_needs_header(env):      # PUT without X-MOS -> 403
def test_apps_llm_status(env):                    # app with llm alias:default -> "not_connected"; after PUT provider + alias -> "connected"
# test_compose.py
def test_restart_container():                     # runner got ["docker", "restart", "mos-litellm"]
```

- [ ] **Step 2: Run, verify FAIL.**  - [ ] **Step 3: Implement**; wire `GatewayStore(Path(state)/"gateway.json", Path(os.environ.get("MOS_GATEWAY_DIR", "gateway-state"))/"config.yaml")` in `main.py` and call `gateway.write_config()` at startup.
- [ ] **Step 4: Run, verify PASS** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `git commit -m "feat: gateway API"`.

---

### Task 4: LiteLLM service in the stack

**Files:**
- Modify: `docker-compose.yml` (root), `.gitignore` (add `gateway-state/`)
- Create: `tests/e2e/test_gateway.py`

**Interfaces:**
- Produces root compose additions:
  - `myopensuite`: volume `mos-gateway:/gateway`, env `MOS_GATEWAY_DIR: /gateway`.
  - `litellm`: `image: docker.litellm.ai/berriai/litellm:main-stable`, `container_name: mos-litellm`, `command: ["--config", "/app/gateway/config.yaml", "--port", "4000"]`, volume `mos-gateway:/app/gateway:ro`, networks `[mos-net]`, `restart: unless-stopped`, no published port.
  - top-level `mos-gateway: { name: mos-gateway }`.

- [ ] **Step 1: Write e2e tests (first)** — gated by `MOS_E2E=1`, `X-MOS: 1`:

```python
def test_gateway_running():          # wait up to 120 s for GET /api/gateway .running True
def test_alias_listed_by_litellm():  # PUT provider "e2e-or" kind openrouter key "sk-or-invalid"; PUT alias "e2e" -> wait running;
                                     # podman exec myopensuite-myopensuite-1 python -c "<httpx GET http://litellm:4000/v1/models with bearer master>" lists "e2e"
                                     #   (read master key inside the container from /data/gateway.json)
def test_gateway_test_reaches_provider():  # POST /api/gateway/test/e2e -> ok False and error mentions auth/401/key (provider rejected the fake key = plumbing works end to end)
# teardown: DELETE alias e2e, DELETE provider e2e-or
```

- [ ] **Step 2: Run against the current stack, verify FAIL** (404 on `/api/gateway`).
- [ ] **Step 3: Update root compose and `.gitignore`.**
- [ ] **Step 4: Rebuild and run e2e, verify PASS** — `$env:MOS_DEV='1'; podman compose up -d --build`; `$env:MOS_E2E='1'; uv run pytest tests/e2e -v`.
- [ ] **Step 5: Commit** — `git commit -m "feat: LiteLLM gateway service"`.

---

### Task 5: LLM Gateway page

**Files:**
- Create: `frontend/src/Gateway.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/Tile.tsx`, `frontend/src/styles.css`

**Interfaces:**
- Consumes: Task 3 endpoints; `AppInfo.llm: "connected" | "not_connected" | null`.

- [ ] **Step 1: `api.ts`** — typed `getGateway`, `putProvider`, `deleteProvider`, `putAlias`, `deleteAlias`, `testAlias`, sending JSON bodies with `Content-Type: application/json` and `X-MOS: 1`. 400/409 errors surface `detail` as the message.

- [ ] **Step 2: `Gateway.tsx`** — third header tab **LLM Gateway**. Polls `GET /api/gateway` every 3 s.
  - Status pill: "Running" / "Restarting…" (shown for 20 s after any save, then from `running`) / "Not running".
  - **Providers** card: rows `id · kind · ••••key_hint · base_url` with Remove. Add form: kind `<select>` (OpenRouter, Anthropic, OpenAI, Gemini, Custom OpenAI-compatible), id (defaults to the kind), API key (`type=password`), base URL (only for Custom). Save → `PUT`.
  - **Model aliases** card: rows `name → provider / model` with **Test** and Remove; Test shows the reply (green) or error (red) inline. Add form: name (placeholder `default`), provider `<select>` from the providers list, model (placeholder per kind, e.g. OpenRouter `anthropic/claude-sonnet-4.5`). Save → `PUT`.
  - Footer note: "Apps pick up changes the next time they start. Endpoint for apps: http://litellm:4000/v1".
  - Errors from the API show inline under the form that caused them.

- [ ] **Step 3: `Tile.tsx`** — badge "AI ✓" when `llm == "connected"`, "AI: not connected" (muted, title "Add a provider and a `default` alias on the LLM Gateway page") when `"not_connected"`.

- [ ] **Step 4: Build and browser check** — `npm run build`; rebuild stack; in the browser: add an OpenRouter provider with a fake key → key shows as `••••` + last 4; add alias `default`; Test → red auth error from the provider; Next AI Draw.io tile shows "AI ✓"; remove alias → tile shows "AI: not connected"; remove provider.

- [ ] **Step 5: Commit** — `git commit -m "feat: LLM Gateway page"`.

---

### Task 6: Connect Next AI Draw.io

**Files:**
- Modify: `catalog/next-ai-draw-io/app.yml`, `catalog/next-ai-draw-io/docker-compose.yml`, `catalog/next-ai-draw-io/NOTES.md`, `tests/e2e/test_apps.py`, `README.md`

- [ ] **Step 1: Write the e2e test (first)** — in `test_apps.py`:

```python
def test_next_ai_draw_io_gets_gateway_env():
    # setup: PUT provider "e2e-or" (openrouter, fake key) + alias "default"; restart app via stop/start
    env = podman exec mos-next-ai-draw-io-next-ai-draw-io-1 printenv
    assert "OPENAI_BASE_URL=http://litellm:4000/v1" in env and "AI_PROVIDER=openai" in env and "AI_MODEL=default" in env
    # reachability: from inside the app container, GET http://litellm:4000/health/liveliness -> 200 (wget or node -e fetch)
    # teardown: delete alias + provider, stop/start app
```

- [ ] **Step 2: Run, verify FAIL** (env vars absent).

- [ ] **Step 3: Wire it** — `app.yml`: `llm: { AI_PROVIDER: "const:openai", OPENAI_BASE_URL: gateway_url, OPENAI_API_KEY: gateway_key, AI_MODEL: "alias:default" }`. Compose `environment:` references each as `"${VAR:-}"`. `NOTES.md`: "With a `default` alias on the LLM Gateway page the app uses the gateway automatically; otherwise set a provider in its own Settings." README Apps row note updated.

- [ ] **Step 4: Lint, rebuild, run e2e, verify PASS** — `uv run pytest -q`; rebuild; `$env:MOS_E2E_APPS='1'; uv run pytest tests/e2e/test_apps.py -v -k draw`.

- [ ] **Step 5: Manual check with a real key (owner, optional)** — add a real OpenRouter/Anthropic key and a `default` alias, Test → "OK"; Start Next AI Draw.io, ask for a flowchart. If the app fails because it calls OpenAI's Responses API, record the error in NOTES and set `llm_manual: true` for it instead (ruling).

- [ ] **Step 6: Commit** — `git commit -m "feat: connect Next AI Draw.io to the gateway"`.
