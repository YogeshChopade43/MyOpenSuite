import io
import tarfile
from pathlib import Path

import pytest
import yaml

from backend.catalog import lint_compose, load_catalog
from backend.importer import ImportRefused, convert, find_run, image_ref, inspect, parse_repo, parse_run, save


class FakeGitHub:
    def __init__(self, files, license="MIT", archived=False, tar=None):
        self.files, self.license, self.archived, self.tar = files, license, archived, tar

    def repo(self, owner, name):
        return {"full_name": f"{owner}/{name}", "name": name, "description": "A tool", "stargazers_count": 50000,
                "default_branch": "main", "archived": self.archived, "html_url": f"https://github.com/{owner}/{name}",
                "license": {"spdx_id": self.license}}

    def sha(self, full_name, branch):
        return "abc123"

    def text(self, full_name, ref, path):
        return self.files.get(path)

    def tarball(self, full_name, ref):
        return self.tar

    def avatar(self, owner):
        return b"png"


def compose(service, name="web"):
    return yaml.safe_dump({"services": {name: service}})


URL = "https://github.com/acme/tool"


def preview(files, **kw):
    return inspect(URL, FakeGitHub(files, **kw), {})


@pytest.mark.parametrize("url", [
    "http://github.com/a/b", "https://gitlab.com/a/b", "https://github.com.evil.io/a/b", "https://github.com/a",
    "https://github.com/a/b/../../c", "https://user@github.com/a/b", "file:///etc/passwd", "github.com/a/b", ""])
def test_only_github_repo_links_are_accepted(url):
    with pytest.raises(ImportRefused):
        parse_repo(url)


@pytest.mark.parametrize("url", ["https://github.com/a/b", "https://github.com/a/b/", "https://github.com/a/b.git",
                                 "  https://github.com/a/b  ", "https://www.github.com/a/b"])
def test_repo_links(url):
    assert parse_repo(url) == ("a", "b")


def test_repo_link_ignores_deeper_paths():
    assert parse_repo("https://github.com/a/b/tree/main/docs") == ("a", "b")


@pytest.mark.parametrize("given,want", [
    ("nginx", "docker.io/library/nginx"), ("louislam/uptime-kuma:2", "docker.io/louislam/uptime-kuma:2"),
    ("ghcr.io/a/b:1", "ghcr.io/a/b:1"), ("localhost:5000/a", "localhost:5000/a")])
def test_image_names_are_fully_qualified(given, want):
    assert image_ref(given) == want


def test_compose_with_image_becomes_one_localhost_service():
    plan = convert({"image": "acme/tool:1", "ports": ["3000:80"], "volumes": ["./data:/app/data", "cfg:/cfg"],
                    "restart": "always", "labels": {"x": "y"}, "container_name": "z"}, "tool", 7810)
    svc = plan.compose["services"]["tool"]
    assert svc["image"] == "docker.io/acme/tool:1"
    assert svc["ports"] == ["127.0.0.1:7810:80"] and svc["networks"] == ["mos-net"]
    assert svc["restart"] == "unless-stopped"
    assert "labels" not in svc and "container_name" not in svc
    assert set(plan.compose["volumes"]) == {"data", "cfg"}
    assert svc["volumes"] == ["data:/app/data", "cfg:/cfg"]
    assert plan.compose["networks"]["mos-net"]["external"] is True
    assert plan.internal_port == 80


@pytest.mark.parametrize("port,want", [
    ("8080:80", 80), ("127.0.0.1:5000:5000", 5000), ("${PORT:-3000}:3000", 3000), ("443:443/tcp", 443),
    ("8000-8010:8000-8010", 8000), ("9000", 9000), ({"target": 81, "published": 8081}, 81)])
def test_container_port_forms(port, want):
    assert convert({"image": "a", "ports": [port]}, "t", 7810).internal_port == want


@pytest.mark.parametrize("bad", [
    {"privileged": True}, {"network_mode": "host"}, {"pid": "host"}, {"ipc": "host"},
    {"cap_add": ["SYS_ADMIN"]}, {"cap_add": ["ALL"]}, {"devices": ["/dev/sda:/dev/sda"]},
    {"security_opt": ["seccomp:unconfined"]}, {"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]},
    {"volumes": ["/run/podman/podman.sock:/var/run/docker.sock"]},
    {"volumes": [{"type": "bind", "source": "/var/run/docker.sock", "target": "/s"}]}])
def test_dangerous_settings_are_refused(bad):
    assert convert({"image": "a", "ports": ["80"], **bad}, "t", 7810).blockers


def test_no_web_port_is_refused():
    assert convert({"image": "a"}, "t", 7810).blockers


def test_host_folders_become_volumes_and_config_files_are_dropped():
    plan = convert({"image": "a", "ports": ["80"], "volumes": [
        "/srv/app:/data", "./config.yml:/app/config.yml", "/etc/localtime:/etc/localtime:ro", "$(pwd)/x:/x", "/anon"]},
        "t", 7810)
    assert plan.compose["services"]["t"]["volumes"] == ["data:/data", "x:/x", "/anon"]
    assert any("config.yml" in w for w in plan.warnings)


def test_blank_or_placeholder_passwords_become_secrets():
    plan = convert({"image": "a", "ports": ["80"], "environment": {
        "ADMIN_PASSWORD": "changeme", "API_KEY": "", "JWT_SECRET": "${JWT_SECRET}", "TZ": "UTC", "DB_PASSWORD": "kept-as-is"}},
        "t", 7810)
    env = plan.compose["services"]["t"]["environment"]
    assert env["ADMIN_PASSWORD"] == "${ADMIN_PASSWORD}" and env["API_KEY"] == "${API_KEY}"
    assert env["JWT_SECRET"] == "${JWT_SECRET}" and env["TZ"] == "UTC" and env["DB_PASSWORD"] == "kept-as-is"
    assert set(plan.secrets) == {"ADMIN_PASSWORD", "API_KEY", "JWT_SECRET"}


def test_environment_list_form():
    plan = convert({"image": "a", "ports": ["80"], "environment": ["TZ=UTC", "EMPTY"]}, "t", 7810)
    assert plan.compose["services"]["t"]["environment"] == {"TZ": "UTC", "EMPTY": ""}


def test_gpu_request_is_dropped_with_a_warning():
    plan = convert({"image": "a", "ports": ["80"], "deploy": {"resources": {"reservations": {"devices": [{"driver": "nvidia"}]}}}},
                   "t", 7810)
    assert not plan.blockers and "deploy" not in plan.compose["services"]["t"]
    assert any("GPU" in w for w in plan.warnings)


def test_env_file_is_dropped_with_a_warning():
    plan = convert({"image": "a", "ports": ["80"], "env_file": ".env"}, "t", 7810)
    assert "env_file" not in plan.compose["services"]["t"] and any("settings file" in w for w in plan.warnings)


def test_docker_run_line():
    s = parse_run("docker run -d --name x --restart=always -p 8080:80 -v /a/b:/data -e TZ=UTC --env K=v"
                  " -it --rm ghcr.io/acme/tool:1 serve --port 80")
    assert s == {"image": "ghcr.io/acme/tool:1", "ports": ["8080:80"], "volumes": ["/a/b:/data"],
                 "environment": {"TZ": "UTC", "K": "v"}, "command": ["serve", "--port", "80"]}


@pytest.mark.parametrize("line,key", [("docker run --privileged -p 80:80 a", "privileged"),
                                      ("docker run --network=host a", "network_mode"),
                                      ("docker run --cap-add SYS_ADMIN -p 1:1 a", "cap_add")])
def test_docker_run_keeps_dangerous_flags_so_they_are_refused(line, key):
    s = parse_run(line)
    assert key in s and convert(s, "t", 7810).blockers


def test_readme_run_prefers_a_real_published_line():
    readme = """Intro
```
docker run <image>
```
```bash
$ docker run -d \\
    -p 8080:8080 \\
    acme/tool:latest
```
"""
    assert find_run(readme)["image"] == "acme/tool:latest"


def test_no_run_line():
    assert find_run("just words about docker") is None


def test_compose_image_beats_readme():
    p = preview({"docker-compose.yml": compose({"image": "acme/tool", "ports": ["80:80"]}),
                 "README.md": "docker run -p 1:1 acme/other"})
    assert p.source == "compose" and p.image == "docker.io/acme/tool" and not p.blockers


def test_readme_beats_build():
    p = preview({"docker-compose.yml": compose({"build": ".", "ports": ["80:80"]}),
                 "README.md": "docker run -p 8080:8080 acme/tool"})
    assert p.source == "docker run" and not p.build


def test_build_only_compose_warns():
    p = preview({"compose.yaml": compose({"build": ".", "ports": ["80:80"]})})
    assert p.source == "compose" and p.build and any("source" in w for w in p.warnings)


def test_dockerfile_only():
    p = preview({"Dockerfile": "FROM x\nEXPOSE 3000\n"})
    assert p.source == "Dockerfile" and p.build and p.internal_port == 3000


def test_multi_container_stack_is_refused():
    doc = yaml.safe_dump({"services": {"a": {"image": "a", "ports": ["80"]}, "b": {"image": "b"}}})
    p = preview({"docker-compose.yml": doc})
    assert p.blockers and "multi-container" in p.blockers[0]


def test_stack_with_a_readme_line_uses_the_line():
    doc = yaml.safe_dump({"services": {"a": {"image": "a"}, "b": {"image": "b"}}})
    p = preview({"docker-compose.yml": doc, "README.md": "docker run -p 7860:7860 acme/tool:1"})
    assert p.source == "docker run" and not p.blockers


def test_nothing_runnable_is_refused():
    assert preview({"README.md": "A library"}).blockers


def test_build_context_outside_the_repo_is_refused():
    p = preview({"docker-compose.yml": compose({"build": "../..", "ports": ["80"]})})
    assert p.blockers


def test_build_context_is_relative_to_the_compose_file():
    p = preview({"docker/docker-compose.yml": compose({"build": {"context": "..", "dockerfile": "docker/Dockerfile"}, "ports": ["80"]})})
    assert p.plan.compose["services"]["tool"]["build"] == {"context": "./src", "dockerfile": "docker/Dockerfile"}


@pytest.mark.parametrize("license,flagged", [("MIT", False), ("AGPL-3.0", False), ("NOASSERTION", True), (None, True)])
def test_unclear_licences_are_flagged(license, flagged):
    p = preview({"docker-compose.yml": compose({"image": "a", "ports": ["80"]})}, license=license)
    assert any("licence" in w.lower() for w in p.warnings) is flagged


def test_archived_repo_is_flagged():
    p = preview({"docker-compose.yml": compose({"image": "a", "ports": ["80"]})}, archived=True)
    assert any("archived" in w for w in p.warnings)


def test_latest_tag_is_flagged():
    p = preview({"docker-compose.yml": compose({"image": "a:latest", "ports": ["80"]})})
    assert any("Update" in w for w in p.warnings)


def test_already_in_the_catalog_is_refused():
    gh = FakeGitHub({"docker-compose.yml": compose({"image": "a", "ports": ["80"]})})
    apps = load_catalog(Path("catalog"))
    gh2 = FakeGitHub(gh.files)
    p = inspect("https://github.com/x/openhands", gh2, apps)
    assert p.blockers and "already" in p.blockers[0]


def test_port_skips_ones_in_use(tmp_path):
    gh = FakeGitHub({"docker-compose.yml": compose({"image": "a", "ports": ["80"]})})
    p1 = inspect(URL, gh, {})
    save(p1, tmp_path, "Paid thing", gh)
    apps = load_catalog(tmp_path)
    p2 = inspect("https://github.com/acme/other", gh, apps)
    assert (p1.port, p2.port) == (7810, 7811)


def test_saved_app_loads_and_passes_the_catalog_rules(tmp_path):
    gh = FakeGitHub({"docker-compose.yml": compose({"image": "a", "ports": ["80"],
                                                    "environment": {"ADMIN_PASSWORD": "changeme"}})})
    app = save(inspect(URL, gh, {}), tmp_path, "Paid thing", gh)
    assert app.imported and app.replaces == "Paid thing" and app.port == 7810 and app.category == "Imported"
    assert app.secrets == {"ADMIN_PASSWORD": "Generated by MyOpenSuite"}
    assert lint_compose(app) == []
    assert (app.dir / "icon.png").read_bytes() == b"png"
    assert load_catalog(tmp_path)["tool"] == app


def tar_with(*names):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as t:
        for n in names:
            info = tarfile.TarInfo(n)
            info.size = 2
            t.addfile(info, io.BytesIO(b"hi"))
    return out.getvalue()


def test_build_source_is_unpacked_without_the_top_folder(tmp_path):
    gh = FakeGitHub({"Dockerfile": "EXPOSE 80\n"}, tar=tar_with("tool-abc/Dockerfile", "tool-abc/src/a.py"))
    app = save(inspect(URL, gh, {}), tmp_path, "", gh)
    assert (app.dir / "src" / "Dockerfile").is_file() and (app.dir / "src" / "src" / "a.py").is_file()


def test_tar_escape_is_refused(tmp_path):
    gh = FakeGitHub({"Dockerfile": "EXPOSE 80\n"}, tar=tar_with("tool-abc/../../evil"))
    with pytest.raises(ImportRefused):
        save(inspect(URL, gh, {}), tmp_path, "", gh)
    assert not (tmp_path / "evil").exists() and not (tmp_path / "tool").exists()


def test_a_preview_with_blockers_cannot_be_saved(tmp_path):
    gh = FakeGitHub({"README.md": "library"})
    with pytest.raises(ImportRefused):
        save(inspect(URL, gh, {}), tmp_path, "", gh)


def api_client(tmp_path, gh):
    from fastapi.testclient import TestClient
    from backend.api import create_app
    from backend.compose import Compose
    calls = []

    def runner(cmd, env):
        calls.append(cmd)
        return 0, "[]" if "ls" in cmd else ""
    api = create_app({}, Compose(runner=runner), probe=lambda a: False, imports=tmp_path, github=gh)
    return TestClient(api, base_url="http://localhost", headers={"X-MOS": "1"}), calls


GOOD = {"docker-compose.yml": compose({"image": "acme/tool:1", "ports": ["80:80"]})}


def test_preview_writes_nothing(tmp_path):
    c, _ = api_client(tmp_path, FakeGitHub(GOOD))
    r = c.post("/api/import/preview", json={"url": URL})
    assert r.status_code == 200 and r.json()["id"] == "tool" and r.json()["sha"] == "abc123"
    assert "plan" not in r.json() and list(tmp_path.iterdir()) == []


def test_import_adds_the_app_to_the_live_catalog(tmp_path):
    c, _ = api_client(tmp_path, FakeGitHub(GOOD))
    r = c.post("/api/import", json={"url": URL, "sha": "abc123", "replaces": "Paid thing"})
    assert r.status_code == 200 and r.json() == {"id": "tool"}
    apps = c.get("/api/apps").json()
    assert [(a["id"], a["imported"], a["replaces"], a["status"]) for a in apps] == [("tool", True, "Paid thing", "not_installed")]


def test_refused_link_gives_a_readable_error(tmp_path):
    c, _ = api_client(tmp_path, FakeGitHub(GOOD))
    r = c.post("/api/import/preview", json={"url": "https://evil.com/a/b"})
    assert r.status_code == 400 and "github.com" in r.json()["detail"]


def test_blocked_app_cannot_be_imported_through_the_api(tmp_path):
    c, _ = api_client(tmp_path, FakeGitHub({"docker-compose.yml": compose({"image": "a", "ports": ["80"], "privileged": True})}))
    r = c.post("/api/import", json={"url": URL, "sha": "abc123"})
    assert r.status_code == 400 and "privileged" in r.json()["detail"] and list(tmp_path.iterdir()) == []


def test_import_needs_the_custom_header(tmp_path):
    c, _ = api_client(tmp_path, FakeGitHub(GOOD))
    assert c.post("/api/import", json={"url": URL}, headers={"X-MOS": ""}).status_code == 403


def test_uninstalling_an_imported_app_removes_it(tmp_path):
    c, calls = api_client(tmp_path, FakeGitHub(GOOD))
    c.post("/api/import", json={"url": URL, "sha": "abc123"})
    assert c.delete("/api/apps/tool?delete_data=true").status_code == 200
    assert c.get("/api/apps").json() == [] and not (tmp_path / "tool").exists()
    assert any("down" in cmd and "-v" in cmd for cmd in calls)


def test_an_import_during_an_idle_check_does_not_end_the_loop():
    from backend.catalog import App
    from backend.idle import IdleStopper
    one = App(id="a", name="a", replaces="", description="", repo="", port=1, internal_port=1, dir=Path("."))
    apps = {"a": one}
    seen = []

    def running(app):
        apps["new"] = one  # what an import does mid-check
        seen.append(app)
        return False
    IdleStopper(apps, activity=None, stop=None, is_running=running, busy_job=None, clock=lambda: 0, idle_seconds=1).tick()
    assert seen == [one]


def test_two_folders_never_share_a_volume():
    plan = convert({"image": "a", "ports": ["80"], "volumes": ["/var/cache/ntfy:/var/cache/ntfy", "/etc/ntfy:/etc/ntfy"]}, "t", 7810)
    vols = plan.compose["services"]["t"]["volumes"]
    assert len({v.split(":")[0] for v in vols}) == 2 and set(plan.compose["volumes"]) == {v.split(":")[0] for v in vols}


@pytest.mark.parametrize("src", [".", "./", "..", "../.."])
def test_the_repo_itself_is_not_a_volume(src):
    plan = convert({"build": ".", "ports": ["80"], "volumes": [f"{src}:/app"]}, "t", 7810)
    assert "volumes" not in plan.compose["services"]["t"]


def test_dotfiles_are_files_not_folders():
    plan = convert({"image": "a", "ports": ["80"], "volumes": ["./.env:/app/.env"]}, "t", 7810)
    assert "volumes" not in plan.compose["services"]["t"] and any(".env" in w for w in plan.warnings)


def test_dockerfile_prefers_a_web_port_over_ssh():
    assert preview({"Dockerfile": "FROM x\nEXPOSE 22 3000\n"}).internal_port == 3000
    assert preview({"Dockerfile": "FROM x\nEXPOSE 22\nEXPOSE 8080\n"}).internal_port == 8080


def test_ssh_only_dockerfile_has_no_web_port():
    assert preview({"Dockerfile": "FROM x\nEXPOSE 22\n"}).blockers


def test_local_build_tag_is_not_a_published_image():
    p = preview({"docker-compose.yml": compose({"image": "actual-development", "build": ".", "ports": ["80"]})})
    assert p.build and not p.image


def test_published_image_wins_over_its_build_section():
    p = preview({"docker-compose.yml": compose({"image": "acme/tool:1", "build": ".", "ports": ["80"]})})
    assert p.image == "docker.io/acme/tool:1" and not p.build
