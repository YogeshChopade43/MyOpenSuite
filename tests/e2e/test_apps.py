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


def test_voicestudio():
    install_and_wait("voicestudio")
    assert status("voicestudio") in ("stopped", "running")
    API.post("/api/apps/voicestudio/start?confirm=true").raise_for_status()
    wait(lambda: status("voicestudio") == "running", "voicestudio running", timeout=900)
    assert httpx.get("http://localhost:7801/health").status_code == 200
    gpu = subprocess.run(["podman", "exec", "mos-voicestudio-voicestudio-1", "nvidia-smi", "-L"],
                         capture_output=True, text=True)
    assert "RTX 4050" in gpu.stdout, gpu.stdout + gpu.stderr
    key = API.get("/api/apps/voicestudio/secrets").json()[0]
    assert key["name"] == "OMNIVOICE_API_KEY" and key["value"]


def test_comfyui():
    install_and_wait("comfyui")
    API.post("/api/apps/comfyui/start?confirm=true").raise_for_status()
    wait(lambda: status("comfyui") == "running", "comfyui running", timeout=600)
    stats = httpx.get("http://localhost:7802/system_stats").json()
    assert stats["devices"][0]["type"] == "cuda"


def test_gpu_rule_between_real_apps():
    # comfyui running (previous test), voicestudio installed
    r = API.post("/api/apps/voicestudio/start")
    assert r.status_code == 409 and r.json()["detail"] == {"conflicts": ["comfyui"]}
    assert API.post("/api/apps/voicestudio/start?confirm=true").json() == {"stopped": ["comfyui"]}
    wait(lambda: status("comfyui") == "stopped", "comfyui stopped")
    wait(lambda: status("voicestudio") == "running", "voicestudio running", timeout=900)
