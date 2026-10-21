"""Release validation and Windows ordering share the canonical version rules."""

import pytest

from app.version import is_prerelease, windows_version


@pytest.mark.parametrize("version,numeric,prerelease", [
    ("0.1.3", (0, 1, 3, 65535), True),
    ("1.3.0", (1, 3, 0, 65535), False),
    ("1.4.0-alpha.1", (1, 4, 0, 1), True),
    ("1.4.0-beta.1", (1, 4, 0, 10001), True),
    ("1.4.0-rc.2", (1, 4, 0, 20002), True),
    ("1.4.0", (1, 4, 0, 65535), False),
])
def test_release_metadata(version, numeric, prerelease):
    assert windows_version(version) == numeric
    assert is_prerelease(version) is prerelease


def test_beta_and_final_windows_upgrades_sort_after_previous_stable():
    versions = ["1.3.0", "1.4.0-alpha.9999", "1.4.0-beta.1", "1.4.0-beta.2", "1.4.0-rc.1", "1.4.0"]
    numeric = [windows_version(version) for version in versions]
    assert sorted(numeric) == numeric
    # Previously published stable executables used revision zero.
    assert (1, 3, 0, 0) < numeric[1]
    assert numeric[-1] > numeric[-2]


@pytest.mark.parametrize("version", [
    "v1.4.0", "1.4", "01.4.0", "1.4.0-beta", "1.4.0-beta.0",
    "1.4.0-beta.01", "1.4.0-beta.10000", "1.4.0-preview.1", "1.4.0+build",
    "1.4.0-BETA.1", "1.4.0-beta.1\n", "65536.0.0", "1.65536.0", "1.4.65536",
])
def test_invalid_or_unrepresentable_release_is_rejected(version):
    with pytest.raises(ValueError):
        windows_version(version)
    with pytest.raises(ValueError):
        is_prerelease(version)
