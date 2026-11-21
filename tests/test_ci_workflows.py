"""Synthetic Quick decisions and actual workflow wiring, without Actions/builds."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

import pytest
import yaml

from scripts import ci_checks, release_evidence
from scripts.check_distribution_inputs import check_container_inputs, check_dependencies, check_windows_inputs, read_pins


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_actions_summary(monkeypatch):
    # Synthetic gate/timing output must never enter a real runner's job summary.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def workflow(name):
    # BaseLoader preserves the Actions 'on' key rather than YAML 1.1's boolean.
    return yaml.load((ROOT / f".github/workflows/{name}.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("paths,expected", [
    (["README.md", "docs/development.md"], (False, False, True)),
    (["AGENTS.md", "CLAUDE.md"], (False, False, True)),
    (["app/commands/fun.py"], (True, False, True)),
    (["tests/behavior.py"], (True, False, False)),
    (["frontend/src/pages/FiltersPage.tsx"], (False, True, True)),
    (["frontend/src/bridge.ts"], (False, True, True)),
    (["frontend/package-lock.json"], (False, True, True)),
    (["app/management_api.py"], (True, True, True)),
    (["app/management.py", "app/webview_host.py"], (True, True, True)),
    (["pyproject.toml"], (True, True, True)),
    (["packaging/windows/requirements.txt"], (True, True, True)),
    (["packaging/linux/requirements.txt"], (True, True, True)),
    (["packaging/python-bootstrap.txt"], (True, True, True)),
    ([".github/workflows/quick.yml"], (True, True, True)),
    (["scripts/ci_checks.py"], (True, True, True)),
    ([".github/ISSUE_TEMPLATE/bug.yml"], (False, False, True)),
    (["docs/releases/v1.4.1.md"], (False, False, True)),
    (["app/version.py"], (True, False, True)),
    (["Dockerfile"], (True, True, True)),
    ([".dockerignore"], (True, True, True)),
    (["frontend/src/i18n/commands.ts"], (False, True, True)),
    (["frontend/src/pages/analytics.css"], (False, True, True)),
    (["scripts/build_windows.py"], (True, True, True)),
    (["frontend/tests/browser-server.spec.ts", "app/config/settings.py"], (True, True, True)),
    (["app/new_area/module.py"], (True, False, True)),
    (["new_runtime/entrypoint"], (True, True, True)),
    ([], (False, False, False)),
])
def test_path_selection(paths, expected):
    plan = ci_checks.select_checks(paths)
    assert tuple(bool(plan.reasons[name]) for name in ci_checks.QUICK_GROUPS) == expected


@pytest.mark.parametrize("path", [
    "frontend/src/App.tsx", "frontend/src/styles.css", "frontend/src/components/EditorDialog.tsx",
    "frontend/src/components/Select.tsx", "frontend/src/components/Switch.tsx",
    "frontend/src/bridge.ts", "frontend/src/httpTransport.ts", "frontend/src/components/BrowserSession.tsx",
    "frontend/src/new_area/new.ts", "frontend/tests/new-custom-scenario.ts",
    "frontend/tests/removed.spec.ts", "frontend/package-lock.json",
    "app/management.py", "app/management_api.py", "app/webview_host.py", "app/server_setup.py",
    "app/credentials.py", "app/config/profile_settings.py", "tests/fixtures/management_browser.py",
])
def test_shared_uncertain_and_deleted_paths_include_both_browser_hosts(path):
    plan = ci_checks.select_checks([path])
    assert plan.all_browser
    assert plan.outputs()["server"] == "true"


def test_named_feature_and_changed_or_new_tests_are_combined_once(tmp_path):
    frontend_tests = tmp_path / "frontend/tests"
    frontend_tests.mkdir(parents=True)
    for name in ("filters.spec.ts", "navigation.spec.ts", "browser-management.spec.ts", "responsive.spec.ts",
                 "i18n.spec.ts", "browser-server.spec.ts", "new[scenario].test.mts"):
        (frontend_tests / name).touch()
    plan = ci_checks.select_checks([
        "frontend/src/pages/FiltersPage.tsx", "frontend/tests/filters.spec.ts",
        "frontend/tests/new[scenario].test.mts", "frontend/tests/browser-server.spec.ts",
    ], root=tmp_path)
    assert not plan.all_browser
    assert plan.outputs()["server"] == "true"
    assert set(json.loads(plan.outputs()["browser_files"])) == {
        "tests/filters.spec.ts", "tests/navigation.spec.ts", "tests/browser-management.spec.ts",
        "tests/responsive.spec.ts", "tests/i18n.spec.ts", "tests/browser-server.spec.ts", "tests/new[scenario].test.mts",
    }
    command = ci_checks.browser_command(list(plan.browser_files) + ["tests/filters.spec.ts"])
    filters = command[len(ci_checks.browser_command(None)):]
    assert len(filters) == len(plan.browser_files)
    new_scenario = next(pattern for pattern in filters if "scenario" in pattern)
    assert re.search(new_scenario, "C:/checkout/tests/new[scenario].test.mts")
    assert not re.search(new_scenario, "/checkout/tests/new[scenario].test.mtsx")
    with pytest.raises(ValueError, match="empty browser selection"):
        ci_checks.browser_command([])


def test_focused_orchestration_does_not_repeat_tests_when_python_is_selected():
    paths = ["docs/releases/v1.5.5.md"]
    docs_plan = ci_checks.select_checks(paths).outputs()
    assert docs_plan["orchestration"] == "true"
    assert docs_plan["distribution"] == "false"
    mixed = ci_checks.select_checks([*paths, "tests/test_release_evidence.py"]).outputs()
    assert mixed["python"] == "true"
    assert mixed["orchestration"] == "false"


def test_whole_push_diff_includes_both_commits_deletions_and_rename(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-c", "user.email=ci@example.invalid", "-c", "user.name=CI",
                                        *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    (tmp_path / "app").mkdir()
    (tmp_path / "frontend/src").mkdir(parents=True)
    for path in ("app/deleted.py", "app/edited.py", "frontend/src/old.ts"):
        (tmp_path / path).write_text(f"# {path}\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "base")
    before = git("rev-parse", "HEAD")
    git("rm", "app/deleted.py")
    (tmp_path / "app/edited.py").write_text("# edited\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "backend")
    git("mv", "frontend/src/old.ts", "frontend/src/new.ts")
    (tmp_path / "README.md").touch()
    git("add", ".")
    git("commit", "-qm", "frontend")
    plan, paths, reason = ci_checks.plan_event("push", "refs/heads/main", before, git("rev-parse", "HEAD"), root=tmp_path)
    assert set(paths) == {"app/deleted.py", "app/edited.py", "frontend/src/old.ts", "frontend/src/new.ts", "README.md"}
    assert all(plan.outputs()[name] == "true" for name in ci_checks.QUICK_GROUPS)
    assert reason == "whole-push diff"


@pytest.mark.parametrize("before,fail_diff", [("0" * 40, False), ("a" * 40, True)])
def test_new_branch_or_missing_base_selects_all_groups(monkeypatch, before, fail_diff):
    def git(args, **kwargs):
        if args[1] == "diff" and fail_diff:
            raise subprocess.CalledProcessError(128, args)
        assert args == ["git", "ls-tree", "-r", "--name-only", "-z", "b" * 40]
        return b"README.md\0"

    monkeypatch.setattr(subprocess, "check_output", git)
    plan, paths, reason = ci_checks.plan_event("push", "refs/heads/main", before, "b" * 40)
    assert all(plan.outputs()[name] == "true" for name in ci_checks.QUICK_GROUPS)
    assert plan.all_browser and plan.distribution
    assert paths == ["README.md"]
    assert "base unavailable" in reason


@pytest.mark.parametrize("event,ref,payload", [
    ("push", "refs/tags/v1.4.1", {}), ("push", "refs/heads/feature", {}),
    ("workflow_dispatch", "refs/tags/v1.4.1", {}), ("schedule", "refs/heads/main", {}),
    ("pull_request", "refs/pull/7/merge", {"pull_request": {"base": {"ref": "release", "sha": "a" * 40}}}),
])
def test_quick_rejects_tags_other_branch_pushes_and_other_targets(event, ref, payload):
    with pytest.raises(ValueError, match="Quick accepts only"):
        ci_checks.plan_event(event, ref, "a" * 40, "b" * 40, payload=payload)


def _history(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-c", "user.email=ci@example.invalid", "-c", "user.name=CI",
                                        *args], cwd=tmp_path, text=True).strip()

    git("init", "-q", "-b", "main")
    (tmp_path / "app").mkdir()
    (tmp_path / "app/core.py").write_text("# core\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", base)
    git("checkout", "-qb", "task/docs")
    (tmp_path / "README.md").write_text("# docs\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "docs")
    return base, git("rev-parse", "HEAD")


def test_pull_request_compares_with_its_base(tmp_path):
    base, head = _history(tmp_path)
    payload = {"pull_request": {"base": {"ref": "main", "sha": base}}}
    plan, paths, reason = ci_checks.plan_event("pull_request", "refs/pull/3/merge", "", head, root=tmp_path, payload=payload)
    assert paths == ["README.md"] and reason == "pull request diff"
    assert plan.outputs()["python"] == "false" and plan.outputs()["inputs"] == "true"


def test_manual_branch_run_compares_with_main_and_can_run_everything(tmp_path):
    base, head = _history(tmp_path)
    plan, paths, reason = ci_checks.plan_event("workflow_dispatch", "refs/heads/task/docs", "", head, root=tmp_path, payload={})
    assert paths == ["README.md"] and reason == "branch diff from main"
    plan, paths, reason = ci_checks.plan_event("workflow_dispatch", "refs/heads/main", "", base, root=tmp_path, payload={})
    assert "base unavailable" in reason and plan.all_browser
    plan, _, reason = ci_checks.plan_event("workflow_dispatch", "refs/heads/task/docs", "", head, root=tmp_path,
                                           payload={}, complete=True)
    assert reason == "complete run requested"
    assert all(plan.outputs()[name] == "true" for name in ci_checks.QUICK_GROUPS)
    assert plan.outputs()["browser_shards"] == json.dumps(list(range(1, ci_checks.BROWSER_SHARDS + 1)))


def test_browser_shards_follow_selection_size():
    assert ci_checks.select_checks(["frontend/src/pages/AboutPage.tsx"]).shards() == [1]
    assert ci_checks.select_checks(["frontend/src/pages/CommandsPage.tsx"]).shards() == [1, 2]
    assert ci_checks.select_checks(["frontend/src/bridge.ts"]).shards() == list(range(1, ci_checks.BROWSER_SHARDS + 1))
    assert "--shard=2/3" in ci_checks.browser_command(None, "2/3")
    assert not any(item.startswith("--shard") for item in ci_checks.browser_command(None, "1/1"))
    with pytest.raises(ValueError, match="shard"):
        ci_checks.browser_command(None, "4/3")


def test_no_moving_ref_is_accepted_by_diff():
    with pytest.raises(ValueError, match="immutable"):
        ci_checks.changed_paths("a" * 40, "main")


def _merged_repo(tmp_path, *, branch_has_main=True, same_tree=True):
    def git(*args):
        return subprocess.check_output(["git", "-c", "user.email=ci@example.invalid", "-c", "user.name=CI",
                                        *args], cwd=tmp_path, text=True).strip()

    git("init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("switch", "-qc", "task")
    (tmp_path / "app.py").write_text("# feature\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "feature")
    git("switch", "-q", "main")
    if not branch_has_main:
        (tmp_path / "other.py").write_text("# other\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "other main change")
    before = git("rev-parse", "HEAD")
    git("merge", "-q", "--squash", "task")
    if not same_tree:
        (tmp_path / "extra.py").write_text("# merge-time edit\n", encoding="utf-8")
        git("add", ".")
    git("commit", "-qm", "squash")
    return base, before, git("rev-parse", "HEAD"), git("rev-parse", "task")


def _api(sha, head, *, conclusion="success", path=ci_checks.QUICK_WORKFLOW, merged=True):
    calls = []

    def api(resource):
        calls.append(resource)
        if resource.startswith("commits/"):
            return [{"number": 7, "merged_at": "2026-11-20T00:00:00Z" if merged else None,
                     "merge_commit_sha": sha, "base": {"ref": "main"}, "head": {"sha": head}}]
        assert f"head_sha={head}" in resource and "event=pull_request" in resource
        return {"workflow_runs": [{"path": path, "conclusion": conclusion, "html_url": "https://example.invalid/run/1"}]}
    return api, calls


def test_main_push_reuses_quick_of_identical_merged_pull_request(tmp_path):
    _, before, sha, head = _merged_repo(tmp_path)
    api, _ = _api(sha, head)
    reason = ci_checks.verified_merge(before, sha, root=tmp_path, api=api)
    assert reason.startswith(ci_checks.VERIFIED) and "#7" in reason and head in reason
    plan, paths, reported = ci_checks.plan_event(
        "push", "refs/heads/main", before, sha, root=tmp_path,
        verify=lambda b, s: ci_checks.verified_merge(b, s, root=tmp_path, api=api))
    assert paths == [] and reported == reason
    assert all(plan.outputs()[name] == "false" for name in ci_checks.QUICK_GROUPS)
    complete, _, _ = ci_checks.plan_event("push", "refs/heads/main", before, sha, root=tmp_path, complete=True,
                                          verify=lambda b, s: reason)
    assert all(complete.outputs()[name] == "true" for name in ci_checks.QUICK_GROUPS)


@pytest.mark.parametrize("case", ["main moved", "tree differs", "quick failed", "other workflow", "not merged", "api error"])
def test_main_push_runs_quick_without_exact_verified_evidence(tmp_path, case):
    _, before, sha, head = _merged_repo(tmp_path, branch_has_main=case != "main moved", same_tree=case != "tree differs")
    api, _ = _api(sha, head, conclusion="failure" if case == "quick failed" else "success",
                  path=".github/workflows/full-validation.yml" if case == "other workflow" else ci_checks.QUICK_WORKFLOW,
                  merged=case != "not merged")
    if case == "api error":
        def api(resource):
            raise ci_checks.URLError("offline")
    assert ci_checks.verified_merge(before, sha, root=tmp_path, api=api) == ""
    plan, paths, reason = ci_checks.plan_event(
        "push", "refs/heads/main", before, sha, root=tmp_path,
        verify=lambda b, s: ci_checks.verified_merge(b, s, root=tmp_path, api=api))
    assert paths and reason == "whole-push diff" and plan.outputs()["python"] == "true"


def test_only_main_pushes_look_for_a_verified_merge(tmp_path):
    base, _, _, head = _merged_repo(tmp_path)
    calls = []
    payload = {"pull_request": {"base": {"ref": "main", "sha": base}}}
    ci_checks.plan_event("pull_request", "refs/pull/7/merge", "", head, root=tmp_path, payload=payload,
                         verify=lambda b, s: calls.append(s) or "unexpected")
    ci_checks.plan_event("workflow_dispatch", "refs/heads/task", "", head, root=tmp_path, payload={},
                         verify=lambda b, s: calls.append(s) or "unexpected")
    assert calls == []
    assert ci_checks.verified_merge("0" * 40, head, root=tmp_path, api=lambda r: calls.append(r)) == ""
    assert calls == []


def test_plan_cli_outputs_and_summary(monkeypatch, tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": "a" * 40}), encoding="utf-8")
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    for key, value in {"GITHUB_EVENT_PATH": str(event), "GITHUB_OUTPUT": str(output),
                       "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_EVENT_NAME": "push",
                       "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": "b" * 40}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: b"docs/development.md\0")
    monkeypatch.setattr("sys.argv", ["ci_checks.py", "plan"])
    assert ci_checks.main() == 0
    assert dict(line.split("=", 1) for line in output.read_text().splitlines()) == {
        "python": "false", "frontend": "false", "inputs": "true", "browser_files": "[]", "browser_shards": "[1]",
        "server": "false", "distribution": "false", "orchestration": "false",
    }
    assert "python: skip (no applicable changes)" in summary.read_text()
    assert "metadata only" in summary.read_text()
    assert "docs/development.md" in summary.read_text()
    assert "b" * 40 in summary.read_text()


@pytest.mark.parametrize("job,result,success", [
    ("python", "success", True), ("python", "failure", False),
    ("python", "skipped", False), ("python", "cancelled", False),
    ("frontend", "skipped", True), ("frontend", "success", False),
    ("inputs", "skipped", False),
    ("plan", "failure", False), ("plan", "skipped", False),
])
def test_required_gate_distinguishes_deliberate_skips_and_failures(job, result, success):
    results = {"plan": {"result": "success"}, "python": {"result": "success"},
               "frontend": {"result": "skipped"}, "inputs": {"result": "success"}}
    results[job]["result"] = result
    assert ci_checks.check_results(results, {"python": True, "frontend": False, "inputs": True}) is success


@pytest.mark.parametrize("job,result", [("", "success"), ("python", "failure"), ("frontend", "cancelled"),
                                       ("containers", "skipped"), ("resolve", "missing")])
def test_full_gate_only_produces_evidence_after_all_required_jobs(tmp_path, monkeypatch, job, result):
    jobs = workflow("full-validation")["jobs"]["complete"]["needs"]
    results = {name: {"result": "success"} for name in jobs}
    if result == "missing":
        del results[job]
    elif job:
        results[job] = {"result": result}
    monkeypatch.setattr("sys.argv", ["ci_checks.py", "finish"])
    for key, value in {
        "CI_RESULTS": json.dumps(results), "SELECTED_SHA": "a" * 40, "GITHUB_SHA": "b" * 40,
        "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": "example/heetkit", "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2", "GITHUB_WORKFLOW_REF": "example/heetkit/.github/workflows/full-validation.yml@refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    target = tmp_path / "release-evidence.json"
    if ci_checks.main() == 0:
        release_evidence.record("full", target)
    if not job:
        evidence = json.loads(target.read_text())
        assert evidence["sha"] == "a" * 40 and evidence["workflow_sha"] == "b" * 40 and evidence["attempt"] == 2
    else:
        assert not target.exists()


def test_only_quick_runs_automatically_and_only_it_cancels():
    quick, full, candidate, containers = map(workflow, ("quick", "full-validation", "windows-build", "linux-container"))
    assert set(quick["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert quick["on"]["push"] == {"branches": ["main"]}
    assert quick["on"]["pull_request"]["branches"] == ["main"]
    assert "ready_for_review" in quick["on"]["pull_request"]["types"]
    assert quick["on"]["workflow_dispatch"]["inputs"]["complete"]["type"] == "boolean"
    assert quick["concurrency"]["group"] == "quick-${{ github.ref }}"
    assert set(full["on"]) == {"workflow_dispatch"}
    assert set(candidate["on"]) == {"workflow_dispatch"}
    assert set(workflow("publish-release")["on"]) == {"workflow_dispatch"}
    assert set(containers["on"]) == {"workflow_call"}
    assert quick["concurrency"]["cancel-in-progress"] == "true"
    for item in (full, candidate, containers, workflow("publish-release")):
        assert "concurrency" not in item
        assert all("concurrency" not in job for job in item["jobs"].values())


def test_quick_gate_and_workload_wiring():
    jobs = workflow("quick")["jobs"]
    assert jobs["complete"]["name"] == "Quick result"
    assert jobs["complete"]["if"] == "always() && needs.plan.result != 'skipped'"
    assert "pull_request.draft" in jobs["plan"]["if"]
    assert jobs["frontend"]["strategy"]["matrix"]["shard"] == "${{ fromJSON(needs.plan.outputs.browser_shards) }}"
    assert jobs["frontend"]["strategy"]["fail-fast"] == "false"
    assert set(jobs["complete"]["needs"]) == {"plan", *ci_checks.QUICK_GROUPS}
    for name in ci_checks.QUICK_GROUPS:
        assert jobs[name]["if"] == f"needs.plan.outputs.{name} == 'true'"
    assert jobs["plan"]["steps"][0]["with"]["fetch-depth"] == "0"
    assert jobs["plan"]["permissions"] == {"contents": "read", "actions": "read", "pull-requests": "read"}
    plan_step = next(step for step in jobs["plan"]["steps"] if step.get("id") == "plan")
    assert plan_step["env"]["GH_TOKEN"] == "${{ github.token }}"
    python = "\n".join(step.get("run", "") for step in jobs["python"]["steps"])
    assert "python -m pytest -q --junitxml" in python and "tests/" not in python
    frontend = "\n".join(step.get("run", "") for step in jobs["frontend"]["steps"])
    assert "npm run build" in frontend and "npm run typecheck" not in frontend
    assert "ci_checks.py browser" in frontend and "ci_checks.py frontend-output" in frontend
    steps = {step["id"]: step for step in jobs["frontend"]["steps"] if "id" in step}
    assert steps["browser_tests"]["env"]["BROWSER_FILES"] == "${{ needs.plan.outputs.browser_files }}"
    assert steps["browser_tests"]["env"]["BROWSER_SHARD"] == "${{ matrix.shard }}/${{ strategy.job-total }}"
    input_python = next(step for step in jobs["inputs"]["steps"] if step.get("uses", "").startswith("actions/setup-python@"))
    assert input_python["with"]["cache"] == "pip"
    assert input_python["with"]["cache-dependency-path"] == ".github/workflows/quick.yml"
    tests = next(step for step in jobs["inputs"]["steps"] if step.get("id") == "pytest")
    assert tests["if"] == "needs.plan.outputs.orchestration == 'true'"
    assert "tests/test_ci_workflows.py tests/test_release_publication.py tests/test_release_evidence.py" in tests["run"]
    source = (ROOT / ".github/workflows/quick.yml").read_text(encoding="utf-8")
    for forbidden in ("build_windows.py", "build_installer.py", "check_linux_container.py"):
        assert forbidden not in source


@pytest.mark.parametrize("name,worker", [
    ("full-validation", "python"), ("full-validation", "frontend"), ("windows-build", "windows-build"),
])
def test_manual_ref_resolved_once_and_consumers_pin_same_sha(name, worker):
    data = workflow(name)
    assert data["on"]["workflow_dispatch"]["inputs"]["ref"]["type"] == "string"
    jobs = data["jobs"]
    resolver = jobs["resolve"]
    assert resolver["steps"][0]["with"]["ref"] == "${{ inputs.ref || github.sha }}"
    assert "git rev-parse HEAD" in resolver["steps"][1]["run"]
    assert resolver["outputs"]["sha"] == "${{ steps.commit.outputs.sha }}"
    assert jobs[worker]["needs"] == "resolve"
    assert jobs[worker]["steps"][0]["with"]["ref"] == "${{ needs.resolve.outputs.sha }}"
    for job_name, job in jobs.items():
        for step in job.get("steps", []):
            if step.get("uses", "").startswith("actions/checkout@") and job_name != "resolve":
                assert "needs.resolve.outputs.sha" in step["with"]["ref"]
                assert step["with"]["persist-credentials"] == "false"


def test_full_covers_complete_suites_and_native_containers_without_packaging():
    data = workflow("full-validation")
    jobs = data["jobs"]
    assert jobs["python"]["needs"] == jobs["frontend"]["needs"] == jobs["containers"]["needs"] == "resolve"
    python = "\n".join(step.get("run", "") for step in jobs["python"]["steps"])
    frontend = "\n".join(step.get("run", "") for step in jobs["frontend"]["steps"])
    assert "python -m pytest -q --junitxml" in python and "tests/" not in python
    assert "npm run build" in frontend and "npm run typecheck" not in frontend
    assert "npm test -- '--reporter=line,junit' --workers=2 --trace=retain-on-failure" in frontend
    assert "playwright install msedge" in frontend
    assert "build_windows.py" not in python + frontend
    assert jobs["containers"]["uses"] == "./.github/workflows/linux-container.yml"
    assert jobs["containers"]["with"]["sha"] == "${{ needs.resolve.outputs.sha }}"
    assert jobs["complete"]["if"] == "always()"
    assert set(jobs["complete"]["needs"]) == {"resolve", "python", "frontend", "containers"}
    container = workflow("linux-container")["jobs"]["container"]
    assert container["strategy"]["matrix"]["include"] == [
        {"runner": "ubuntu-24.04", "platform": "linux/amd64"},
        {"runner": "ubuntu-24.04-arm", "platform": "linux/arm64"},
    ]
    assert container["steps"][0]["with"]["ref"] == "${{ inputs.sha }}"
    assert container["steps"][1]["run"] == "python3 scripts/check_linux_container.py"


def test_candidate_preserves_canonical_builds_without_publication():
    data = workflow("windows-build")
    jobs = data["jobs"]
    build = jobs["windows-build"]
    assert "if" not in build
    assert jobs["resolve"]["if"] == "github.ref == 'refs/heads/main'"
    commands = "\n".join(s.get("run", "") for s in build["steps"])
    for command in ("python scripts/build_windows.py", "scripts/build_installer.py --inno-compiler", "tests/test_profile_isolation.py", "tests/test_release_publication.py"):
        assert command in commands
    assert "publish-release" not in jobs
    assert data["permissions"] == {"contents": "read"}
    assert all(job.get("permissions", {}).get("contents", "read") == "read" for job in jobs.values())
    upload = next(s for s in build["steps"] if s.get("id") == "candidate")
    assert len(upload["with"]["path"].splitlines()) == 5
    assert build["steps"][-2]["with"]["name"] == "candidate-evidence-${{ github.run_attempt }}"
    assert "CANDIDATE_ARTIFACT_ID" in build["steps"][-3]["env"]


def test_publish_is_manual_and_only_publication_gets_write_permission():
    data = workflow("publish-release")
    assert set(data["on"]) == {"workflow_dispatch"}
    assert set(data["on"]["workflow_dispatch"]["inputs"]) == {
        "sha", "tag", "candidate_run_id", "full_run_id", "installer_manifest", "installer_signature",
    }
    assert all(i["required"] == "true" for i in data["on"]["workflow_dispatch"]["inputs"].values())
    job = data["jobs"]["publish-release"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["permissions"] == {"contents": "write", "actions": "read"}
    commands = "\n".join(s.get("run", "") for s in job["steps"])
    assert "python -m scripts.release_evidence verify" in commands
    assert "python -m scripts.release_evidence verify-update" in commands
    assert "gh @releaseArgs @assets" in commands
    for forbidden in ("build_windows.py", "build_installer.py", "npm", "gh workflow run"):
        assert forbidden not in commands
    checkout = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert [s["with"]["ref"] for s in checkout] == ["${{ github.sha }}"]
    assert all(s["with"]["persist-credentials"] == "false" for s in checkout)
    gate, publish = job["steps"][-2:]
    assert gate["env"]["RELEASE_SHA"] == "${{ inputs.sha }}"
    assert publish["env"]["INSTALLER_MANIFEST"] == "${{ inputs.installer_manifest }}"
    assert publish["env"]["INSTALLER_SIGNATURE"] == "${{ inputs.installer_signature }}"
    assert "if" not in publish  # Default success gate: failed verification cannot publish.


def test_full_records_evidence_only_after_required_gate_succeeds():
    steps = workflow("full-validation")["jobs"]["complete"]["steps"]
    assert steps[-3]["run"] == "python3 scripts/ci_checks.py finish"
    assert steps[-2]["run"] == "python3 scripts/release_evidence.py record-full"
    assert steps[-2]["env"]["SELECTED_SHA"] == "${{ needs.resolve.outputs.sha }}"
    assert steps[-1]["with"]["name"] == "full-evidence-${{ github.run_attempt }}"
    assert all("if" not in s for s in steps[-2:])


@pytest.mark.parametrize("workflow_name,job_name", [
    ("quick", "frontend"), ("full-validation", "frontend"), ("windows-build", "windows-build"),
])
def test_browser_diagnostics_are_uploaded_on_failure_with_bounded_paths(workflow_name, job_name):
    steps = workflow(workflow_name)["jobs"][job_name]["steps"]
    index = next(i for i, step in enumerate(steps) if step.get("id") == "browser_tests")
    test, upload = steps[index:index + 2]
    assert test["env"]["PLAYWRIGHT_JUNIT_OUTPUT_FILE"].endswith("/heetkit-browser-junit.xml")
    assert upload["if"] == "failure() && steps.browser_tests.outcome == 'failure'"
    assert upload["with"]["retention-days"] == "7"
    assert upload["with"]["path"].splitlines() == [
        "${{ runner.temp }}/heetkit-browser-junit.xml",
        "frontend/node_modules/.tmp/playwright-results/**/trace.zip",
        "frontend/node_modules/.tmp/playwright-results/**/test-failed-*.png",
    ]


def test_actual_machine_inputs_parse():
    ci_checks.check_inputs()


@pytest.mark.parametrize("asset", ["frontend/src/new/nested/module.ts", "frontend/public/new.png"])
def test_new_container_inputs_follow_context_rules(tmp_path, asset):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("COPY frontend/ ./\nCOPY --from=frontend /frontend/dist/ ./frontend/\n")
    tracked = {"Dockerfile", ".dockerignore", asset}
    path = tmp_path / asset
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic build input")
    ignore = tmp_path / ".dockerignore"
    ignore.write_text("**\n")
    with pytest.raises(ValueError, match=f"Docker context excludes required build input: {re.escape(asset)}"):
        check_container_inputs(tmp_path, tracked, set())
    allow = f"**\n!{asset}\n"
    ignore.write_text(allow + f"{asset}\n")
    with pytest.raises(ValueError, match="Docker context excludes"):
        check_container_inputs(tmp_path, tracked, set())
    ignore.write_text(allow)
    check_container_inputs(tmp_path, tracked, set())
    path.unlink()
    with pytest.raises(ValueError, match="Missing, untracked or linked"):
        check_container_inputs(tmp_path, tracked, set())


def test_broad_container_rules_cannot_admit_private_decoys(tmp_path):
    (tmp_path / "Dockerfile").write_text("COPY frontend/ ./\n")
    (tmp_path / ".dockerignore").write_text("**\n!frontend/**\n")
    with pytest.raises(ValueError, match="Docker context admits private or generated paths"):
        check_container_inputs(tmp_path, {"Dockerfile", ".dockerignore"}, set())


def test_container_required_runtime_resource_cannot_disappear(tmp_path):
    (tmp_path / "Dockerfile").write_text("COPY app/ ./app/\n")
    (tmp_path / ".dockerignore").write_text("**\n!app/resources/public.json\n")
    with pytest.raises(ValueError, match="app/resources/public.json"):
        check_container_inputs(tmp_path, {"Dockerfile", ".dockerignore"}, {"public.json"})


def test_windows_notice_hashes_are_verified_at_source(tmp_path):
    import hashlib

    files = {
        "packaging/windows/HeetKit.iss": b"synthetic installer configuration",
        "packaging/windows/HeetKit.spec": b"# synthetic spec",
        "packaging/windows/HeetKit.exe.config": b"<configuration/>",
        "packaging/windows/launcher.py": b"# synthetic launcher",
        "packaging/windows/PORTABLE.txt": b"synthetic portable instructions",
        "third_party_licenses/inno-setup/LICENSE.txt": b"synthetic installer notice",
        "THIRD_PARTY_NOTICES.md": b"synthetic redistribution notices",
    }
    notice = "third_party_licenses/inno-setup/LICENSE.txt"
    files["packaging/windows/redistribution.json"] = json.dumps({
        "schema": "heetkit.windows-redistribution.v1", "required_notices": {},
        "required_documents": ["_internal/THIRD_PARTY_NOTICES.md"],
        "notice_sources": [{"path": notice, "sha256": hashlib.sha256(files[notice]).hexdigest()}],
    }).encode()
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    check_windows_inputs(tmp_path, set(files))
    (tmp_path / notice).write_bytes(b"synthetic modified notice")
    with pytest.raises(ValueError, match="Redistribution notice hash mismatch"):
        check_windows_inputs(tmp_path, set(files))


@pytest.mark.parametrize("change,message", [
    ("missing-backend", "Linux requires a compatible pin for new-backend"),
    ("missing-desktop", "Windows requires a compatible pin for new-desktop"),
    ("divergent", "Shared Python pin differs for httpx"),
    ("stale-npm-lock", "Frontend manifest and lockfile disagree"),
])
def test_platform_requirements_and_npm_lock_must_match_declarations(tmp_path, change, message):
    files = ("packaging/windows/requirements.txt", "packaging/linux/requirements.txt",
             "packaging/python-bootstrap.txt", "frontend/package.json", "frontend/package-lock.json")
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if change == "missing-backend":
        project["dependencies"].append("new-backend>=1")
    elif change == "missing-desktop":
        project["optional-dependencies"]["desktop"].append("new-desktop>=1")
    elif change == "divergent":
        path = tmp_path / files[0]
        path.write_text(path.read_text().replace("httpx==0.28.1", "httpx==0.28.0"))
    else:
        path = tmp_path / files[3]
        manifest = json.loads(path.read_text())
        manifest["dependencies"]["synthetic"] = "1.0.0"
        path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=message):
        check_dependencies(tmp_path, set(files), project)


def test_linux_lock_requires_hashes(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("example==1.0\n")
    with pytest.raises(ValueError, match="with SHA-256 hashes"):
        read_pins(path, hashes_required=True)


@pytest.mark.parametrize("content", ["- invalid mapping", "name: missing triggers"])
def test_invalid_workflow_input_fails(tmp_path, content):
    path = tmp_path / ".github/workflows/quick.yml"
    path.parent.mkdir(parents=True)
    path.write_text(content)
    with pytest.raises(ValueError):
        ci_checks.check_inputs(tmp_path)


@pytest.mark.parametrize("notes", [None, "", "# Wrong version\n" + "Synthetic notes. " * 20])
def test_missing_empty_or_mismatched_release_input_fails(tmp_path, notes):
    from app.version import VERSION

    if notes is not None:
        path = tmp_path / f"docs/releases/v{VERSION}.md"
        path.parent.mkdir(parents=True)
        path.write_text(notes, encoding="utf-8")
    with pytest.raises(ValueError, match="release notes"):
        ci_checks.check_inputs(tmp_path)


def test_browser_cli_forwards_test_failure(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", ["ci_checks.py", "browser"])
    monkeypatch.setenv("BROWSER_FILES", json.dumps(["tests/filters.spec.ts"]))
    monkeypatch.setattr(subprocess, "call", lambda args, **kwargs: calls.append((args, kwargs)) or 7)
    assert ci_checks.main() == 7
    assert calls == [(ci_checks.browser_command(["tests/filters.spec.ts"]), {"cwd": ROOT / "frontend"})]


def test_finish_cli_fails_when_selection_failed(monkeypatch):
    monkeypatch.setattr("sys.argv", ["ci_checks.py", "finish"])
    monkeypatch.setenv("CI_RESULTS", json.dumps({
        "plan": {"result": "failure", "outputs": {}},
        "python": {"result": "skipped"}, "frontend": {"result": "skipped"},
        "inputs": {"result": "skipped"},
    }))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert ci_checks.main() == 1


def test_docs_only_quick_finishes_successfully(monkeypatch):
    outputs = ci_checks.select_checks(["docs/development.md"]).outputs()
    monkeypatch.setattr("sys.argv", ["ci_checks.py", "finish"])
    monkeypatch.setenv("CI_RESULTS", json.dumps({
        "plan": {"result": "success", "outputs": outputs},
        "python": {"result": "skipped"}, "frontend": {"result": "skipped"}, "inputs": {"result": "success"},
    }))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert ci_checks.main() == 0


def test_observed_durations_use_this_attempt_and_no_estimates(monkeypatch, capsys):
    from io import BytesIO

    for key, value in {"GH_TOKEN": "synthetic-token", "GITHUB_REPOSITORY": "test/repo",
                       "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "2"}.items():
        monkeypatch.setenv(key, value)

    def request(req, **kwargs):
        assert req.full_url.endswith("/repos/test/repo/actions/runs/42/attempts/2/jobs?per_page=100")
        assert kwargs["timeout"] == 15
        return BytesIO(json.dumps({"jobs": [{"name": "Synthetic job", "started_at": "2026-10-22T10:00:00Z",
            "completed_at": "2026-10-22T10:00:12Z", "steps": [{"name": "Test: synthetic step", "conclusion": "failure", "number": 5,
            "started_at": "2026-10-22T10:00:02Z", "completed_at": "2026-10-22T10:00:05Z"}]}]}).encode())

    monkeypatch.setattr(ci_checks, "urlopen", request)
    ci_checks.report_actions()
    output = capsys.readouterr().out
    assert "12.0s" in output and "3.0s" in output
    assert "Synthetic job / Test: synthetic step" in output
    assert "#step:5:1" in output and "actions/runs/42#artifacts" in output
    assert "synthetic-token" not in output


def test_unavailable_timings_do_not_mask_check_results(monkeypatch, capsys):
    from urllib.error import URLError

    for key in ("GH_TOKEN", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        monkeypatch.setenv(key, "synthetic")

    def unavailable(*args, **kwargs):
        raise URLError("synthetic unavailable metadata")

    monkeypatch.setattr(ci_checks, "urlopen", unavailable)
    monkeypatch.setattr("sys.argv", ["ci_checks.py", "finish"])
    monkeypatch.setenv("CI_RESULTS", json.dumps({"validation": {"result": "failure"}}))
    assert ci_checks.main() == 1
    assert "metadata unavailable" in capsys.readouterr().out
