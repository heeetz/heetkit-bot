"""Validate source inputs without resolving wheels, running Docker or freezing Windows."""

from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
import subprocess
import tomllib
from xml.etree import ElementTree

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from scripts.build_windows import WINDOWS_RESOURCES
from scripts.check_linux_container import CONTEXT_DECOYS, CONTEXT_PATHS
from scripts.windows_redistribution import load_policy, verify_notice


DESKTOP_RESOURCES = {"icon.ico", "icon.icns", "icon.png", "tray.png", "update-publisher.pub"}
RESOURCE_DIR = "app/resources/"
WINDOWS_DIR = "packaging/windows/"
HASH = re.compile(r"--hash=sha256:[a-f0-9]{64}")


def require_source(root: Path, tracked: set[str], name: str) -> Path:
    path = root / name
    if name not in tracked or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError(f"Missing, untracked or linked distribution input: {name}")
    return path


def docker_context_rules(text: str) -> list[tuple[bool, tuple[str, ...]]]:
    """Read the project's rooted allowlist; fail on syntax this check cannot model."""
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        allow = line.startswith("!")
        pattern = line.removeprefix("!").strip("/")
        parts = tuple(pattern.split("/"))
        if not re.fullmatch(r"[\w./*-]+", pattern) or any(part in {"", ".", ".."} for part in parts) or any(
            "**" in part and (part != "**" or index != len(parts) - 1) for index, part in enumerate(parts)
        ):
            raise ValueError(f"Unsupported Docker context pattern: {line}")
        rules.append((allow, parts))
    if not rules or rules[0] != (False, ("**",)):
        raise ValueError("Docker context must start with a deny-all rule")
    return rules


def in_docker_context(name: str, rules: list[tuple[bool, tuple[str, ...]]]) -> bool:
    parts = name.split("/")
    included = False
    for allow, pattern in rules:
        # Docker rules also match ancestors. A trailing /** requires a descendant.
        if len(parts) >= len(pattern) and all(fnmatchcase(part, glob) for part, glob in zip(parts, pattern)):
            included = allow
    return included


def check_container_inputs(root: Path, tracked: set[str], runtime: set[str]) -> None:
    dockerfile = require_source(root, tracked, "Dockerfile")
    ignore = "Dockerfile.dockerignore" if (root / "Dockerfile.dockerignore").exists() else ".dockerignore"
    rules = docker_context_rules(require_source(root, tracked, ignore).read_text(encoding="utf-8"))
    if leaked := [name for name in CONTEXT_DECOYS if in_docker_context(name, rules)]:
        raise ValueError("Docker context admits private or generated paths: " + ", ".join(leaked))

    required = set()
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields or fields[0].upper() not in {"COPY", "ADD"}:
            continue
        if len(fields) > 1 and fields[1].startswith("--from="):
            continue
        sources = fields[1:-1]
        if not sources or any(not re.fullmatch(r"[\w./-]+", source) for source in sources):
            raise ValueError(f"Unsupported Dockerfile context input: {line}")
        for source in sources:
            if not source.endswith("/"):
                required.add(source)
            elif source == "app/":
                required.update(name for name in tracked if name.startswith(source) and name.endswith(".py"))
                required.update(RESOURCE_DIR + name for name in runtime - DESKTOP_RESOURCES)
            else:
                members = {name for name in tracked if name.startswith(source)}
                if not members:
                    raise ValueError(f"Missing tracked Docker input directory: {source}")
                required.update(members)
    for name in sorted(required):
        require_source(root, tracked, name)
        if not any(name == path or name.startswith(path + "/") for path in CONTEXT_PATHS):
            raise ValueError(f"Native Linux validation does not stage Docker input: {name}")
        if not in_docker_context(name, rules):
            raise ValueError(f"Docker context excludes required build input: {name}")


def read_pins(path: Path, *, hashes_required: bool = False) -> dict[str, str]:
    pins = {}
    content = path.read_text(encoding="utf-8").replace("\\\n", " ")
    for line in content.splitlines():
        tokens = line.partition("#")[0].split()
        if not tokens:
            continue
        pin, *hashes = tokens
        match = re.fullmatch(r"([\w.-]+)==([\w.+!-]+)", pin)
        if not match or (hashes_required and not hashes) or any(not HASH.fullmatch(item) for item in hashes):
            raise ValueError(f"Expected an exact pin{' with SHA-256 hashes' if hashes_required else ''} in {path}: {pin}")
        name = canonicalize_name(match[1])
        if name in pins:
            raise ValueError(f"Duplicate pin in {path}: {name}")
        pins[name] = match[2]
    if not pins:
        raise ValueError(f"No dependency pins found in {path}")
    return pins


def require_dependencies(declarations: list[str], pins: dict[str, str], platform: str) -> None:
    for declaration in declarations:
        requirement = Requirement(declaration)
        if requirement.marker and not requirement.marker.evaluate(
            {"sys_platform": "win32" if platform == "Windows" else "linux", "platform_system": platform,
             "os_name": "nt" if platform == "Windows" else "posix", "python_version": "3.14",
             "python_full_version": "3.14.7"}
        ):
            continue
        version = pins.get(canonicalize_name(requirement.name))
        if not version or not requirement.specifier.contains(version, prereleases=True):
            raise ValueError(f"{platform} requires a compatible pin for {declaration}; found {version or 'none'}")


def check_dependencies(root: Path, tracked: set[str], project: dict) -> None:
    windows = read_pins(require_source(root, tracked, WINDOWS_DIR + "requirements.txt"))
    linux = read_pins(require_source(root, tracked, "packaging/linux/requirements.txt"), hashes_required=True)
    read_pins(require_source(root, tracked, "packaging/python-bootstrap.txt"), hashes_required=True)
    require_dependencies(project["dependencies"], linux, "Linux")
    require_dependencies(project["dependencies"] + project["optional-dependencies"]["desktop"], windows, "Windows")
    for name in sorted(windows.keys() & linux.keys()):
        if windows[name] != linux[name]:
            raise ValueError(f"Shared Python pin differs for {name}: Windows {windows[name]}, Linux {linux[name]}")

    manifest, lock = (json.loads(require_source(root, tracked, f"frontend/{name}").read_text(encoding="utf-8"))
                      for name in ("package.json", "package-lock.json"))
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        if manifest.get(key, {}) != lock["packages"][""].get(key, {}):
            raise ValueError(f"Frontend manifest and lockfile disagree on {key}; regenerate the lockfile")


def check_windows_inputs(root: Path, tracked: set[str]) -> None:
    for name in ("HeetKit.iss", "HeetKit.spec", "HeetKit.exe.config", "launcher.py", "PORTABLE.txt", "redistribution.json"):
        path = require_source(root, tracked, WINDOWS_DIR + name)
        if not path.stat().st_size:
            raise ValueError(f"Empty Windows packaging input: {name}")
    compile((root / WINDOWS_DIR / "HeetKit.spec").read_bytes(), "HeetKit.spec", "exec")
    ElementTree.parse(root / WINDOWS_DIR / "HeetKit.exe.config")
    require_source(root, tracked, "third_party_licenses/inno-setup/LICENSE.txt")
    policy = load_policy(root / WINDOWS_DIR / "redistribution.json")
    for entry in policy["notice_sources"]:
        verify_notice(require_source(root, tracked, entry["path"]), entry["path"], entry["sha256"])
    for name, entry in policy["required_notices"].items():
        relative = name.removeprefix("_internal/")
        # Installed distribution license bytes are only verifiable in the actual builder.
        if not relative.startswith("licenses/"):
            verify_notice(require_source(root, tracked, relative), name, entry["sha256"])
    for name in policy["required_documents"]:
        if not require_source(root, tracked, name.removeprefix("_internal/")).stat().st_size:
            raise ValueError(f"Empty Windows redistribution document: {name}")


def check_distribution_inputs(root: Path) -> None:
    root = root.resolve()
    tracked = set(subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0"))
    configuration = tomllib.loads(require_source(root, tracked, "pyproject.toml").read_text(encoding="utf-8"))
    package_data = configuration["tool"]["setuptools"]["package-data"]["app.resources"]
    runtime = {name.removeprefix(RESOURCE_DIR) for name in tracked if name.startswith(RESOURCE_DIR)}
    runtime.discard("__init__.py")
    for name in sorted(runtime | set(WINDOWS_RESOURCES)):
        require_source(root, tracked, RESOURCE_DIR + name)
        if name not in WINDOWS_RESOURCES and name not in DESKTOP_RESOURCES:
            raise ValueError(f"Runtime resource missing from Windows staging: {name}")
        if name != "update-publisher.pub" and not any(Path(name).match(pattern) for pattern in package_data):
            raise ValueError(f"Runtime resource missing from installed package data: {name}")
    check_container_inputs(root, tracked, runtime | set(WINDOWS_RESOURCES))
    check_dependencies(root, tracked, configuration["project"])
    check_windows_inputs(root, tracked)
