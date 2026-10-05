"""Load optional message-filter rules independently from text files."""

import logging
import re
from pathlib import Path

from app.runtime_paths import RuntimePaths
from app.services.filter_manager import FilterManager, FilterRule, compile_filter_pattern


logger = logging.getLogger(__name__)


def load_filters_from_directory(
    filter_manager: FilterManager, directory_path: str | Path | None = None
) -> None:
    """Reload each readable file, retaining its previous rules if reading fails."""
    directory = Path(directory_path) if directory_path is not None else RuntimePaths.default().filters
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logger.error("Cannot access filter directory %s; keeping existing rules: %s", directory, error)
        return

    for filename, replace_rules in (
        ("blocked_words.txt", filter_manager.replace_blocked_words),
        ("blocked_phrases.txt", filter_manager.replace_blocked_phrases),
        ("blocked_patterns.txt", filter_manager.replace_blocked_patterns),
    ):
        path = directory / filename
        try:
            if not path.exists():
                logger.warning("Filter file %s is missing; keeping existing rules", path)
                continue
            rules, invalid_count = _read_rules(path, patterns=filename == "blocked_patterns.txt")
        except OSError as error:
            logger.error("Cannot load filter file %s; keeping existing rules: %s", path, error)
            continue
        if invalid_count and not rules:
            logger.error("Filter file %s has no valid rules; keeping existing rules", path)
            continue
        replace_rules(rules)


def _read_rules(path: Path, *, patterns: bool) -> tuple[list[str] | list[FilterRule], int]:
    rules: list[str] | list[FilterRule] = []
    invalid_count = 0
    # Replacement decoding lets a corrupt line be rejected without losing later rules.
    with path.open("r", encoding="utf-8", errors="replace") as source:
        for line_number, line in enumerate(source, 1):
            content = line.strip()
            if not content or content.startswith("#"):
                continue
            if "\ufffd" in content:
                logger.warning("Invalid UTF-8 in %s line %d; skipping rule", path, line_number)
                invalid_count += 1
                continue
            if patterns:
                try:
                    compile_filter_pattern(content)
                except re.error as error:
                    logger.warning("Invalid regex in %s line %d (%r): %s", path, line_number, content, error)
                    invalid_count += 1
                    continue
                rules.append(FilterRule(pattern=content))
            elif content not in rules:
                rules.append(content)
    return rules, invalid_count
