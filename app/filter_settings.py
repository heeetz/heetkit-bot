"""Desktop editing of the existing line-based global message filters."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from app.runtime_paths import DEFAULT_FILTERS, FILTER_NAMES, RuntimePaths
from app.services.filter_manager import FilterManager, FilterRule, compile_filter_pattern


FILTER_KEYS = ("words", "phrases", "patterns")


class FilterValidationError(ValueError):
    def __init__(self, category: str, index: int, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.index = index


def _entries(path: Path, *, patterns: bool) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            error = None
            if "\ufffd" in value:
                error = "Invalid UTF-8; edit or remove this rule."
            elif patterns:
                try:
                    compile_filter_pattern(value)
                except re.error as reason:
                    error = f"Invalid regex: {reason}"
            entries.append({"value": value, "valid": error is None, "error": error})
    return entries


def get_filter_settings(
    manager: FilterManager,
    directory: Path | None = None,
    defaults_directory: Path = DEFAULT_FILTERS,
) -> dict[str, object]:
    """Describe local lines, including invalid ones, and their source defaults."""
    directory = directory or RuntimePaths.default().filters
    result: dict[str, object] = {}
    active_words, active_phrases, active_patterns = manager.snapshot()
    current = (active_words, active_phrases, [rule.pattern for rule in active_patterns])
    for key, filename, active in zip(FILTER_KEYS, FILTER_NAMES, current):
        patterns = key == "patterns"
        try:
            default_entries = _entries(defaults_directory / filename, patterns=patterns)
            defaults = [str(entry["value"]) for entry in default_entries if entry["valid"]]
        except OSError:
            defaults = []
        try:
            entries = _entries(directory / filename, patterns=patterns)
            load_error = None
            if entries and not any(entry["valid"] for entry in entries):
                visible = {entry["value"] for entry in entries}
                entries.extend(
                    {"value": value, "valid": True, "error": None}
                    for value in active
                    if value not in visible
                )
                load_error = "No valid rules could be loaded; prior active rules are also shown."
        except OSError:
            # The startup loader keeps prior rules for this case. Show those rules
            # instead of presenting an empty list that could imply no protection.
            entries = [{"value": value, "valid": True, "error": None} for value in active]
            load_error = "Could not read the local filter file; active rules are shown."
        for entry in entries:
            entry["origin"] = "default" if entry["value"] in defaults else "local"
        result[key] = {"rules": entries, "defaults": defaults, "load_error": load_error}
    return result


def validate_filter_input(payload: object) -> tuple[list[str], list[str], list[FilterRule]]:
    if not isinstance(payload, dict) or set(payload) != set(FILTER_KEYS):
        raise ValueError("Provide words, phrases, and patterns lists.")
    parsed: list[list[str]] = []
    for key in FILTER_KEYS:
        values = payload[key]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"{key.capitalize()} must be a list of text rules.")
        rules: list[str] = []
        for index, raw in enumerate(values, 1):
            value = raw.strip()
            if not value or value.startswith("#"):
                continue  # Exactly as the existing file loader treats these lines.
            if "\n" in value or "\r" in value or "\ufffd" in value:
                raise FilterValidationError(key, index - 1, f"{key.capitalize()} rule {index} contains invalid text.")
            if key == "patterns":
                try:
                    compile_filter_pattern(value)
                except re.error as error:
                    raise FilterValidationError(
                        key, index - 1, f"Invalid regex in pattern {index}: {error}"
                    ) from error
            if key == "patterns" or value not in rules:
                rules.append(value)
        parsed.append(rules)
    words, phrases, patterns = parsed
    return words, phrases, [FilterRule(pattern=value) for value in patterns]


def apply_filter_settings(
    manager: FilterManager,
    parsed: tuple[list[str], list[str], list[FilterRule]],
) -> None:
    words, phrases, patterns = parsed
    manager.replace_blocked_words(words)
    manager.replace_blocked_phrases(phrases)
    manager.replace_blocked_patterns(patterns)


def save_filter_settings(
    manager: FilterManager,
    parsed: tuple[list[str], list[str], list[FilterRule]],
    directory: Path | None = None,
) -> None:
    """Write validated rules to the existing local files, then apply them."""
    directory = directory or RuntimePaths.default().filters
    directory.mkdir(parents=True, exist_ok=True)
    values = (parsed[0], parsed[1], [rule.pattern for rule in parsed[2]])
    staged: list[tuple[Path, Path]] = []
    backups: list[tuple[Path | None, Path]] = []
    replaced: list[tuple[Path | None, Path]] = []
    try:
        for filename, rules in zip(FILTER_NAMES, values):
            destination = directory / filename
            try:
                existing = _entries(destination, patterns=filename == "blocked_patterns.txt")
                if all(entry["valid"] for entry in existing) and [
                    entry["value"] for entry in existing
                ] == rules:
                    continue  # Keep comments and formatting in untouched files.
            except OSError:
                pass
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=directory, delete=False
            ) as output:
                temporary = Path(output.name)
                staged.append((temporary, destination))
                output.write("".join(f"{rule}\n" for rule in rules))
                output.flush()
                os.fsync(output.fileno())
        # Prepare rollback copies before replacing any file. A failed save must
        # not leave a mixture of old and new moderation rules on disk.
        for _, destination in staged:
            if destination.exists():
                with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
                    backup = Path(output.name)
                    backups.append((backup, destination))
                    with destination.open("rb") as source:
                        shutil.copyfileobj(source, output)
                    output.flush()
                    os.fsync(output.fileno())
            else:
                backups.append((None, destination))
        for temporary, destination in staged:
            temporary.replace(destination)
            replaced.append(backups[len(replaced)])
    except OSError:
        for backup, destination in reversed(replaced):
            if backup is None:
                destination.unlink(missing_ok=True)
            else:
                backup.replace(destination)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        for backup, _ in backups:
            if backup is not None:
                backup.unlink(missing_ok=True)
    apply_filter_settings(manager, parsed)
