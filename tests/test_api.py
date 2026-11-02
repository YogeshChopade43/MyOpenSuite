import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import RUNTIME_DOWN_MSG, create_app
from backend.catalog import App
from backend.compose import Compose
from backend.secrets_store import SecretStore


def app(id, port, gpu=False, dev=False, secrets=None):
    return App(id=id, name=id, replaces="x", description="x", repo="x",
               port=port, internal_port=80, dir=Path("catalog") / id, gpu=gpu, dev=dev,
               secrets=secrets or {})


APPS = {"hello": app("hello", 7800, dev=True), "sd": app("sd", 7801, gpu=True, secrets={"SD_KEY": "Admin key"}),
        "comfy": app("comfy", 7802, gpu=True)}


class Fake:
    """Command runner/streamer for Compose: records commands, answers ls/info."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.projects: dict[str, str] = {}
        self.runtime = True
        self.gate: threading.Event | None = None

    def run(self, cmd, env):
        if cmd == ["docker", "info"]:
            return (0 if self.runtime else 1), ""
        if cmd[2:4] == ["ls", "-a"]:
            return 0, json.dumps([{"Name": k, "Status": v} for k, v in self.projects.items()])
        self.calls.append(cmd)
        return 0, "logs here" if "logs" in cmd else ""

    def stream(self, cmd, env):
        self.calls.append(cmd)
        if self.gate:
            self.gate.wait(2)
        yield "ok"

    def args_for(self, app_id):
        return [c[6:] for c in self.calls if c[3] == f"mos-{app_id}"]


@pytest.fixture
def env(tmp_path):
    fake = Fake()
    probes: dict[str, bool] = {}
    clock = {"t": 0.0}
    holder = {}

    def client(show_dev=False):
        api = create_app(APPS, Compose(runner=fake.run, streamer=fake.stream),
                         probe=lambda a: probes.get(a.id, False),
                         clock=lambda: clock["t"], show_dev=show_dev,
                         secrets=SecretStore(tmp_path / "s.json"))
        holder["c"] = TestClient(api, base_url="http://localhost", headers={"X-MOS": "1"})
        return holder["c"]

    return fake, probes, clock, client


def status(c, id):
    return next(a for a in c.get("/api/apps").json() if a["id"] == id)


def wait_job(c, id):
    end = time.time() + 2
    while c.get(f"/api/apps/{id}/job").json()["state"] == "running":
        assert time.time() < end
        time.sleep(0.01)


def test_apps_hides_dev_by_default(env):
    _, _, _, client = env
    assert [a["id"] for a in client().get("/api/apps").json()] == ["comfy", "sd"]


def test_apps_shows_dev_when_enabled(env):
    _, _, _, client = env
    assert "hello" in [a["id"] for a in client(show_dev=True).get("/api/apps").json()]


def test_apps_503_when_runtime_down(env):
    fake, _, _, client = env
    fake.runtime = False
    r = client().get("/api/apps")
    assert r.status_code == 503 and r.json()["detail"] == RUNTIME_DOWN_MSG


def test_health_reports_runtime(env):
    fake, _, _, client = env
    fake.runtime = False
    assert client().get("/api/health").json() == {"runtime": False}


def test_apps_status_and_url(env):
    fake, probes, _, client = env
    fake.projects = {"mos-sd": "running(1)"}
    probes["sd"] = True
    c = client()
    sd = status(c, "sd")
    assert sd["status"] == "running" and sd["url"] == "http://localhost:7801/" and sd["job"] is None
    assert status(c, "comfy")["status"] == "not_installed"


def test_started_at_recorded_for_unprobed_app(env):
    fake, _, clock, client = env
    fake.projects = {"mos-sd": "running(1)"}
    c = client()
    assert status(c, "sd")["status"] == "starting"
    clock["t"] = 181
    assert status(c, "sd")["status"] == "error"


def test_install_runs_up_build(env):
    fake, _, _, client = env
    c = client()
    r = c.post("/api/apps/hello/install")
    assert r.status_code == 202 and r.json()["kind"] == "install"
    wait_job(c, "hello")
    assert fake.args_for("hello") == [["up", "-d", "--build"]]
    assert c.get("/api/apps/hello/job").json()["log"] == ["ok"]


def test_install_gpu_app_does_not_start(env):
    fake, _, _, client = env
    c = client()
    c.post("/api/apps/sd/install")
    wait_job(c, "sd")
    assert fake.args_for("sd") == [["up", "--build", "--no-start"]]


def test_update_running_app_restarts_it(env):
    fake, _, _, client = env
    fake.projects = {"mos-sd": "running(1)"}
    c = client()
    c.post("/api/apps/sd/update")
    wait_job(c, "sd")
    assert fake.args_for("sd") == [["pull", "--ignore-buildable"], ["up", "-d", "--build"]]


def test_update_stopped_app_stays_stopped(env):
    fake, _, _, client = env
    fake.projects = {"mos-hello": "exited(1)"}
    c = client()
    c.post("/api/apps/hello/update")
    wait_job(c, "hello")
    assert fake.args_for("hello") == [["pull", "--ignore-buildable"], ["up", "--build", "--no-start"]]


def test_restarting_app_reaches_error(env):
    fake, _, clock, client = env
    fake.projects = {"mos-sd": "restarting(1)"}
    c = client()
    assert status(c, "sd")["status"] == "starting"
    clock["t"] = 181
    assert status(c, "sd")["status"] == "error"


def test_rejects_foreign_host(env):
    _, _, _, client = env
    assert client().get("/api/apps", headers={"Host": "evil.example"}).status_code == 400


def test_mutation_requires_header(env):
    fake, _, _, client = env
    r = client().post("/api/apps/sd/stop", headers={"X-MOS": ""})
    assert r.status_code == 403 and fake.calls == []


def test_install_twice_returns_409(env):
    fake, _, _, client = env
    fake.gate = threading.Event()
    c = client()
    assert c.post("/api/apps/sd/install").status_code == 202
    r = c.post("/api/apps/sd/install")
    assert r.status_code == 409 and r.json()["detail"] == "A job is already running for sd"
    fake.gate.set()
    wait_job(c, "sd")
    assert len(fake.args_for("sd")) == 1


def test_start_gpu_conflict_needs_confirm(env):
    fake, _, _, client = env
    fake.projects = {"mos-sd": "running(1)", "mos-comfy": "exited(1)"}
    r = client().post("/api/apps/comfy/start")
    assert r.status_code == 409 and r.json()["detail"] == {"conflicts": ["sd"]}
    assert fake.calls == []


def test_start_gpu_conflict_confirmed_stops_others(env):
    fake, _, _, client = env
    fake.projects = {"mos-sd": "running(1)", "mos-comfy": "exited(1)"}
    r = client().post("/api/apps/comfy/start?confirm=true")
    assert r.json() == {"stopped": ["sd"]}
    assert [(c[3], c[6:]) for c in fake.calls] == [("mos-sd", ["stop"]), ("mos-comfy", ["up", "-d"])]


def test_stop(env):
    fake, _, _, client = env
    assert client().post("/api/apps/sd/stop").status_code == 200
    assert fake.args_for("sd") == [["stop"]]


def test_uninstall_keeps_data_by_default(env):
    fake, _, _, client = env
    client().delete("/api/apps/sd")
    assert fake.args_for("sd") == [["down", "--rmi", "all"]]


def test_uninstall_delete_data(env):
    fake, _, _, client = env
    client().delete("/api/apps/sd?delete_data=true")
    assert fake.args_for("sd") == [["down", "--rmi", "all", "-v"]]


def test_unknown_app_404(env):
    _, _, _, client = env
    assert client().post("/api/apps/nope/start").status_code == 404


def test_job_404_when_none(env):
    _, _, _, client = env
    assert client().get("/api/apps/sd/job").status_code == 404


def test_logs_default_50(env):
    fake, _, _, client = env
    r = client().get("/api/apps/sd/logs")
    assert r.json() == {"logs": "logs here"}
    assert fake.args_for("sd") == [["logs", "--no-color", "--tail", "50"]]


def test_compose_error_is_500(env):
    fake, _, _, client = env
    fake.run = lambda cmd, env: (1, "boom") if cmd != ["docker", "info"] and "ls" not in cmd else (0, "[]")
    r = client().post("/api/apps/sd/stop")
    assert r.status_code == 500 and "boom" in r.json()["detail"]


def test_secrets_endpoint(env):
    _, _, _, client = env
    c = client()
    got = c.get("/api/apps/sd/secrets").json()
    assert [(g["name"], g["description"]) for g in got] == [("SD_KEY", "Admin key")] and got[0]["value"]
    assert c.get("/api/apps/sd/secrets").json() == got


def test_apps_never_include_secret_values(env):
    _, _, _, client = env
    c = client()
    value = c.get("/api/apps/sd/secrets").json()[0]["value"]
    r = c.get("/api/apps")
    assert value not in r.text
    flags = {a["id"]: a["has_secrets"] for a in r.json()}
    assert flags == {"comfy": False, "sd": True}
