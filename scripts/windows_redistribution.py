"""Check finished Windows payloads against reviewed binaries and upstream notices.

This checks artifact evidence, not legal clearance. Updating the allowlist requires
reviewing exact upstream distributions; never regenerate it from a new build alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "packaging/windows/redistribution.json"
STAGED_POLICY = "_internal/licenses/windows-redistribution.json"
NATIVE_SUFFIXES = {".dll", ".pyd", ".exe", ".so", ".dylib", ".node", ".ocx"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(bundle: Path, policy_path: Path = POLICY) -> dict:
    """Require exact native inventory and byte-preserved required notice texts."""
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if policy["schema"] != "heetkit.windows-redistribution.v1":
        raise ValueError("Unsupported Windows redistribution evidence schema")
    staged_policy = bundle / STAGED_POLICY
    if not staged_policy.is_file() or sha256(staged_policy) != sha256(policy_path):
        raise ValueError("Missing or mismatched staged Windows redistribution evidence")
    native = {}
    for path in bundle.rglob("*"):
        if not path.is_file():
            continue
        name = path.relative_to(bundle).as_posix()
        if path.is_symlink():
            raise ValueError(f"Linked artifact file: {name}")
        # Also catch a renamed Windows binary with an innocent extension.
        with path.open("rb") as stream:
            is_pe = stream.read(2) == b"MZ"
        if path.suffix.lower() in NATIVE_SUFFIXES or is_pe:
            if name != "HeetKit.exe":  # Generated application; inspected by the existing PYZ check.
                native[name] = path
    expected = policy["native_files"]
    unexpected = sorted(set(native) - set(expected))
    missing = sorted(set(expected) - set(native))
    if unexpected:
        raise ValueError(f"Unexpected native components: {', '.join(unexpected)}")
    if missing:
        raise ValueError(f"Missing reviewed native components: {', '.join(missing)}")
    for name, entry in expected.items():
        if sha256(native[name]) != entry["sha256"]:
            raise ValueError(f"Native hash/version mismatch: {name} (reviewed {entry['version']})")
    for name, entry in policy["required_notices"].items():
        path = bundle / name
        if not path.is_file():
            raise ValueError(f"Required redistribution notice missing: {name}")
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"Redistribution notice hash mismatch: {name}")
    for name in policy["required_documents"]:
        path = bundle / name
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Required redistribution document missing: {name}")
    manifest_path = bundle / "BUILD-MANIFEST.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["python"] != policy["python_version"]:
            raise ValueError("Artifact Python version differs from reviewed native evidence")
    return {
        "native_files": len(native), "required_notices": len(policy["required_notices"]),
        "unresolved_findings": policy["unresolved_findings"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        result = validate(args.bundle)
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error)) from error
    print(f"Redistribution artifact evidence passed: {result['native_files']} native files, "
          f"{result['required_notices']} required notice texts; "
          f"{len(result['unresolved_findings'])} owner/legal findings remain open")


if __name__ == "__main__":
    main()
