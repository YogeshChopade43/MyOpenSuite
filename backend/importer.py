"""Turn a GitHub link into a catalog entry. Plain rules, and the owner reviews the result before anything runs."""
import io
import posixpath
import re
import shlex
import shutil
import tarfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx
import yaml

from backend.catalog import App, _load_app, lint_compose

FIRST_PORT = 7810
MAX_TARBALL = 200 * 1024 * 1024
MAX_UNPACKED = 800 * 1024 * 1024
COMPOSE_PATHS = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
                 "docker/docker-compose.yml", "docker/docker-compose.yaml", "docker/compose.yml", "docker/compose.yaml",
                 "deploy/docker-compose.yml", "docker-compose.prod.yml")
README_PATHS = ("README.md", "readme.md", "Readme.md", "README.rst")
KEPT_KEYS = ("command", "entrypoint", "working_dir", "user", "shm_size", "tmpfs", "init", "stop_grace_period")
OPEN_LICENCES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0", "EPL-2.0", "Unlicense", "Zlib",
                 "GPL-2.0", "GPL-3.0", "LGPL-2.1", "LGPL-3.0", "AGPL-3.0", "EUPL-1.2"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]*(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|_KEY)$")
PLACEHOLDER = re.compile(r"^(|change[-_ ]?me.*|password|secret|example|xxx+|your[-_ ].*|<.*>)$", re.I)
IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._/:@-]*$")
RUN_VALUE_FLAGS = {"--name", "--restart", "-h", "--hostname", "--pull", "--platform", "--memory", "-m", "--ulimit",
                   "--label", "-l", "--add-host", "--gpus", "--mount", "--dns", "--stop-timeout", "--log-driver",
                   "--log-opt", "--cpus"}
SAFE_CAPS = {"NET_BIND_SERVICE", "CHOWN", "SETUID", "SETGID", "DAC_OVERRIDE", "FOWNER", "KILL"}


class ImportRefused(Exception):
    pass


def parse_repo(url: str) -> tuple[str, str]:
    parts = urlsplit(url.strip())
    bits = [b for b in parts.path.split("/") if b]
    if parts.scheme != "https" or parts.netloc not in ("github.com", "www.github.com") or len(bits) < 2:
        raise ImportRefused("Paste a link like https://github.com/owner/repo")
    owner, name = bits[0], bits[1].removesuffix(".git")
    if ".." in bits or not (NAME_RE.match(owner) and NAME_RE.match(name)):
        raise ImportRefused("Paste a link like https://github.com/owner/repo")
    return owner, name


def image_ref(image: str) -> str:
    """Podman needs a full name: `nginx` is ambiguous, `docker.io/library/nginx` is not."""
    first = image.split("/")[0]
    if "/" in image and ("." in first or ":" in first or first == "localhost"):
        return image
    return f"docker.io/{image}" if "/" in image else f"docker.io/library/{image}"


def parse_run(line: str) -> dict:
    """A `docker run` line as a compose service. Dangerous flags are kept so `convert` can refuse them."""
    tokens = shlex.split(line)
    tokens = tokens[tokens.index("run") + 1:]
    svc: dict = {}

    def add(key, value):
        svc.setdefault(key, []).append(value)

    def env(pair):
        k, _, v = pair.partition("=")
        svc.setdefault("environment", {})[k] = "" if v.startswith("$") else v.replace("$", "$$")

    handlers = {"-p": lambda v: add("ports", v), "--publish": lambda v: add("ports", v),
                "-v": lambda v: add("volumes", v), "--volume": lambda v: add("volumes", v),
                "-e": env, "--env": env, "--env-file": lambda v: svc.__setitem__("env_file", v),
                "--network": lambda v: svc.__setitem__("network_mode", v), "--net": lambda v: svc.__setitem__("network_mode", v),
                "--pid": lambda v: svc.__setitem__("pid", v), "--ipc": lambda v: svc.__setitem__("ipc", v),
                "--cap-add": lambda v: add("cap_add", v), "--device": lambda v: add("devices", v),
                "--security-opt": lambda v: add("security_opt", v),
                "-w": lambda v: svc.__setitem__("working_dir", v), "--workdir": lambda v: svc.__setitem__("working_dir", v),
                "-u": lambda v: svc.__setitem__("user", v), "--user": lambda v: svc.__setitem__("user", v),
                "--entrypoint": lambda v: svc.__setitem__("entrypoint", v), "--shm-size": lambda v: svc.__setitem__("shm_size", v),
                "--tmpfs": lambda v: add("tmpfs", v)}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if not t.startswith("-"):
            svc["image"] = t
            if tokens[i + 1:]:
                svc["command"] = [c.replace("$", "$$") for c in tokens[i + 1:]]
            break
        flag, eq, value = t.partition("=")
        if flag == "--privileged":
            svc["privileged"] = True
        elif flag == "--gpus":
            svc["deploy"] = {"gpu": True}
            i += 0 if eq else 1
        elif flag in handlers:
            if not eq:
                i += 1
                value = tokens[i] if i < len(tokens) else ""
            handlers[flag](value)
        elif flag in RUN_VALUE_FLAGS and not eq:
            i += 1
        i += 1
    return svc


def find_run(readme: str) -> dict | None:
    """The first usable `docker run` line: publishes a port and names a real image, not a placeholder or a local build."""
    text = re.sub(r"\\\r?\n", " ", readme)
    local = set(re.findall(r"build\b[^\n]*?-t\s+(\S+)", text))
    for m in re.finditer(r"(?:^|\n)[ \t]*(?:[$#>][ \t]*)?(?:sudo[ \t]+)?(?:docker|podman)[ \t]+run\b[^\n`]*", text):
        try:
            svc = parse_run(m.group().strip().lstrip("$#> "))
        except (ValueError, IndexError):
            continue
        image = svc.get("image", "")
        if svc.get("ports") and IMAGE_RE.match(image) and image not in local and image.split(":")[0] != "image":
            return svc
    return None


@dataclass
class Plan:
    compose: dict = field(default_factory=dict)
    internal_port: int = 0
    secrets: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def _container_port(p) -> int | None:
    if isinstance(p, dict):
        return p.get("target")
    s = re.sub(r"\$\{[^}]*\}", "0", str(p)).split("/")[0]
    m = re.match(r"\d+", s.split(":")[-1])
    return int(m.group()) if m else None


def _volumes(volumes, plan: Plan) -> tuple[list[str], dict]:
    out, named = [], {}
    for v in volumes or []:
        if isinstance(v, dict):
            src, target = str(v.get("source", "")), str(v.get("target", ""))
        else:
            parts = str(v).split(":")
            src, target = (parts[0], parts[1]) if len(parts) > 1 else ("", parts[0])
        if src.endswith(".sock") or "docker.sock" in target:
            plan.blockers.append("It asks for control of the container system (the socket), which gives it full access.")
            continue
        if target in ("/etc/localtime", "/etc/timezone"):
            continue
        if not src:
            out.append(target)
            continue
        if re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", src):  # already a named volume
            named[src] = {}
            out.append(f"{src}:{target}")
            continue
        if posixpath.normpath(src).strip("./") == "":  # the repo itself, a dev setup: the image already has the code
            continue
        base = PurePosixPath(src).name
        if PurePosixPath(src).suffix or base.startswith("."):
            plan.warnings.append(f"Its config file {src} isn't carried over, so it starts with defaults.")
            continue
        name = re.sub(r"[^a-z0-9]+", "-", PurePosixPath(target).name.lower()).strip("-") or "data"
        if name in named:  # /var/cache/ntfy and /etc/ntfy must stay two volumes
            name = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-")
        named[name] = {}
        out.append(f"{name}:{target}")
    return out, named


def _environment(env, plan: Plan) -> dict:
    if isinstance(env, list):
        env = dict((str(e).split("=", 1) + [""])[:2] for e in env)
    out = {}
    for k, v in (env or {}).items():
        k, v = str(k), "" if v is None else str(v)
        if SECRET_NAME.match(k) and (PLACEHOLDER.match(v) or v == "${" + k + "}"):
            plan.secrets[k] = "Generated by MyOpenSuite"
            v = "${" + k + "}"
        out[k] = v
    return out


def _build(build, base: str, plan: Plan) -> dict | None:
    spec = {"context": build} if isinstance(build, str) else dict(build)
    context = posixpath.normpath(posixpath.join(base, str(spec.get("context", "."))))
    if context.startswith(("..", "/")):
        plan.blockers.append("It builds from outside its own repository.")
        return None
    out = {"context": "./src" if context == "." else f"./src/{context}"}
    if spec.get("dockerfile"):
        out["dockerfile"] = str(spec["dockerfile"])
    return out


def convert(service: dict, app_id: str, port: int, base: str = "") -> Plan:
    """Rewrite one service to the catalog's rules. Only known-safe settings survive."""
    plan = Plan()
    svc = service or {}
    if svc.get("privileged"):
        plan.blockers.append("It asks for privileged mode, which gives it full access to the system.")
    for key in ("network_mode", "pid", "ipc"):
        if svc.get(key) == "host":
            plan.blockers.append(f"It asks to share the host's {key.replace('_mode', '')}, which removes its isolation.")
    caps = {str(c).upper().removeprefix("CAP_") for c in svc.get("cap_add") or []}
    if caps - SAFE_CAPS:
        plan.blockers.append(f"It asks for system capabilities: {', '.join(sorted(caps - SAFE_CAPS))}.")
    if svc.get("devices"):
        plan.blockers.append("It asks for direct access to hardware devices.")
    if any("unconfined" in str(o) or "disable" in str(o) for o in svc.get("security_opt") or []):
        plan.blockers.append("It asks to switch off container security.")

    ports = [p for p in map(_container_port, svc.get("ports") or []) if p]
    if not ports:
        plan.blockers.append("It has no web port, so there is nothing for the dashboard to open.")
    else:
        plan.internal_port = ports[0]

    out: dict = {}
    if svc.get("image"):
        out["image"] = image_ref(str(svc["image"]))
    elif svc.get("build"):
        built = _build(svc["build"], base, plan)
        if built:
            out["build"] = built
    else:
        plan.blockers.append("It names no image to run.")
    out.update({k: svc[k] for k in KEPT_KEYS if k in svc})
    out["ports"] = [f"127.0.0.1:{port}:{plan.internal_port}"]
    volumes, named = _volumes(svc.get("volumes"), plan)
    if volumes:
        out["volumes"] = volumes
    environment = _environment(svc.get("environment"), plan)
    if environment:
        out["environment"] = environment
    if svc.get("env_file"):
        plan.warnings.append("Its settings file isn't carried over; it may need settings added by hand.")
    if svc.get("deploy"):
        plan.warnings.append("GPU settings were removed, so it runs on the CPU.")
    out["networks"] = ["mos-net"]
    out["restart"] = "unless-stopped"
    plan.compose = {"services": {app_id: out}, "networks": {"mos-net": {"external": True}}}
    if named:
        plan.compose["volumes"] = named
    return plan


@dataclass
class Preview:
    url: str
    full_name: str
    sha: str
    id: str
    name: str
    description: str
    stars: int
    license: str
    port: int = 0
    internal_port: int = 0
    source: str = ""
    image: str = ""
    build: bool = False
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    plan: Plan | None = None

    def json(self) -> dict:
        out = asdict(self)
        out.pop("plan")
        return out


class GitHub:
    """Every URL is built from a repo name that passed `parse_repo`, so links can't reach anywhere else."""

    def __init__(self):
        self._c = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "MyOpenSuite"})

    def repo(self, owner: str, name: str) -> dict:
        r = self._c.get(f"https://api.github.com/repos/{owner}/{name}")
        if r.status_code == 404:
            raise ImportRefused("That repository doesn't exist or isn't public.")
        if r.status_code in (403, 429):
            raise ImportRefused("GitHub's hourly limit is used up. Try again in a while.")
        r.raise_for_status()
        return r.json()

    def sha(self, full_name: str, branch: str) -> str:
        r = self._c.get(f"https://api.github.com/repos/{full_name}/commits/{branch}",
                        headers={"Accept": "application/vnd.github.sha"})
        if r.status_code in (403, 429):
            raise ImportRefused("GitHub's hourly limit is used up. Try again in a while.")
        r.raise_for_status()
        return r.text.strip()

    def text(self, full_name: str, ref: str, path: str) -> str | None:
        r = self._c.get(f"https://raw.githubusercontent.com/{full_name}/{ref}/{path}")
        return r.text if r.status_code == 200 else None

    def tarball(self, full_name: str, ref: str) -> bytes:
        # ponytail: held in memory, capped at MAX_TARBALL; stream to disk if bigger repos matter
        out = bytearray()
        with self._c.stream("GET", f"https://codeload.github.com/{full_name}/tar.gz/{ref}") as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                out += chunk
                if len(out) > MAX_TARBALL:
                    raise ImportRefused("The repository is too big to build here.")
        return bytes(out)

    def avatar(self, owner: str) -> bytes | None:
        r = self._c.get(f"https://github.com/{owner}.png?size=128")
        return r.content if r.status_code == 200 else None


def _first(gh, full_name: str, ref: str, paths) -> tuple[str, str] | None:
    for p in paths:
        text = gh.text(full_name, ref, p)
        if text is not None:
            return p, text
    return None


def _services(text: str) -> dict:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    services = doc.get("services") if isinstance(doc, dict) else None
    return services if isinstance(services, dict) else {}


def _pick(gh, full_name: str, ref: str) -> tuple[str, dict, str] | str:
    """(source, service, compose folder), or the reason nothing can run. Published images beat building from source."""
    found = _first(gh, full_name, ref, COMPOSE_PATHS)
    services = _services(found[1]) if found else {}
    only = next(iter(services.values())) if len(services) == 1 else None
    if isinstance(only, dict) and only.get("build") and "/" not in str(only.get("image", "/")):
        only = {k: v for k, v in only.items() if k != "image"}  # a name for the local build, not a published image
    if isinstance(only, dict) and only.get("image"):
        return "compose", only, ""
    readme = _first(gh, full_name, ref, README_PATHS)
    run = find_run(readme[1]) if readme else None
    if run:
        return "docker run", run, ""
    if isinstance(only, dict) and only.get("build"):
        return "compose", only, posixpath.dirname(found[0])
    if len(services) > 1:
        return "This is a multi-container stack, which needs setting up by hand."
    dockerfile = gh.text(full_name, ref, "Dockerfile")
    if dockerfile is not None:
        exposed = re.findall(r"\d+", " ".join(re.findall(r"(?im)^\s*EXPOSE\s+(.+)$", dockerfile)))
        return "Dockerfile", {"build": ".", "ports": [p for p in exposed if p != "22"][:1]}, ""
    return "No setup was found: no compose file, no `docker run` line and no Dockerfile."


def inspect(url: str, gh, apps: dict[str, App], sha: str | None = None) -> Preview:
    owner, name = parse_repo(url)
    info = gh.repo(owner, name)
    full_name = info["full_name"]
    sha = sha or gh.sha(full_name, info["default_branch"])
    if not re.fullmatch(r"[0-9a-f]{6,40}", sha):
        raise ImportRefused("That review is out of date. Check the link again.")
    app_id = re.sub(r"[^a-z0-9]+", "-", info["name"].lower()).strip("-")
    licence = (info.get("license") or {}).get("spdx_id") or "None"
    p = Preview(url=info.get("html_url", url), full_name=full_name, sha=sha, id=app_id, name=info["name"],
                description=(info.get("description") or "Imported from GitHub.")[:300],
                stars=info.get("stargazers_count", 0), license=licence)
    if app_id in apps:
        p.blockers.append(f"{apps[app_id].name} is already in your catalog.")
        return p
    picked = _pick(gh, full_name, sha)
    if isinstance(picked, str):
        p.blockers.append(picked)
        return p
    p.source, service, base = picked
    used = {a.port for a in apps.values()}
    p.port = next(n for n in range(FIRST_PORT, 65535) if n not in used)
    plan = convert(service, app_id, p.port, base)
    p.plan, p.internal_port = plan, plan.internal_port
    p.blockers += plan.blockers
    p.warnings += plan.warnings
    built = plan.compose["services"][app_id]
    p.image, p.build = built.get("image", ""), "build" in built
    if p.build:
        p.warnings.append("It builds from source: slow, and heavy on memory and disk.")
    if p.image and (":" not in p.image.rsplit("/", 1)[-1] or p.image.endswith(":latest")):
        p.warnings.append("It uses a moving version tag, so pressing Update can change what you run.")
    if licence not in OPEN_LICENCES:
        p.warnings.append(f"Its licence isn't clearly open source ({licence}); check it before relying on it.")
    if info.get("archived"):
        p.warnings.append("The project is archived, so it gets no more updates.")
    return p


def _unpack(data: bytes, dest: Path) -> None:
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        for m in t:
            parts = PurePosixPath(m.name).parts[1:]  # drop GitHub's top folder
            if ".." in parts or PurePosixPath(m.name).is_absolute():
                raise ImportRefused("The repository's archive tried to write outside its folder.")
            if not parts:
                continue
            total += m.size
            if total > MAX_UNPACKED:
                raise ImportRefused("The repository is too big to build here.")
            m.name = "/".join(parts)
            try:
                t.extract(m, dest, filter="data")
            except tarfile.FilterError:
                continue  # a link pointing outside the repo: skip it, nothing is written


def save(p: Preview, root: Path, replaces: str, gh) -> App:
    if p.blockers or not p.plan:
        raise ImportRefused(p.blockers[0] if p.blockers else "Nothing to import.")
    folder = root / p.id
    if folder.exists():
        raise ImportRefused(f"{p.name} is already in your catalog.")
    try:
        folder.mkdir(parents=True)
        (folder / "docker-compose.yml").write_text(yaml.safe_dump(p.plan.compose, sort_keys=False))
        entry = {"id": p.id, "name": p.name, "replaces": replaces.strip()[:80], "description": p.description,
                 "repo": p.url, "port": p.port, "internal_port": p.internal_port, "category": "Imported",
                 "imported": True, "start_timeout": 600}
        if p.plan.secrets:
            entry["secrets"] = p.plan.secrets
        (folder / "app.yml").write_text(yaml.safe_dump(entry, sort_keys=False))
        if p.build:
            _unpack(gh.tarball(p.full_name, p.sha), folder / "src")
        icon = gh.avatar(p.full_name.split("/")[0])
        if icon:
            (folder / "icon.png").write_bytes(icon)
        app = _load_app(folder)
        problems = lint_compose(app)
        if problems:
            raise ImportRefused(f"The converted setup failed the catalog checks: {problems[0]}")
        return app
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
