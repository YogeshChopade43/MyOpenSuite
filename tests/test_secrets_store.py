from pathlib import Path

from backend.catalog import App
from backend.secrets_store import SecretStore


def app(secrets=None):
    return App(id="a", name="a", replaces="x", description="x", repo="x",
               port=1, internal_port=1, dir=Path("."), secrets=secrets or {})


def test_generates_and_persists(tmp_path):
    f = tmp_path / "s.json"
    env = SecretStore(f).env_for(app({"K": "d"}))
    assert list(env) == ["K"] and len(env["K"]) >= 40
    assert env["K"] in f.read_text()


def test_stable_across_calls(tmp_path):
    s = SecretStore(tmp_path / "s.json")
    assert s.env_for(app({"K": "d"})) == s.env_for(app({"K": "d"}))


def test_secret_persists_across_instances(tmp_path):
    f = tmp_path / "s.json"
    first = SecretStore(f).env_for(app({"K": "d"}))
    assert SecretStore(f).env_for(app({"K": "d"})) == first


def test_no_secrets_no_file(tmp_path):
    f = tmp_path / "s.json"
    assert SecretStore(f).env_for(app()) == {}
    assert not f.exists()


def test_corrupt_store_is_backed_up(tmp_path):
    f = tmp_path / "s.json"
    f.write_text("{nope")
    assert SecretStore(f).env_for(app({"K": "d"}))["K"]
    backups = list(tmp_path.glob("s.json.corrupt-*"))
    assert len(backups) == 1 and backups[0].read_text() == "{nope"
