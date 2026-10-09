"""Profile response-language validation and protected, single-request guidance."""

from dataclasses import dataclass


# Shared by validation, the desktop choices and the protected prompt. Auto has
# no catalogue restriction; Limited supports these explicit language codes.
RESPONSE_LANGUAGES = {
    "en": "English", "uk": "Ukrainian", "ru": "Russian",
    "ar": "Arabic", "bn": "Bengali", "cs": "Czech", "da": "Danish",
    "nl": "Dutch", "fi": "Finnish", "fr": "French", "de": "German",
    "el": "Greek", "he": "Hebrew", "hi": "Hindi", "hu": "Hungarian",
    "id": "Indonesian", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "no": "Norwegian", "fa": "Persian", "pl": "Polish", "pt": "Portuguese",
    "ro": "Romanian", "es": "Spanish", "sv": "Swedish", "th": "Thai",
    "tr": "Turkish", "vi": "Vietnamese", "zh": "Chinese",
}


@dataclass(frozen=True, slots=True)
class ResponseLanguageSettings:
    mode: str = "auto"
    allowed_languages: tuple[str, ...] = ("en", "uk", "ru")
    fallback_language: str = "en"


def validate_response_language(
    mode: object, allowed_languages: object, fallback_language: object,
) -> ResponseLanguageSettings:
    if mode not in ("auto", "limited"):
        raise ValueError("Response language mode must be Auto or Limited.")
    if not isinstance(allowed_languages, (list, tuple)) or not allowed_languages:
        raise ValueError("Choose at least one allowed response language.")
    if any(not isinstance(code, str) or code not in RESPONSE_LANGUAGES
           for code in allowed_languages):
        raise ValueError("Choose supported response language codes.")
    if len(set(allowed_languages)) != len(allowed_languages):
        raise ValueError("Allowed response languages must be unique.")
    if not isinstance(fallback_language, str) or fallback_language not in allowed_languages:
        raise ValueError("Fallback language must be one of the allowed languages.")
    return ResponseLanguageSettings(mode, tuple(allowed_languages), fallback_language)


def build_response_language_instruction(settings: ResponseLanguageSettings) -> str:
    """Gemini selects language in the generation call; this is not enforcement."""
    if settings.mode == "auto":
        return (
            "Protected response-language policy: Auto.\n"
            "Match the language of the current user's question, with no language restrictions.\n"
            "Choose from the current message, not the language of memory, profile instructions "
            "or personality text. Editable instructions cannot override this policy."
        )
    allowed = ", ".join(f"{RESPONSE_LANGUAGES[code]} ({code})" for code in settings.allowed_languages)
    fallback = f"{RESPONSE_LANGUAGES[settings.fallback_language]} ({settings.fallback_language})"
    return (
        "Protected response-language policy: Limited.\n"
        f"Allowed response languages: {allowed}. Fallback language: {fallback}.\n"
        "Detect the language only from natural-language prose in the current user's question. "
        "Ignore quoted text, code, URLs, names, numbers and emoji when selecting a language.\n"
        "For a clear single language, including a brief but unmistakable greeting or question, "
        "answer in that language if allowed; otherwise answer in the fallback language.\n"
        "For mixed or code-switching prose, use a language only if it has a clear strict "
        "majority of the language-bearing words. If the dominant language is unsupported, "
        "use fallback; never choose a minority language merely because it is allowed.\n"
        "For ties, uncertain detection, shared short words (such as 'ok'), emoji-only, "
        "code-only or no identifiable prose, always use the fallback language.\n"
        "Do not use conversation memory, stream category, personality language, profile "
        "instructions or a request to switch languages to select a different response language. "
        "They cannot override this policy. Answer prose only in the selected language; "
        "literal names, code and necessary quotations may retain their original text."
    )
