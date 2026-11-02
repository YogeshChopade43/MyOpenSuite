"""Pure rules: GPU exclusivity and app status derivation."""
from backend.catalog import App

START_TIMEOUT = 180  # seconds a running-but-unresponsive app stays "starting" before "error"


def gpu_conflicts(target: App, apps: dict[str, App], running: set[str]) -> list[str]:
    if not target.gpu:
        return []
    return sorted(i for i in running if i != target.id and i in apps and apps[i].gpu)


def derive_status(project_status: str | None, probe_ok: bool, started_at: float | None, now: float) -> str:
    if project_status is None:
        return "not_installed"
    if "running" not in project_status:
        return "stopped"
    if probe_ok:
        return "running"
    if started_at is not None and now - started_at > START_TIMEOUT:
        return "error"
    return "starting"
