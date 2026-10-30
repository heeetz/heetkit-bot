"""Synthetic Quick decisions and actual workflow wiring, without Actions/builds."""

import json
from pathlib import Path
import subprocess

import pytest
import yaml

from scripts import ci_checks


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_actions_summary(monkeypatch):
    # Synthetic gate/timing output must never enter a real runner's job summary.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def workflow(name):
    # BaseLoader preserves the Actions 'on' key rather than YAML 1.1's boolean.
    return yaml.load((ROOT / f".github/workflows/{name}.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("paths,expected", [
    (["README.md", "docs/development.md"], (False, False, False)),
    (["app/commands/fun.py"], (True, False, False)),
    (["tests/test_commands.py"], (True, False, False)),
    (["frontend/src/bridge.ts"], (False, True, False)),
    (["frontend/package-lock.json"], (False, True, False)),
    (["app/management_api.py"], (True, True, False)),
    (["app/management.py", "app/webview_host.py"], (True, True, False)),
    (["pyproject.toml"], (True, True, True)),
    (["packaging/windows/requirements.txt"], (True, True, True)),
    (["packaging/linux/requirements.txt"], (True, True, True)),
    (["packaging/python-bootstrap.txt"], (True, True, True)),
    ([".github/workflows/quick.yml"], (False, True, True)),
    (["scripts/ci_checks.py"], (True, True, True)),
    ([".github/ISSUE_TEMPLATE/bug.yml"], (False, False, True)),
    (["docs/releases/v1.4.1.md"], (False, False, True)),
    (["app/version.py"], (True, False, True)),
    (["Dockerfile"], (True, False, False)),
    ([".dockerignore"], (True, False, True)),
    (["frontend/src/pages/analytics.css"], (False, True, True)),
    (["scripts/build_windows.py"], (True, False, True)),
    (["frontend/tests/browser-server.spec.ts", "app/config/settings.py"], (True, True, False)),
])
def test_coarse_path_selection(paths, expected):
    assert tuple(ci_checks.select_checks(paths).values()) == expected


def test_whole_push_diff_includes_deleted_and_renamed_paths(monkeypatch):
    calls = []

    def git(args, **kwargs):
        calls.append(args)
        return b"app/deleted.py\0frontend/src/new.ts\0frontend/src/old.ts\0"

    monkeypatch.setattr(subprocess, "check_output", git)
    selected, reason = ci_checks.plan_event("push", "refs/heads/main", "a" * 40, "b" * 40)
    assert selected == {"smoke": True, "typecheck": True, "inputs": False}
    assert reason == "whole-push diff"
    assert calls == [["git", "diff", "--no-renames", "--name-only", "-z", "a" * 40, "b" * 40, "--"]]


@pytest.mark.parametrize("before,fail_diff", [("0" * 40, False), ("a" * 40, True)])
def test_new_branch_or_missing_base_selects_all_tracked_paths(monkeypatch, before, fail_diff):
    def git(args, **kwargs):
        if args[1] == "diff" and fail_diff:
            raise subprocess.CalledProcessError(128, args)
        assert args == ["git", "ls-tree", "-r", "--name-only", "-z", "b" * 40]
        return b"app/main.py\0frontend/package.json\0.github/workflows/quick.yml\0"

    monkeypatch.setattr(subprocess, "check_output", git)
    selected, reason = ci_checks.plan_event("push", "refs/heads/main", before, "b" * 40)
    assert all(selected.values())
    assert "base unavailable" in reason


@pytest.mark.parametrize("event,ref", [("workflow_dispatch", "refs/heads/main"), ("push", "refs/tags/v1.4.1"), ("push", "refs/heads/feature")])
def test_quick_rejects_manual_tags_and_other_branches(event, ref):
    with pytest.raises(ValueError, match="only main pushes"):
        ci_checks.plan_event(event, ref, "a" * 40, "b" * 40)


def test_no_moving_ref_is_accepted_by_diff():
    with pytest.raises(ValueError, match="immutable"):
        ci_checks.changed_paths("a" * 40, "main")


def test_plan_cli_outputs_and_summary(monkeypatch, tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": "a" * 40}), encoding="utf-8")
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    for key, value in {"GITHUB_EVENT_PATH": str(event), "GITHUB_OUTPUT": str(output),
                       "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_EVENT_NAME": "push",
                       "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": "b" * 40}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: b"docs/development.md\0")
    monkeypatch.setattr("sys.argv", ["ci_checks.py", "plan"])
    assert ci_checks.main() == 0
    assert output.read_text() == "smoke=false\ntypecheck=false\ninputs=false\n"
    assert "skip (no matching paths)" in summary.read_text()
    assert "b" * 40 in summary.read_text()


@pytest.mark.parametrize("job,result,success", [
    ("smoke", "success", True), ("smoke", "failure", False),
    ("smoke", "skipped", False), ("smoke", "cancelled", False),
    ("typecheck", "skipped", True), ("typecheck", "success", False),
    ("plan", "failure", False), ("plan", "skipped", False),
])
def test_required_gate_distinguishes_deliberate_skips_and_failures(job, result, success):
    results = {"plan": {"result": "success"}, "smoke": {"result": "success"},
               "typecheck": {"result": "skipped"}, "inputs": {"result": "skipped"}}
    results[job]["result"] = result
    assert ci_checks.check_results(results, {"smoke": True, "typecheck": False, "inputs": False}) is success


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_full_gate_requires_every_job_success(result):
    assert not ci_checks.check_results({"resolve": {"result": "success"}, "containers": {"result": result}})


def test_only_quick_runs_on_main_pushes_and_only_it_cancels():
    quick, full, candidate, containers = map(workflow, ("quick", "full-validation", "windows-build", "linux-container"))
    assert quick["on"] == {"push": {"branches": ["main"]}}
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
    assert jobs["complete"]["if"] == "always()"
    assert set(jobs["complete"]["needs"]) == {"plan", "smoke", "typecheck", "inputs"}
    for name in ("smoke", "typecheck", "inputs"):
        assert jobs[name]["if"] == f"needs.plan.outputs.{name} == 'true'"
    assert jobs["plan"]["steps"][0]["with"]["fetch-depth"] == "0"
    source = (ROOT / ".github/workflows/quick.yml").read_text()
    for forbidden in ("npm run build", "npm test", "playwright install", "build_windows.py", "build_installer.py", "check_linux_container.py"):
        assert forbidden not in source
    assert "python scripts/ci_checks.py smoke" in source
    assert "npm run typecheck" in source
    assert "tests/test_ci_workflows.py tests/test_release_publication.py tests/test_release_evidence.py" in source
    assert all((ROOT / path.split("::")[0]).is_file() for path in ci_checks.SMOKE_TESTS)


@pytest.mark.parametrize("name,worker", [("full-validation", "validation"), ("windows-build", "windows-build")])
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
    commands = "\n".join(s.get("run", "") for s in jobs["validation"]["steps"])
    for command in ("python -m pytest -q", "npm run build", "npm test -- --reporter=line --workers=2", "playwright install msedge"):
        assert command in commands
    assert "build_windows.py" not in commands
    assert jobs["containers"]["uses"] == "./.github/workflows/linux-container.yml"
    assert jobs["containers"]["with"]["sha"] == "${{ needs.resolve.outputs.sha }}"
    assert jobs["complete"]["if"] == "always()"
    assert set(jobs["complete"]["needs"]) == {"resolve", "validation", "containers"}
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
    assert build["steps"][-1]["with"]["name"] == "candidate-evidence-${{ github.run_attempt }}"
    assert "CANDIDATE_ARTIFACT_ID" in build["steps"][-2]["env"]


def test_publish_is_manual_and_only_publication_gets_write_permission():
    data = workflow("publish-release")
    assert set(data["on"]) == {"workflow_dispatch"}
    assert set(data["on"]["workflow_dispatch"]["inputs"]) == {"sha", "tag", "candidate_run_id", "full_run_id"}
    assert all(i["required"] == "true" for i in data["on"]["workflow_dispatch"]["inputs"].values())
    job = data["jobs"]["publish-release"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["permissions"] == {"contents": "write", "actions": "read"}
    commands = "\n".join(s.get("run", "") for s in job["steps"])
    assert "python scripts/release_evidence.py verify" in commands
    assert "gh @releaseArgs @assets" in commands
    for forbidden in ("build_windows.py", "build_installer.py", "npm", "pip install", "gh workflow run"):
        assert forbidden not in commands
    checkout = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert [s["with"]["ref"] for s in checkout] == ["${{ github.sha }}", "${{ inputs.sha }}"]
    assert all(s["with"]["persist-credentials"] == "false" for s in checkout)
    gate, publish = job["steps"][-2:]
    assert gate["env"]["RELEASE_SHA"] == "${{ inputs.sha }}"
    assert publish["working-directory"] == "release-source"
    assert "if" not in publish  # Default success gate: failed verification cannot publish.


def test_full_records_evidence_only_after_required_gate_succeeds():
    steps = workflow("full-validation")["jobs"]["complete"]["steps"]
    assert steps[-3]["run"] == "python3 scripts/ci_checks.py finish"
    assert steps[-2]["run"] == "python3 scripts/release_evidence.py record-full"
    assert steps[-2]["env"]["SELECTED_SHA"] == "${{ needs.resolve.outputs.sha }}"
    assert steps[-1]["with"]["name"] == "full-evidence-${{ github.run_attempt }}"
    assert all("if" not in s for s in steps[-2:])


def test_actual_machine_inputs_parse():
    ci_checks.check_inputs()


def test_missing_container_page_stylesheet_allowlist_fails_before_build(tmp_path):
    asset = tmp_path / "frontend/src/pages/analytics.css"
    asset.parent.mkdir(parents=True)
    asset.write_text("/* synthetic stylesheet */")
    rules = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    (tmp_path / ".dockerignore").write_text(rules.replace("!frontend/src/pages/analytics.css\n", ""))
    with pytest.raises(ValueError, match="Missing required container stylesheet input"):
        ci_checks.check_container_stylesheet_input(tmp_path)
    (tmp_path / ".dockerignore").write_text(rules)
    ci_checks.check_container_stylesheet_input(tmp_path)
    asset.unlink()
    with pytest.raises(ValueError, match="Missing required container stylesheet input"):
        ci_checks.check_container_stylesheet_input(tmp_path)


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


def test_smoke_cli_forwards_test_failure(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", ["ci_checks.py", "smoke"])
    monkeypatch.setattr(subprocess, "call", lambda args, **kwargs: calls.append(args) or 7)
    assert ci_checks.main() == 7
    assert calls[0][1:] == ["-m", "pytest", "-q", *ci_checks.SMOKE_TESTS]


def test_finish_cli_fails_when_selection_failed(monkeypatch):
    monkeypatch.setattr("sys.argv", ["ci_checks.py", "finish"])
    monkeypatch.setenv("CI_RESULTS", json.dumps({
        "plan": {"result": "failure", "outputs": {}},
        "smoke": {"result": "skipped"}, "typecheck": {"result": "skipped"},
        "inputs": {"result": "skipped"},
    }))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert ci_checks.main() == 1


def test_observed_durations_use_this_attempt_and_no_estimates(monkeypatch, capsys):
    from io import BytesIO

    for key, value in {"GH_TOKEN": "synthetic-token", "GITHUB_REPOSITORY": "test/repo",
                       "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "2"}.items():
        monkeypatch.setenv(key, value)

    def request(req, **kwargs):
        assert req.full_url.endswith("/repos/test/repo/actions/runs/42/attempts/2/jobs?per_page=100")
        assert kwargs["timeout"] == 15
        return BytesIO(json.dumps({"jobs": [{"name": "Synthetic job", "started_at": "2026-10-22T10:00:00Z",
            "completed_at": "2026-10-22T10:00:12Z", "steps": [{"name": "Synthetic step",
            "started_at": "2026-10-22T10:00:02Z", "completed_at": "2026-10-22T10:00:05Z"}]}]}).encode())

    monkeypatch.setattr(ci_checks, "urlopen", request)
    ci_checks.report_durations()
    output = capsys.readouterr().out
    assert "12.0s" in output and "3.0s" in output
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
