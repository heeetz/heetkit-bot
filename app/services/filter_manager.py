"""Filter manager for determining if incoming Twitch messages should be allowed or ignored."""

import re
import time
from dataclasses import dataclass
from typing import List

import regex as regex_engine


REGEX_MATCH_BUDGET_SECONDS = 0.05
_REGEX_TIMEOUT_ERROR = getattr(regex_engine, "TimeoutError", TimeoutError)


@dataclass(frozen=True, slots=True)
class FilterRule:
    """A rule for filtering messages."""
    pattern: str
    is_regex: bool = True
    case_sensitive: bool = False


def compile_filter_pattern(
    pattern: str, *, is_regex: bool = True, case_sensitive: bool = False
) -> object:
    """Validate and compile a configured pattern for bounded message matching."""
    re_flags = 0 if case_sensitive else re.IGNORECASE
    if is_regex:
        # Keep the existing Python ``re`` compatibility contract before handing
        # the pattern to the bounded engine.
        re.compile(pattern, re_flags)
        engine_pattern = pattern
    else:
        # Keep the literal mode's existing escaping semantics.
        engine_pattern = re.escape(pattern)
    engine_flags = 0 if case_sensitive else regex_engine.IGNORECASE
    try:
        return regex_engine.compile(engine_pattern, engine_flags | regex_engine.VERSION0)
    except regex_engine.error as error:
        # Surface engine-only incompatibilities through the existing re.error
        # validation path used by the loader and desktop settings UI.
        raise re.error(str(error)) from error


class FilterManager:
    """Manages message filtering rules to determine if a message should be ALLOWED or IGNORED."""
    
    def __init__(self) -> None:
        self._blocked_words: List[str] = []
        self._blocked_phrases: List[str] = []
        self._blocked_patterns: List[FilterRule] = []
        self._compiled_patterns: list[object] = []
    
    def add_blocked_word(self, word: str) -> None:
        """Add a word to the blocked words list."""
        if word and word not in self._blocked_words:
            self._blocked_words.append(word)
    
    def add_blocked_phrase(self, phrase: str) -> None:
        """Add a phrase to the blocked phrases list."""
        if phrase and phrase not in self._blocked_phrases:
            self._blocked_phrases.append(phrase)
    
    def add_blocked_pattern(self, pattern: str, is_regex: bool = True, case_sensitive: bool = False) -> None:
        """Add a regex pattern to the blocked patterns list."""
        if pattern:
            compiled = compile_filter_pattern(
                pattern, is_regex=is_regex, case_sensitive=case_sensitive
            )
            self._blocked_patterns.append(FilterRule(pattern=pattern, is_regex=is_regex, case_sensitive=case_sensitive))
            self._compiled_patterns.append(compiled)

    def replace_blocked_words(self, words: list[str]) -> None:
        self._blocked_words = list(words)

    def replace_blocked_phrases(self, phrases: list[str]) -> None:
        self._blocked_phrases = list(phrases)

    def replace_blocked_patterns(self, patterns: list[FilterRule]) -> None:
        compiled = [
            compile_filter_pattern(
                rule.pattern,
                is_regex=rule.is_regex,
                case_sensitive=rule.case_sensitive,
            )
            for rule in patterns
        ]
        self._blocked_patterns = list(patterns)
        self._compiled_patterns = compiled

    def snapshot(self) -> tuple[list[str], list[str], list[FilterRule]]:
        """Return copies of the currently active rule lists for the desktop UI."""
        return (
            list(self._blocked_words),
            list(self._blocked_phrases),
            list(self._blocked_patterns),
        )
    
    def filter_message(self, message_content: str) -> bool:
        """
        Determine if a message should be ALLOWED (True) or IGNORED (False).
        
        Returns True if the message should be allowed, False if it should be ignored.
        """
        return not self.contains_blocked_content(message_content)

    def contains_blocked_content(self, message_content: str) -> bool:
        """Return whether the message matches any loaded global filter rule."""
        # Check for blocked words - use word boundary matching
        for word in self._blocked_words:
            # Use word boundary matching to avoid partial matches
            pattern = r'\b' + re.escape(word) + r'\b'
            flags = re.IGNORECASE  # Always case insensitive for words
            if re.search(pattern, message_content, flags):
                return True
        
        # Check for blocked phrases - simple substring matching, case-insensitive by default
        for phrase in self._blocked_phrases:
            flags = re.IGNORECASE  # Always case insensitive for phrases
            if re.search(re.escape(phrase), message_content, flags):
                return True
        
        # Configured patterns are compiled when rules are loaded or edited so
        # the chat path only performs bounded searches. One deadline is shared
        # across every configured pattern for this message.
        deadline = time.monotonic() + REGEX_MATCH_BUDGET_SECONDS
        for compiled in self._compiled_patterns:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            try:
                if compiled.search(message_content, timeout=remaining):
                    return True
            except _REGEX_TIMEOUT_ERROR:
                # A timeout is fail-closed: a message that cannot be checked
                # within the configured budget must not pass moderation.
                return True

        return False
