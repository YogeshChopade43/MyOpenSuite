"""HTTP API: list apps with live status, and install/start/stop/update/uninstall them."""
import time
from collections.abc import Callable

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.catalog import App
from backend.compose import Compose, ComposeError
from backend.jobs import JobBusy, JobManager
from backend.rules import derive_status, gpu_conflicts, is_up
from backend.secrets_store import SecretStore

RUNTIME_DOWN_MSG = "Podman isn't running — run `podman machine start`"


def probe(app: App) -> bool:
    try:
        httpx.get(f"http://{app.id}:{app.internal_port}{app.path}", timeout=1)
        return True
    except httpx.HTTPError:
        return False


def create_app(apps: dict[str, App], compose: Compose, probe: Callable[[App], bool],
               clock: Callable[[], float] = time.time, show_dev: bool = False,
               secrets: SecretStore | None = None) -> FastAPI:
    api = FastAPI(title="MyOpenSuite")
    # Only localhost may talk to us (blocks DNS rebinding), and mutations need a custom
    # header, which forces a CORS preflight (blocks cross-site requests from any web page).
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    @api.middleware("http")
    async def require_header(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-mos") != "1":
            return JSONResponse(status_code=403, content={"detail": "Missing X-MOS header"})
        return await call_next(request)
    jobs = JobManager()
    started_at: dict[str, float] = {}

    @api.exception_handler(ComposeError)
    def compose_error(request, exc: ComposeError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    def runtime():
        if not compose.runtime_ok():
            raise HTTPException(503, RUNTIME_DOWN_MSG)

    def get_app(app_id: str) -> App:
        if app_id not in apps:
            raise HTTPException(404, f"Unknown app {app_id}")
        return apps[app_id]

    def idle(app: App) -> None:
        job = jobs.get(app.id)
        if job and job.state == "running":
            raise HTTPException(409, f"A job is already running for {app.id}")

    def running_ids(projects: dict[str, str]) -> set[str]:
        return {i for i in apps if is_up(projects.get(f"mos-{i}"))}

    def job_json(app_id: str, with_log=False):
        job = jobs.get(app_id)
        if not job:
            return None
        out = {"kind": job.kind, "state": job.state}
        if with_log:
            out["log"] = list(job.log)
        return out

    def start_job(app: App, kind: str, steps: list[list[str]]):
        def work(log):
            for args in steps:
                for line in compose.stream(app, *args):
                    log(line)
        try:
            jobs.start(app.id, kind, work)
        except JobBusy:
            raise HTTPException(409, f"A job is already running for {app.id}")
        return JSONResponse(status_code=202, content=job_json(app.id))

    @api.get("/api/health")
    def health():
        return {"runtime": compose.runtime_ok()}

    @api.get("/api/apps", dependencies=[Depends(runtime)])
    def list_apps():
        projects = compose.projects()
        now = clock()
        out = []
        for app in sorted(apps.values(), key=lambda a: a.name.lower()):
            if app.dev and not show_dev:
                continue
            ps = projects.get(f"mos-{app.id}")
            ok = False
            if is_up(ps):
                ok = probe(app)
                if ok:
                    started_at.pop(app.id, None)
                else:
                    started_at.setdefault(app.id, now)
            else:
                started_at.pop(app.id, None)
            out.append({
                "id": app.id, "name": app.name, "replaces": app.replaces,
                "description": app.description, "gpu": app.gpu, "size_gb": app.size_gb,
                "warnings": app.warnings, "has_secrets": bool(app.secrets),
                "status": derive_status(ps, ok, started_at.get(app.id), now),
                "url": f"http://localhost:{app.port}{app.path}",
                "job": job_json(app.id),
            })
        return out

    @api.post("/api/apps/{app_id}/install", dependencies=[Depends(runtime)])
    def install(app: App = Depends(get_app)):
        # GPU apps are only created; starting them goes through Start and the GPU rule.
        up = ["up", "--build", "--no-start"] if app.gpu else ["up", "-d", "--build"]
        return start_job(app, "install", [up])

    @api.post("/api/apps/{app_id}/update", dependencies=[Depends(runtime)])
    def update(app: App = Depends(get_app)):
        # Keep the app's run state: only a running app is started again.
        running = app.id in running_ids(compose.projects())
        up = ["up", "-d", "--build"] if running else ["up", "--build", "--no-start"]
        return start_job(app, "update", [["pull", "--ignore-buildable"], up])

    @api.post("/api/apps/{app_id}/start", dependencies=[Depends(runtime)])
    def start(confirm: bool = False, app: App = Depends(get_app)):
        idle(app)
        conflicts = gpu_conflicts(app, apps, running_ids(compose.projects()))
        if conflicts and not confirm:
            raise HTTPException(409, {"conflicts": conflicts})
        for other in conflicts:
            compose.run(apps[other], "stop")
        compose.run(app, "up", "-d")
        started_at[app.id] = clock()
        return {"stopped": conflicts}

    @api.post("/api/apps/{app_id}/stop", dependencies=[Depends(runtime)])
    def stop(app: App = Depends(get_app)):
        idle(app)
        compose.run(app, "stop")
        return {}

    @api.delete("/api/apps/{app_id}", dependencies=[Depends(runtime)])
    def uninstall(delete_data: bool = False, app: App = Depends(get_app)):
        idle(app)
        compose.run(app, "down", "--rmi", "all", *(["-v"] if delete_data else []))
        return {}

    @api.get("/api/apps/{app_id}/job")
    def job(app: App = Depends(get_app)):
        out = job_json(app.id, with_log=True)
        if not out:
            raise HTTPException(404, f"No job for {app.id}")
        return out

    @api.get("/api/apps/{app_id}/logs", dependencies=[Depends(runtime)])
    def logs(lines: int = 50, app: App = Depends(get_app)):
        return {"logs": compose.logs(app, lines)}

    @api.get("/api/apps/{app_id}/secrets")
    def get_secrets(app: App = Depends(get_app)):
        values = secrets.env_for(app) if secrets else {}
        return [{"name": k, "description": d, "value": values[k]} for k, d in app.secrets.items()]

    @api.get("/api/apps/{app_id}/icon")
    def icon(app: App = Depends(get_app)):
        f = app.dir / "icon.png"
        if not f.is_file():
            raise HTTPException(404, "No icon")
        return FileResponse(f)

    return api
