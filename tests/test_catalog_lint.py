from pathlib import Path

import pytest

from backend.catalog import GPU_DEVICE, App, lint_compose, load_catalog


def make(tmp_path, compose: str, id="a", **kw) -> App:
    (tmp_path / "docker-compose.yml").write_text(compose)
    return App(id=id, name=id, replaces="x", description="x", repo="x",
               port=7900, internal_port=80, dir=tmp_path, **kw)


GOOD = """services:
  a:
    image: x
    ports: ["127.0.0.1:7900:80"]
    networks: [mos-net]
{extra}networks:
  mos-net:
    external: true
"""


def problems(tmp_path, compose, **kw) -> str:
    return "\n".join(lint_compose(make(tmp_path, compose, **kw)))


@pytest.mark.parametrize("app", load_catalog(Path("catalog")).values(), ids=lambda a: a.id)
def test_catalog_entry_is_clean(app):
    assert lint_compose(app) == []


def test_lint_good_is_clean(tmp_path):
    assert problems(tmp_path, GOOD.format(extra="")) == ""


def test_lint_port_not_localhost(tmp_path):
    c = GOOD.format(extra="").replace("127.0.0.1:7900:80", "7900:80")
    assert "must bind 127.0.0.1" in problems(tmp_path, c)


def test_lint_missing_network(tmp_path):
    c = GOOD.format(extra="").replace("    networks: [mos-net]\n", "")
    assert "mos-net" in problems(tmp_path, c)


def test_lint_network_not_external(tmp_path):
    c = GOOD.format(extra="").replace("    external: true\n", "    driver: bridge\n")
    assert "external" in problems(tmp_path, c)


def test_lint_host_bind_mount(tmp_path):
    c = GOOD.format(extra="").replace("    networks: [mos-net]\n", '    networks: [mos-net]\n    volumes: ["./data:/data"]\n')
    assert "host bind mount" in problems(tmp_path, c)


SOCKET = GOOD.format(extra="").replace(
    "    networks: [mos-net]\n", '    networks: [mos-net]\n    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]\n')


def test_lint_socket_needs_warning(tmp_path):
    assert "warnings" in problems(tmp_path, SOCKET)


def test_lint_socket_allowed_with_warning(tmp_path):
    assert problems(tmp_path, SOCKET, warnings=["Needs container socket access"]) == ""


def test_lint_gpu_app_without_gpu(tmp_path):
    assert "GPU" in problems(tmp_path, GOOD.format(extra=""), gpu=True)


def test_lint_gpu_app_with_gpu(tmp_path):
    c = GOOD.format(extra="").replace("    networks: [mos-net]\n", f'    networks: [mos-net]\n    devices: ["{GPU_DEVICE}"]\n')
    assert problems(tmp_path, c, gpu=True) == ""


def test_lint_main_service_named_id(tmp_path):
    c = GOOD.format(extra="").replace("  a:\n", "  web:\n")
    assert "service named 'a'" in problems(tmp_path, c)


def test_lint_shared_volume_must_be_external(tmp_path):
    c = GOOD.format(extra="volumes:\n  mos-models: {}\n")
    assert "mos-models" in problems(tmp_path, c)


def test_lint_shared_volume_external_ok(tmp_path):
    c = GOOD.format(extra="volumes:\n  mos-models:\n    external: true\n")
    assert problems(tmp_path, c) == ""
