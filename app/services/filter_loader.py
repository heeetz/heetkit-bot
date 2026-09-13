"""Filter loader for loading rules from text files."""

import logging
import os

from app.services.filter_manager import FilterManager


logger = logging.getLogger(__name__)


def load_filters_from_directory(filter_manager: FilterManager, directory_path: str = "data/filters") -> None:
    """
    Load filter rules from text files in the specified directory.
    
    Args:
        filter_manager: The FilterManager instance to populate with rules
        directory_path: Path to the directory containing filter files
    """
    # Ensure the directory exists
    if not os.path.exists(directory_path):
        try:
            os.makedirs(directory_path, exist_ok=True)
            logger.info("Created filter directory: %s", directory_path)
        except Exception as e:
            logger.warning("Failed to create filter directory %s: %s", directory_path, str(e))
            return
    
    # Load blocked words
    blocked_words_file = os.path.join(directory_path, "blocked_words.txt")
    _load_blocked_words(filter_manager, blocked_words_file)
    
    # Load blocked phrases  
    blocked_phrases_file = os.path.join(directory_path, "blocked_phrases.txt")
    _load_blocked_phrases(filter_manager, blocked_phrases_file)
    
    # Load blocked patterns
    blocked_patterns_file = os.path.join(directory_path, "blocked_patterns.txt")
    _load_blocked_patterns(filter_manager, blocked_patterns_file)


def _load_blocked_words(filter_manager: FilterManager, file_path: str) -> None:
    """Load blocked words from a file."""
    if not os.path.exists(file_path):
        # Create empty file if it doesn't exist
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# Blocked words file\n")
            logger.info("Created empty blocked_words.txt file")
        except Exception as e:
            logger.warning("Failed to create blocked_words.txt: %s", str(e))
        return
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line_num, line in enumerate(lines, 1):
            # Strip whitespace and skip comments/empty lines
            content = line.strip()
            if not content or content.startswith('#'):
                continue
            
            # Add the word to filter manager
            filter_manager.add_blocked_word(content)
            
    except Exception as e:
        logger.error("Failed to load blocked words from %s: %s", file_path, str(e))


def _load_blocked_phrases(filter_manager: FilterManager, file_path: str) -> None:
    """Load blocked phrases from a file."""
    if not os.path.exists(file_path):
        # Create empty file if it doesn't exist
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# Blocked phrases file\n")
            logger.info("Created empty blocked_phrases.txt file")
        except Exception as e:
            logger.warning("Failed to create blocked_phrases.txt: %s", str(e))
        return
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line_num, line in enumerate(lines, 1):
            # Strip whitespace and skip comments/empty lines
            content = line.strip()
            if not content or content.startswith('#'):
                continue
            
            # Add the phrase to filter manager
            filter_manager.add_blocked_phrase(content)
            
    except Exception as e:
        logger.error("Failed to load blocked phrases from %s: %s", file_path, str(e))


def _load_blocked_patterns(filter_manager: FilterManager, file_path: str) -> None:
    """Load blocked regex patterns from a file."""
    if not os.path.exists(file_path):
        # Create empty file if it doesn't exist
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# Blocked patterns file\n")
            logger.info("Created empty blocked_patterns.txt file")
        except Exception as e:
            logger.warning("Failed to create blocked_patterns.txt: %s", str(e))
        return
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line_num, line in enumerate(lines, 1):
            # Strip whitespace and skip comments/empty lines
            content = line.strip()
            if not content or content.startswith('#'):
                continue
            
            # Add the pattern to filter manager (treat as regex by default)
            try:
                filter_manager.add_blocked_pattern(content)
            except Exception as e:
                logger.warning("Invalid regex pattern in %s line %d: %s", file_path, line_num, str(e))
                
    except Exception as e:
        logger.error("Failed to load blocked patterns from %s: %s", file_path, str(e))