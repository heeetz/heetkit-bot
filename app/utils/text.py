"""Small text normalization helpers."""

from app.errors import UserError
import re
import unicodedata


CHAT_RESPONSE_BYTES = 450
_VARIABLE_PATTERN = re.compile(r"\{([^{}]+)\}")


def validate_chat_template(value, *, required, optional=()):
    if not isinstance(value, str) or not value.strip() or any(char in value for char in "\r\n\x00"):
        raise UserError("text.enter_a_single_line_chat_message")
    if len(value.encode("utf-8")) > CHAT_RESPONSE_BYTES:
        raise UserError("text.chat_messages_can_use_up_to_utf_8_bytes", value1=str(CHAT_RESPONSE_BYTES))
    variables = set(_VARIABLE_PATTERN.findall(value))
    if not set(required) <= variables or not variables <= set((*required, *optional)):
        allowed = ", ".join(f"{{{name}}}" for name in required)
        raise UserError("text.the_message_must_include_and_may_include", allowed=str(allowed), sender="{sender}")
    if any(char in _VARIABLE_PATTERN.sub("", value) for char in "{}"):
        raise UserError("text.use_braces_only_for_supported_template_variables")
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


# Cyrillic and Greek letters that read as a Latin letter (after casefold). Folding both
# the rule and the message to this skeleton makes "слово" typed with Latin "c"/"o"
# match a blocked "слово", and the other way round.
_CONFUSABLES = str.maketrans({
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
    "с": "c", "т": "t", "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j", "ѕ": "s", "ԁ": "d",
    "ү": "y", "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
    "υ": "u", "χ": "x",
})
# Single letters joined by separators: "w.o.r.d", "с л о в о", "w_o-r_d".
_SPACED_LETTERS = re.compile(r"(?<![^\W_])[^\W_](?:[\W_]{1,3}[^\W_](?![^\W_]))+")
_SEPARATORS = re.compile(r"[\W_]+")


def fold_for_filter(value: str) -> str:
    """A matching skeleton that undoes common filter evasion; never shown or sent.

    NFKC folds styled and full-width letters, invisible and combining characters are
    dropped, case and look-alike letters are folded, and spaced-out letters are joined.
    """
    decomposed = unicodedata.normalize("NFD", unicodedata.normalize("NFKC", value))
    visible = "".join(
        character for character in decomposed
        if character.isspace() or unicodedata.category(character) not in {"Cf", "Cc", "Mn", "Me"}
    )
    folded = unicodedata.normalize("NFC", visible).casefold().translate(_CONFUSABLES)
    joined = _SPACED_LETTERS.sub(lambda match: _SEPARATORS.sub("", match.group()), folded)
    return " ".join(joined.split())
