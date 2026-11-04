"""Catalog of installable apps: one folder per app with app.yml + docker-compose.yml."""
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REQUIRED = ("id", "name", "replaces", "description", "repo", "port", "internal_port")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
LLM_RE = re.compile(r"^(gateway_url|gateway_key|alias:.+)$")
SECRET_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
GPU_DEVICE = "nvidia.com/gpu=all"  # CDI form, verified in docs/podman-gpu.md
SOCKET = "/var/run/docker.sock"


class CatalogError(Exception):
    pass


@dataclass(frozen=True)
class App:
    id: str
    name: str
    replaces: str
    description: str
    repo: str
    port: int
    internal_port: int
    dir: Path
    path: str = "/"
    gpu: bool = False
    size_gb: float = 0
    llm: dict[str, str] = field(default_factory=dict)
    llm_manual: bool = False
    warnings: list[str] = field(default_factory=list)
    dev: bool = False
    secrets: dict[str, str] = field(default_factory=dict)  # env var -> description
    start_timeout: int = 180  # seconds before a running-but-unresponsive app shows "error"
    idle_stop: bool = True  # False for apps that work unattended with little CPU (an agent waiting on its AI)


def _load_app(app_dir: Path) -> App:
    f = app_dir / "app.yml"
    try:
        data = yaml.safe_load(f.read_text())
    except yaml.YAMLError as e:
        raise CatalogError(f"{f}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise CatalogError(f"{f}: must be a mapping")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise CatalogError(f"{f}: missing field(s): {', '.join(missing)}")
    if not ID_RE.match(str(data["id"])):
        raise CatalogError(f"{f}: id {data['id']!r} must match {ID_RE.pattern}")
    if data["id"] != app_dir.name:
        raise CatalogError(f"{f}: id {data['id']!r} does not match folder {app_dir.name!r}")
    for k in ("port", "internal_port"):
        if not isinstance(data[k], int) or not 1 <= data[k] <= 65535:
            raise CatalogError(f"{f}: {k} must be an integer 1-65535")
    if not str(data.get("path", "/")).startswith("/"):
        raise CatalogError(f"{f}: path must start with /")
    for var, value in (data.get("llm") or {}).items():
        if not LLM_RE.match(str(value)):
            raise CatalogError(f"{f}: llm.{var} must be gateway_url, gateway_key or alias:<name>")
    for var in data.get("secrets") or {}:
        if not SECRET_RE.match(str(var)):
            raise CatalogError(f"{f}: secrets name {var!r} must match {SECRET_RE.pattern}")
    unknown = set(data) - (set(App.__dataclass_fields__) - {"dir"})
    if unknown:
        raise CatalogError(f"{f}: unknown field(s): {', '.join(sorted(unknown))}")
    return App(dir=app_dir, **data)


def _volume_source(v) -> str:
    if isinstance(v, dict):
        return str(v.get("source", "")) if v.get("type") == "bind" else ""
    parts = str(v).split(":")
    return parts[0] if len(parts) > 1 else ""


def lint_compose(app: App) -> list[str]:
    """Check an app's compose file against the catalog conventions (spec §5)."""
    f = app.dir / "docker-compose.yml"
    text = f.read_text()
    doc = yaml.safe_load(text) or {}
    services = doc.get("services") or {}
    out = []
    if app.id not in services:
        out.append(f"{f}: needs a service named '{app.id}' (used for probing over mos-net)")
    if not ((doc.get("networks") or {}).get("mos-net") or {}).get("external"):
        out.append(f"{f}: top-level network mos-net must be declared with external: true")
    has_gpu = False
    for name, svc in services.items():
        svc = svc or {}
        nets = svc.get("networks") or []  # list or mapping; `in` works for both
        # Only the main service joins the shared network, so stacks' generic names (db, redis) never collide.
        if name == app.id:
            if "mos-net" not in nets:
                out.append(f"{f}: service {name} must join mos-net")
            if len(services) > 1 and "default" not in nets:
                out.append(f"{f}: service {name} must also join the default network to reach its stack")
        elif "mos-net" in nets:
            out.append(f"{f}: service {name} must not join mos-net (only the main service may)")
        # Without a grace period a slow first boot (migrations) marks the service unhealthy and `up` fails.
        if svc.get("healthcheck") and "start_period" not in svc["healthcheck"]:
            out.append(f"{f}: service {name} healthcheck needs start_period")
        for p in svc.get("ports") or []:
            ok = p.get("host_ip") == "127.0.0.1" if isinstance(p, dict) else str(p).startswith("127.0.0.1:")
            if not ok:
                out.append(f"{f}: service {name} port {p} must bind 127.0.0.1")
        for v in svc.get("volumes") or []:
            src = _volume_source(v)
            if src.startswith((".", "/")) or "\\" in src:
                if src != SOCKET:
                    out.append(f"{f}: service {name} has host bind mount {src}; use a named volume")
                elif not app.warnings:
                    out.append(f"{f}: service {name} mounts the container socket; add an entry to warnings")
        if GPU_DEVICE in (svc.get("devices") or []):
            has_gpu = True
    if app.gpu and not has_gpu:
        out.append(f"{f}: gpu: true but no service requests the GPU via devices: [\"{GPU_DEVICE}\"]")
    for var in app.secrets:
        if "${" + var + "}" not in text and "${" + var + ":" not in text:
            out.append(f"{f}: secret {var} is not used as ${{{var}}} in the compose file")
    for vname, vdef in (doc.get("volumes") or {}).items():
        if vname.startswith("mos-") and not (vdef or {}).get("external"):
            out.append(f"{f}: shared volume {vname} must be declared with external: true")
    return out


def load_catalog(root: Path) -> dict[str, App]:
    apps: dict[str, App] = {}
    ports: dict[int, str] = {}
    for f in sorted(root.glob("*/app.yml")):
        app = _load_app(f.parent)
        if app.port in ports:
            raise CatalogError(f"{f}: port {app.port} already used by {ports[app.port]}")
        ports[app.port] = app.id
        apps[app.id] = app
    return apps
