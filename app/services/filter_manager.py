"""Filter manager for determining if incoming Twitch messages should be allowed or ignored."""

import re
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True, slots=True)
class FilterRule:
    """A rule for filtering messages."""
    pattern: str
    is_regex: bool = True
    case_sensitive: bool = False


class FilterManager:
    """Manages message filtering rules to determine if a message should be ALLOWED or IGNORED."""
    
    def __init__(self) -> None:
        self._blocked_words: List[str] = []
        self._blocked_phrases: List[str] = []
        self._blocked_patterns: List[FilterRule] = []
    
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
            if is_regex:
                re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
            self._blocked_patterns.append(FilterRule(pattern=pattern, is_regex=is_regex, case_sensitive=case_sensitive))

    def replace_blocked_words(self, words: list[str]) -> None:
        self._blocked_words = list(words)

    def replace_blocked_phrases(self, phrases: list[str]) -> None:
        self._blocked_phrases = list(phrases)

    def replace_blocked_patterns(self, patterns: list[FilterRule]) -> None:
        self._blocked_patterns = list(patterns)
    
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
        
        # Check for blocked regex patterns
        for rule in self._blocked_patterns:
            try:
                flags = 0 if rule.case_sensitive else re.IGNORECASE
                if rule.is_regex:
                    if re.search(rule.pattern, message_content, flags):
                        return True
                else:
                    # Treat as literal pattern matching
                    if re.search(re.escape(rule.pattern), message_content, flags):
                        return True
            except re.error:
                # If regex is invalid, skip this rule (no crash)
                continue
        
        return False
