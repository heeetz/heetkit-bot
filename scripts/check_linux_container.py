"""Build and validate the canonical Compose image using disposable synthetic state."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    target_platform = os.environ.get("HEETKIT_PLATFORM") or "linux/amd64"
    if target_platform not in {"linux/amd64", "linux/arm64"}:
        raise ValueError("HEETKIT_PLATFORM must be linux/amd64 or linux/arm64")
    project = "heetkit-b3-" + uuid4().hex[:12]
    image = "heetkit-headless:" + project
    built = False
    with tempfile.TemporaryDirectory(prefix="heetkit-b3-") as temporary:
        private = Path(temporary)
        context = private / "context"
        context.mkdir()
        tracked = subprocess.run(["git", "ls-files", "-z", "--", "app", "frontend", "Dockerfile", ".dockerignore", "LICENSE", "NOTICE", "packaging/linux/requirements.txt", "packaging/python-bootstrap.txt"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        for name in filter(None, tracked.split("\0")):
            source = ROOT / name
            if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
                raise ValueError("Unsafe tracked container build input")
            target = context / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        # Poison only this temporary context, never the user's ignored profile,
        # credentials or built frontend. Directory exceptions must not admit these.
        for name in (".env", ".git/config", "data/heetkit.db", "auth/twitchio_tokens.json",
                     "app/data/twitchio_tokens.json", "app/resources/private.json",
                     "app/resources/frontend/index.html", "frontend/dist/index.html", "frontend/src/private.json",
                     "frontend/.env", "frontend/node_modules/private.json", "frontend/public/private.json",
                     "tests/private.json", "packaging/windows/private.txt"):
            decoy = context / name
            decoy.parent.mkdir(parents=True, exist_ok=True)
            decoy.write_text("synthetic-excluded-build-context-sentinel")
        # These are public synthetic sentinels, never a real profile or credential.
        for name, value in (("twitch_client_secret", "synthetic-client-secret"), ("gemini_api_key", "")):
            target = private / name
            target.write_text(value)
            # Native Compose bind-mount secrets preserve host permissions. The
            # temp parent is private; container UID 10001 must read the files.
            target.chmod(0o444)
        override = private / "probe.json"
        override.write_text(json.dumps({"services": {"bot": {
            "image": image,
            "build": {"context": str(context)},
            "restart": "no", "network_mode": "none",
            "entrypoint": ["python", "/validation/headless_container.py", "run"], "command": [],
            "volumes": [{"type": "bind", "source": str(ROOT / "tests/fixtures"), "target": "/validation", "read_only": True}],
        }}}))
        empty_env = private / "empty.env"
        empty_env.write_text("")
        environment = os.environ | {"HEETKIT_SECRETS_DIR": str(private)}
        compose = ["docker", "compose", "--env-file", str(empty_env), "--project-name", project,
                   "-f", str(ROOT / "compose.yaml"), "-f", str(override)]

        def run(*arguments: str, capture: bool = False, timeout: int = 60) -> str:
            result = subprocess.run(arguments, cwd=ROOT, env=environment, text=True, capture_output=capture, timeout=timeout, check=True)
            return result.stdout.strip() if capture else ""

        def container_id() -> str:
            return run(*compose, "ps", "--all", "--quiet", "bot", capture=True)

        def state() -> dict:
            return json.loads(run("docker", "inspect", container_id(), capture=True))[0]["State"]

        def wait_healthy() -> None:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                status = state()
                if status.get("Health", {}).get("Status") == "healthy":
                    return
                if not status["Running"]:
                    raise RuntimeError("Synthetic container exited before readiness")
                time.sleep(0.5)
            raise TimeoutError("Synthetic container did not become healthy")

        def stopped_cleanly() -> None:
            status = state()
            assert not status["Running"] and status["ExitCode"] == 0, status

        def policy(*arguments: str) -> str:
            return run(*compose, "run", "--rm", "--no-deps", "--entrypoint", "python", "bot",
                "/validation/headless_container.py", "policy", *arguments, capture=True)

        def wait_sessions(starts: int, stops: int) -> None:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                counters = json.loads(policy("stats"))
                if counters["starts"] == starts and counters["stops"] == stops:
                    return
                time.sleep(0.2)
            raise TimeoutError(f"Synthetic policy sessions did not settle: {counters}")

        try:
            run(*compose, "config", "--quiet")
            engine = run("docker", "version", "--format", "{{.Server.Arch}}", capture=True)
            execution = "native" if engine == target_platform.split("/")[1] else "emulated"
            print(f"Validating {target_platform} on {engine} Docker Engine ({execution} execution).", flush=True)
            run(*compose, "build", timeout=600)
            built = True
            assert run("docker", "image", "inspect", image, "--format", "{{.Architecture}}", capture=True) == target_platform.split("/")[1]
            machine = run(*compose, "run", "--rm", "--no-deps", "--entrypoint", "python", "bot",
                "-c", "import platform; print(platform.machine())", capture=True)
            assert machine in ({"x86_64", "amd64"} if target_platform == "linux/amd64" else {"aarch64", "arm64"}), machine
            run(*compose, "run", "--rm", "--no-deps", "--entrypoint", "python", "bot", "/validation/headless_container.py", "seed")
            run(*compose, "up", "--detach", "--no-build")
            wait_healthy()
            first = container_id()
            duplicate = subprocess.run([*compose, "exec", "-T", "bot", "python", "-m", "app.headless"], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
            assert duplicate.returncode == 1
            assert "Another HeetKit process owns this profile" in duplicate.stderr
            run("docker", "kill", "--signal=SIGINT", first)
            run("docker", "wait", first)
            stopped_cleanly()
            run(*compose, "start", "bot")
            wait_healthy()
            assert container_id() == first
            run(*compose, "stop", "bot")  # Real SIGTERM and Compose's stop deadline.
            stopped_cleanly()
            run(*compose, "up", "--detach", "--no-build", "--force-recreate", "bot")
            wait_healthy()
            assert container_id() != first
            run(*compose, "stop", "bot")
            stopped_cleanly()
            run(*compose, "run", "--rm", "--no-deps", "--entrypoint", "python", "bot", "/validation/headless_container.py", "verify")
            # The same saved profile survives actual container restarts/recreation
            # in every operation mode. The only remote boundary remains synthetic.
            for mode in ("manual", "disabled", "stream_only"):
                policy("set-mode", mode)
                policy("set-live", "false")
                for recreate in (False, True):
                    if recreate:
                        run(*compose, "up", "--detach", "--no-build", "--force-recreate", "bot")
                    else:
                        run(*compose, "start", "bot")
                    wait_healthy()
                    assert json.loads(policy("stats")) == {"mode": mode, "starts": 3, "stops": 3}
                    run(*compose, "stop", "bot")
                    stopped_cleanly()
            policy("set-mode", "always_on")
            run(*compose, "start", "bot")
            wait_healthy()
            wait_sessions(4, 3)
            run(*compose, "stop", "bot")
            stopped_cleanly()
            policy("set-mode", "stream_only")
            run(*compose, "start", "bot")
            wait_healthy()
            policy("set-live", "true")
            wait_sessions(5, 4)
            policy("set-live", "unknown")
            time.sleep(1)
            wait_sessions(5, 4)  # Failure must not disconnect or cycle sessions.
            policy("set-live", "false")
            wait_sessions(5, 5)
            policy("set-live", "true")
            wait_sessions(6, 5)
            run(*compose, "stop", "bot")
            stopped_cleanly()
            wait_sessions(6, 6)
            run(*compose, "run", "--rm", "--no-deps", "--entrypoint", "python", "bot",
                "/validation/headless_container.py", "availability")
            run(*compose, "run", "--rm", "--no-deps", "--entrypoint", "python", "bot", "-m", "pip", "check")
            # Exercise the unmodified production CLI against an empty separate
            # profile: safe failure must not hang or print the mounted secret.
            failure = subprocess.run([*compose, "run", "--rm", "--no-deps", "--entrypoint", "python", "bot", "-m", "app.headless", "--data-dir", "/tmp/unconfigured"], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
            assert failure.returncode == 1
            assert "Missing: TWITCH_CLIENT_ID" in failure.stderr
            assert "synthetic-client-secret" not in failure.stderr
            print(f"Canonical Linux Compose checks passed for {target_platform} ({execution} execution); no live authorization or application network used.")
        except BaseException:
            subprocess.run([*compose, "logs", "--no-color"], cwd=ROOT, env=environment, timeout=30, check=False)
            raise
        finally:
            # Only this randomly named disposable validation project is removed.
            run(*compose, "down", "--volumes", "--remove-orphans")
            if built:
                run("docker", "image", "rm", image)


if __name__ == "__main__":
    main()
