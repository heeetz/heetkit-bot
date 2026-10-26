"""Canonical HeetKit application version."""

import re


VERSION = "1.5.0"

_VERSION_RE = re.compile(
    r"(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})"
    r"(?:-(alpha|beta|rc)\.([1-9][0-9]{0,3}))?"
)


def windows_version(version: str = VERSION) -> tuple[int, int, int, int]:
    """Derive ordered 16-bit Windows metadata from the public release version.

    Alpha, beta and rc revisions occupy separate ranges; stable sorts last.
    Display versions, tags and artifact names always retain the full suffix.
    """
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        raise ValueError("Release versions require major.minor.patch with an optional -alpha.N, -beta.N or -rc.N suffix.")
    core = tuple(int(part) for part in match.group(1, 2, 3))
    if any(part > 65535 for part in core):
        raise ValueError("Windows version components must be at most 65535.")
    stage, number = match.group(4, 5)
    revision = 65535 if stage is None else {"alpha": 0, "beta": 10000, "rc": 20000}[stage] + int(number)
    return (*core, revision)


def is_prerelease(version: str = VERSION) -> bool:
    """Preserve the pre-1.0 policy and recognize explicit prerelease suffixes."""
    return windows_version(version)[0] == 0 or "-" in version
