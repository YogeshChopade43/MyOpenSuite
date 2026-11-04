"""Real imports from GitHub, one at a time. Only repos above 20k stars that need no GPU; downloads several GB."""
import os
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("MOS_E2E_IMPORT") != "1", reason="set MOS_E2E_IMPORT=1")

API = httpx.Client(base_url="http://localhost:8080", timeout=180, headers={"X-MOS": "1"})
REPOS = os.environ.get("MOS_IMPORT_REPOS", "louislam/uptime-kuma").split()


def status(id):
    return next((a["status"] for a in API.get("/api/apps").json() if a["id"] == id), None)


@pytest.mark.parametrize("repo", REPOS)
def test_import_runs_and_cleans_up(repo):
    url = f"https://github.com/{repo}"
    p = API.post("/api/import/preview", json={"url": url}).json()
    assert p.get("blockers") == [], p
    id = p["id"]
    assert API.post("/api/import", json={"url": url, "sha": p["sha"]}).status_code == 200
    try:
        assert API.post(f"/api/apps/{id}/install").status_code == 202
        end = time.time() + 1500
        while API.get(f"/api/apps/{id}/job").json()["state"] == "running":
            assert time.time() < end, "install timed out"
            time.sleep(5)
        job = API.get(f"/api/apps/{id}/job").json()
        assert job["state"] == "done", "\n".join(job["log"][-20:])
        end = time.time() + 300
        while status(id) != "running":
            assert time.time() < end and status(id) != "error", API.get(f"/api/apps/{id}/logs").text[-1500:]
            time.sleep(3)
        r = httpx.get(f"http://localhost:{p['port']}/", follow_redirects=True, timeout=30)
        assert r.status_code < 500, r.status_code
    finally:
        API.delete(f"/api/apps/{id}?delete_data=true")
    assert status(id) is None
