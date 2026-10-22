"""Coarse Quick selection and CI reporting; never build or publish artifacts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SMOKE_TESTS = (
    "tests/test_version.py",
    "tests/test_registry.py",
    "tests/test_cooldown.py",
    "tests/test_command_settings.py",
    "tests/test_management_api.py::test_authentication_origin_host_and_private_surface",
)


def select_checks(paths: list[str]) -> dict[str, bool]:
    """Select fixed check groups, not individual tests based on source files."""
    python_dependencies = any(
        p == "pyproject.toml" or p.startswith("packaging/") and p.endswith(".txt")
        for p in paths
    )
    orchestration = any(
        p.startswith(".github/workflows/") or p in (
            "scripts/ci_checks.py", "tests/test_ci_workflows.py",
            "tests/test_release_publication.py", "tests/test_release_evidence.py",
            "scripts/release_evidence.py",
        ) for p in paths
    )
    return {
        "smoke": python_dependencies or any(p.startswith(("app/", "tests/", "scripts/", "packaging/"))
                                             or p in ("Dockerfile", ".dockerignore", "compose.yaml", "compose.remote.yaml")
                                             for p in paths),
        "typecheck": python_dependencies or orchestration or any(
            p.startswith("frontend/") or p in ("app/management.py", "app/management_api.py", "app/webview_host.py")
            for p in paths
        ),
        "inputs": orchestration or any(
            p.startswith(("docs/releases/", "scripts/", "packaging/"))
            or p in ("app/version.py", "pyproject.toml")
            or p.startswith(".github/") and p.endswith((".yml", ".yaml"))
            for p in paths
        ),
    }


def changed_paths(before: str, sha: str, *, root: Path = ROOT) -> tuple[list[str], str]:
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)

    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected an immutable commit SHA")
    if re.fullmatch(r"[0-9a-f]{40}", before) and before != "0" * 40:
        try:
            # Includes deleted paths and both names of renames, across the whole push.
            data = git("diff", "--no-renames", "--name-only", "-z", before, sha, "--")
            return data.decode("utf-8").rstrip("\0").split("\0") if data else [], "whole-push diff"
        except subprocess.CalledProcessError:
            pass
    # New branch/unavailable old commit: fail safe by selecting all tracked inputs.
    data = git("ls-tree", "-r", "--name-only", "-z", sha)
    return data.decode("utf-8").rstrip("\0").split("\0"), "all tracked paths (base unavailable)"


def plan_event(event: str, ref: str, before: str, sha: str, *, root: Path = ROOT) -> tuple[dict[str, bool], str]:
    if event != "push" or ref != "refs/heads/main":
        raise ValueError("Quick accepts only main pushes")
    paths, reason = changed_paths(before, sha, root=root)
    return select_checks(paths), reason


def summary(message: str) -> None:
    print(message)
    if target := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(target, "a", encoding="utf-8") as stream:
            stream.write(message + "\n")


def check_inputs(root: Path = ROOT) -> None:
    import yaml  # CI-only dependency; never part of the application payload.

    for suffix in ("*.yml", "*.yaml"):
        for path in (root / ".github").rglob(suffix):
            data = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
            if not isinstance(data, dict):
                raise ValueError(f"Expected YAML mapping: {path.name}")
            if path.parent.name == "workflows" and not (data.get("on") and data.get("jobs")):
                raise ValueError(f"Missing workflow triggers/jobs: {path.name}")
    sys.path.insert(0, str(root))
    from app.version import VERSION, windows_version

    windows_version(VERSION)
    notes_paths = list((root / "docs/releases").glob("v*.md"))
    if root / f"docs/releases/v{VERSION}.md" not in notes_paths:
        raise ValueError("Missing canonical version's curated release notes")
    for path in notes_paths:
        windows_version(path.stem[1:])
        notes = path.read_text(encoding="utf-8")
        if not notes.splitlines() or notes.splitlines()[0].strip() != f"# HeetKit {path.stem}" or len(notes.strip()) < 100:
            raise ValueError(f"Invalid curated release notes: {path.name}")
    summary("Workflow/issue YAML and curated release inputs passed.")


def check_results(results: dict, selected: dict[str, bool] | None = None) -> bool:
    """Skipped work is valid only when the successful plan deliberately omitted it."""
    good = True
    for name, job in results.items():
        result = job["result"]
        expected = selected is None or name == "plan" or selected.get(name, True)
        good &= result == ("success" if expected else "skipped")
        summary(f"- {name}: {result}; {'required' if expected else 'no matching paths'}")
    return good


def report_durations() -> None:
    """Report observed completed jobs/steps from this attempt, when Actions exposes them."""
    from datetime import datetime

    if not os.environ.get("GH_TOKEN"):
        summary("Actions durations unavailable locally; no runtime estimate.")
        return
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    url = (f"{base}/repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
           f"{os.environ['GITHUB_RUN_ID']}/attempts/{os.environ['GITHUB_RUN_ATTEMPT']}/jobs?per_page=100")
    try:
        request = Request(url, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                        "Accept": "application/vnd.github+json"})
        with urlopen(request, timeout=15) as response:
            jobs = json.load(response)["jobs"]
        summary("\nObserved durations for this attempt (seconds; no time budget):")
        for job in jobs:
            for item in [job, *job.get("steps", [])]:
                if item.get("started_at") and item.get("completed_at"):
                    seconds = (datetime.fromisoformat(item["completed_at"]) - datetime.fromisoformat(item["started_at"])).total_seconds()
                    summary(f"- {job['name']} / {item['name']}: {seconds:.1f}s")
    except (URLError, KeyError, ValueError):
        summary("Actions duration metadata unavailable; check the run's job/step timings.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "smoke", "inputs", "finish", "durations"))
    args = parser.parse_args()
    if args.mode == "plan":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        selected, reason = plan_event(os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"],
                                      event.get("before", ""), os.environ["GITHUB_SHA"])
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            for name, value in selected.items():
                stream.write(f"{name}={str(value).lower()}\n")
        summary(f"Quick at {os.environ['GITHUB_SHA']}: {reason}.\n" + "\n".join(
            f"- {name}: {'run (matching paths)' if run else 'skip (no matching paths)'}" for name, run in selected.items()
        ))
    elif args.mode == "smoke":
        summary("Fixed Python smoke set:\n" + "\n".join(f"- {name}" for name in SMOKE_TESTS))
        return subprocess.call([sys.executable, "-m", "pytest", "-q", *SMOKE_TESTS], cwd=ROOT)
    elif args.mode == "inputs":
        check_inputs()
    elif args.mode == "finish":
        results = json.loads(os.environ["CI_RESULTS"])
        selected = None
        if "plan" in results:
            selected = {name: value == "true" for name, value in results["plan"].get("outputs", {}).items()}
        good = check_results(results, selected)
        report_durations()
        return 0 if good else 1
    else:
        report_durations()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
