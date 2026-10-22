"""Record immutable CI evidence and verify an explicitly selected release candidate.

GitHub access uses the runner's gh CLI/token. No build or release creation here.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import quote
import zipfile


SUFFIXES = (".zip", ".zip.sha256", "-setup.exe", "-setup.exe.sha256", "-setup.exe.build.json")
WORKFLOWS = {"full": "full-validation.yml", "candidate": "windows-build.yml"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def record(kind: str, target: Path) -> None:
    sha = os.environ["SELECTED_SHA"]
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "Expected exact selected SHA")
    require(os.environ["GITHUB_REF"] == "refs/heads/main", "Dispatch workflow from main")
    evidence = {
        "schema": 1, "kind": kind, "sha": sha,
        "repository": os.environ["GITHUB_REPOSITORY"],
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "workflow_sha": os.environ["GITHUB_SHA"],
        "workflow_ref": os.environ["GITHUB_WORKFLOW_REF"],
    }
    if kind == "candidate":
        evidence.update(version=os.environ["APP_VERSION"],
                        artifact_id=int(os.environ["CANDIDATE_ARTIFACT_ID"]),
                        artifact_digest="sha256:" + os.environ["CANDIDATE_ARTIFACT_DIGEST"])
    target.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    message = f"{kind}: selected SHA {sha}, run {evidence['run_id']}, attempt {evidence['attempt']}"
    if kind == "candidate":
        message += f", artifact {evidence['artifact_id']} ({evidence['artifact_digest']})"
    print(message)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(message + "\n")


class GitHub:
    def __init__(self, repository: str):
        self.prefix = f"repos/{repository}/"

    def get(self, path: str) -> dict:
        return json.loads(subprocess.check_output(["gh", "api", self.prefix + path]))

    def artifacts(self, run_id: int) -> list[dict]:
        result = []
        page = 1
        while True:
            data = self.get(f"actions/runs/{run_id}/artifacts?per_page=100&page={page}")
            result.extend(data["artifacts"])
            if len(result) >= data["total_count"]:
                return result
            require(bool(data["artifacts"]), "Incomplete artifact listing")
            page += 1

    def download(self, artifact: dict, target: Path) -> None:
        with target.open("xb") as stream:
            subprocess.run(["gh", "api", self.prefix + f"actions/artifacts/{artifact['id']}/zip"],
                           stdout=stream, check=True)
        with target.open("rb") as stream:
            digest = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
        require(digest == artifact["digest"], "Downloaded artifact digest mismatch")


def artifact_named(artifacts: list[dict], name: str, run_id: int, workflow_sha: str) -> dict:
    matches = [item for item in artifacts if item["name"] == name]
    require(len(matches) == 1, f"Missing or ambiguous artifact: {name}")
    artifact = matches[0]
    require(artifact.get("expired") is False and
            datetime.fromisoformat(artifact["expires_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc),
            "Expired artifact")
    require(artifact["workflow_run"]["id"] == run_id and
            artifact["workflow_run"]["head_sha"] == workflow_sha, "Artifact run/ref mismatch")
    require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("digest", ""))), "Missing artifact digest")
    return artifact


def verified_run(api: GitHub, kind: str, run_id: int, repository: str, sha: str, work: Path) -> tuple[dict, list[dict], dict]:
    run = api.get(f"actions/runs/{run_id}")
    require(run["id"] == run_id and run["repository"]["full_name"] == repository and
            run["head_repository"]["full_name"] == repository, "Run repository mismatch")
    require(run["path"] == f".github/workflows/{WORKFLOWS[kind]}" and
            run["event"] == "workflow_dispatch" and run["head_branch"] == "main", "Run workflow/ref mismatch")
    require(run["status"] == "completed" and run["conclusion"] == "success", "Run must complete successfully")
    artifacts = api.artifacts(run_id)
    artifact = artifact_named(artifacts, f"{kind}-evidence-{run['run_attempt']}", run_id, run["head_sha"])
    archive = work / f"{kind}-evidence.zip"
    api.download(artifact, archive)
    with zipfile.ZipFile(archive) as bundle:
        require(bundle.namelist() == ["release-evidence.json"], "Unexpected evidence files")
        require(bundle.getinfo("release-evidence.json").file_size <= 16384, "Oversized evidence")
        evidence = json.loads(bundle.read("release-evidence.json"))
    expected = {
        "schema": 1, "kind": kind, "sha": sha, "repository": repository,
        "run_id": run_id, "attempt": run["run_attempt"], "workflow_sha": run["head_sha"],
        "workflow_ref": f"{repository}/.github/workflows/{WORKFLOWS[kind]}@refs/heads/main",
    }
    require(all(evidence.get(key) == value for key, value in expected.items()), "Run evidence SHA/ref/attempt mismatch")
    return evidence, artifacts, run


def verify(*, repository: str, sha: str, tag: str, version: str, candidate_run: str,
           full_run: str, destination: Path, api: GitHub | None = None) -> None:
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "Expected exact immutable release SHA")
    require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)), "Invalid repository")
    require(tag == "v" + version, "Release tag/version mismatch")
    require(all(re.fullmatch(r"[1-9][0-9]*", value) for value in (candidate_run, full_run)), "Expected explicit run IDs")
    api = api or GitHub(repository)
    # Resolve annotated and lightweight tags through the commits endpoint.
    require(api.get(f"commits/{quote('refs/tags/' + tag, safe='')}")["sha"] == sha, "Release tag/SHA mismatch")
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        full, _, _ = verified_run(api, "full", int(full_run), repository, sha, work)
        candidate, artifacts, run = verified_run(api, "candidate", int(candidate_run), repository, sha, work)
        require(candidate.get("version") == version, "Candidate version mismatch")
        base = f"HeetKit-{version}-windows-x64"
        artifact = artifact_named(artifacts, base, int(candidate_run), run["head_sha"])
        require(artifact["id"] == candidate.get("artifact_id") and
                artifact["digest"] == candidate.get("artifact_digest"), "Candidate artifact identity mismatch")
        archive = work / "candidate.zip"
        api.download(artifact, archive)
        with zipfile.ZipFile(archive) as bundle:
            expected = {base + suffix for suffix in SUFFIXES}
            require(len(bundle.infolist()) == 5 and set(bundle.namelist()) == expected, "Unexpected candidate files")
            # Fixed flat filenames only; never extract archive-controlled paths or links.
            destination.mkdir(parents=True, exist_ok=False)
            for name in sorted(expected):
                with bundle.open(name) as source, (destination / name).open("xb") as target:
                    shutil.copyfileobj(source, target)
        # Recheck current status/attempt and tag after downloading; reruns invalidate old evidence.
        for evidence, run_id in ((full, int(full_run)), (candidate, int(candidate_run))):
            current = api.get(f"actions/runs/{run_id}")
            require(current["status"] == "completed" and current["conclusion"] == "success" and
                    current["run_attempt"] == evidence["attempt"], "Run changed during verification")
        require(api.get(f"commits/{quote('refs/tags/' + tag, safe='')}")["sha"] == sha, "Release tag/SHA mismatch")
    print(f"Verified {repository} {sha}: Full {full_run}, candidate {candidate_run}, artifact {artifact['id']}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("record-full", "record-candidate", "verify"))
    args = parser.parse_args()
    if args.mode.startswith("record-"):
        record(args.mode.removeprefix("record-"), Path("release-evidence.json"))
    else:
        require(os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch" and
                os.environ["GITHUB_REF"] == "refs/heads/main", "Publish must be dispatched from main")
        verify(repository=os.environ["GITHUB_REPOSITORY"], sha=os.environ["RELEASE_SHA"],
               tag=os.environ["RELEASE_TAG"], version=os.environ["APP_VERSION"],
               candidate_run=os.environ["CANDIDATE_RUN_ID"], full_run=os.environ["FULL_RUN_ID"],
               destination=Path("release-source/release-artifacts"))


if __name__ == "__main__":
    main()
