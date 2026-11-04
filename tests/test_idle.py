from pathlib import Path

from backend.catalog import App, load_catalog
from backend.compose import Compose
from backend.idle import IdleStopper, browser_connected

ROUTE = "Iface Destination Gateway Flags\neth0 00000000 0101590A 0003 0 0 100 00000000 0 0 0\n"
TCP = "  sl  local_address rem_address   st\n"
BROWSER = TCP + "   0: 1101590A:0050 0101590A:8ECC 01 00000000\n"
UPSTREAM = TCP + "   0: 1604590A:80D0 1204590A:1F40 01 00000000\n"
CLOSING = TCP + "   0: 1101590A:0050 0101590A:8ECC 06 00000000\n"
BROWSER_V6 = TCP + "   0: 00000000000000000000000000000000:0050 0000000000000000FFFF00000101590A:8ECC 01 00000000\n"


def test_browser_connection_comes_from_the_gateway():
    assert browser_connected(BROWSER + ROUTE)
    assert browser_connected(BROWSER_V6 + ROUTE)


def test_other_connections_are_not_a_browser():
    assert not browser_connected(UPSTREAM + ROUTE)
    assert not browser_connected(CLOSING + ROUTE)
    assert not browser_connected(ROUTE)


def app(id="a", **kw):
    return App(id=id, name=id, replaces="x", description="x", repo="x", port=7900, internal_port=80,
               dir=Path("."), **kw)


class Rig:
    def __init__(self, *apps):
        self.now, self.browser, self.cpu, self.stopped, self.job, self.up = 0.0, False, 0.0, [], False, True
        self.stopper = IdleStopper({a.id: a for a in apps}, activity=self.activity, stop=self.stopped.append,
                                   is_running=lambda a: self.up, busy_job=lambda a: self.job,
                                   clock=lambda: self.now, idle_seconds=1800)

    def activity(self, a):
        return self.browser, self.cpu

    def minutes(self, n):
        for _ in range(n):
            self.now += 60
            self.cpu += self.per_minute if hasattr(self, "per_minute") else 1
            self.stopper.tick()


def test_stops_after_idle_time():
    r = Rig(a := app())
    r.minutes(30)
    assert r.stopped == []
    r.minutes(2)
    assert r.stopped == [a]


def test_open_browser_keeps_app_running():
    r = Rig(app())
    r.browser = True
    r.minutes(60)
    assert r.stopped == []


def test_closing_the_browser_restarts_the_clock():
    r = Rig(a := app())
    r.browser = True
    r.minutes(25)
    r.browser = False
    r.minutes(20)
    assert r.stopped == []
    r.minutes(12)
    assert r.stopped == [a]


def test_cpu_work_keeps_app_running():
    r = Rig(app())
    r.per_minute = 45  # three quarters of a core, e.g. a render with the tab closed
    r.minutes(60)
    assert r.stopped == []


def test_running_job_keeps_app_running():
    r = Rig(app())
    r.job = True
    r.minutes(60)
    assert r.stopped == []


def test_opted_out_app_is_never_stopped():
    r = Rig(app(idle_stop=False))
    r.minutes(60)
    assert r.stopped == []


def test_stopped_app_starts_a_fresh_clock_when_started_again():
    r = Rig(a := app())
    r.up = False
    r.minutes(40)
    r.up = True
    r.minutes(20)
    assert r.stopped == []


def test_unknown_activity_counts_as_active():
    r = Rig(app())

    def broken(a):
        raise RuntimeError("cannot read")
    r.stopper._activity = broken
    r.minutes(60)
    assert r.stopped == []


def test_one_failing_stop_does_not_end_the_loop():
    r = Rig(a := app(), b := app("b"))
    done = []

    def stop(x):
        if x is a:
            raise RuntimeError("boom")
        done.append(x)
    r.stopper._stop = stop
    r.minutes(32)
    assert b in done


def test_openhands_is_never_auto_stopped():
    assert load_catalog(Path("catalog"))["openhands"].idle_stop is False


def test_compose_activity_reads_main_service():
    calls = []

    def runner(cmd, env):
        calls.append(cmd)
        return 0, "abc\ndef\n" if "ps" in cmd else BROWSER + ROUTE
    c = Compose(runner=runner, cpu_reader=lambda ids: 12.5 if ids == ["abc", "def"] else 0)
    assert c.activity(app()) == (True, 12.5)
    assert any(cmd[-5:-3] == ["sh", "-c"] or "exec" in cmd for cmd in calls)
