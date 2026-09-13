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
            self._blocked_patterns.append(FilterRule(pattern=pattern, is_regex=is_regex, case_sensitive=case_sensitive))
    
    def clear_filters(self) -> None:
        """Clear all filters."""
        self._blocked_words.clear()
        self._blocked_phrases.clear()
        self._blocked_patterns.clear()
    
    def filter_message(self, message_content: str) -> bool:
        """
        Determine if a message should be ALLOWED (True) or IGNORED (False).
        
        Returns True if the message should be allowed, False if it should be ignored.
        """
        # Check for blocked words - use word boundary matching
        for word in self._blocked_words:
            # Use word boundary matching to avoid partial matches
            pattern = r'\b' + re.escape(word) + r'\b'
            flags = re.IGNORECASE  # Always case insensitive for words
            if re.search(pattern, message_content, flags):
                return False
        
        # Check for blocked phrases - simple substring matching, case-insensitive by default
        for phrase in self._blocked_phrases:
            flags = re.IGNORECASE  # Always case insensitive for phrases
            if re.search(re.escape(phrase), message_content, flags):
                return False
        
        # Check for blocked regex patterns
        for rule in self._blocked_patterns:
            try:
                flags = 0 if rule.case_sensitive else re.IGNORECASE
                if rule.is_regex:
                    if re.search(rule.pattern, message_content, flags):
                        return False
                else:
                    # Treat as literal pattern matching
                    if re.search(re.escape(rule.pattern), message_content, flags):
                        return False
            except re.error:
                # If regex is invalid, skip this rule (no crash)
                continue
        
        return True  # Allow the message by default