"""Thin wrapper over the `docker compose` CLI (talks to Podman's Docker-compatible socket)."""
import json
import os
import subprocess
from collections.abc import Callable, Iterator

import httpx

from backend.catalog import App
from backend.idle import browser_connected

Runner = Callable[[list[str], dict[str, str] | None], tuple[int, str]]
Streamer = Callable[[list[str], dict[str, str] | None], Iterator[str]]


class ComposeError(Exception):
    def __init__(self, returncode: int, output: str):
        super().__init__("\n".join(output.splitlines()[-20:]))
        self.returncode = returncode


def _env(env: dict[str, str] | None) -> dict[str, str]:
    return {**os.environ, **(env or {})}


# `up` waits for a stack's healthchecks (AppFlowy's first-boot migrations take minutes); queries stay short.
LIFECYCLE_TIMEOUT = 900
LIFECYCLE = {"up", "stop", "down"}


def run_subprocess(cmd: list[str], env: dict[str, str] | None) -> tuple[int, str]:
    timeout = LIFECYCLE_TIMEOUT if LIFECYCLE & set(cmd) else 120
    try:
        p = subprocess.run(cmd, env=_env(env), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return 124, f"{e.output or ''}\ntimed out after {timeout}s"
    return p.returncode, p.stdout + p.stderr


def stream_subprocess(cmd: list[str], env: dict[str, str] | None) -> Iterator[str]:
    p = subprocess.Popen(cmd, env=_env(env), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail: list[str] = []
    for line in p.stdout:
        line = line.rstrip("\n")
        tail = (tail + [line])[-20:]
        yield line
    if p.wait():
        raise ComposeError(p.returncode, "\n".join(tail))


def read_cpu_seconds(ids: list[str]) -> float:
    """Total CPU time used by containers. `docker stats` percentages are wrong under Podman, so use the raw counter."""
    with httpx.Client(transport=httpx.HTTPTransport(uds="/var/run/docker.sock"), base_url="http://podman", timeout=30) as c:
        stats = [c.get(f"/containers/{i}/stats", params={"stream": "false"}).json() for i in ids]
    return sum(s["cpu_stats"]["cpu_usage"]["total_usage"] for s in stats) / 1e9


class Compose:
    def __init__(self, runner: Runner = run_subprocess, streamer: Streamer = stream_subprocess,
                 env_for: Callable[[App], dict[str, str]] = lambda app: {},
                 cpu_reader: Callable[[list[str]], float] = read_cpu_seconds):
        self._run, self._stream, self._env_for, self._cpu_reader = runner, streamer, env_for, cpu_reader

    def _env(self, app: App, env: dict[str, str] | None) -> dict[str, str] | None:
        merged = {**self._env_for(app), **(env or {})}
        return merged or None

    def cmd(self, app: App, *args: str) -> list[str]:
        return ["docker", "compose", "-p", f"mos-{app.id}",
                "-f", str(app.dir / "docker-compose.yml"), *args]

    def projects(self) -> dict[str, str]:
        code, out = self._run(["docker", "compose", "ls", "-a", "--format", "json"], None)
        if code:
            raise ComposeError(code, out)
        if not out.strip():
            return {}
        return {p["Name"]: p["Status"] for p in json.loads(out) if p["Name"].startswith("mos-")}

    def runtime_ok(self) -> bool:
        return self._run(["docker", "info"], None)[0] == 0

    def run(self, app: App, *args: str, env: dict[str, str] | None = None) -> str:
        code, out = self._run(self.cmd(app, *args), self._env(app, env))
        if code:
            raise ComposeError(code, out)
        return out

    def stream(self, app: App, *args: str, env: dict[str, str] | None = None) -> Iterator[str]:
        return self._stream(self.cmd(app, *args), self._env(app, env))

    def logs(self, app: App, lines: int = 50) -> str:
        return self.run(app, "logs", "--no-color", "--tail", str(lines))

    def activity(self, app: App) -> tuple[bool, float]:
        """(a browser is connected, CPU seconds used so far by the app's containers)."""
        proc = self.run(app, "exec", "-T", app.id, "sh", "-c",
                        "cat /proc/net/tcp /proc/net/tcp6 /proc/net/route 2>/dev/null; true")
        return browser_connected(proc), self._cpu_reader(self.run(app, "ps", "-q").split())
