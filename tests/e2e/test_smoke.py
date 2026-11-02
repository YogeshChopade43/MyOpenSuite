"""End-to-end smoke test against the running stack (podman compose up with MOS_DEV=1)."""
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("MOS_E2E") != "1", reason="set MOS_E2E=1")

API = httpx.Client(base_url="http://localhost:8080", timeout=120, headers={"X-MOS": "1"})


def wait(cond, what, timeout=300):
    end = time.time() + timeout
    while not cond():
        assert time.time() < end, f"timed out waiting for {what}"
        time.sleep(2)


def status(id):
    return next(a for a in API.get("/api/apps").json() if a["id"] == id)["status"]


def secret(id):
    return API.get(f"/api/apps/{id}/secrets").json()[0]["value"]


def test_hello_lifecycle():
    if status("hello") != "not_installed":
        API.delete("/api/apps/hello").raise_for_status()
    assert API.post("/api/apps/hello/install").status_code == 202
    wait(lambda: API.get("/api/apps/hello/job").json()["state"] != "running", "install job")
    assert API.get("/api/apps/hello/job").json()["state"] == "done"
    wait(lambda: status("hello") == "running", "hello running")
    assert httpx.get("http://localhost:7800/").status_code == 200

    token = secret("hello")
    assert token and token == secret("hello")
    out = subprocess.run(["podman", "exec", "mos-hello-hello-1", "printenv", "HELLO_TOKEN"],
                         capture_output=True, text=True).stdout.strip()
    assert out == token

    API.post("/api/apps/hello/stop").raise_for_status()
    wait(lambda: status("hello") == "stopped", "hello stopped")
    API.post("/api/apps/hello/start").raise_for_status()
    wait(lambda: status("hello") == "running", "hello running again")

    API.delete("/api/apps/hello").raise_for_status()
    wait(lambda: status("hello") == "not_installed", "hello uninstalled")


def test_secret_survives_rebuild():
    before = secret("hello")
    root = Path(__file__).resolve().parents[2]
    subprocess.run(["podman", "compose", "up", "-d", "--build"], cwd=root, check=True,
                   env={**os.environ, "MOS_DEV": "1"}, capture_output=True)

    def healthy():
        try:
            return API.get("/api/health").json()["runtime"]
        except httpx.HTTPError:
            return False

    wait(healthy, "dashboard back up")
    assert secret("hello") == before
