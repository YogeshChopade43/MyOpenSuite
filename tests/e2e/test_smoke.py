"""End-to-end smoke test against the running stack (podman compose up with MOS_DEV=1)."""
import os
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("MOS_E2E") != "1", reason="set MOS_E2E=1")

API = httpx.Client(base_url="http://localhost:8080", timeout=120)


def wait(cond, what, timeout=300):
    end = time.time() + timeout
    while not cond():
        assert time.time() < end, f"timed out waiting for {what}"
        time.sleep(2)


def status(id):
    return next(a for a in API.get("/api/apps").json() if a["id"] == id)["status"]


def test_hello_lifecycle():
    if status("hello") != "not_installed":
        API.delete("/api/apps/hello").raise_for_status()
    assert API.post("/api/apps/hello/install").status_code == 202
    wait(lambda: API.get("/api/apps/hello/job").json()["state"] != "running", "install job")
    assert API.get("/api/apps/hello/job").json()["state"] == "done"
    wait(lambda: status("hello") == "running", "hello running")
    assert httpx.get("http://localhost:7800/").status_code == 200

    API.post("/api/apps/hello/stop").raise_for_status()
    wait(lambda: status("hello") == "stopped", "hello stopped")
    API.post("/api/apps/hello/start").raise_for_status()
    wait(lambda: status("hello") == "running", "hello running again")

    API.delete("/api/apps/hello").raise_for_status()
    wait(lambda: status("hello") == "not_installed", "hello uninstalled")
