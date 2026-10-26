"""Synthetic host/command boundaries only: never Docker, SSH, profiles or accounts."""

import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import tarfile
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deploy_release", ROOT / "scripts/deploy_release.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
SHA = "a" * 40
OLD_IMAGE, NEW_IMAGE = ("sha256:" + value * 64 for value in ("1", "2"))
OLD, NEW = "b" * 64, "c" * 64


def test_loopback_management_http_emulates_trusted_https_proxy(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            assert limit == 2 * 1024 * 1024 + 1
            return b"{}"

    class Opener:
        def open(self, request, timeout):
            assert timeout == 10
            assert request.get_header("X-forwarded-proto") == "https"
            assert request.get_header("Authorization") == "Bearer synthetic-token"
            return Response()

    monkeypatch.setattr(deploy, "build_opener", lambda *handlers: Opener())
    assert deploy.http(deploy.LOCAL + "/v1/status", "synthetic-token") == (200, b"{}")


def profile_archive(tmp_path, mode="manual", corrupt=False):
    profile = tmp_path / "synthetic-profile"
    (profile / "config").mkdir(parents=True)
    (profile / "data").mkdir()
    (profile / "auth").mkdir()
    (profile / "config/app_settings.json").write_text(json.dumps({"startup": {"operation_mode": mode}}))
    database = profile / "data/heetkit.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE synthetic (value TEXT)")
        connection.execute("INSERT INTO synthetic VALUES ('private synthetic data')")
    connection.close()
    if corrupt:
        database.write_bytes(b"invalid SQLite")
    (profile / "auth/twitchio_tokens.json").write_text('"synthetic-rotated-token"')
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as output:
        output.add(profile, arcname=".")
    return archive.getvalue()


class Host:
    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path
        self.calls = []
        self.events = []
        self.fail = None
        self.current = OLD
        self.running = True
        self.connected = False
        self.mode = "manual"
        self.old_revision = "d" * 40
        self.release_sha = SHA
        self.source_version = "1.4.1"
        self.image_arch = "arm64"
        self.release_draft = False
        self.publication = "2026-01-01T00:00:00Z"
        self.secret_drift = False
        self.backup_bytes = profile_archive(tmp_path)
        self.restart_count = 0
        self.funnel = False
        self.live_token = "synthetic-before-deployment"
        self.health_calls = 0
        self.config = {"state_dir": str(tmp_path), "env_file": str(tmp_path / "host.env"),
                       "compose_files": [str(tmp_path / "compose.yaml"), str(tmp_path / "compose.remote.yaml")],
                       "health_timeout_seconds": 90}
        for name in ("host.env", "compose.yaml", "compose.remote.yaml"):
            (tmp_path / name).write_text("synthetic input")
        self.secret_paths = {}
        for name in ("twitch_client_secret", "gemini_api_key", "management_token"):
            path = tmp_path / name
            path.write_text("synthetic-hidden-secret")
            self.secret_paths[name] = path
        self.command = ["--health-file", "/tmp/heetkit-health.json", "--management-api", "--management-host", "127.0.0.1",
                        "--management-trusted-origin", "https://synthetic.ts.net", "--management-trusted-proxy", "127.0.0.1",
                        "--twitch-redirect-uri", "https://synthetic.ts.net/oauth/callback"]
        self.model = {"name": "heetkit", "services": {"bot": {"image": "heetkit-headless:old", "build": {"context": "."},
                      "platform": "linux/arm64", "network_mode": "host", "command": self.command,
                      "user": "10001:10001", "read_only": True,
                      "volumes": [{"type": "volume", "source": "profile", "target": "/var/lib/heetkit"}],
                      "secrets": [{"source": name} for name in self.secret_paths]}},
                      "volumes": {"profile": {"name": "heetkit_profile"}},
                      "secrets": {name: {"file": str(path)} for name, path in self.secret_paths.items()}}
        self.current_image = OLD_IMAGE
        monkeypatch.setattr(deploy, "run", self.run)
        monkeypatch.setattr(deploy, "http", self.http)
        monkeypatch.setattr(deploy, "private_file", lambda path: path)
        monkeypatch.setattr(deploy.shutil, "disk_usage", lambda path: SimpleNamespace(free=20 * 1024**3))
        original_read = Path.read_text
        def read(path, *args, **kwargs):
            return "MemAvailable: 2097152 kB\n" if str(path).replace("\\", "/") == "/proc/meminfo" else original_read(path, *args, **kwargs)
        monkeypatch.setattr(Path, "read_text", read)
        clock = iter(range(0, 100000, 10))
        monkeypatch.setattr(deploy.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(deploy.time, "sleep", lambda seconds: None)

    def info(self):
        return {"Image": self.current_image, "State": {"Running": self.running, "ExitCode": 137 if self.fail == "unclean_stop" else 0,
                "OOMKilled": False, "Health": {"Status": "unhealthy" if self.fail == "health" and self.current == NEW else "healthy"}},
                "RestartCount": self.restart_count, "Config": {"Cmd": self.command, "User": "10001:10001",
                "Labels": {"com.docker.compose.project": "heetkit", "com.docker.compose.service": "bot"}},
                "Mounts": [{"Type": "volume", "Name": "heetkit_profile", "Destination": "/var/lib/heetkit"}] +
                [{"Source": str(path), "Destination": "/run/secrets/" + name, "RW": False} for name, path in self.secret_paths.items()],
                "HostConfig": {"PortBindings": {}, "NetworkMode": "host", "ReadonlyRootfs": True}}

    def run(self, args, *, cwd=None, output=None, timeout=60):
        args = [str(arg) for arg in args]
        self.calls.append(args)
        def encoded(value):
            return json.dumps(value).encode()
        if args[:2] == ["docker", "compose"]:
            if "config" in args:
                return encoded(self.model)
            if "ps" in args:
                return (self.current or "").encode()
            path = Path(args[args.index("-f") + 1])
            if "stop" in args:
                self.events.append("stop")
                self.running = self.connected = False
                if self.fail == "stop":
                    self.fail = None
                    raise deploy.DeployError("safe command failure")
                return b""
            if "up" in args or "create" in args:
                self.events.append("candidate" if path.name.startswith("candidate") else "rollback")
                if self.fail == "partial_recreate" and path.name.startswith("candidate"):
                    self.current = None
                    raise deploy.DeployError("safe partial failure")
                self.current = NEW if path.name.startswith("candidate") else OLD
                if self.current == NEW:
                    self.live_token = "synthetic-rotated-after-start"
                self.current_image = json.loads(path.read_text())["services"]["bot"]["image"]
                self.running = "up" in args
                self.connected = self.running and self.mode == "always_on"
                return b""
            raise AssertionError(args)
        if args[:2] == ["docker", "inspect"]:
            return encoded([self.info()])
        if args[:2] == ["docker", "ps"]:
            assert "--no-trunc" in args
            return (self.current if self.running else "").encode()
        if args[:2] == ["docker", "info"]:
            return encoded({"OSType": "linux", "Architecture": "aarch64", "DockerRootDir": str(self.root)})
        if args[:3] == ["docker", "image", "inspect"]:
            old = args[-1] == OLD_IMAGE
            return encoded([{"Id": OLD_IMAGE if old else NEW_IMAGE, "Architecture": "arm64" if old else self.image_arch,
                             "Os": "linux", "Config": {"Labels": {"org.opencontainers.image.revision": self.old_revision if old else SHA}}}])
        if args[:3] == ["docker", "image", "tag"]:
            return b""
        if args[:2] == ["docker", "build"]:
            self.events.append("build")
            assert self.running or not self.before_running
            if self.fail == "build":
                raise deploy.DeployError("safe build failure")
            if self.secret_drift:
                self.secret_paths["management_token"].write_text("synthetic changed")
            return b""
        if args[:2] == ["docker", "run"]:
            self.events.append("backup")
            assert not self.running and "--network" in args and "--entrypoint" in args and args[-4:] == ["/profile", "-czf", "-", "."]
            if self.fail == "backup":
                raise deploy.DeployError("safe backup failure")
            output.write(self.backup_bytes)
            return b""
        if args[:2] == ["docker", "start"]:
            self.events.append("resume")
            assert self.current == OLD
            self.running = True
            return b""
        if args[0] == "git":
            if "rev-parse" in args:
                return self.release_sha.encode()
            if "archive" in args:
                with tarfile.open(fileobj=output, mode="w") as archive:
                    content = f'VERSION = "{self.source_version}"\n'.encode()
                    member = tarfile.TarInfo("app/version.py")
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
            return b""
        if args[0] == "tailscale":
            return encoded({"Web": {"synthetic.ts.net:443": {"Handlers": {"/": {"Proxy": deploy.LOCAL}}}},
                            "AllowFunnel": {"synthetic.ts.net:443": self.funnel}})
        if args[0] == "ss":
            return b"LISTEN 0 128 127.0.0.1:8765 0.0.0.0:*\n"
        raise AssertionError(args)

    def http(self, url, token=None, post=False):
        if url.startswith(deploy.RELEASE_API):
            return 200, json.dumps({"tag_name": "v1.4.1", "draft": self.release_draft, "published_at": self.publication,
                                    "html_url": "https://github.com/heeetz/heetkit-bot/releases/tag/v1.4.1"}).encode()
        if url.startswith("https://synthetic.ts.net"):
            assert token is None
            return 401, b""
        if url.endswith("/v1/bot/start"):
            self.events.append("connect")
            assert self.mode == "manual"
            self.connected = True
            return 200, b'{"ok":true}'
        if url.endswith("/v1/status"):
            self.health_calls += 1
            assert self.running
            return 200, json.dumps({"operation": {"mode": self.mode, "pending": False, "error": None},
                                   "twitch_connected": self.connected, "twitch_connection_state": "connected" if self.connected else "stopped",
                                   "channel": "synthetic_channel", "account": "synthetic_bot"}).encode()
        assert url == deploy.LOCAL + "/"
        return 200, b'<div id="root"></div>'

    def execute(self, compatible=True):
        self.before_running = self.running
        self.deployment = deploy.Deployment(self.config, "v1.4.1", SHA, compatible)
        self.deployment.execute()
        return self.record()

    def record(self):
        return json.loads((self.deployment.attempt / "deployment.json").read_text())


@pytest.fixture
def host(tmp_path, monkeypatch):
    return Host(tmp_path, monkeypatch)


@pytest.mark.parametrize("release,sha", [("latest", SHA), ("main", SHA), ("v1.4.1;echo unsafe", SHA), ("v1.4.1", "abc123")])
def test_explicit_immutable_inputs_only(tmp_path, release, sha):
    with pytest.raises(deploy.DeployError):
        deploy.Deployment({"state_dir": str(tmp_path)}, release, sha, False)


@pytest.mark.parametrize("mode,connected", [("manual", False), ("manual", True), ("disabled", False),
                                           ("always_on", True), ("stream_only", False)])
def test_deploy_preserves_policy_and_one_service(host, mode, connected):
    host.mode, host.connected = mode, connected
    host.backup_bytes = profile_archive(host.root / "other", mode)
    result = host.execute()
    assert result["result"] == "deployed"
    assert result["sha"] == SHA and result["image"] == NEW_IMAGE and result["old_image"] == OLD_IMAGE
    assert result["before"] == result["after"]
    assert result["backup"]["sqlite_integrity"] == "ok"
    assert host.events[:4] == ["build", "stop", "backup", "candidate"]
    assert host.events.count("connect") == int(mode == "manual" and connected)
    candidate = json.loads((host.deployment.attempt / "candidate.compose.json").read_text())
    previous = json.loads((host.deployment.attempt / "previous.compose.json").read_text())
    previous["services"]["bot"]["image"] = NEW_IMAGE
    assert candidate == previous
    assert "build" not in candidate["services"]["bot"]
    assert json.loads((host.root / "active-compose.json").read_text()) == candidate
    assert (host.deployment.attempt / "profile.tar.gz").read_bytes() == host.backup_bytes
    assert all("down" not in args and "prune" not in args for args in host.calls)
    for args in host.calls:
        if "up" in args or "create" in args:
            assert "--no-build" in args and args[args.index("--pull") + 1] == "never"


def test_stopped_process_is_recreated_stopped(host):
    host.running = False
    record = host.execute()
    assert not host.running and record["after"]["process"] == "stopped" and record["after"]["health"] == "not_run"
    assert "connect" not in host.events


def test_exact_healthy_sha_is_noop_without_build_or_downtime(host):
    host.old_revision = SHA
    assert host.execute()["result"] == "already_running_verified"
    assert host.events == []


@pytest.mark.parametrize("failure", ["build", "draft", "unpublished", "sha", "version", "platform", "funnel", "restarts", "secret_drift"])
def test_preparation_failure_never_stops_original(host, failure):
    if failure == "build":
        host.fail = "build"
    elif failure == "draft":
        host.release_draft = True
    elif failure == "unpublished":
        host.publication = None
    elif failure == "sha":
        host.release_sha = "e" * 40
    elif failure == "version":
        host.source_version = "1.4.0"
    elif failure == "platform":
        host.image_arch = "amd64"
    elif failure == "funnel":
        host.funnel = True
    elif failure == "restarts":
        host.restart_count = 1
    else:
        host.secret_drift = True
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert host.running and host.current == OLD
    assert "stop" not in host.events and "candidate" not in host.events
    assert host.record()["result"] == "failed"


@pytest.mark.parametrize("failure", ["backup", "sqlite", "stop", "unclean_stop"])
def test_failed_stop_or_backup_resumes_only_original(host, failure):
    host.fail = failure
    host.connected = True
    if failure == "sqlite":
        host.backup_bytes = profile_archive(host.root / "corrupt", corrupt=True)
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert host.running and host.current == OLD and host.connected
    assert "candidate" not in host.events and "rollback" not in host.events
    assert host.record()["rollback"] == "original_service_preserved"


@pytest.mark.parametrize("compatible", [True, False])
def test_failed_new_health_rollback_gate_retains_current_tokens(host, compatible):
    host.fail = "health"
    with pytest.raises(deploy.DeployError):
        host.execute(compatible)
    assert host.events.count("stop") == 2
    assert host.running == compatible
    assert ("rollback" in host.events) == compatible
    assert host.record()["rollback"] == ("healthy_previous_image_current_profile" if compatible else "stopped_requires_migration_recovery")
    assert not (host.root / "active-compose.json").exists()
    assert host.live_token == "synthetic-rotated-after-start"
    # No helper command ever extracts or imports a backup into the live profile.
    assert not any("-x" in arg or "restore" in arg for args in host.calls for arg in args)


def test_partial_recreate_can_rollback_when_new_container_is_missing(host):
    host.fail = "partial_recreate"
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert host.current == OLD and host.running
    assert host.record()["rollback"] == "healthy_previous_image_current_profile"


def test_backup_digest_manifest_and_sqlite_are_verified(tmp_path):
    archive = tmp_path / "profile.tar.gz"
    archive.write_bytes(profile_archive(tmp_path))
    checked = deploy.verify_backup(archive)
    assert checked["sha256"] == deploy.digest(archive)
    assert checked["mode"] == "manual"
    manifest = json.loads((tmp_path / "profile-manifest.json").read_text())
    assert any(item["name"].endswith("auth/twitchio_tokens.json") and "mode" in item and "uid" in item for item in manifest)


@pytest.mark.parametrize("name,kind", [("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                                       ("link", tarfile.SYMTYPE), ("fifo", tarfile.FIFOTYPE)])
def test_backup_rejects_unsafe_archive_members(tmp_path, name, kind):
    path = tmp_path / "unsafe.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = "/outside"
        archive.addfile(member)
    with pytest.raises(deploy.DeployError):
        deploy.verify_backup(path)


def test_command_failure_never_exposes_private_output(monkeypatch):
    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], output=b"synthetic-private-token", stderr=b"synthetic-private-profile")
    monkeypatch.setattr(deploy.subprocess, "run", failed)
    with pytest.raises(deploy.DeployError, match="^External command failed or timed out$"):
        deploy.run(["docker", "inspect", "synthetic"])


@pytest.mark.parametrize("drift", ["public_port", "wrong_volume", "extra_mount", "environment", "user"])
def test_actual_container_drift_blocks_cutover(host, monkeypatch, drift):
    original = host.info
    def info():
        value = original()
        if drift == "public_port":
            value["HostConfig"]["PortBindings"] = {"8765/tcp": [{"HostIp": "0.0.0.0"}]}
        elif drift == "wrong_volume":
            value["Mounts"][0]["Name"] = "other_profile"
        elif drift == "extra_mount":
            value["Mounts"].append({"Destination": "/extra"})
        elif drift == "environment":
            value["Config"]["Env"] = ["SYNTHETIC_UNDECLARED=value"]
        else:
            value["Config"]["User"] = "0:0"
        return value
    monkeypatch.setattr(host, "info", info)
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert host.running and "stop" not in host.events


def test_insufficient_headroom_blocks_build_and_stop(host, monkeypatch):
    monkeypatch.setattr(deploy.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert host.events == [] and host.running


def test_other_profile_owner_prevents_cutover(host, monkeypatch):
    monkeypatch.setattr(deploy.Deployment, "owners", lambda self: [OLD, "f" * 64])
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert host.events == [] and host.running


def test_stopped_policy_mismatch_prevents_candidate(host):
    host.backup_bytes = profile_archive(host.root / "changed", "disabled")
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert "candidate" not in host.events and host.current == OLD and host.running


def test_failed_rollback_does_not_claim_recovery(host, monkeypatch):
    host.fail = "health"
    original = host.run
    def run(args, **kwargs):
        if "up" in args and any(str(arg).endswith("previous.compose.json") for arg in args):
            raise deploy.DeployError("safe rollback command failure")
        return original(args, **kwargs)
    monkeypatch.setattr(deploy, "run", run)
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert host.record()["rollback"] == "recovery_required_no_success_claim"
    assert not host.running


def test_failed_rollback_health_stops_unverified_old_process(host, monkeypatch):
    host.fail = "health"
    original = host.info
    def info():
        value = original()
        if "rollback" in host.events:
            value["State"]["Health"]["Status"] = "unhealthy"
        return value
    monkeypatch.setattr(host, "info", info)
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert host.current == OLD and not host.running
    assert host.record()["rollback"] == "recovery_required_no_success_claim"
    assert host.record()["recovery_stop_verified"] is True


def test_exited_candidate_can_roll_back_without_clean_candidate_exit(host, monkeypatch):
    original = host.info
    def info():
        value = original()
        if host.current == NEW:
            host.running = False
            value["State"].update(Running=False, ExitCode=1)
        return value
    monkeypatch.setattr(host, "info", info)
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert host.current == OLD and host.running
    assert host.record()["rollback"] == "healthy_previous_image_current_profile"


def test_stopped_partial_recreate_rollback_stays_stopped(host):
    host.running = False
    host.fail = "partial_recreate"
    with pytest.raises(deploy.DeployError):
        host.execute()
    assert host.current == OLD and not host.running
    assert host.record()["rollback"] == "previous_image_process_stopped"


def test_subprocess_inputs_are_bounded_and_do_not_inherit_host_overrides(monkeypatch):
    monkeypatch.setenv("HEETKIT_SECRETS_DIR", "synthetic-unexpected-path")
    monkeypatch.setenv("COMPOSE_FILE", "synthetic-unexpected-compose")
    def command(args, **kwargs):
        assert isinstance(args, list) and "shell" not in kwargs
        assert not any(key.startswith(("HEETKIT_", "COMPOSE_")) for key in kwargs["env"])
        assert kwargs["timeout"] == 17 and kwargs["check"] is True
        return SimpleNamespace(stdout=b"synthetic")
    monkeypatch.setattr(deploy.subprocess, "run", command)
    assert deploy.run(["docker", "inspect", "synthetic"], timeout=17) == b"synthetic"


def test_lock_refuses_another_deployment(tmp_path):
    pytest.importorskip("fcntl")
    tmp_path.chmod(0o700)
    with deploy.deployment_lock(tmp_path), pytest.raises(deploy.DeployError, match="host lock"):
        with deploy.deployment_lock(tmp_path):
            pytest.fail("Concurrent deployment admitted")
