from pathlib import Path

from backend.catalog import App
from backend.rules import START_TIMEOUT, derive_status, gpu_conflicts


def app(id, gpu=False):
    return App(id=id, name=id, replaces="x", description="x", repo="x",
               port=1, internal_port=1, dir=Path("."), gpu=gpu)


apps = {"comfyui": app("comfyui", gpu=True), "sd": app("sd", gpu=True), "hello": app("hello")}


def test_gpu_conflicts_lists_other_running_gpu_apps():
    assert gpu_conflicts(apps["comfyui"], apps, {"sd", "hello", "comfyui"}) == ["sd"]


def test_gpu_conflicts_empty_for_non_gpu_target():
    assert gpu_conflicts(apps["hello"], apps, {"sd"}) == []


def test_start_timeout_is_180():
    assert START_TIMEOUT == 180


def test_no_project_is_not_installed():
    assert derive_status(None, False, None, 0) == "not_installed"


def test_exited_is_stopped():
    assert derive_status("exited(1)", False, None, 0) == "stopped"


def test_running_and_probed():
    assert derive_status("running(1)", True, 0, 500) == "running"


def test_running_unprobed_is_starting():
    assert derive_status("running(1)", False, 100, 279) == "starting"


def test_running_unprobed_after_timeout_is_error():
    assert derive_status("running(1)", False, 100, 281) == "error"


def test_partially_running_uses_probe():
    assert derive_status("running(1), exited(1)", True, 0, 1) == "running"


def test_unprobed_without_started_at_is_starting():
    assert derive_status("running(1)", False, None, 999) == "starting"


def test_restarting_unprobed_after_timeout_is_error():
    assert derive_status("restarting(1)", False, 100, 281) == "error"


def test_custom_timeout():
    assert derive_status("running(1)", False, 0, 600, timeout=1800) == "starting"
    assert derive_status("running(1)", False, 0, 1801, timeout=1800) == "error"
