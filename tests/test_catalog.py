from pathlib import Path

import pytest
import yaml

from backend.catalog import CatalogError, load_catalog

COMPOSE = """services:
  {id}:
    image: x
    ports: ["127.0.0.1:{port}:80"]
    networks: [mos-net]
networks:
  mos-net:
    external: true
"""


def write_app(root: Path, folder: str, raw: str | None = None, **overrides) -> Path:
    d = root / folder
    d.mkdir(parents=True)
    data = {
        "id": folder, "name": folder, "replaces": "x", "description": "x",
        "repo": "https://example.com", "port": 7900, "internal_port": 80,
    }
    data.update(overrides)
    data = {k: v for k, v in data.items() if v is not None}
    (d / "app.yml").write_text(raw if raw is not None else yaml.safe_dump(data))
    (d / "docker-compose.yml").write_text(COMPOSE.format(id=data["id"], port=data["port"]))
    return d


def test_load_reads_hello():
    apps = load_catalog(Path("catalog"))
    assert apps["hello"].port == 7800 and apps["hello"].internal_port == 80
    assert apps["hello"].dev is True and apps["hello"].gpu is False
    assert apps["hello"].dir == Path("catalog/hello")


def test_load_rejects_bad_yaml(tmp_path):
    write_app(tmp_path, "a", raw="id: [unclosed")
    with pytest.raises(CatalogError, match=r"app\.yml"):
        load_catalog(tmp_path)


def test_load_rejects_id_folder_mismatch(tmp_path):
    write_app(tmp_path, "a", id="b")
    with pytest.raises(CatalogError, match="does not match folder"):
        load_catalog(tmp_path)


def test_load_rejects_duplicate_port(tmp_path):
    write_app(tmp_path, "a", port=7900)
    write_app(tmp_path, "b", port=7900)
    with pytest.raises(CatalogError, match="port 7900"):
        load_catalog(tmp_path)


def test_load_rejects_missing_field(tmp_path):
    write_app(tmp_path, "a", internal_port=None)
    with pytest.raises(CatalogError, match="internal_port"):
        load_catalog(tmp_path)


def test_load_rejects_bad_llm_value(tmp_path):
    write_app(tmp_path, "a", llm={"OPENAI_API_KEY": "secret"})
    with pytest.raises(CatalogError, match="gateway_url, gateway_key or alias:"):
        load_catalog(tmp_path)


def test_load_rejects_unknown_field(tmp_path):
    write_app(tmp_path, "a", gpus=True)
    with pytest.raises(CatalogError, match="unknown field.*gpus"):
        load_catalog(tmp_path)
