"""Gemini AI service implementation."""

import logging
from re import Pattern
import re

from app.config.settings import Settings
from app.services.contracts import AIReply
from app.config import AI_MAX_RESPONSE_LENGTH, build_ai_system_instruction as build_system_instruction
from app.runtime_state import RuntimeState

logger = logging.getLogger(__name__)


class GeminiAIService:
    """Gemini AI service that implements the AIService protocol."""

    def __init__(self, settings: Settings, runtime_state: RuntimeState | None = None):
        self.settings = settings
        self.runtime_state = runtime_state
        self._blocked_response_patterns: list[Pattern] = [
            # Dedicated hard block for the specified term and grammatical forms.
            re.compile(
                r"(?<![А-Яа-яЁёІіЇїЄєҐґ])додик"
                r"(?:а|у|ом|и|ов|ами|ів|ам|ах|ові|ових|ою|ий|ого|ому|ими|их|им)?"
                r"(?![А-Яа-яЁёІіЇїЄєҐґ])",
                re.IGNORECASE,
            ),

            # Owner references
            re.compile(
                r"(?<![a-z0-9_])(heet[_\s-]?ok|heet)(?![a-z0-9_])",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?<![а-яёіїєґ])хит(?:ок)?(?![а-яёіїєґ])",
                re.IGNORECASE,
            ),

            # Internal information / secrets
            re.compile(
                r"\b(system\s+prompt|hidden\s+instructions?|developer\s+instructions?|"
                r"api\s*key|access\s+token|password|credentials?|internal\s+config)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"(системн\w*\s+промпт|скрыт\w*\s+инструкци|"
                r"api[- ]?ключ|токен|парол[ья]|учётн\w*\s+данн|"
                r"внутренн\w*\s+настройк)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(системн\w*\s+промпт|прихован\w*\s+інструкці|"
                r"api[- ]?ключ|токен|парол[ія]|внутрішн\w*\s+налаштуван)",
                re.IGNORECASE,
            ),

            # Explicit political / geopolitical statements
            re.compile(
                r"\b(president|prime\s+minister|government|election|political\s+party|"
                r"geopolitical|annexation|occupation|sovereignty|territorial\s+dispute)\b"
                r".*\b(is|was|are|were|controls?|owns?|belongs?|annexed|occupied)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(президент\w*|правительств\w*|выбор\w*|политичес\w*|"
                r"геополит\w*|аннекси\w*|оккупаци\w*|суверенитет\w*)\b"
                r".*\b(это|был|была|является|принадлежит|контролирует|захватил)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(президент\w*|уряд\w*|вибор\w*|політич\w*|"
                r"геополітик\w*|анексі\w*|окупаці\w*|суверенітет\w*)\b"
                r".*\b(це|був|була|є|належить|контролює|захопив)\b",
                re.IGNORECASE,
            ),

            # Explicit war / military statements
            re.compile(
                r"\b(war|military\s+conflict|armed\s+conflict|invasion|bombing|"
                r"missile\s+strike|military\s+operation|war\s+crime|battle)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(войн\w*|военн\w*|боев\w*|вторжени\w*|бомбардировк\w*|"
                r"ракет\w*|обстрел\w*|военн\w*\s+преступлени\w*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(війн\w*|воєнн\w*|бойов\w*|вторгнен\w*|бомбардуван\w*|"
                r"ракет\w*|обстріл\w*|воєнн\w*\s+злочин\w*)\b",
                re.IGNORECASE,
            ),

            # Extremism / Nazi / fascist / terrorism
            re.compile(
                r"\b(nazi|nazism|neo[- ]?nazi|fascis[tm]|hitler|third\s+reich|"
                r"holocaust|genocide|terroris[tm]|extremis[tm])\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(нацизм|нацист\w*|неонацист\w*|фашизм|фашист\w*|"
                r"гитлер\w*|холокост\w*|геноцид\w*|терроризм|террорист\w*|экстремизм|экстремист\w*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(нацизм|нацист\w*|неонацист\w*|фашизм|фашист\w*|"
                r"гітлер\w*|голокост\w*|геноцид\w*|тероризм|терорист\w*|екстремізм|екстреміст\w*)\b",
                re.IGNORECASE,
            ),

            # Sensitive real-world incidents
            re.compile(
                r"\b(tiananmen|tiananmen\s+square|massacre|mass\s+killing|"
                r"political\s+repression|violent\s+protest|terrorist\s+attack)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"(тяньаньмэнь|массов\w*\s+убийств\w*|массов\w*\s+расстрел\w*|"
                r"политическ\w*\s+репресси|теракт|террористическ\w*\s+акт)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(тяньаньмень|масов\w*\s+вбивств\w*|масов\w*\s+розстріл\w*|"
                r"політичн\w*\s+репресі|теракт|терористичн\w*\s+акт)",
                re.IGNORECASE,
            ),

            # Twitch moderation / blacklist information
            re.compile(
                r"\b(twitch|stream\s+chat)\b.*\b("
                r"banned\s+words?|prohibited\s+words?|blacklist|moderation\s+filter|"
                r"automod|filter\s+list)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(твич\w*|twitch)\b.*\b("
                r"запрещенн\w*\s+слов\w*|чёрн\w*\s+список|черн\w*\s+список|"
                r"автомод\w*|фильтр\w*\s+слов|модераци\w*\s+слов)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(твіч\w*|twitch)\b.*\b("
                r"заборонен\w*\s+слов\w*|чорн\w*\s+список|блеклист\w*|"
                r"автомод\w*|фільтр\w*\s+слів|модераці\w*\s+слів)\b",
                re.IGNORECASE,
            ),
    ]
        self._blocked_sexual_fetish_patterns: list[Pattern] = [
            re.compile(
                r"(?<![A-Za-z])(?:cuckold|cook[\s_-]*old|qcold|kucold|kukkold)"
                r"[a-z]*(?![A-Za-z])",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?<![А-Яа-яЁёІіЇїЄєҐґ])кук[\s_-]*олд[а-яёіїєґ]*"
                r"(?![А-Яа-яЁёІіЇїЄєҐґ])",
                re.IGNORECASE,
            ),
        ]
        self._blocked_substance_response_patterns: list[Pattern] = [
            re.compile(
                r"\b(?:how\s+to|steps?\s+to|recipe\s+for|instructions?\s+for|"
                r"to\s+(?:make|prepare|synthesize|manufacture|produce|extract|formulate|cook))\b"
                r".{0,120}\b(?:cocaine|methamphetamine|meth|heroin|fentanyl|lsd|mdma|ecstasy|"
                r"crack|illegal\s+drugs?|controlled\s+substances?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:cocaine|methamphetamine|meth|heroin|fentanyl|lsd|mdma|ecstasy|crack|"
                r"illegal\s+drugs?|controlled\s+substances?)\b.{0,120}\b"
                r"(?:recipe|ingredients?|proportions?|ratios?|dosage|steps?|instructions?|"
                r"synthesize|manufacture|produce|extract|formulate|cook)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:как\s+(?:приготовить|синтезировать|изготовить|произвести|получить|"
                r"экстрагировать|выделить)|рецепт|ингредиенты|пропорции|дозировка|инструкция)\b"
                r".{0,120}\b(?:кокаин|метамфетамин|мет|героин|фентанил|лсд|мдма|экстази|крэк|"
                r"наркотик[а-яё]*|запрещенн(?:ые|ых)\s+веществ[а-яё]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:кокаин|метамфетамин|мет|героин|фентанил|лсд|мдма|экстази|крэк|наркотик[а-яё]*|"
                r"запрещенн(?:ые|ых)\s+веществ[а-яё]*)\b.{0,120}\b"
                r"(?:рецепт|ингредиент[а-яё]*|пропорци[а-яё]*|дозировк[а-яё]*|инструкци[а-яё]*|"
                r"синтезировать|изготовить|произвести|экстрагировать|выделить)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:як\s+(?:приготувати|синтезувати|виготовити|виробити|отримати|добути|"
                r"екстрагувати|виділити)|рецепт|інгредієнти|пропорції|дозування|інструкція)\b"
                r".{0,120}\b(?:кокаїн|метамфетамін|мет|героїн|фентаніл|лсд|мдма|екстазі|крек|"
                r"наркотик[а-яіїєґ]*|заборонен(?:і|их)\s+речовин[а-яіїєґ]*)\b",
                re.IGNORECASE,
            ),
        ]

    async def generate_reply(
        self,
        prompt: str,
        user_id: str,
        memory_context: str | None = None,
    ) -> AIReply:
        """Generate a reply using the Gemini model with Google Search grounding."""
        try:
            # If no API key is configured, return unavailable but don't crash
            if self.settings.gemini_api_key is None:
                return AIReply(
                    text="",
                    is_available=False,
                )

            # Import the Gemini client only when needed to avoid import errors.
            try:
                from google import genai
                from google.genai import types
            except ImportError:
                logger.warning("google-genai package is not available")
                return AIReply(
                    text="",
                    is_available=False,
                )

            # Create the client with API key
            client = genai.Client(api_key=self.settings.gemini_api_key.get_secret_value())

            # Configure Google Search tool for grounding
            search_tool = types.Tool(
                google_search=types.GoogleSearch()
            )

            # Generate content using the modern async approach with Google Search tool
            response = await client.aio.models.generate_content(
                model=self.settings.gemini_model,
                contents=self._build_request_content(prompt, memory_context),
                config=types.GenerateContentConfig(
                    system_instruction=build_system_instruction(
                        self.runtime_state.active_ai_personality
                        if self.runtime_state is not None
                        else None
                    ),
                    tools=[search_tool],
                ),
            )

            # Get the text response
            if not response.text:
                return AIReply(
                    text="",
                    is_available=False,
                )

            # Apply maximum response length limit with smart truncation
            original_text = response.text.strip()
            if self._contains_blocked_response_content(original_text):
                logger.info("Gemini response blocked by local response filter")
                return AIReply(
                    text="",
                    is_available=False,
                )
            
            max_length = AI_MAX_RESPONSE_LENGTH

            # If already within limit, return as-is
            if len(original_text) <= max_length:
                return AIReply(
                    text=original_text,
                    is_available=True,
                )

            # Smart truncation to avoid breaking sentences
            truncated_text = self._smart_truncate(original_text, max_length)

            return AIReply(
                text=truncated_text,
                is_available=True,
            )

        except Exception as e:
            # Log error type safely without exposing secrets or stack traces to chat
            logger.warning("Gemini AI generation failed: %s", type(e).__name__)
            return AIReply(
                text="",
                is_available=False,
            )

    @staticmethod
    def _build_request_content(prompt: str, memory_context: str | None) -> str:
        if not memory_context:
            return prompt
        return (
            f"{memory_context}\n\n"
            "Current user request (the task to answer; higher priority than the history):\n"
            f"{prompt}"
        )

    def _contains_blocked_response_content(self, text: str) -> bool:
        for pattern in self._blocked_sexual_fetish_patterns:
            if pattern.search(text):
                return True
        for pattern in self._blocked_response_patterns:
            if pattern.search(text):
                return True
        for pattern in self._blocked_substance_response_patterns:
            if pattern.search(text):
                return True
        return False

    def _smart_truncate(self, text: str, max_length: int) -> str:
        """Truncate text to max_length while preserving sentence boundaries."""
        clean_text = text.strip()
        if len(clean_text) <= max_length:
            return clean_text

        sentence_endings = ('.', '!', '?', '…')

        # Search backwards across the slice for the last complete sentence boundary
        for i in range(max_length - 1, -1, -1):
            if clean_text[i] in sentence_endings:
                candidate = clean_text[:i + 1].strip()
                if candidate:
                    return candidate

        # If no sentence boundary found, search for the last word boundary (space)
        for i in range(max_length - 1, -1, -1):
            if clean_text[i].isspace():
                candidate = clean_text[:i].strip()
                if candidate:
                    return candidate

        # Hard cut fallback
        return clean_text[:max_length].strip()
