import threading
import time

import pytest

from backend.jobs import JobBusy, JobManager


def until(cond, timeout=2):
    end = time.time() + timeout
    while not cond():
        assert time.time() < end, "timed out"
        time.sleep(0.01)


def test_job_completes():
    def work(log):
        log("a")
        log("b")

    job = JobManager().start("x", "install", work)
    until(lambda: job.state != "running")
    assert job.state == "done" and list(job.log) == ["a", "b"] and job.kind == "install"


def test_job_error_keeps_log():
    def work(log):
        log("a")
        raise RuntimeError("boom")

    job = JobManager().start("x", "install", work)
    until(lambda: job.state != "running")
    assert job.state == "error" and list(job.log) == ["a", "boom"]


def test_second_start_while_running_raises_busy():
    gate = threading.Event()
    jm = JobManager()
    job = jm.start("x", "install", lambda log: gate.wait())
    with pytest.raises(JobBusy):
        jm.start("x", "update", lambda log: None)
    gate.set()
    until(lambda: job.state == "done")


def test_new_job_after_done_allowed():
    jm = JobManager()
    first = jm.start("x", "install", lambda log: None)
    until(lambda: first.state == "done")
    second = jm.start("x", "update", lambda log: None)
    assert jm.get("x") is second


def test_get_unknown_is_none():
    assert JobManager().get("nope") is None


def test_job_log_is_capped():
    def work(log):
        for i in range(2500):
            log(f"line {i}")

    job = JobManager().start("x", "install", work)
    until(lambda: job.state != "running")
    assert len(job.log) == 2000 and job.log[-1] == "line 2499"
