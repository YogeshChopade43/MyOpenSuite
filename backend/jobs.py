"""In-memory background jobs (install/update), at most one running per app."""
import threading
from collections.abc import Callable
from dataclasses import dataclass, field


class JobBusy(Exception):
    pass


@dataclass
class Job:
    app_id: str
    kind: str
    state: str = "running"  # running | done | error
    log: list[str] = field(default_factory=list)


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, app_id: str, kind: str, work: Callable[[Callable[[str], None]], None]) -> Job:
        with self._lock:
            current = self._jobs.get(app_id)
            if current and current.state == "running":
                raise JobBusy(app_id)
            job = self._jobs[app_id] = Job(app_id, kind)

        def run():
            try:
                work(job.log.append)
                job.state = "done"
            except Exception as e:
                job.log.append(str(e))
                job.state = "error"

        threading.Thread(target=run, daemon=True).start()
        return job

    def get(self, app_id: str) -> Job | None:
        return self._jobs.get(app_id)
