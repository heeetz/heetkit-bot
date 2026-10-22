"""Explicit, serialized release updates of the existing private ARM64 Compose bot.

No provisioning, registry, workflow dispatch, profile restore or automatic update.
All subprocess output and private runtime data stay off the terminal.
"""

from __future__ import annotations

import argparse
import ast
from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request
from uuid import uuid4


REPOSITORY = "https://github.com/heeetz/heetkit-bot.git"
RELEASE_API = "https://api.github.com/repos/heeetz/heetkit-bot/releases/tags/"
VERSION = re.compile(r"v(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})(?:-(alpha|beta|rc)\.([1-9][0-9]{0,3}))?")
SHA = re.compile(r"[0-9a-f]{40}")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
LOCAL = "http://127.0.0.1:8765"
VOLUME = "heetkit_profile"
MODES = {"manual", "disabled", "always_on", "stream_only"}


class DeployError(RuntimeError):
    """Fixed safe message; never include subprocess/HTTP/profile payloads."""


def require(condition, message):
    if not condition:
        raise DeployError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def private_file(path):
    require(path.is_absolute() and path.is_file() and not path.is_symlink(), "Expected an absolute private input file")
    require(path.stat().st_uid == os.getuid() and not stat.S_IMODE(path.stat().st_mode) & 0o077,
            "Private configuration must be owned by the operator and mode 600")
    return path


@contextmanager
def deployment_lock(state):
    import fcntl  # Linux only; keep synthetic tests importable on Windows.

    require(state.is_absolute() and not state.is_symlink(), "Expected an absolute private state directory")
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(state.stat().st_uid == os.getuid() and not stat.S_IMODE(state.stat().st_mode) & 0o077,
            "Deployment state must be owned by the operator and mode 700")
    with (state / "deploy.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeployError("Another deployment holds the host lock") from None
        yield


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http(url, token=None, post=False):
    headers = {"Accept": "application/json", "User-Agent": "HeetKit-release-deploy"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if post:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=b"{}" if post else None, headers=headers)
    # No proxy environment or redirects may forward the private bearer elsewhere.
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=10) as response:
            body = response.read(2 * 1024 * 1024 + 1)
            require(len(body) <= 2 * 1024 * 1024, "HTTP response exceeds bound")
            return response.status, body
    except HTTPError as error:
        return error.code, b""
    except (OSError, URLError):
        raise DeployError("HTTP verification unavailable") from None


def run(args, *, cwd=None, output=None, timeout=60):
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("HEETKIT_", "COMPOSE_"))}
    try:
        result = subprocess.run([str(arg) for arg in args], cwd=cwd, env=environment,
                                stdout=output or subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=True)
        return result.stdout or b""
    except (OSError, subprocess.SubprocessError):
        raise DeployError("External command failed or timed out") from None


def archive_members(archive):
    members = archive.getmembers()
    names = set()
    for member in members:
        path = PurePosixPath(member.name)
        require(not path.is_absolute() and ".." not in path.parts and
                (member.isfile() or member.isdir()) and str(path) not in names,
                "Archive contains unsafe or duplicate entries")
        names.add(str(path))
    return members


def verify_backup(path):
    """Read every byte; inspect copied SQLite files without touching the volume."""
    manifest = []
    with tarfile.open(path, "r:gz") as archive, tempfile.TemporaryDirectory(dir=path.parent) as scratch:
        members = archive_members(archive)
        for member in members:
            if not member.isfile():
                continue
            with archive.extractfile(member) as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            manifest.append({"name": member.name, "size": member.size, "mode": member.mode,
                             "uid": member.uid, "gid": member.gid, "sha256": checksum})
            if any(member.name.endswith(extension + suffix) for extension in (".db", ".sqlite", ".sqlite3")
                   for suffix in ("", "-wal", "-shm", "-journal")):
                target = Path(scratch).joinpath(*PurePosixPath(member.name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream, target.open("wb") as output:
                    shutil.copyfileobj(stream, output)
        for database in Path(scratch).rglob("*"):
            if database.is_file() and database.suffix in {".db", ".sqlite", ".sqlite3"}:
                with closing(sqlite3.connect(database)) as connection:
                    require(connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
                            "Stopped backup SQLite integrity failed")
        settings = archive.extractfile("./config/app_settings.json")
        with settings:
            mode = json.load(settings)["startup"]["operation_mode"]
        require(mode in MODES, "Stopped backup operation policy is invalid")
    require(any(PurePosixPath(item["name"]) == PurePosixPath("data/heetkit.db") for item in manifest),
            "Stopped backup lacks the profile database")
    checksum = digest(path)
    path.with_suffix(path.suffix + ".sha256").write_text(checksum + "  " + path.name + "\n", encoding="ascii")
    write_json(path.parent / "profile-manifest.json", manifest)
    return {"sha256": checksum, "mode": mode, "sqlite_integrity": "ok"}


def projection(status):
    operation = status["operation"]
    require(operation["mode"] in MODES and not operation.get("pending") and not operation.get("error"),
            "Operation policy is pending or needs operator attention")
    require(status["twitch_connection_state"] in {"connected", "stopped"}, "Twitch is in a transitional state")
    return {"mode": operation["mode"], "connected": status["twitch_connected"],
            "channel": status["channel"], "account": status["account"]}


class Deployment:
    def __init__(self, config, release, sha, compatible):
        require(VERSION.fullmatch(release) and SHA.fullmatch(sha), "Expected an explicit version tag and full SHA")
        self.config, self.release, self.sha, self.compatible = config, release, sha, compatible
        self.state = Path(config["state_dir"])
        self.record = {"release": release, "sha": sha, "rollback_compatible": compatible,
                       "result": "preparing", "stage": "preflight"}
        self.attempt = None
        self.before = None
        self.stopping = self.cutover = False
        self.old = None
        self.deadline = int(config.get("health_timeout_seconds", 180))
        require(90 <= self.deadline <= 600, "Health timeout must allow startup grace and remain bounded")

    def save(self, **updates):
        self.record.update(updates)
        write_json(self.attempt / "deployment.json", self.record)

    def command_json(self, args):
        return json.loads(run(args))

    def compose(self, path, *args):
        return run(["docker", "compose", "--project-name", "heetkit", "-f", path, *args], timeout=90)

    def inspect(self, container):
        return self.command_json(["docker", "inspect", container])[0]

    def owners(self):
        return run(["docker", "ps", "--quiet", "--no-trunc", "--filter", "volume=" + VOLUME]).decode().split()

    def container(self, path):
        ids = self.compose(path, "ps", "--all", "--quiet", "bot").decode().split()
        require(len(ids) == 1, "Expected exactly one existing bot container")
        return ids[0]

    def api(self, path="status", post=False):
        code, body = http(LOCAL + "/v1/" + path, self.token.read_text().strip(), post)
        require(code == 200, "Authenticated management check failed")
        return json.loads(body)

    def boundaries(self):
        code, _ = http(self.origin + "/v1/status")
        require(code == 401, "Private HTTPS must reject unauthenticated status")
        serve = self.command_json(["tailscale", "serve", "status", "--json"])
        require(isinstance(serve.get("Web"), dict) and serve["Web"] and
                isinstance(serve.get("AllowFunnel", {}), dict) and not any(serve.get("AllowFunnel", {}).values()),
                "Private Serve configuration is missing or Funnel is enabled")
        handler = serve["Web"].get(urlsplit(self.origin).hostname + ":443", {}).get("Handlers", {}).get("/", {})
        require(handler.get("Proxy") in {LOCAL, LOCAL + "/"} and not serve.get("Foreground"),
                "Expected the persistent private HTTPS proxy to the management listener")
        listeners = run(["ss", "-H", "-ltn"]).decode().splitlines()
        addresses = [line.split()[3] for line in listeners if len(line.split()) >= 4 and line.split()[3].endswith(":8765")]
        require(addresses == ["127.0.0.1:8765"], "Management listener must be loopback only")
        code, body = http(LOCAL + "/")
        require(code == 200 and b'id="root"' in body, "Management panel asset check failed")

    def check_container(self, info, image):
        require(info["Image"] == image and not info["State"].get("OOMKilled") and info["RestartCount"] == 0,
                "Image, restart or OOM verification failed")
        mounts = [m for m in info["Mounts"] if m["Destination"] == "/var/lib/heetkit"]
        require(len(mounts) == 1 and mounts[0]["Type"] == "volume" and mounts[0]["Name"] == VOLUME,
                "Existing profile volume identity changed")
        require(not info["HostConfig"].get("PortBindings") and info["HostConfig"]["NetworkMode"] == "host",
                "Container network boundaries changed")
        require(info["Config"]["Cmd"] == self.model["services"]["bot"]["command"],
                "Deployed command differs from the preserved Compose inputs")
        for name, source in self.secrets.items():
            require(any(mount["Destination"] == "/run/secrets/" + name and mount["Source"] == str(source)
                        and not mount["RW"] for mount in info["Mounts"]), "External secret mount changed")
        require(len(info["Mounts"]) == 1 + len(self.secrets), "Unexpected additional runtime mount")

    def ready(self, path, image, before, *, reconnect=False):
        finish = time.monotonic() + self.deadline
        requested = False
        while time.monotonic() < finish:
            info = self.inspect(self.container(path))
            self.check_container(info, image)
            require(info["State"]["Running"], "Bot process stopped during startup")
            try:
                current = projection(self.api())
                require(all(current[key] == before[key] for key in ("mode", "channel", "account")),
                        "Operation mode or bot identity changed")
                if reconnect and before["mode"] == "manual" and before["connected"] and not current["connected"] and not requested:
                    self.api("bot/start", post=True)
                    requested = True
                expected = current["connected"] == before["connected"] if before["mode"] in {"manual", "disabled"} else (
                    current["connected"] if before["mode"] == "always_on" else True)
                if expected and info["State"].get("Health", {}).get("Status") == "healthy":
                    self.boundaries()
                    return current
            except (DeployError, KeyError, ValueError):
                pass  # Startup/stream reconciliation is bounded; raw payloads stay private.
            time.sleep(3)
        raise DeployError("Startup, panel, boundary or operation verification timed out")

    def inputs(self):
        env = private_file(Path(self.config["env_file"]))
        files = [Path(path) for path in self.config["compose_files"]]
        require(files and all(path.is_absolute() and path.is_file() for path in files), "Expected existing absolute Compose inputs")
        args = ["docker", "compose", "--project-name", "heetkit", "--env-file", env]
        for path in files:
            args.extend(["-f", path])
        model = self.command_json([*args, "config", "--format", "json"])
        require(set(model["services"]) == {"bot"} and model["volumes"]["profile"]["name"] == VOLUME,
                "Expected the existing single-service heetkit project and volume")
        bot = model["services"]["bot"]
        command = bot["command"]
        require(isinstance(command, list) and "--management-api" in command, "Expected private management overlay")
        def flag(name):
            require(command.count(name) == 1 and command.index(name) + 1 < len(command), "Required management option missing")
            return command[command.index(name) + 1]
        self.origin = flag("--management-trusted-origin")
        url = urlsplit(self.origin)
        require(url.scheme == "https" and url.hostname and url.hostname.endswith(".ts.net") and
                self.origin == "https://" + url.hostname and flag("--twitch-redirect-uri") == self.origin + "/oauth/callback" and
                flag("--management-host") == "127.0.0.1" and "--management-port" not in command,
                "Expected unchanged private Tailscale HTTPS and loopback management")
        require(bot["platform"] == "linux/arm64" and bot.get("network_mode") == "host" and not bot.get("ports"),
                "Expected ARM64 host networking without published ports")
        require(bot.get("user") == "10001:10001" and bot.get("read_only") is True,
                "Expected the existing non-root read-only service")
        require(len(bot["volumes"]) == 1 and all(bot["volumes"][0].get(key) == value for key, value in
                {"type": "volume", "source": "profile", "target": "/var/lib/heetkit"}.items()) and
                not bot["volumes"][0].get("read_only"),
                "Expected the existing profile mount only")
        mounted = {item["source"]: item.get("target", item["source"]) for item in bot["secrets"]}
        require(mounted == {name: name for name in ("twitch_client_secret", "gemini_api_key", "management_token")},
                "Expected the existing external secret mounts")
        self.secrets = {name: Path(model["secrets"][name]["file"]) for name in mounted}
        require(all(path.is_absolute() and path.is_file() and not path.is_symlink() for path in self.secrets.values()),
                "Expected external secret files")
        self.token = self.secrets["management_token"]
        self.original_inputs = {path: digest(path) for path in [env, *files, *self.secrets.values()]}
        self.model = model
        self.old = self.command_container(args)
        info = self.inspect(self.old)
        self.old_image = info["Image"]
        require(IMAGE.fullmatch(self.old_image), "Expected immutable previous image ID")
        self.check_container(info, self.old_image)
        image_config = self.command_json(["docker", "image", "inspect", self.old_image])[0]["Config"]
        expected_env = dict(item.split("=", 1) for item in image_config.get("Env", [])) | bot.get("environment", {})
        require(dict(item.split("=", 1) for item in info["Config"].get("Env", [])) == expected_env,
                "Running environment differs from the preserved Compose inputs")
        require(info["Config"].get("User", "") == bot.get("user", image_config.get("User", "")) and
                info["HostConfig"].get("ReadonlyRootfs", False) == bot.get("read_only", False) and
                not info["HostConfig"].get("Privileged"), "Running user or filesystem protections differ from Compose")
        labels = info["Config"]["Labels"]
        require(labels["com.docker.compose.project"] == "heetkit" and labels["com.docker.compose.service"] == "bot",
                "Existing container project identity mismatch")
        self.was_running = info["State"]["Running"]
        require(set(self.owners()) == ({self.old} if self.was_running else set()), "Another running container shares the profile")
        bot.pop("build", None)
        bot["image"] = self.old_image
        write_json(self.attempt / "previous.compose.json", model)
        recovery = self.attempt / "inputs"
        recovery.mkdir(mode=0o700)
        for index, path in enumerate(self.original_inputs):
            target = recovery / str(index)
            shutil.copyfile(path, target)
            target.chmod(0o600)
        write_json(recovery / "manifest.json", [{"copy": str(index), "source": str(path), "sha256": checksum}
                                                for index, (path, checksum) in enumerate(self.original_inputs.items())])

    def command_container(self, args):
        ids = run([*args, "ps", "--all", "--quiet", "bot"]).decode().split()
        require(len(ids) == 1, "Expected exactly one existing bot container")
        return ids[0]

    def prepare(self):
        code, body = http(RELEASE_API + self.release)
        require(code == 200, "Requested published release is unavailable")
        release = json.loads(body)
        require(release["tag_name"] == self.release and not release["draft"] and release.get("published_at"),
                "Requested tag is not a published release")
        self.save(release_url=release["html_url"], old_image=self.old_image, was_running=self.was_running)
        info = self.command_json(["docker", "info", "--format", "{{json .}}"])
        require(info["OSType"] == "linux" and info["Architecture"] in {"aarch64", "arm64"}, "Expected native Linux ARM64 Docker")
        source = self.attempt / "source"
        source.mkdir(mode=0o755)
        run(["git", "init", source])
        run(["git", "-C", source, "fetch", "--depth=1", REPOSITORY, "refs/tags/" + self.release], timeout=180)
        resolved = run(["git", "-C", source, "rev-parse", "FETCH_HEAD^{commit}"]).decode().strip()
        require(resolved == self.sha, "Published tag does not match the requested full SHA")
        archive_path = self.attempt / "source.tar"
        with archive_path.open("wb") as output:
            run(["git", "-C", source, "archive", self.sha], output=output)
        with tarfile.open(archive_path) as archive:
            archive_members(archive)
            archive.extractall(source, filter="data")
        module = ast.parse((source / "app/version.py").read_text())
        version = next(ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign) and
                       any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets))
        require("v" + version == self.release, "Release tag does not match app/version.py")
        old = self.command_json(["docker", "image", "inspect", self.old_image])[0]
        if (self.was_running and old["Id"] == self.old_image and old["Architecture"] == "arm64" and
                old["Os"] == "linux" and old["Config"].get("Labels", {}).get("org.opencontainers.image.revision") == self.sha):
            self.image = self.old_image
            self.save(image=self.image, stage="already_running")
            return
        minimum = int(self.config.get("minimum_free_bytes", 4 * 1024**3))
        require(minimum > 0 and all(shutil.disk_usage(path).free >= minimum for path in (self.state, info["DockerRootDir"])),
                "Insufficient free disk for build and backup")
        memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        minimum_memory = int(self.config.get("minimum_available_memory_bytes", 512 * 1024**2))
        require(minimum_memory > 0 and int(memory["MemAvailable"].split()[0]) * 1024 >= minimum_memory,
                "Insufficient available memory to build while serving")
        self.save(stage="build")
        tag = "heetkit-headless:release-" + self.sha
        run(["docker", "build", "--platform", "linux/arm64", "--label", "org.opencontainers.image.revision=" + self.sha,
             "--tag", tag, source], timeout=1800)
        image = self.command_json(["docker", "image", "inspect", tag])[0]
        require(image["Architecture"] == "arm64" and image["Os"] == "linux" and
                image["Config"]["Labels"]["org.opencontainers.image.revision"] == self.sha and IMAGE.fullmatch(image["Id"]),
                "Prepared image identity or platform mismatch")
        self.image = image["Id"]
        candidate = deepcopy(self.model)
        candidate["services"]["bot"]["image"] = self.image
        write_json(self.attempt / "candidate.compose.json", candidate)
        run(["docker", "image", "tag", self.old_image, "heetkit-headless:rollback-" + self.attempt.name.lower()])
        self.save(image=self.image, stage="prepared")

    def stopped(self, container):
        require(not self.inspect(container)["State"]["Running"] and not self.owners(), "Profile is not quiescent")

    def stop(self, path, *, clean=True):
        container = self.container(path)
        self.compose(path, "stop", "--timeout", "30", "bot")
        self.stopped(container)
        if clean:
            require(self.inspect(container)["State"]["ExitCode"] in {0, 143}, "Container did not stop cleanly; cutover refused")

    def backup(self):
        self.stopped(self.old)
        archive = self.attempt / "profile.tar.gz"
        with archive.open("wb") as output:
            run(["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--log-driver", "none", "--user", "10001:10001", "--mount",
                 "type=volume,src=" + VOLUME + ",dst=/profile,readonly", "--entrypoint", "tar",
                 self.old_image, "-C", "/profile", "-czf", "-", "."], output=output, timeout=300)
        checked = verify_backup(archive)
        if self.before:
            require(checked["mode"] == self.before["mode"], "Stopped profile policy changed before backup")
        self.save(backup=checked, stage="backed_up")

    def recover(self):
        previous = self.attempt / "previous.compose.json"
        if not self.cutover:
            # Only the unchanged original container may resume after a failed backup/stop.
            if self.was_running and not self.inspect(self.old)["State"]["Running"]:
                self.stopped(self.old)
                run(["docker", "start", self.old])
                self.ready(previous, self.old_image, self.before, reconnect=True)
            return "original_service_preserved"
        candidate = self.attempt / "candidate.compose.json"
        ids = self.compose(candidate, "ps", "--all", "--quiet", "bot").decode().split()
        require(len(ids) <= 1, "Ambiguous bot containers after cutover")
        if ids:
            self.stop(candidate, clean=False)
        require(not self.owners(), "Profile is still in use; rollback refused")
        if not self.compatible:
            return "stopped_requires_migration_recovery"
        require(all(digest(path) == checksum for path, checksum in self.original_inputs.items()),
                "Deployment inputs changed; automatic rollback refused")
        # Preserve the current volume and rotated OAuth tokens; never restore the archive.
        if self.was_running:
            self.compose(previous, "up", "-d", "--no-build", "--pull", "never", "--no-deps", "--force-recreate", "bot")
            self.ready(previous, self.old_image, self.before, reconnect=True)
            return "healthy_previous_image_current_profile"
        self.compose(previous, "create", "--no-build", "--pull", "never", "--no-deps", "--force-recreate", "bot")
        self.stopped(self.container(previous))
        self.check_container(self.inspect(self.container(previous)), self.old_image)
        return "previous_image_process_stopped"

    def execute(self):
        self.attempt = self.state / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
        self.attempt.mkdir(mode=0o700)
        self.save()
        previous, candidate = (self.attempt / name for name in ("previous.compose.json", "candidate.compose.json"))
        try:
            self.inputs()
            if self.was_running:
                self.before = projection(self.api())
                self.ready(previous, self.old_image, self.before)
            self.prepare()
            if self.image == self.old_image and self.was_running:
                self.before = projection(self.api())
                self.ready(previous, self.old_image, self.before)
                write_json(self.state / "active-compose.json", self.model)
                self.save(result="already_running_verified", before=self.before, after=self.before)
                return
            require(all(digest(path) == checksum for path, checksum in self.original_inputs.items()),
                    "Deployment inputs changed during preparation")
            require(self.inspect(self.old)["State"]["Running"] == self.was_running, "Process state changed during preparation")
            if self.was_running:
                self.before = projection(self.api())
            self.save(before=self.before, stage="stopping", interruption_started=datetime.now(timezone.utc).isoformat())
            self.stopping = True
            self.stop(previous)
            self.backup()
            self.save(stage="cutover")
            self.cutover = True  # A failed recreate may already have replaced the old container.
            if self.was_running:
                self.compose(candidate, "up", "-d", "--no-build", "--pull", "never", "--no-deps", "--force-recreate", "bot")
                after = self.ready(candidate, self.image, self.before, reconnect=True)
            else:
                self.compose(candidate, "create", "--no-build", "--pull", "never", "--no-deps", "--force-recreate", "bot")
                self.check_container(self.inspect(self.container(candidate)), self.image)
                self.stopped(self.container(candidate))
                after = {"process": "stopped", "mode": self.record["backup"]["mode"], "health": "not_run"}
            write_json(self.state / "active-compose.json", json.loads(candidate.read_text()))
            self.save(result="deployed", stage="complete", after=after, rollback="not_needed",
                      interruption_ended=datetime.now(timezone.utc).isoformat())
        except (Exception, KeyboardInterrupt) as error:
            rollback = "not_needed"
            if self.stopping:
                try:
                    rollback = self.recover()
                except (Exception, KeyboardInterrupt):
                    rollback = "recovery_required_no_success_claim"
                    # A failed rollback may already have started an unverified old
                    # process. Quiesce this project's bot before handing off recovery.
                    verified_stopped = False
                    try:
                        ids = self.compose(previous, "ps", "--all", "--quiet", "bot").decode().split()
                        require(len(ids) <= 1, "Ambiguous containers during recovery shutdown")
                        if ids:
                            self.stop(previous, clean=False)
                        verified_stopped = not self.owners()
                    except (Exception, KeyboardInterrupt):
                        pass
                    self.record["recovery_stop_verified"] = verified_stopped
            self.save(result="failed", rollback=rollback,
                      failure=str(error) if isinstance(error, DeployError) else type(error).__name__,
                      finished_at=datetime.now(timezone.utc).isoformat())
            raise DeployError("Deployment failed; consult the private deployment record") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--release", required=True, help="Published tag, such as v1.4.1; never latest/main")
    parser.add_argument("--sha", required=True, help="Full expected release commit SHA")
    parser.add_argument("--rollback-compatible", action="store_true", help="Operator has checked old-code/current-profile compatibility")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        require(os.name == "posix", "Deploy only on the existing Linux host")
        config = json.loads(private_file(args.config).read_text())
        deployment = Deployment(config, args.release, args.sha, args.rollback_compatible)
        with deployment_lock(deployment.state):
            deployment.execute()
        print("Deployment verified; private record: " + str(deployment.attempt / "deployment.json"))
        return 0
    except (Exception, KeyboardInterrupt):
        print("Deployment did not complete; inspect the private host record and runbook. No success claimed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
