"""Small text normalization helpers."""

import re
import unicodedata


CHAT_RESPONSE_BYTES = 450
_VARIABLE_PATTERN = re.compile(r"\{([^{}]+)\}")


def validate_chat_template(value, *, required, optional=()):
    if not isinstance(value, str) or not value.strip() or any(char in value for char in "\r\n\x00"):
        raise ValueError("Enter a single-line chat message.")
    if len(value.encode("utf-8")) > CHAT_RESPONSE_BYTES:
        raise ValueError(f"Chat messages can use up to {CHAT_RESPONSE_BYTES} UTF-8 bytes.")
    variables = set(_VARIABLE_PATTERN.findall(value))
    if not set(required) <= variables or not variables <= set((*required, *optional)):
        allowed = ", ".join(f"{{{name}}}" for name in required)
        raise ValueError(f"The message must include {allowed} and may include {{sender}}.")
    if any(char in _VARIABLE_PATTERN.sub("", value) for char in "{}"):
        raise ValueError("Use braces only for supported template variables.")
    return value.strip()


def render_chat_template(template, values):
    return _VARIABLE_PATTERN.sub(lambda match: values[match.group(1)], template)


def _is_invisible_command_character(value: str) -> bool:
    if value in {"\u200c", "\u200d"}:
        return False
    category = unicodedata.category(value)
    if category in {"Cf", "Cc"}:
        return True
    return unicodedata.name(value, "") == "COMBINING GRAPHEME JOINER"


def _remove_invisible_command_characters(value: str) -> str:
    return "".join(
        character
        for character in value
        if character.isspace() or not _is_invisible_command_character(character)
    )


def _strip_invisible_command_edges(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and (value[start].isspace() or _is_invisible_command_character(value[start])):
        start += 1
    while end > start and (value[end - 1].isspace() or _is_invisible_command_character(value[end - 1])):
        end -= 1
    return value[start:end]


def normalize_text(value: str) -> str:
    """Normalize Unicode and collapse whitespace without changing case."""

    return " ".join(unicodedata.normalize("NFKC", value).split())


def normalize_command_name(value: str) -> str:
    """Return a canonical command key without its prefix marker."""

    return _remove_invisible_command_characters(normalize_text(value)).lstrip("!").casefold()


def parse_command(content: str, prefix: str) -> tuple[str, str] | None:
    """Extract a normalized command name and its unmodified argument tail."""

    stripped = content.strip()
    if not stripped.startswith(prefix):
        return None

    command_text = stripped[len(prefix) :].strip()
    if not command_text:
        return None

    command_parts = command_text.split(maxsplit=1)
    raw_name = command_parts[0]
    arguments = command_parts[1] if len(command_parts) == 2 else ""
    arguments = _strip_invisible_command_edges(
        _remove_invisible_command_characters(arguments)
    )
    return normalize_command_name(raw_name), arguments


def format_duration(total_seconds: int) -> str:
    """Format an elapsed duration concisely for a chat response."""

    total_seconds = max(0, total_seconds)
    days, remaining = divmod(total_seconds, 86_400)
    hours, remaining = divmod(remaining, 3_600)
    minutes, seconds = divmod(remaining, 60)
    if days:
        return f"{days}d {hours:02}h {minutes:02}m"
    if hours:
        return f"{hours}h {minutes:02}m {seconds:02}s"
    if minutes:
        return f"{minutes}m {seconds:02}s"
    return f"{seconds}s"
