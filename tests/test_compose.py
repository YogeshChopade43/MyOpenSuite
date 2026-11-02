from pathlib import Path

import pytest

from backend.catalog import load_catalog
from backend.compose import Compose, ComposeError

hello = load_catalog(Path("catalog"))["hello"]


class FakeRunner:
    def __init__(self, code=0, out=""):
        self.code, self.out, self.calls = code, out, []

    def __call__(self, cmd, env):
        self.calls.append(cmd)
        return self.code, self.out


def test_cmd_uses_project_and_file():
    assert Compose().cmd(hello, "up", "-d") == [
        "docker", "compose", "-p", "mos-hello", "-f",
        str(Path("catalog/hello/docker-compose.yml")), "up", "-d"]


def test_projects_parses_ls_json():
    r = FakeRunner(out='[{"Name":"mos-hello","Status":"running(1)"},{"Name":"other","Status":"exited(1)"}]')
    assert Compose(runner=r).projects() == {"mos-hello": "running(1)"}
    assert r.calls[0] == ["docker", "compose", "ls", "-a", "--format", "json"]


def test_projects_empty_output():
    assert Compose(runner=FakeRunner(out="")).projects() == {}


def test_runtime_ok_false_on_error():
    assert Compose(runner=FakeRunner(code=1)).runtime_ok() is False


def test_runtime_ok_true():
    r = FakeRunner()
    assert Compose(runner=r).runtime_ok() is True
    assert r.calls[0] == ["docker", "info"]


def test_run_raises_with_tail():
    out = "\n".join(f"line {i}" for i in range(1, 31))
    with pytest.raises(ComposeError) as e:
        Compose(runner=FakeRunner(code=2, out=out)).run(hello, "up", "-d")
    assert e.value.returncode == 2
    assert "line 30" in str(e.value) and "line 11" in str(e.value)
    assert "line 10" not in str(e.value)


def test_run_returns_output():
    assert Compose(runner=FakeRunner(out="done")).run(hello, "stop") == "done"


def test_stream_raises_after_lines():
    def streamer(cmd, env):
        yield "a"
        yield "b"
        raise ComposeError(1, "failed")

    got = []
    with pytest.raises(ComposeError):
        for line in Compose(streamer=streamer).stream(hello, "up"):
            got.append(line)
    assert got == ["a", "b"]


def test_logs_tail():
    r = FakeRunner(out="log")
    assert Compose(runner=r).logs(hello) == "log"
    assert r.calls[0][-4:] == ["logs", "--no-color", "--tail", "50"]
