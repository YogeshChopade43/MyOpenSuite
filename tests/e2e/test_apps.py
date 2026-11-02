"""End-to-end tests for real catalog apps. Downloads ~25 GB; run in file order against the running stack."""
import os
import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("MOS_E2E_APPS") != "1", reason="set MOS_E2E_APPS=1")

API = httpx.Client(base_url="http://localhost:8080", timeout=120, headers={"X-MOS": "1"})


def wait(cond, what, timeout=300):
    end = time.time() + timeout
    while not cond():
        assert time.time() < end, f"timed out waiting for {what}"
        time.sleep(3)


def status(id):
    return next(a for a in API.get("/api/apps").json() if a["id"] == id)["status"]


def install_and_wait(id, timeout=1800):
    """Install if needed; GPU apps end 'stopped' (install never starts them), others 'running'."""
    app = next(a for a in API.get("/api/apps").json() if a["id"] == id)
    if app["status"] == "not_installed":
        assert API.post(f"/api/apps/{id}/install").status_code == 202
        wait(lambda: API.get(f"/api/apps/{id}/job").json()["state"] != "running", f"{id} install", timeout)
        job = API.get(f"/api/apps/{id}/job").json()
        assert job["state"] == "done", "\n".join(job["log"][-30:])
    target = "stopped" if app["gpu"] else "running"
    wait(lambda: status(id) in (target, "running"), f"{id} {target}", timeout=600)


def test_next_ai_draw_io():
    install_and_wait("next-ai-draw-io")
    r = httpx.get("http://localhost:7803/", follow_redirects=True)
    assert r.status_code == 200 and "draw" in r.text.lower()
