# MyOpenSuite — Design

Date: 2026-11-02 · Status: draft for review

## 1. Goal

A personal, self-hosted marketplace of open-source alternatives to paid AI software. A CasaOS-style
dashboard lists a catalog of tools; **Install** pulls/builds a tool's containers, **Open** launches its
web UI. Two AI routes:

- **Gateway route** — an LLM gateway section where provider keys (OpenRouter, Anthropic, OpenAI, Gemini,
  any OpenAI-compatible endpoint) are configured once and injected into every tool.
- **Claude Pro route** — an MCP server exposing the suite's tools to Claude Desktop / Claude Code, so
  Claude does the thinking and drives the tools. No provider key needed. (A Claude Pro subscription
  cannot be used as an API key in the gateway; this is the only way Pro is used.)

Single user (the owner). Runs on the owner's Windows PC.

## 2. Constraints

| Item | Value |
|---|---|
| Host | Windows 11, 16 GB RAM, RTX 4050 Laptop 6 GB VRAM |
| Container runtime | Podman 5.8.5, WSL machine `podman-machine-default`, **rootful**, VM disk at `E:\podman\ext4.vhdx` |
| Disk | All container data lives inside the Podman VM disk on E: (~58 GB free) |
| Exposure | localhost only in v1 (no LAN, no internet) |

Consequences: tools are installed on demand (not all at once), only one GPU tool runs at a time, and
no compose file references Windows paths.

## 3. Initial catalog (11 tools)

| id | Repo | Replaces | GPU | LLM | MCP actions (v1) |
|---|---|---|---|---|---|
| voicestudio | debpalash/VoiceStudio | ElevenLabs | yes | no | yes |
| next-ai-draw-io | DayuanJiang/next-ai-draw-io | Napkin.ai / Lucid AI | no | yes | yes |
| sd-webui | AUTOMATIC1111/stable-diffusion-webui | Midjourney | yes | no | yes |
| comfyui | Comfy-Org/ComfyUI | Midjourney / Runway | yes | no | yes |
| open-notebook | lfnovo/open-notebook | NotebookLM | no | yes | yes |
| openhands | OpenHands/OpenHands | Devin | no | yes | lifecycle only |
| openmanus | FoundationAgents/OpenManus | Manus | no | yes | lifecycle only |
| open-lovable | firecrawl/open-lovable | Lovable | no | yes | lifecycle only |
| bolt-diy | stackblitz-labs/bolt.diy | Bolt.new | no | yes | lifecycle only |
| dify | langgenius/dify | Zapier AI / GPTs | no | yes | lifecycle only |
| appflowy | AppFlowy-IO/AppFlowy (AppFlowy Cloud) | Notion AI | no | maybe | lifecycle only |

Known per-tool caveats: sd-webui has no official image (built from git); openhands needs the
container socket for its sandboxes; dify and appflowy are multi-container stacks; appflowy's main
client is a desktop app — only AppFlowy Cloud is self-hosted.

## 4. Architecture

```
Windows PC · Podman machine (rootful, disk on E:)
┌───────────────────────────────────────────────────────────────────────┐
│ myopensuite container  127.0.0.1:8080                                 │
│   React UI (Dashboard · Marketplace · LLM Gateway)                    │
│   FastAPI backend ── docker compose CLI ── /var/run/docker.sock ──┐   │
│   MCP endpoint /mcp (same backend)                                │   │
│   catalog/ (one folder per tool)                                  │   │
│                                                                   ▼   │
│ litellm container  :4000  ◀── OPENAI_BASE_URL ──  tool containers     │
│                                                   (mos-<id> projects) │
│ all on network mos-net                                                │
└───────────────────────────────────────────────────────────────────────┘
```

- **myopensuite**: one image. Python FastAPI backend, serves the built React frontend and the MCP
  endpoint (official MCP Python SDK, streamable HTTP). Contains the Compose v2 CLI.
- **Runtime access**: Podman's Docker-compatible API socket `/run/podman/podman.sock` is mounted into
  the container as `/var/run/docker.sock` (with `security_opt: [label=disable]`). The backend only
  speaks the Docker API / `docker compose`, so it runs unchanged on Docker later.
- **litellm**: the LLM gateway (BerriAI/litellm proxy).
- **Tools**: each runs as its own Compose project `mos-<id>` on the shared external network `mos-net`.
- The root `docker-compose.yml` starts `myopensuite` + `litellm` and creates `mos-net`. It is the only
  thing the owner runs (`podman compose up -d`).

## 5. Catalog format

```
catalog/<id>/
  app.yml              metadata
  docker-compose.yml   how it runs
  icon.png
  mcp.py               optional MCP tool actions
  NOTES.md             optional manual setup / verification notes
```

`app.yml`:

```yaml
id: voicestudio
name: VoiceStudio
replaces: ElevenLabs
description: Voice cloning, TTS, dubbing
repo: https://github.com/debpalash/VoiceStudio
port: 7801            # host port, unique across catalog
path: /               # appended to the Open URL
gpu: true             # participates in the GPU-exclusive rule
size_gb: 12           # estimate shown before install
llm:                  # optional: env var -> injected value (gateway_url | gateway_key | alias:<name>)
  OPENAI_BASE_URL: gateway_url
  OPENAI_API_KEY: gateway_key
  MODEL: alias:default
llm_manual: false     # true = tool is configured in its own UI; dashboard shows a "Connect to gateway" card
warnings: []          # shown on the tile, e.g. "Needs container socket access"
```

Compose conventions (enforced by the catalog lint test):

1. Joins external network `mos-net`.
2. Every published port binds `127.0.0.1:<port>`.
3. Named volumes only — no host bind mounts, except the container socket for tools that declare it in
   `warnings`.
4. GPU services request the GPU via CDI: `devices: ["nvidia.com/gpu=all"]`.
5. Tools without a published image use Compose's git build context
   (`build: { context: https://github.com/<repo>.git }`).
6. LLM values are referenced as `${VAR}` and supplied by the backend at start.

Shared volumes: `mos-models` (checkpoints shared by sd-webui and comfyui), `mos-outputs` (MCP outputs).

## 6. App lifecycle

Every action is one `docker compose -p mos-<id> -f catalog/<id>/docker-compose.yml` call.

| Action | Command | Notes |
|---|---|---|
| Install | `pull` or `build`, then `up -d` | shows `size_gb` first; background job, live log |
| Open | — | `http://localhost:<port><path>` in a new tab |
| Start | `up -d` | GPU rule applies; LLM env injected |
| Stop | `stop` | |
| Update | `pull`/`build`, then `up -d` | |
| Uninstall | `down`, plus `-v` only if "Also delete data" is ticked | confirm dialog; data kept by default |

**State** is derived from the runtime, never stored: `not_installed`, `stopped`, `starting`, `running`,
`error`, from `docker compose ls`/`ps` plus an HTTP probe on the port. `starting` → `running` when the
probe answers; `starting` → `error` after 3 minutes without an answer.

**GPU rule**: starting a `gpu: true` app first stops every other running `gpu: true` app. The UI
confirms ("This will stop ComfyUI. Continue?"); MCP `start_app` does it and reports what it stopped.

**Jobs**: install/update run in a background task, at most one job per app; the UI tails the job log.
Jobs are in-memory; if the backend restarts, a running job is reported as failed and can be retried.

## 7. LLM Gateway

UI page with:

- **Providers**: add/remove OpenRouter, Anthropic, OpenAI, Gemini, or Custom (OpenAI-compatible base URL
  + key). Keys are shown masked (last 4 chars) and never returned to the browser in full.
- **Aliases**: names tools ask for (`default`, `fast`, user-added) mapped to `provider/model`.
- **Test**: one-shot chat completion through the gateway per provider/alias; shows the raw error on
  failure.
- **Endpoint info**: `http://litellm:4000/v1` and that the key is auto-injected.

Mechanics: the backend writes LiteLLM `config.yaml` (aliases → models, keys as `os.environ/...`
references) and a `.env` with provider keys into the `mos-gateway` volume, then restarts the `litellm`
container. One LiteLLM master key, generated on first run, is what tools receive as `gateway_key`.

Injection: on Start, values from the app's `llm:` block are resolved and passed as environment to
`docker compose up`. Apps with `llm_manual: true` get a card in the dashboard with the exact URL, key
and model to paste. Which of the 11 apps support env-based configuration is verified per app during
implementation and recorded in its `app.yml`.

The gateway is optional: with no providers, tools still run; AI features inside them just won't work.

## 8. MCP server

Endpoint `http://localhost:8080/mcp` (streamable HTTP).

**Suite actions** (all apps): `list_apps`, `start_app(id)`, `stop_app(id)`, `install_app(id)`,
`uninstall_app(id)` (never deletes data), `app_logs(id, lines)`.

**App actions** (`catalog/<id>/mcp.py`, registered at startup):

| App | Actions | Via |
|---|---|---|
| voicestudio | `voice_list`, `voice_speak(text, voice)` | its OpenAI-compatible speech API |
| sd-webui | `sd_txt2img(prompt, negative, width, height, steps, seed)` | `/sdapi/v1/txt2img` (`--api`) |
| comfyui | `comfy_list_workflows`, `comfy_run(workflow, inputs)` | `/prompt` with workflows saved in a volume |
| next-ai-draw-io | `drawio_open(xml)` → URL | Claude authors the draw.io XML; mechanism to load it verified in implementation |
| open-notebook | `notebook_list`, `notebook_add_source(notebook, url_or_text)`, `notebook_ask(notebook, question)` | its REST API |

Rules:

- If the app is installed but stopped, the action starts it (GPU rule applies), waits for healthy, then
  runs. If not installed, it returns `"<id> is not installed — call install_app('<id>')"`.
- Outputs are written to `mos-outputs` and returned as `http://localhost:8080/files/<path>`; images are
  also returned inline as MCP image content.
- Long actions wait up to 10 minutes, then return a timeout error.

Connecting: Claude Code — `claude mcp add --transport http mos http://localhost:8080/mcp`; Claude
Desktop — the same URL in its connector config.

## 9. Error handling

| Failure | Behaviour |
|---|---|
| Container runtime unreachable | Banner on every page; API/MCP return "Podman isn't running — run `podman machine start`" |
| Install/update fails | Job marked `error`, full log kept, Retry button; app is not started |
| App not healthy within 3 min of start | Status `error`, last 50 log lines shown; same via `app_logs` |
| Gateway provider error | Test shows provider's error; tools keep running |
| MCP app action on missing/broken app | Plain-language message with the fixing action, no stack trace |
| Backend restart | Status re-read from runtime; settings persist in volumes; in-flight jobs marked failed |

## 10. Security (v1)

- Dashboard, MCP and all tool ports bound to `127.0.0.1`.
- No authentication in v1 (single user, localhost). Add a token before any tunnel/LAN exposure.
- Provider keys stored only in the `mos-gateway` volume; masked in the UI.
- Apps that mount the container socket (openhands) carry a visible warning.

## 11. Testing

- **Unit (pytest, no runtime)**: `app.yml` parsing/validation, GPU-rule selection, LiteLLM config
  generation, LLM env resolution.
- **Catalog lint**: every `catalog/*/` passes the conventions in §5.
- **End-to-end smoke** against real Podman with dummy app `catalog/_hello` (nginx): install → start →
  healthy → MCP `list_apps`/`start_app` → stop → uninstall.
- **GPU smoke**: CDI container runs `nvidia-smi` successfully. Gate for adding any GPU app.
- **Per-app MCP wrappers**: one documented manual check each in `catalog/<id>/NOTES.md`.

## 12. Repo layout

```
backend/        FastAPI app: api.py, compose.py, catalog.py, gpu.py, gateway.py, mcp_server.py, jobs.py
frontend/       React + Vite: Dashboard, Marketplace, Gateway
catalog/        <id>/app.yml, docker-compose.yml, icon.png, mcp.py?, NOTES.md?
gateway/        LiteLLM service definition and config template
tests/
docker-compose.yml
Dockerfile
docs/superpowers/specs/
```

## 13. Milestones

1. **Core** — GPU/CDI smoke test, backend, compose wrapper, catalog with `_hello`, minimal dashboard:
   install/start/stop/open.
2. **Marketplace UI** — CasaOS-style tiles, install log panel, GPU confirm, uninstall dialog.
3. **First real apps** — voicestudio, comfyui, next-ai-draw-io.
4. **LLM Gateway** — litellm service, providers/aliases page, env injection.
5. **MCP** — suite actions, then the five app-action wrappers.
6. **Remaining apps** — sd-webui, open-notebook, openhands, openmanus, open-lovable, bolt-diy, dify,
   appflowy.

## 14. Owner prerequisites

- Done: Podman machine recreated rootful, disk on `E:\podman`.
- To do: install `nvidia-container-toolkit` in the Podman machine and generate the CDI spec (exact
  commands in the implementation plan).

## 15. Out of scope for v1

Authentication; LAN/tunnel exposure; per-tool gateway keys, budgets and usage dashboards (need LiteLLM
with Postgres); local models via Ollama; automatic free-disk checks; catalog search/categories;
proxying other apps' MCP servers; streaming progress for long MCP actions; desktop-only tools
(Upscayl, Dyad, Continue, Screenpipe).
