"""Quick selection, lightweight input checks and Actions reporting."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
QUICK_GROUPS = ("python", "frontend", "inputs")
PLAN_FLAGS = (*QUICK_GROUPS, "server", "distribution", "orchestration")
COMPARED = ("whole-push diff", "pull request diff", "branch diff from main")
QUICK_WORKFLOW = ".github/workflows/quick.yml"
VERIFIED = "already verified"
BROWSER_SHARDS = 3  # complete browser suite, split across parallel Windows jobs
BROWSER_TEST = re.compile(r".+\.(?:spec|test)\.[cm]?[jt]sx?$")
SERVER_TEST = "tests/browser-server.spec.ts"

# Match only files owned by one area. Unknown and shared source gets the full suite.
# Names are relative to frontend/src; test stems are relative to frontend/tests.
BROWSER_AREAS = (
    ("pages/AIPage.tsx components/AISetupPanel.tsx components/AIBehaviorSection.tsx "
     "components/AIMemoryLimits.tsx components/AIPlayground.tsx components/BlockedAIUsers.tsx components/ai-setup.css i18n/ai.ts",
     "browser-ai browser-settings"),
    ("pages/CommandsPage.tsx components/AnnouncementsPanel.tsx components/ChatLeaderboards.tsx "
     "components/ChatReactions.tsx components/CommandEditorDialog.tsx components/CommandList.tsx "
     "components/CommandRestrictions.tsx components/OptOutManagement.tsx i18n/commands.ts",
     "browser-commands browser-announcements browser-analytics"),
    ("pages/AnalyticsPage.tsx pages/analytics.css i18n/analytics.ts", "browser-analytics"),
    ("pages/FiltersPage.tsx i18n/filters.ts", "browser-filters"),
    ("pages/SettingsPage.tsx components/ConfigurationTransfer.tsx components/SetupChecklist.tsx "
     "components/TwitchSecretField.tsx components/TwitchSetupInstructions.tsx components/settings-layout.css i18n/settings.ts",
     "browser-settings browser-configuration-transfer desktop-startup"),
    ("pages/AboutPage.tsx i18n/about.ts", "about browser-about"),
)
PAGE_INTEGRATION_TESTS = "browser-management browser-i18n browser-dashboard"
SHARED_HOST_PATHS = {
    "app/app_settings.py", "app/bot_runtime.py", "app/configuration_transfer.py", "app/container.py",
    "app/credentials.py", "app/desktop_relaunch.py", "app/headless.py", "app/main.py", "app/management.py",
    "app/management_api.py",
    "app/operation_policy.py", "app/runtime_paths.py", "app/server_credentials.py", "app/twitch_setup.py",
    "app/settings_recovery.py", "app/twitch/client.py", "app/webview_host.py",
}


@dataclass
class QuickPlan:
    reasons: dict[str, set[str]] = field(default_factory=lambda: {name: set() for name in QUICK_GROUPS})
    browser_files: set[str] = field(default_factory=set)
    all_browser: bool = False
    distribution: bool = False
    orchestration: bool = False

    def broaden(self, reason: str) -> None:
        for reasons in self.reasons.values():
            reasons.add(reason)
        self.all_browser = self.distribution = self.orchestration = True

    def shards(self) -> list[int]:
        if self.all_browser:
            count = BROWSER_SHARDS
        else:
            count = 2 if len(self.browser_files) > 6 else 1
        return list(range(1, count + 1))

    def outputs(self) -> dict[str, str]:
        groups = {name: str(bool(reasons)).lower() for name, reasons in self.reasons.items()}
        return {**groups, "browser_files": json.dumps(None if self.all_browser else sorted(self.browser_files)),
                "browser_shards": json.dumps(self.shards()),
                "server": str(self.all_browser or SERVER_TEST in self.browser_files).lower(),
                "distribution": str(self.distribution).lower(),
                "orchestration": str(self.orchestration and not self.reasons["python"]).lower()}


def select_checks(paths: list[str], *, root: Path = ROOT, missing_base: bool = False) -> QuickPlan:
    plan = QuickPlan()
    if missing_base:
        plan.broaden("comparison base unavailable")
        return plan

    for path in paths:
        if path.startswith("frontend/"):
            plan.reasons["frontend"].add("frontend source, setup or tests")
            plan.reasons["inputs"].add("frontend distribution and dependency inputs")
            plan.distribution = True
            relative = path.removeprefix("frontend/")
            if relative.startswith("tests/") and BROWSER_TEST.fullmatch(relative) and (root / path).is_file():
                plan.browser_files.add(relative)
            else:
                for sources, test_stems in BROWSER_AREAS:
                    if relative.removeprefix("src/") in sources.split() and relative.startswith("src/"):
                        plan.browser_files.update(f"tests/{stem}.spec.ts"
                                                  for stem in (test_stems + " " + PAGE_INTEGRATION_TESTS).split())
                        break
                else:
                    plan.all_browser = True
                    plan.reasons["frontend"].add("shared, removed or unmapped frontend input")
        elif path.startswith(("app/", "tests/")):
            plan.reasons["python"].add("application source or Python tests")
            if path.startswith("app/"):
                plan.reasons["inputs"].add("application distribution inputs")
                plan.distribution = True
            if path in SHARED_HOST_PATHS or path.startswith(("app/config/", "tests/fixtures/")):
                plan.reasons["frontend"].add("shared Desktop and Server boundary")
                plan.all_browser = True
        elif (path.startswith(("scripts/", "packaging/", ".github/workflows/", ".github/actions/"))
              or path in {"pyproject.toml", ".gitattributes", "Dockerfile", "Dockerfile.dockerignore",
                          ".dockerignore", "run.bat"} or path.startswith("compose.")):
            plan.broaden("build, workflow or dependency configuration")
        elif path.startswith("third_party_licenses/") or path in {"LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"}:
            plan.reasons["inputs"].add("distribution notices")
            plan.distribution = True
        elif path.startswith(("docs/releases/", ".github/ISSUE_TEMPLATE/")):
            plan.reasons["inputs"].add("machine-consumed release or issue metadata")
            plan.orchestration = True
        elif (path in {"README.md", "CONTRIBUTING.md", "SECURITY.md", "AGENTS.md", "CLAUDE.md",
                      ".github/pull_request_template.md"}
              or path.startswith("docs/") and (path.endswith(".md") or path.startswith("docs/assets/"))):
            plan.reasons["inputs"].add("lightweight documentation and metadata checks")
        else:
            plan.broaden("unclassified executable or input path")

    if not plan.all_browser and any(not (root / "frontend" / name).is_file() for name in plan.browser_files):
        plan.all_browser = True
        plan.reasons["frontend"].add("a mapped browser test moved or is missing")
    return plan


def changed_paths(before: str, sha: str, *, root: Path = ROOT, label: str = COMPARED[0]) -> tuple[list[str], str]:
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)

    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected an immutable commit SHA")
    if re.fullmatch(r"[0-9a-f]{40}", before) and before != "0" * 40:
        try:
            # Includes deleted paths and both names of renames, across the whole push.
            data = git("diff", "--no-renames", "--name-only", "-z", before, sha, "--")
            return data.decode("utf-8").rstrip("\0").split("\0") if data else [], label
        except subprocess.CalledProcessError:
            pass
    # New branch/unavailable old commit: fail safe by selecting all tracked inputs.
    data = git("ls-tree", "-r", "--name-only", "-z", sha)
    return data.decode("utf-8").rstrip("\0").split("\0"), "all tracked paths (base unavailable)"


def event_base(event: str, ref: str, payload: dict, sha: str, *, root: Path = ROOT) -> tuple[str, str]:
    """Return the comparison base and its label for a supported Quick trigger."""
    if event == "push":
        if ref != "refs/heads/main":
            raise ValueError("Quick accepts only main pushes, pull requests to main and manual branch runs")
        return payload.get("before", ""), COMPARED[0]
    if event == "pull_request":
        base = payload.get("pull_request", {}).get("base", {})
        if base.get("ref") != "main":
            raise ValueError("Quick accepts only pull requests to main")
        return base.get("sha", ""), COMPARED[1]
    if event == "workflow_dispatch":
        if not ref.startswith("refs/heads/"):
            raise ValueError("Quick accepts only manual runs on a branch")
        try:
            base = subprocess.check_output(["git", "merge-base", "refs/remotes/origin/main", sha], cwd=root,
                                           stderr=subprocess.DEVNULL, text=True).strip()
        except (subprocess.CalledProcessError, OSError):
            base = ""
        return base, COMPARED[2]
    raise ValueError("Quick accepts only main pushes, pull requests to main and manual branch runs")


def github_api(path: str) -> object:
    """Read one repository API resource with the workflow token."""
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    request = Request(f"{base}/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
                      headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                               "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def verified_merge(before: str, sha: str, *, root: Path = ROOT, api: Callable[[str], object] = github_api) -> str:
    """Explain why a main push needs no new Quick run, or return "" to run the selected checks.

    A squash or merge commit is already verified when its file tree is identical to the head of
    the merged pull request, that head already contained the previous main commit, and Quick
    passed on that head. Any missing evidence or lookup failure keeps the normal selection.
    """
    hexsha = re.compile(r"[0-9a-f]{40}")
    if not (hexsha.fullmatch(before or "") and hexsha.fullmatch(sha)) or before == "0" * 40:
        return ""

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()

    try:
        pulls = api(f"commits/{sha}/pulls")
        pull = next(item for item in pulls if isinstance(item, dict) and item.get("merged_at")
                    and item.get("merge_commit_sha") == sha and item.get("base", {}).get("ref") == "main")
        head = pull["head"]["sha"]
        if not hexsha.fullmatch(head):
            return ""
        try:
            git("cat-file", "-e", f"{head}^{{commit}}")
        except subprocess.CalledProcessError:
            git("fetch", "--no-tags", "--quiet", "origin", head)
        if git("rev-parse", f"{sha}^{{tree}}") != git("rev-parse", f"{head}^{{tree}}"):
            return ""
        git("merge-base", "--is-ancestor", before, head)
        runs = api(f"actions/runs?head_sha={head}&event=pull_request&status=success&per_page=100")
        run = next(item for item in runs["workflow_runs"] if str(item.get("path", "")).startswith(QUICK_WORKFLOW)
                   and item.get("conclusion") == "success")
    except (StopIteration, KeyError, TypeError, ValueError, OSError, URLError,
            subprocess.CalledProcessError):
        return ""
    return (f"{VERIFIED}: identical file tree to pull request #{pull.get('number')} head `{head}`, "
            f"which already contained the previous main commit and passed Quick ({run.get('html_url', 'run')})")


def plan_event(event: str, ref: str, before: str, sha: str, *, root: Path = ROOT, payload: dict | None = None,
               complete: bool = False, verify: Callable[[str, str], str] | None = None) -> tuple[QuickPlan, list[str], str]:
    if payload is None:
        payload = {"before": before}
    base, label = event_base(event, ref, payload, sha, root=root)
    if event == "push" and not complete and verify and (reason := verify(base, sha)):
        return QuickPlan(), [], reason
    if complete:
        paths, _ = changed_paths("", sha, root=root)
        plan = QuickPlan()
        plan.broaden("complete run requested")
        return plan, paths, "complete run requested"
    if label == COMPARED[2] and base == sha:
        # A manual run on main (or an unchanged branch) has nothing to compare: run everything.
        base = ""
    paths, reason = changed_paths(base, sha, root=root, label=label)
    return select_checks(paths, root=root, missing_base=reason not in COMPARED), paths, reason


def summary(message: str) -> None:
    print(message)
    if target := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(target, "a", encoding="utf-8") as stream:
            stream.write(message + "\n")


def check_inputs(root: Path = ROOT, *, metadata_only: bool = False) -> None:
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
    summary("Workflow/issue YAML and curated release notes passed.")
    if not metadata_only:
        from scripts.check_distribution_inputs import check_distribution_inputs

        check_distribution_inputs(root)
        summary("Docker context, runtime resources, Python pins and Windows notice inputs passed.")


def browser_command(files: list[str] | None, shard: str = "") -> list[str]:
    if files == []:
        raise ValueError("An empty browser selection cannot run")
    filters = [r"[/\\]".join(map(re.escape, name.split("/"))) + "$" for name in sorted(set(files or []))]
    sharding = []
    if shard:
        if not re.fullmatch(r"([1-9][0-9]*)/([1-9][0-9]*)", shard) or int(shard.split("/")[0]) > int(shard.split("/")[1]):
            raise ValueError("Expected a browser shard such as 1/3")
        if shard != "1/1":
            sharding = [f"--shard={shard}"]
    return ["node", "node_modules/@playwright/test/cli.js", "test", "--reporter=line,junit", "--workers=2",
            "--trace=retain-on-failure", *sharding, *filters]


def check_results(results: dict, selected: dict[str, bool] | None = None, *, required: tuple[str, ...] = ()) -> bool:
    """Skipped work is valid only when the successful plan deliberately omitted it."""
    good = True
    for name in sorted(results.keys() | set(required)):
        result = results.get(name, {}).get("result", "missing")
        expected = selected is None or name == "plan" or selected.get(name, True)
        good &= result == ("success" if expected else "skipped")
        summary(f"- {name}: {result} ({'required' if expected else 'omitted by the plan'})")
    return good


def report_actions() -> None:
    """Report failures and measured job durations from the current Actions attempt."""
    from datetime import datetime

    if not os.environ.get("GH_TOKEN"):
        summary("Actions durations unavailable locally; no runtime estimate.")
        return
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    run = f"{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    run_page = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{run}"
    url = f"{base}/repos/{run}/attempts/{os.environ['GITHUB_RUN_ATTEMPT']}/jobs?per_page=100"
    try:
        request = Request(url, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                        "Accept": "application/vnd.github+json"})
        with urlopen(request, timeout=15) as response:
            jobs = json.load(response)["jobs"]
        failures = []
        for job in jobs:
            job_page = job.get("html_url") or run_page
            failed_steps = [step for step in job.get("steps", []) if step.get("conclusion") in {"failure", "cancelled"}]
            for step in failed_steps:
                label, _, _ = step["name"].partition(":")
                category = label if label in {"Test", "Build", "Packaging", "Inputs", "Container"} else "Setup or workflow"
                step_page = f"{job_page}#step:{step['number']}:1" if step.get("number") else job_page
                failures.append(f"- {category} · [{job['name']} / {step['name']}]({step_page}) · {step['conclusion']}")
            if not failed_steps and job.get("conclusion") in {"failure", "cancelled"}:
                failures.append(f"- [{job['name']}]({job_page}) · {job['conclusion']} before a step reported a result")
        if failures:
            summary("\n### Failed or cancelled steps\n" + "\n".join(failures))
            summary(f"See [run artifacts]({run_page}#artifacts) for available `*-diagnostics-*` JUnit reports, traces and screenshots.")
        summary("\n### Observed job and check durations")
        for job in jobs:
            items = [job, *(step for step in job.get("steps", []) if step["name"].startswith(("Test:", "Build:", "Packaging:", "Container:")))]
            for item in items:
                if item.get("started_at") and item.get("completed_at"):
                    seconds = (datetime.fromisoformat(item["completed_at"]) - datetime.fromisoformat(item["started_at"])).total_seconds()
                    name = job["name"] if item is job else f"{job['name']} / {item['name']}"
                    summary(f"- {name} · {seconds:.1f}s")
    except (URLError, KeyError, ValueError):
        summary("Actions duration metadata unavailable; check the run's job/step timings.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "browser", "inputs", "frontend-output", "finish", "durations"))
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    if args.mode == "plan":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        complete = os.environ.get("QUICK_COMPLETE", "").lower() == "true"
        plan, paths, reason = plan_event(os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"],
                                         event.get("before", ""), os.environ["GITHUB_SHA"], payload=event,
                                         complete=complete,
                                         verify=verified_merge if os.environ.get("GH_TOKEN") else None)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            for name, value in plan.outputs().items():
                stream.write(f"{name}={value}\n")
        summary(f"### Quick selection for `{os.environ['GITHUB_SHA']}`\n\n{reason}.")
        summary("\nPaths from the comparison or fallback inventory:\n\n~~~text\n" +
                ("\n".join(json.dumps(path) for path in paths) or "(empty comparison)") + "\n~~~")
        for name, reasons in plan.reasons.items():
            details = ("; ".join(sorted(reasons)) if reasons else "no applicable changes" if paths
                       else VERIFIED if reason.startswith(VERIFIED) else "empty comparison")
            summary(f"- {name}: {'run' if reasons else 'skip'} ({details})")
        if plan.reasons["frontend"]:
            summary("- Browser files: " + ("complete suite" if plan.all_browser else ", ".join(sorted(plan.browser_files)))
                    + f" ({len(plan.shards())} parallel job(s))")
        if plan.reasons["inputs"]:
            summary("- Input scope: " + ("metadata and distribution" if plan.distribution else "metadata only"))
            if plan.orchestration:
                summary("- Orchestration tests: " + ("included in the Python suite" if plan.reasons["python"] else "focused input job"))
    elif args.mode == "browser":
        return subprocess.call(browser_command(json.loads(os.environ["BROWSER_FILES"]), os.environ.get("BROWSER_SHARD", "")),
                               cwd=ROOT / "frontend")
    elif args.mode == "inputs":
        check_inputs(metadata_only=args.metadata_only)
    elif args.mode == "frontend-output":
        sys.path.insert(0, str(ROOT))
        from scripts.build_windows import frontend_assets

        frontend_assets(ROOT / "frontend/dist")
    elif args.mode == "finish":
        summary(f"### Selected SHA\n\n`{os.environ.get('SELECTED_SHA', os.environ.get('GITHUB_SHA')) or 'unresolved'}`")
        results = json.loads(os.environ["CI_RESULTS"])
        if os.environ.get("CI_QUICK") == "true" or "plan" in results:
            outputs = results.get("plan", {}).get("outputs", {})
            selected = {name: outputs.get(name) == "true" for name in QUICK_GROUPS}
            good = check_results(results, selected, required=("plan", *QUICK_GROUPS))
            if any(outputs.get(name) not in {"true", "false"} for name in PLAN_FLAGS):
                summary("Quick selection did not report a valid decision for every group.")
                good = False
        else:
            good = check_results(results, required=("resolve", "python", "frontend", "containers"))
        report_actions()
        return 0 if good else 1
    else:
        summary(f"### Selected SHA\n\n`{os.environ.get('SELECTED_SHA') or 'unresolved'}`")
        report_actions()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
