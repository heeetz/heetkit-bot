"""Windows Setup language choice and its one-time hand-off to the app (task 2.3)."""

import json
import re
from pathlib import Path

import pytest

from app import webview_host
from app.app_settings import AppSettingsStore

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "packaging/windows/HeetKit.iss").read_text(encoding="utf-8")


@pytest.mark.parametrize("existing,expected,seeded", [
    ("new", "uk", True), ("legacy", "uk", True), ("saved", "en", False),
])
def test_setup_seeds_only_profiles_without_a_saved_language(tmp_path, existing, expected, seeded):
    path = tmp_path / "app_settings.json"
    if existing == "legacy":
        path.write_text(json.dumps({"version": 1, "window": {}}), encoding="utf-8")
    elif existing == "saved":
        AppSettingsStore(path).update_interface_language("en")
    assert AppSettingsStore(path).seed_interface_language("uk") is seeded
    assert AppSettingsStore(path).seed_interface_language("ru") is False
    assert AppSettingsStore(path).snapshot().interface.language == expected


@pytest.mark.parametrize("value", [None, "", "de", "UK", 3])
def test_missing_or_unknown_setup_values_are_ignored(tmp_path, value) -> None:
    path = tmp_path / "app_settings.json"
    store = AppSettingsStore(path)
    assert store.seed_interface_language(value) is False
    assert store.snapshot().interface.language == "en"
    assert not path.exists()


def test_portable_and_non_windows_copies_do_not_read_setup(monkeypatch) -> None:
    monkeypatch.setattr(webview_host.sys, "platform", "linux")
    assert webview_host.setup_interface_language() is None
    monkeypatch.setattr(webview_host.sys, "platform", "win32")
    monkeypatch.setattr(webview_host.desktop_relaunch, "installed_directory", lambda: None)
    assert webview_host.setup_interface_language() is None


def section(name: str) -> str:
    match = re.search(rf"^\[{name}\]\n(.*?)(?=^\[|\Z)", SCRIPT, re.M | re.S)
    assert match, name
    return match.group(1)


def test_installer_offers_english_first_and_preselected() -> None:
    languages = re.findall(r'^Name: "(\w+)"', section("Languages"), re.M)
    assert languages == ["en", "uk", "ru"]
    setup = section("Setup")
    assert "ShowLanguageDialog=yes" in setup
    assert "LanguageDetectionMethod=none" in setup  # not the Windows language
    assert 'compiler:Languages\\Ukrainian.isl' in SCRIPT and 'compiler:Languages\\Russian.isl' in SCRIPT


def test_every_heetkit_setup_message_exists_in_all_languages() -> None:
    entries: dict[str, dict[str, str]] = {}
    for block in ("Messages", "CustomMessages"):
        for language, name, text in re.findall(r"^(\w+)\.(\w+)=(.*)$", section(block), re.M):
            entries.setdefault(name, {})[language] = text
    assert entries
    for name, texts in entries.items():
        assert set(texts) == {"en", "uk", "ru"}, name
        assert all(text.strip() for text in texts.values()), name
        assert len({len(re.findall(r"%\d", text)) for text in texts.values()}) == 1, name
        assert "ё" not in texts["ru"].lower(), name
    used = set(re.findall(r"CustomMessage\('(\w+)'\)|\{cm:(\w+)\}", SCRIPT))
    for pair in used:
        assert (pair[0] or pair[1]) in entries


def test_installer_has_no_untranslated_literal_text_in_code() -> None:
    code = re.sub(r"\{[^}]*\}", "", SCRIPT.split("[Code]", 1)[1])  # drop { comments }
    literals = [text for text in re.findall(r"'([^'\n]*)'", code) if re.search(r"[A-Za-z]{3,}", text)]
    technical = re.compile(r"^(https?://|\\|Software\\|SOFTWARE\\|/LANG=|open|pv|Release|InstallLocation|InitialUiLanguage|"
                           r"HEETKIT_DATA_DIR|\{|\w+$)")
    assert [text for text in literals if not technical.match(text)] == []


def test_setup_hands_the_language_to_the_app_and_uninstall_removes_it() -> None:
    code = SCRIPT.split("[Code]", 1)[1]
    assert f"LanguageKey = '{webview_host.SETUP_REGISTRY_KEY}'" in code
    assert f"LanguageValue = '{webview_host.SETUP_LANGUAGE_VALUE}'" in code
    assert "RegWriteStringValue(HKCU, LanguageKey, LanguageValue, ActiveLanguage)" in code
    # A silent update without an explicit /LANG= keeps the value an earlier install wrote.
    assert "WizardSilent and not HasExplicitLanguage" in code
    assert "RegDeleteValue(HKCU, LanguageKey, LanguageValue)" in code
