"""Mock Actions responses and immutable artifact downloads; never contact GitHub."""

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from scripts import release_evidence as release


SHA = "a" * 40
CONTROLLER = "b" * 40  # Dispatch commit can differ from the selected source commit.
REPO = "test/repo"
VERSION = "1.4.1"
BASE = f"HeetKit-{VERSION}-windows-x64"


@pytest.fixture(autouse=True)
def isolate_actions_summary(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def archive(files):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        for name, data in files:
            bundle.writestr(name, data)
    return stream.getvalue()


class Actions:
    def __init__(self):
        self.runs = {}
        self.items = {}
        self.payloads = {}
        self.evidence = {}
        self.calls = []
        self.tag_sha = SHA
        self.mutate_on_recheck = False
        for kind, run_id in (("candidate", 10), ("full", 20)):
            self.runs[run_id] = {
                "id": run_id, "repository": {"full_name": REPO}, "head_repository": {"full_name": REPO},
                "head_branch": "main", "head_sha": CONTROLLER, "run_attempt": 2,
                "path": f".github/workflows/{release.WORKFLOWS[kind]}", "event": "workflow_dispatch",
                "status": "completed", "conclusion": "success",
            }
            self.items[run_id] = []
            self.evidence[kind] = {
                "schema": 1, "kind": kind, "sha": SHA, "repository": REPO, "run_id": run_id,
                "attempt": 2, "workflow_sha": CONTROLLER,
                "workflow_ref": f"{REPO}/.github/workflows/{release.WORKFLOWS[kind]}@refs/heads/main",
            }
        payload = archive([(BASE + suffix, f"original bytes {suffix}") for suffix in release.SUFFIXES])
        artifact = self.add(10, 100, BASE, payload)
        self.evidence["candidate"].update(version=VERSION, artifact_id=100, artifact_digest=artifact["digest"])
        for kind, run_id in (("candidate", 10), ("full", 20)):
            self.add(run_id, run_id + 1, f"{kind}-evidence-2", b"")
            self.refresh(kind)

    def add(self, run_id, artifact_id, name, payload):
        item = {"id": artifact_id, "name": name, "expired": False, "expires_at": "2099-01-01T00:00:00Z",
                "workflow_run": {"id": run_id, "head_sha": CONTROLLER}}
        self.items[run_id].append(item)
        self.set_payload(item, payload)
        return item

    def set_payload(self, item, payload):
        self.payloads[item["id"]] = payload
        item["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()

    def refresh(self, kind):
        run_id = 10 if kind == "candidate" else 20
        self.set_payload(self.items[run_id][-1], archive([("release-evidence.json", json.dumps(self.evidence[kind]))]))

    def get(self, path):
        self.calls.append(path)
        if path.startswith("commits/"):
            assert path == f"commits/refs%2Ftags%2Fv{VERSION}"
            return {"sha": self.tag_sha}
        run_id = int(path.rsplit("/", 1)[1])
        data = deepcopy(self.runs[run_id])
        if self.mutate_on_recheck and self.calls.count(path) > 1:
            data["run_attempt"] += 1
        return data

    def artifacts(self, run_id):
        return self.items[run_id]

    def download(self, item, target):
        target.write_bytes(self.payloads[item["id"]])


def verify(tmp_path, api, **overrides):
    options = dict(repository=REPO, sha=SHA, tag=f"v{VERSION}", version=VERSION,
                   candidate_run="10", full_run="20", destination=tmp_path / "outputs", api=api)
    options.update(overrides)
    return release.verify(**options)


def test_exact_selected_sha_and_original_candidate_bytes_are_reused(tmp_path):
    api = Actions()
    verify(tmp_path, api)
    assert {p.name: p.read_bytes() for p in (tmp_path / "outputs").iterdir()} == {
        BASE + suffix: f"original bytes {suffix}".encode() for suffix in release.SUFFIXES
    }
    assert api.calls.count("actions/runs/10") == api.calls.count("actions/runs/20") == 2


@pytest.mark.parametrize("kind", ["candidate", "full"])
@pytest.mark.parametrize("field,value", [
    ("sha", "c" * 40), ("repository", "other/repo"), ("attempt", 1), ("run_id", 99),
    ("workflow_sha", "c" * 40), ("workflow_ref", "test/repo/.github/workflows/other.yml@refs/heads/main"),
    ("schema", 2), ("kind", "other"),
])
def test_mismatched_evidence_is_rejected(tmp_path, kind, field, value):
    api = Actions()
    api.evidence[kind][field] = value
    api.refresh(kind)
    with pytest.raises(ValueError, match="evidence SHA/ref/attempt"):
        verify(tmp_path, api)
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("run_id", [10, 20])
@pytest.mark.parametrize("field,value", [
    ("status", "in_progress"), ("conclusion", "failure"), ("conclusion", "cancelled"),
    ("conclusion", "skipped"), ("repository", {"full_name": "other/repo"}),
    ("head_repository", {"full_name": "fork/repo"}), ("event", "push"),
    ("path", ".github/workflows/quick.yml"), ("head_branch", "feature"),
])
def test_failed_or_wrong_workflow_cannot_supply_evidence(tmp_path, run_id, field, value):
    api = Actions()
    api.runs[run_id][field] = value
    with pytest.raises(ValueError):
        verify(tmp_path, api)
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("problem", ["missing", "expired", "elapsed", "ambiguous", "digest", "run", "ref"])
@pytest.mark.parametrize("kind", ["full", "candidate", "payload"])
def test_unusable_artifact_fails_closed(tmp_path, kind, problem):
    api = Actions()
    run_id = 20 if kind == "full" else 10
    item = api.items[run_id][0 if kind == "payload" else -1]
    if problem == "missing":
        api.items[run_id].remove(item)
    elif problem == "ambiguous":
        api.items[run_id].append(deepcopy(item))
    elif problem == "elapsed":
        item["expires_at"] = "2000-01-01T00:00:00Z"
    elif problem == "digest":
        item["digest"] = None
    elif problem == "run":
        item["workflow_run"]["id"] = 99
    elif problem == "ref":
        item["workflow_run"]["head_sha"] = "c" * 40
    else:
        item["expired"] = True
    with pytest.raises((ValueError, TypeError)):
        verify(tmp_path, api)


@pytest.mark.parametrize("field,value", [("version", "1.4.0"), ("artifact_id", 99), ("artifact_digest", "sha256:" + "0" * 64)])
def test_candidate_version_and_artifact_identity_are_pinned(tmp_path, field, value):
    api = Actions()
    api.evidence["candidate"][field] = value
    api.refresh("candidate")
    with pytest.raises(ValueError):
        verify(tmp_path, api)


@pytest.mark.parametrize("options", [{"sha": "main"}, {"sha": "c" * 40}, {"tag": "v1.4.0"},
                                       {"candidate_run": "latest"}, {"full_run": "0"}, {"repository": "../other"}])
def test_explicit_inputs_and_tag_must_match(tmp_path, options):
    with pytest.raises(ValueError):
        verify(tmp_path, Actions(), **options)


@pytest.mark.parametrize("names", [["../private.json"], [BASE + s for s in release.SUFFIXES[:-1]],
                                   [BASE + s for s in release.SUFFIXES] + ["profile.json"]])
def test_only_five_flat_outputs_can_be_extracted(tmp_path, names):
    api = Actions()
    item = api.items[10][0]
    api.set_payload(item, archive([(name, "synthetic") for name in names]))
    api.evidence["candidate"]["artifact_digest"] = item["digest"]
    api.refresh("candidate")
    with pytest.raises(ValueError, match="Unexpected candidate files"):
        verify(tmp_path, api)
    assert not (tmp_path / "outputs").exists()


def test_rerunning_a_verified_run_invalidates_readiness(tmp_path):
    api = Actions()
    api.mutate_on_recheck = True
    with pytest.raises(ValueError, match="Run changed"):
        verify(tmp_path, api)


def test_actual_download_checks_archive_digest(monkeypatch, tmp_path):
    payload = b"synthetic archive bytes"

    def run(args, stdout, check):
        assert args == ["gh", "api", "repos/test/repo/actions/artifacts/123/zip"] and check
        stdout.write(payload)

    monkeypatch.setattr(subprocess, "run", run)
    api = release.GitHub(REPO)
    item = {"id": 123, "digest": "sha256:" + hashlib.sha256(payload).hexdigest()}
    api.download(item, tmp_path / "good.zip")
    item["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        api.download(item, tmp_path / "bad.zip")


def test_artifact_listing_paginates_and_missing_pages_fail(monkeypatch):
    api = release.GitHub(REPO)
    calls = []

    def get(path):
        calls.append(path)
        return {"total_count": 2, "artifacts": [{"id": len(calls)}]}

    monkeypatch.setattr(api, "get", get)
    assert api.artifacts(10) == [{"id": 1}, {"id": 2}]
    assert calls[-1].endswith("page=2")
    monkeypatch.setattr(api, "get", lambda _: {"total_count": 1, "artifacts": []})
    with pytest.raises(ValueError, match="Incomplete"):
        api.artifacts(10)


@pytest.mark.parametrize("kind", ["full", "candidate"])
def test_record_uses_resolved_sha_and_current_run_attempt(monkeypatch, tmp_path, kind):
    env = {"SELECTED_SHA": SHA, "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": REPO,
           "GITHUB_RUN_ID": "10", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_SHA": CONTROLLER,
           "GITHUB_WORKFLOW_REF": f"{REPO}/.github/workflows/{release.WORKFLOWS[kind]}@refs/heads/main",
           "APP_VERSION": VERSION, "CANDIDATE_ARTIFACT_ID": "100", "CANDIDATE_ARTIFACT_DIGEST": "0" * 64}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    target = tmp_path / "evidence.json"
    release.record(kind, target)
    data = json.loads(target.read_text())
    assert data["sha"] == SHA and data["workflow_sha"] == CONTROLLER and data["attempt"] == 2
    assert ("artifact_id" in data) is (kind == "candidate")
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v1.4.1")
    with pytest.raises(ValueError, match="from main"):
        release.record(kind, target)
