"""Stops apps nobody is using, to free RAM. Anything uncertain counts as in use."""
import time
from collections.abc import Callable

from backend.catalog import App

CHECK_SECONDS = 60
BUSY_CORES = 0.5  # a render or generation with its tab closed; idle stacks measured well below this


def browser_connected(proc: str) -> bool:
    """True if /proc/net/{tcp,tcp6,route} text shows an open connection from a network gateway,
    which is how the owner's browser reaches a published port (other containers use their own address)."""
    rows = [line.split() for line in proc.splitlines()]
    gateways = {r[2] for r in rows if len(r) > 2 and r[1] == "00000000"}
    return any(len(r) > 3 and r[3] == "01" and r[2].split(":")[0].endswith(tuple(gateways))
               for r in rows if gateways)


class IdleStopper:
    def __init__(self, apps: dict[str, App], activity: Callable[[App], tuple[bool, float]],
                 stop: Callable[[App], object], is_running: Callable[[App], bool],
                 busy_job: Callable[[App], bool], clock: Callable[[], float], idle_seconds: float):
        self._apps, self._activity, self._stop = apps, activity, stop
        self._is_running, self._busy_job = is_running, busy_job
        self._clock, self._idle_seconds = clock, idle_seconds
        self._seen: dict[str, tuple[float, float, float]] = {}  # id -> last active, last check, cpu seconds

    def tick(self) -> None:
        for app in self._apps.values():
            try:
                self._check(app)
            except Exception as e:
                print(f"idle check failed for {app.id}: {e}", flush=True)
                self._seen.pop(app.id, None)  # unknown state counts as active

    def _check(self, app: App) -> None:
        if not app.idle_stop or not self._is_running(app):
            self._seen.pop(app.id, None)
            return
        now = self._clock()
        browser, cpu = self._activity(app)
        active, checked, last_cpu = self._seen.get(app.id, (now, now, cpu))
        working = checked < now and (cpu - last_cpu) / (now - checked) >= BUSY_CORES
        if browser or working or self._busy_job(app):
            active = now
        if now - active >= self._idle_seconds:
            self._seen.pop(app.id, None)
            print(f"stopping {app.id}: idle for {int((now - active) / 60)} minutes", flush=True)
            self._stop(app)
        else:
            self._seen[app.id] = (active, now, cpu)

    def run_forever(self) -> None:
        while True:
            time.sleep(CHECK_SECONDS)
            self.tick()
