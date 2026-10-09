"""AI request policy for determining if an !ask request should be processed."""

import re
import unicodedata
from enum import Enum
from typing import List, Pattern


def _terms(pattern: str) -> Pattern:
    return re.compile(r"\b(?:" + pattern + r")\b", re.IGNORECASE)


# Paired signals, not bans on children, illness, jokes, or gaming vocabulary.
_MINORS = _terms(
    r"children|child|kids?|minors?|underage|teens?|(?:[0-9]|1[0-7])[- ]year[- ]olds?|"
    r"дет(?:и|ей|ям|ьми|ях|ск\w*)|реб[её]н\w*|подрост\w*|несовершеннолет\w*|"
    r"діт\w*|дитин\w*|підліт\w*|неповноліт\w*|(?:[0-9]|1[0-7])[- ](?:летн\w*|річн\w*)"
)
_SEXUAL = _terms(r"sex(?:ual\w*)?|porn\w*|erotic\w*|nudes?|fetish\w*|секс\w*|порн\w*|эрот\w*|ерот\w*|трах\w*|оголен\w*")
_JOKING = _terms(r"jok\w*|laugh\w*|funny|шут\w*|сме\w*|жарт\w*|смі\w*")
_SUFFERING = _terms(r"dead|dying|suffer\w*|abuse\w*|м[её]ртв\w*|страда\w*|помер\w*|стражда\w*")
_DEMEANING = _terms(
    r"mock\w*|roast\w*|ridicule|humiliat\w*|demean\w*|cruel|worthless|"
    r"inferior|disgusting|subhuman|useless|stupid|pathetic|idiots?|"
    r"издева\w*|высме\w*|уни[жз]\w*|оскорб\w*|никч[её]мн\w*|неполноцен\w*|"
    r"туп\w*|бесполезн\w*|жесток\w*|глум\w*|знуща\w*|висмі\w*|прини[жз]\w*|"
    r"образ(?:и|ь|лив)\w*|нікчем\w*|неповноцін\w*|дурн\w*|жорсток\w*|глуз\w*"
)
_PROTECTED_TRAITS = _terms(
    r"disab\w*|autis\w*|adhd|neurodiver\w*|mental\s+illness|depress\w*|"
    r"schizophren\w*|cancer|illness|race|ethnic\w*|religio\w*|gay|transgender|"
    r"инвалид\w*|аути\w*|сдвг|нейроотлич\w*|болезн\w*|депрес\w*|"
    r"шизофрен\w*|рак(?:а|ом|у|е|овый)?|национальност\w*|рас(?:а|ы|е|у|ой|ов\w*)|религи\w*|"
    r"інвалід\w*|рдуг|нейровідмін\w*|хвороб\w*|національност\w*|релігі\w*"
)
_SELF_HARM = _terms(
    r"(?:kill|hurt|cut|harm)\s+(?:yourself|myself|himself|herself|themselves)|"
    r"(?:commit|encourage|promote)\s+suicide|(?:encourage|promote)\s+self[- ]harm|"
    r"(?:you|he|she|they)\s+should\s+(?:die|end\s+(?:your|his|her|their)\s+life)|"
    r"(?:убей|убить|порежь|режь|повреди)\s+себя|(?:покончи|покончить)\s+с\s+собой|"
    r"(?:вбей|вбити|поріж|порізати|ушкодь)\s+себе|(?:наклади|накласти)\s+на\s+себе\s+руки|"
    r"(?:нашкодити|нашкодь)\s+собі|"
    r"(?:заохоч\w*|пропаганд\w*|поощр\w*)\s+(?:самоубийств\w*|самогубств\w*|самопошкоджен\w*)"
)
_HARM_OR_HARASSMENT = _terms(
    r"(?:i\s+(?:will|am\s+going\s+to)|you\s+should|help\s+me|how\s+to)\s+"
    r"(?:kill|hurt|attack|threaten|stalk|harass|dox\w*)\s+(?:you|him|her|them|someone|"
    r"(?:a|the|my|that)\s+(?:viewer|streamer|person|neighbou?r|ex))|"
    r"(?:send|write)\s+(?:death\s+)?threats|(?:organize|coordinate)\s+(?:targeted\s+)?harassment|"
    r"i\s+(?:will|am\s+going\s+to)\s+(?:kill|hurt|attack)\s+\w+|"
    r"(?:я\s+тебя\s+убью|я\s+тебе\s+наврежу|я\s+тебе\s+угрожаю|"
    r"я\s+тебе\s+вб'ю|я\s+тебе\s+вбью)|"
    r"(?:как|помоги|допоможи|як)\s+(?:\w+\s+){0,2}"
    r"(?:убить|навредить|угрожать|преследовать|травить|вбити|нашкодити|"
    r"погрожувати|переслідувати|цькувати|затравить)\s+\w+|"
    r"(?:угрожай|погрожуй|переслідуй|преследуй|затрави|цькуй)\s+\w+|"
    r"я\s+(?:\w+\s+){0,2}(?:убью|вб'ю|вбью)\s+\w+"
)
_TARGETED_HARASSMENT = _terms(
    r"(?:stalk|harass|dox\w*)\s+(?:(?:a|the|my|that)\s+)?(?:streamer|viewer|person|ex|him|her|them|you)|"
    r"(?:преследуй|преследовать|затрави|затравить|переслідуй|переслідувати|цькуй|цькувати)\s+\w+"
)
_PRIVATE_DATA = _terms(
    r"(?:home|private|personal|real)\s+(?:address|phone|number|identity|name)|"
    r"(?:домашн\w*|личн\w*|приватн\w*|особист\w*|реальн\w*)\s+"
    r"(?:адрес\w*|телефон\w*|номер\w*|ім'я|имя)"
)
_DISCLOSURE = _terms(
    r"find|leak|publish|share|expose|post|get|lives\s+at|"
    r"найди|слей|опублику\w*|вылож\w*|раскрой|адрес\w*\s*[:=]|"
    r"знайди|злий|оприлюд\w*|опубліку\w*|розкрий|живе|проживает"
)
_ADDRESS_DISCLOSURE = re.compile(
    r"\b(?:home\s+address|домашн\w*\s+адрес\w*)\s*(?:is|это|це|[:=])\s*\d", re.IGNORECASE,
)
_BENIGN_TRAITS = _terms(r"race\s+(?:strategy|cars?|track|pace|conditions?)|motor\s+race")
_PUBLIC_EVENTS = _terms(
    r"orange\s+revolution|revolution\s+of\s+dignity|euromaidan|"
    r"(?:оранжев\w*|помаранчев\w*)\s+революц\w*|революц\w*\s+(?:гідност\w*|достоинств\w*)|"
    r"євромайдан\w*|евромайдан\w*|9/11|september\s+11|tiananmen|тяньаньм[еэ]нь|"
    r"school\s+shootings?|mass\s+(?:shootings?|violence)"
)
_EVENT_TOPICS = _terms(
    r"protests?|revolutions?|uprisings?|coups?|riots?|traged(?:y|ies)|victims?|"
    r"massacres?|terrorist\s+attacks?|"
    r"mass\s+killings?|массов\w*\s+(?:убийств\w*|расстрел\w*)|масов\w*\s+(?:вбивств\w*|розстріл\w*)|"
    r"протест\w*|революц\w*|восстан\w*|повстан\w*|переворот\w*|"
    r"митинг\w*|мітинг\w*|трагед\w*|жертв\w*|теракт\w*|"
    r"anti[- ]government\s+\w+|антиуряд\w*|антиправительств\w*"
)
_REAL_WORLD = _terms(
    r"real[- ]world|real\s+life|historical|"
    r"ukraine|russia|israel|gaza|kyiv|kiev|moscow|"
    r"україн\w*|украин\w*|росси\w*|росі\w*|ізраїл\w*|израил\w*|"
    r"реальн\w*|історич\w*|историч\w*"
)
_GAME_OR_FICTION = r"(?:minecraft|майнкрафт\w*|cs[- ]?2|counter[- ]strike|контр[- ]страйк|(?:a\s+)?(?:fictional|fantasy)\s+(?:game|world|story)|вигадан\w*\s+(?:гр\w*|світ\w*|істор\w*)|вымышлен\w*\s+(?:игр\w*|мир\w*|истори\w*))"
_FICTION_LINK = re.compile(
    r"\b(?:in|inside|of|from|в|у|из|з)\s+" + _GAME_OR_FICTION + r"\b", re.IGNORECASE,
)
_FICTION_PREFIX = re.compile(
    r"\b(?:" + _GAME_OR_FICTION + r"\s*|(?:fictional|вигадан\w*|вымышлен\w*)\s+(?:\w+\s+){0,2})$",
    re.IGNORECASE,
)
_EXPLICIT_FICTION = re.compile(
    r"\b(?:fictional|fantasy|вигадан\w*|вымышлен\w*)\b", re.IGNORECASE,
)
_GAME_ROLES = _terms(r"terrorists?|террорист\w*|терорист\w*")
_FRACTION_MATH = re.compile(
    r"(?:(?:calculate|compute|evaluate|обчисли|вычисли)\s+\d+/\d+|"
    r"(?:convert|what\s+is)\s+\d+/\d+\s+(?:to|as)\s+(?:a\s+)?(?:decimal|fraction)|"
    r"\d+/\d+\s*=\s*\d+(?:[.,]\d+)?)", re.IGNORECASE,
)
_BENIGN_FIGURES = re.compile(
    r"\b(?:a\s+)?revolution\s+in\s+(?:software|technology|gaming)|"
    r"\b(?:software|technological|industrial)\s+revolution\b|"
    r"\bbattle\s+of\s+wits\b|\bwar\s+on\s+(?:bugs|lag)\b|\bcoup\s+de\s+gr[aâ]ce\b|"
    r"\bреволюц\w*\s+(?:в|у)\s+(?:софт\w*|програм\w*|технолог\w*)|"
    r"\bв[іо]йн\w*\s+(?:с|з)\s+(?:баг\w*|лаг\w*)|"
    r"\b(?:my|our|the)\s+(?:failed\s+)?(?:test\s+run|missed\s+shot|game)\s+was\s+(?:a\s+)?tragedy|"
    r"\brevolutions?\s+per\s+minute\b|\b(?:i|we)\s+protest\s+(?:this|the)\s+(?:score|result)\b",
    re.IGNORECASE,
)
_CLAUSES = re.compile(r"[.!?;\n]+|\b(?:but|also|however|then|но|але|однако|також|затем|потім)\b", re.IGNORECASE)
_NEGATED_ACTION = re.compile(
    r"\b(?:do\s+not|don't|never|not|не|ніколи\s+не|никогда\s+не)\s+"
    r"(?:mock\w*|roast\w*|worthless|inferior|useless|"
    r"(?:kill|hurt|cut|harm)\s+(?:yourself|myself)|"
    r"share|publish|leak|post|"
    r"уни[жз]\w*|высме\w*|прини[жз]\w*|висмі\w*|глуз\w*)\b", re.IGNORECASE,
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("’", "'")
    return re.sub(r"[^\S\n]+", " ", re.sub(r"[\u200b-\u200f\ufeff]", "", text)).strip()


class PolicyDecision(Enum):
    """Decision made by the AI request policy."""
    ALLOW = "ALLOW"
    IGNORE = "IGNORE"


class AIRequestPolicy:
    """Policy for evaluating whether an AI request should be allowed or ignored."""

    def __init__(self) -> None:
        # Reveal / Prompt injection / Credentials / System info patterns (EN, RU, UK)
        self._reveal_patterns: List[Pattern] = [
            # English
            re.compile(
                r"\b(system\s+prompt|hidden\s+instructions?|developer\s+mode|jailbreak|dan\s+mode)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(reveal|show|tell|give|display|print|leak|share)\b.*\b(system\s+prompt|instructions?|code|secrets?|credentials?|api\s*key|password|token|config|internal\s+config)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(ignore|forget|disregard|override|bypass)\b.*\b(previous|rules|instructions?|constraints?|restrictions?|guidelines?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(what\s+(is|are)\s+your\s+(system\s+prompt|instructions?|rules|secrets?|api\s*key|token|password|config))\b",
                re.IGNORECASE,
            ),
            re.compile(r"\b(api\s*key|access\s*token|password|secret\s*key)\b", re.IGNORECASE),
            # Russian
            re.compile(
                r"(системн(ый|ого|ому|ым|ом|ая|ой|ую|ое|ые|ых|ыми)\s+промпт)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(системн(ые|ых|ым|ыми|ую|ая|ое)\s+инструкци[ияйю])",
                re.IGNORECASE,
            ),
            re.compile(
                r"(скрыт(ые|ых|ым|ыми|ую|ая|ое)\s+инструкци[ияйю])",
                re.IGNORECASE,
            ),
            re.compile(r"(режим\s+разработчика|джейлбрейк)", re.IGNORECASE),
            re.compile(
                r"(покажи|раскрой|скажи|дай|выдай|назови|напиши)\b.*\b(промпт|код|инструкци[июя]|секрет[ыа]?|парол[ьяеи]|токен[ыа]?|ключ[иа]?|api[- ]?key|конфиг|настройк[иу])",
                re.IGNORECASE,
            ),
            re.compile(
                r"(игнорируй|забудь|отмени|сбрось)\b.*\b(предыдущ[а-я]*|правил[а-я]*|инструкци[а-я]*|ограничени[а-я]*)",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"(системн(ий|ого|ому|им|а|ої|у|е|і|их|ими)\s+промпт)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(системн(і|их|им|ими|у|а|е)\s+інструкці[їяйю])",
                re.IGNORECASE,
            ),
            re.compile(
                r"(приховані\s+інструкці[їяйю])",
                re.IGNORECASE,
            ),
            re.compile(r"(режим\s+розробника)", re.IGNORECASE),
            re.compile(
                r"(покажи|розкрий|скажи|дай|видай|назви|напиши)\b.*\b(промпт|код|інструкці[їюя]|секрет[иа]?|парол[іяе]|токен[иа]?|ключ[іа]?|api[- ]?key|конфіг|налаштуванн[яі])",
                re.IGNORECASE,
            ),
            re.compile(
                r"(ігноруй|забудь|скасуй|скинь)\b.*\b(попередн[а-я]*|правил[а-я]*|інструкці[а-я]*|обмеженн[а-я]*)",
                re.IGNORECASE,
            ),
        ]

        # Operational requests involving controlled or clearly illegal substances.
        self._controlled_substance_patterns: List[Pattern] = [
            re.compile(
                r"\b(?:how\s+(?:to|do\s+i)\s+|instructions?\s+for\s+|recipe\s+for\s+|"
                r"(?:what\s+are|list)\s+(?:the\s+)?(?:ingredients?|proportions?|steps?)\s+for\s+)"
                r"(?:making|preparing|synthesizing|manufacturing|producing|extracting|formulating)?\s*"
                r"(?:cocaine|methamphetamine|meth|heroin|fentanyl|lsd|mdma|ecstasy|crack|illegal\s+drugs?|controlled\s+substances?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\bhow\s+to\s+(?:make|prepare|synthesize|manufacture|produce|extract|formulate|cook)\b"
                r".{0,100}\b(?:cocaine|methamphetamine|meth|heroin|fentanyl|lsd|mdma|ecstasy|crack|"
                r"illegal\s+drugs?|controlled\s+substances?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:cocaine|methamphetamine|meth|heroin|fentanyl|lsd|mdma|ecstasy|crack|"
                r"illegal\s+drugs?|controlled\s+substances?)\b.{0,100}\b"
                r"(?:recipe|ingredients?|proportions?|ratios?|dosage|steps?|instructions?|"
                r"make|prepare|synthesize|manufacture|produce|extract|formulate|cook)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:where|how)\b.{0,60}\b(?:buy|obtain|get|acquire|purchase)\b.{0,60}\b"
                r"(?:cocaine|methamphetamine|meth|heroin|fentanyl|lsd|mdma|ecstasy|crack|"
                r"illegal\s+drugs?|controlled\s+substances?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:как\s+(?:приготовить|синтезировать|изготовить|произвести|получить|"
                r"добыть|достать|купить|сделать|экстрагировать|выделить|составить)|"
                r"из\s+чего\s+(?:делают|готовят|получают|синтезируют)|"
                r"рецепт\s+(?:для|на)|(?:ингредиенты|пропорции|дозировка|дозы|этапы|шаги|"
                r"инструкция)\s+(?:для|на|приготовления|изготовления)?)\b.{0,100}\b"
                r"(?:кокаин|метамфетамин|мет|героин|фентанил|лсд|мдма|экстази|крэк|наркотик[а-яё]*|"
                r"запрещенн(?:ые|ых)\s+веществ[а-яё]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:кокаин|метамфетамин|мет|героин|фентанил|лсд|мдма|экстази|крэк|наркотик[а-яё]*|"
                r"запрещенн(?:ые|ых)\s+веществ[а-яё]*)\b.{0,100}\b"
                r"(?:рецепт|ингредиент[а-яё]*|пропорци[а-яё]*|дозировк[а-яё]*|доз[а-яё]*|"
                r"этап[а-яё]*|шаг[а-яё]*|инструкци[а-яё]*|приготовить|синтезировать|изготовить|"
                r"произвести|получить|экстрагировать|выделить|купить|достать)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:як\s+(?:приготувати|синтезувати|виготовити|виробити|отримати|добути|"
                r"дістати|купити|зробити|екстрагувати|виділити)|з\s+чого\s+(?:роблять|готують|"
                r"отримують|синтезують)|рецепт\s+(?:для|на)|(?:інгредієнти|пропорції|дозування|"
                r"дози|етапи|кроки|інструкція)\s+(?:для|на|приготування|виготовлення)?)\b.{0,100}\b"
                r"(?:кокаїн|метамфетамін|мет|героїн|фентаніл|лсд|мдма|екстазі|крек|наркотик[а-яіїєґ]*|"
                r"заборонен(?:і|их)\s+речовин[а-яіїєґ]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:який\s+рецепт|як\s+(?:приготувати|синтезувати|виготовити|виробити|отримати|"
                r"добути|дістати|купити|зробити|екстрагувати|виділити))\b.{0,100}\b"
                r"(?:кокаїн[а-яіїєґ]*|метамфетамін[а-яіїєґ]*|мет|героїн[а-яіїєґ]*|фентаніл[а-яіїєґ]*|"
                r"лсд|lsd|мдма|mdma|екстазі[а-яіїєґ]*|крек|наркотик[а-яіїєґ]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:какой\s+рецепт|как\s+(?:приготовить|синтезировать|изготовить|произвести|"
                r"получить|добыть|достать|купить|сделать|экстрагировать|выделить))\b.{0,100}\b"
                r"(?:кокаин[а-яё]*|метамфетамин[а-яё]*|мет|героин[а-яё]*|фентанил[а-яё]*|"
                r"лсд|lsd|мдма|mdma|экстази[а-яё]*|крэк|наркотик[а-яё]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:кокаїн|метамфетамін|мет|героїн|фентаніл|лсд|мдма|екстазі|крек|наркотик[а-яіїєґ]*|"
                r"заборонен(?:і|их)\s+речовин[а-яіїєґ]*)\b.{0,100}\b"
                r"(?:рецепт|інгредієнт[а-яіїєґ]*|пропорці[а-яіїєґ]*|дозуван[а-яіїєґ]*|доз[а-яіїєґ]*|"
                r"етап[а-яіїєґ]*|крок[а-яіїєґ]*|інструкці[а-яіїєґ]*|приготувати|синтезувати|виготовити|"
                r"виробити|отримати|екстрагувати|виділити|купити|дістати)\b",
                re.IGNORECASE,
            ),
        ]

        # Global hard block for recipe and cooking-instruction requests.
        self._recipe_request_patterns: List[Pattern] = [
            re.compile(
                r"\b(?:recipes?|how\s+to\s+prepare|"
                r"how\s+to\s+make(?!\s+(?:a\s+)?(?:website|web\s+site|screenshot|"
                r"minecraft\s+mod|program|app|application|software))|cooking\s+instructions?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?<![а-я])(?:рецепт[а-я]*|как\s+приготовить|"
                r"как\s+сделать(?!\s+(?:сайт|скриншот|программ\w*|приложени\w*|"
                r"майнкрафт\s+мод|мод\s+майнкрафт)))"
                r"(?![а-я])",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?<![а-я])(?:рецепт[а-я]*|як\s+приготувати|"
                r"як\s+зробити(?!\s+(?:сайт|скриншот|програм\w*|додаток\w*|"
                r"майнкрафт\s+мод|мод\s+майнкрафт)))"
                r"(?![а-я])",
                re.IGNORECASE,
            ),
        ]

        # Narrow anchors for the specified sexual/fetish term and obvious evasions.
        self._sexual_fetish_anchor_patterns: List[Pattern] = [
            re.compile(
                r"(?<![A-Za-z])(?:cuckold|cook[\s_-]*old|qcold|kucold|kukkold)"
                r"[a-z]*(?![A-Za-z])",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?<![А-Яа-яЁёІіЇїЄєҐґ])кук[\s_-]*олд[а-я]*"
                r"(?![А-Яа-яЁёІіЇїЄєҐґ])",
                re.IGNORECASE,
            ),
        ]

        # Explicit sexual / fetish request patterns (contextual, not anatomy-only).
        self._sexual_fetish_patterns: List[Pattern] = [
            re.compile(
                r"(?:как\s+называют|как\s+называется|что\s+это\s+за|какой\s+фетиш\s+у)"
                r".{0,160}(?:секс\w*|трах\w*|порнограф\w*|фетиш\w*|куколд\w*)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:як\s+називають|як\s+називається|що\s+це\s+за|який\s+фетиш\s+у)"
                r".{0,160}(?:секс\w*|трах\w*|порнограф\w*|фетиш\w*|куколд\w*)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:what\s+do\s+you\s+call|what\s+is\s+it\s+called\s+when|"
                r"what\s+fetish\s+does)"
                r".{0,160}(?:sex\w*|fuck\w*|porn\w*|fetish\w*|cuckold\w*)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:як\s+(?:займатися|робити)\s+сексом|як\s+займатися\s+сексом|"
                r"как\s+(?:заниматься|делать)\s+сексом|"
                r"(?:sexual|sex|еротичн\w*|сексуальн\w*)\s+"
                r"(?:acts?|techniques?|practices?|positions?|практик\w*|технік\w*|поз\w*))",
                re.IGNORECASE,
            ),
        ]

        # Ideological / Nazi / Fascist / Extremist / War Crimes patterns (EN, RU, UK)
        self._ideology_patterns: List[Pattern] = [
            # English
            re.compile(
                r"\b(nazi|nazis|nazism|neo[- ]?nazi(s)?|fascis[tm](s)?|hitler|stalin|mussolini|goebbels|swastika|third\s+reich|holocaust|genocide(s)?|concentration\s+camps?|war\s+crimes?|crimes?\s+against\s+humanity|extremis[tm](s)?|terroris[tm](s)?|white\s+supremac(y|ist|ists)?|ku\s+klux\s+klan|kkk|antisemit(e|ic|ism)?)\b",
                re.IGNORECASE,
            ),
            # Russian
            re.compile(
                r"\b(наци(зм|ст|сты|стов|стам|стами|стах|стск[а-яёіїєґ]+)?|неонаци(зм|ст|сты|стов)?|фаши(зм|ст|сты|стов|стск[а-яёіїєґ]+)?|гитлер[а-яёіїєґ]*|сталин[а-яёіїєґ]*|муссолини|геббельс[а-яёіїєґ]*|свастик[а-яёіїєґ]*|трет(ий|ьего|ьем)\s+рейх[а-яёіїєґ]*|холокост[а-яёіїєґ]*|геноцид[а-яёіїєґ]*|концлагер[а-яёіїєґ]*|военн[ыех]+\s+преступлени[а-яёіїєґ]*|экстреми(зм|ст|сты|стов)?|террори(зм|ст|сты|стов|стическ[а-яёіїєґ]+)?|антисемити(зм|ст|сты|стов)?)\b",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"\b(наци(зм|ст|сти|стів|стам|стами|стах|стськ[а-яёіїєґ]+)?|неонаци(зм|ст|сти|стів)?|фаши(зм|ст|сти|стів|стськ[а-яёіїєґ]+)?|гітлер[а-яёіїєґ]*|сталін[а-яёіїєґ]*|муссоліні|геббельс[а-яёіїєґ]*|свастик[а-яёіїєґ]*|трет(ій|ього|ьому)\s+рейх[а-яёіїєґ]*|голокост[а-яёіїєґ]*|геноцид[а-яёіїєґ]*|концтабір|концтабор[а-яёіїєґ]*|воєнн[іих]+\s+злочин[а-яёіїєґ]*|екстремі(зм|ст|сти|стів)?|терори(зм|ст|сти|стів|стичн[а-яёіїєґ]+)?|антисеміти(зм|ст|сти|стів)?)\b",
                re.IGNORECASE,
            ),
        ]

        # Politics / Leaders / Elections / Government / Parties patterns (EN, RU, UK)
        self._political_patterns: List[Pattern] = [
            # English
            re.compile(
                r"\b(polit(ic|ician|ics|ical)|government|elections?|congress|senat(e|or|ors)?|parliament|presidents?|prime\s+ministers?|chancellors?|dictators?|monarchs?|republicans?|democrats?|communism|socialism|liberalism|conservatism|geopolitics?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(putin|biden|trump|zelensky|zelenskiy|obama|macron|scholz|lukashenko|xi\s+jinping|poroshenko)\b",
                re.IGNORECASE,
            ),
            # Russian
            re.compile(
                r"\b(политик[а-яёіїєґ]*|политическ[а-яёіїєґ]+|правительств[а-яёіїєґ]*|выбор(?:ы|ов|ам|ах|ами)|голосовани[а-яёіїєґ]*|депутат[а-яёіїєґ]*|кандидат[а-яёіїєґ]*|парламент[а-яёіїєґ]*|конгресс[а-яёіїєґ]*|сенат[а-яёіїєґ]*|госдум[а-яёіїєґ]*|президент[а-яёіїєґ]*|премьер[- ]министр[а-яёіїєґ]*|канцлер[а-яёіїєґ]*|диктатор[а-яёіїєґ]*|монарх[а-яёіїєґ]*|политпарти[а-яёіїєґ]*|оппозици[а-яёіїєґ]*|министерств[а-яёіїєґ]*|геополитик[а-яёіїєґ]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(путин[а-яёіїєґ]*|байден[а-яёіїєґ]*|трамп[а-яёіїєґ]*|зеленск(ий|ого|ому|им|ом)|обам[а-яёіїєґ]*|макрон[а-яёіїєґ]*|шольц[а-яёіїєґ]*|лукашенк[а-яёіїєґ]*|си\s+цзиньпин[а-яёіїєґ]*|порошенк[а-яёіїєґ]*)\b",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"\b(політик[а-яёіїєґ]*|політичн[а-яёіїєґ]+|уряд[а-яёіїєґ]*|вибор(?:и|ів|ам|ах|ами)|голосуванн[а-яёіїєґ]*|депутат[а-яёіїєґ]*|кандидат[а-яёіїєґ]*|парламент[а-яёіїєґ]*|сенат[а-яёіїєґ]*|верховн[а-яёіїєґ]+\s+рад[а-яёіїєґ]*|держдум[а-яёіїєґ]*|президент[а-яёіїєґ]*|прем'єр[- ]міністр[а-яёіїєґ]*|диктатор[а-яёіїєґ]*|монарх[а-яёіїєґ]*|політпарті[а-яёіїєґ]*|опозиці[а-яёіїєґ]*|міністерств[а-яёіїєґ]*|геополітик[а-яёіїєґ]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(путін[а-яёіїєґ]*|байден[а-яёіїєґ]*|трамп[а-яёіїєґ]*|зеленськ(ий|ого|ому|им|ому)|обам[а-яёіїєґ]*|макрон[а-яёіїєґ]*|шольц[а-яёіїєґ]*|лукашенк[а-яёіїєґ]*|сі\s+цзіньпін[а-яёіїєґ]*|порошенк[а-яёіїєґ]*)\b",
                re.IGNORECASE,
            ),
        ]

        # War / Military / Armed conflict patterns (EN, RU, UK)
        self._conflict_patterns: List[Pattern] = [
            # English
            re.compile(
                r"\b(war|wars|warfare|conflict|conflicts|invasion|invasions|battle|battles|combat|army|armies|navy|air\s+force|military|soldiers?|troops?|armed\s+forces|bomb|bombs|bombing|missile|missiles|artillery|casualt(y|ies)|trench(es)?|ceasefire|special\s+military\s+operation|frontline)\b",
                re.IGNORECASE,
            ),
            # Russian
            re.compile(
                r"\b(войн[а-яёіїєґ]*|военн[а-яёіїєґ]+|боевы[ехм]+\s+действи[а-яёіїєґ]*|сво|спецопераци[а-яёіїєґ]*|вторжени[а-яёіїєґ]*|арми[а-яёіїєґ]*|солдат[а-яёіїєґ]*|войск[а-яёіїєґ]*|фронт[а-яёіїєґ]*|окоп[а-яёіїєґ]*|обстрел[а-яёіїєґ]*|бомбардировк[а-яёіїєґ]*|ракетирован[а-яёіїєґ]*|артиллери[а-яёіїєґ]*|мобилизаци[а-яёіїєґ]*|конфликт[а-яёіїєґ]*|боевик[а-яёіїєґ]*|всу|вс\s+рф)\b",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"\b(війн[а-яёіїєґ]*|воєнн[а-яёіїєґ]+|військов[а-яёіїєґ]+|бойов[іиа-я]+\s+ді[а-яёіїєґ]*|вторгненн[а-яёіїєґ]*|армі[а-яёіїєґ]*|солдат[а-яёіїєґ]*|військ[а-яёіїєґ]*|фронт[а-яёіїєґ]*|окоп[а-яёіїєґ]*|обстріл[а-яёіїєґ]*|бомбардуванн[а-яёіїєґ]*|артилері[а-яёіїєґ]*|мобілізаці[а-яёіїєґ]*|зсу)\b",
                re.IGNORECASE,
            ),
        ]

        # Geopolitical / Territorial / Sovereignty / Disputed territory patterns (EN, RU, UK)
        self._territorial_patterns: List[Pattern] = [
            # General territorial sovereignty / dispute / annexation / occupation concepts
            # English
            re.compile(
                r"\b(annexation|annexed|annexing|territorial\s+(status|disputes?|claims?|integrity|belonging)|disputed\s+(territor(y|ies)|borders?|land|region|islands?)|border\s+disputes?|occupied\s+(territor(y|ies)|region|lands?)|sovereignty\s+over|unrecognized\s+(state|republic)s?|separatis[tm]s?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(whose\s+is|who\s+(owns|controls|possesses|rules)|who\s+does\s+\w+\s+belong\s+to|does\s+\w+\s+belong\s+to|under\s+whose\s+control|sovereignty\s+of)\b.*\b(crimea|donbas|donbass|taiwan|kosovo|kuril|kurils|karabakh|artsakh|abkhazia|ossetia|transnistria|sevastopol|palestine|gaza|golan|gibraltar|falklands?|kashmir|tibet|donetsk|luhansk|zaporizhzhia|kherson|bakhmut)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(crimea|donbas|donbass|taiwan|kosovo|kuril|kurils|karabakh|artsakh|abkhazia|ossetia|transnistria|sevastopol|palestine|gaza|golan|gibraltar|falklands?|kashmir|tibet|donetsk|luhansk|zaporizhzhia|kherson|bakhmut)\b.*\b(whose|who\s+owns|who\s+controls|belongs\s+to|part\s+of|country|independent|state|russian|ukrainian|chinese|serbian)\b",
                re.IGNORECASE,
            ),
            # Russian
            re.compile(
                r"\b(аннекси[а-яёіїєґ]*|оккупаци[а-яёіїєґ]*|деоккупаци[а-яёіїєґ]*|территориальн[а-яёіїєґ]+\s+(статус|спор[а-яёіїєґ]*|претензи[а-яёіїєґ]*|принадлежност[а-яёіїєґ]*|целостност[а-яёіїєґ]*)|спорн[а-яёіїєґ]+\s+территори[а-яёіїєґ]*|непризнанн[а-яёіїєґ]+\s+(государств[а-яёіїєґ]*|республик[а-яёіїєґ]*)|сепарати(зм|ст|сты)[а-яёіїєґ]*|суверенитет[а-яёіїєґ]*\s+над|днр|лнр)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(че[йяеёи]|кому\s+принадлеж[а-яёіїєґ]+|кто\s+(контролирует|владеет|оккупировал|аннексировал)|под\s+чьим\s+(контролем|управлением)|статус)\b.*\b(крым[а-яёіїєґ]*|донбасс[а-яёіїєґ]*|тайван[а-яёіїєґ]*|косов[а-яёіїєґ]*|курил[а-яёіїєґ]*|карабах[а-яёіїєґ]*|арцах[а-яёіїєґ]*|абхази[а-яёіїєґ]*|осети[а-яёіїєґ]*|приднестровь[а-яёіїєґ]*|севастопол[а-яёіїєґ]*|палестин[а-яёіїєґ]*|газ[а-яёіїєґ]*|голан[а-яёіїєґ]*|гибралтар[а-яёіїєґ]*|фолкленд[а-яёіїєґ]*|кашмир[а-яёіїєґ]*|тибет[а-яёіїєґ]*|донецк[а-яёіїєґ]*|луганск[а-яёіїєґ]*|запорожь[а-яёіїєґ]*|херсон[а-яёіїєґ]*|бахмут[а-яёіїєґ]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(крым[а-яёіїєґ]*|донбасс[а-яёіїєґ]*|тайван[а-яёіїєґ]*|косов[а-яёіїєґ]*|курил[а-яёіїєґ]*|карабах[а-яёіїєґ]*|арцах[а-яёіїєґ]*|абхази[а-яёіїєґ]*|осети[а-яёіїєґ]*|приднестровь[а-яёіїєґ]*|севастопол[а-яёіїєґ]*|палестин[а-яёіїєґ]*|донецк[а-яёіїєґ]*|луганск[а-яёіїєґ]*|запорожь[а-яёіїєґ]*|херсон[а-яёіїєґ]*|бахмут[а-яёіїєґ]*)\b.*\b(наш|ваш|че[йяеёи]|кому\s+принадлеж[а-яёіїєґ]+|кто\s+(контролирует|владеет)|российск[а-яёіїєґ]+|украинск[а-яёіїєґ]+|китайск[а-яёіїєґ]+|сербск[а-яёіїєґ]+|государство|независим[а-яёіїєґ]+|росси[а-яёіїєґ]+|украин[а-яёіїєґ]+|кита[а-яёіїєґ]+|серби[а-яёіїєґ]+)\b",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"\b(анексі[а-яёіїєґ]*|окупаці[а-яёіїєґ]*|деокупаці[а-яёіїєґ]*|територіальн[а-яёіїєґ]+\s+(статус|спір[а-яёіїєґ]*|суперечк[а-яёіїєґ]*|претензі[а-яёіїєґ]*|приналежніст[а-яёіїєґ]*|цілісніст[а-яёіїєґ]*)|спірн[а-яёіїєґ]+\s+територі[а-яёіїєґ]*|невизнан[а-яёіїєґ]+\s+(держав[а-яёіїєґ]*|республік[а-яёіїєґ]*)|сепарати(зм|ст|сти)[а-яёіїєґ]*|суверенітет[а-яёіїєґ]*\s+над)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(чи[йяєї]|кому\s+належит[ьь]?|хто\s+(контролює|володіє|окупував|анексував)|під\s+чиїм\s+(контролем|управлінням)|статус)\b.*\b(крим[а-яёіїєґ]*|донбас[а-яёіїєґ]*|тайван[а-яёіїєґ]*|косов[а-яёіїєґ]*|курил[а-яёіїєґ]*|карабах[а-яёіїєґ]*|арцах[а-яёіїєґ]*|абхазі[а-яёіїєґ]*|осеті[а-яёіїєґ]*|придністров[а-яёіїєґ]*|севастопол[а-яёіїєґ]*|палестин[а-яёіїєґ]*|газ[а-яёіїєґ]*|голан[а-яёіїєґ]*|гібралтар[а-яёіїєґ]*|фолкленд[а-яёіїєґ]*|кашмір[а-яёіїєґ]*|тибет[а-яёіїєґ]*|донецьк[а-яёіїєґ]*|луганськ[а-яёіїєґ]*|запоріжж[а-яёіїєґ]*|херсон[а-яёіїєґ]*|бахмут[а-яёіїєґ]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(крим[а-яёіїєґ]*|донбас[а-яёіїєґ]*|тайван[а-яёіїєґ]*|косов[а-яёіїєґ]*|курил[а-яёіїєґ]*|карабах[а-яёіїєґ]*|арцах[а-яёіїєґ]*|абхазі[а-яёіїєґ]*|осеті[а-яёіїєґ]*|придністров[а-яёіїєґ]*|севастопол[а-яёіїєґ]*|палестин[а-яёіїєґ]*|донецьк[а-яёіїєґ]*|луганськ[а-яёіїєґ]*|запоріжж[а-яёіїєґ]*|херсон[а-яёіїєґ]*|бахмут[а-яёіїєґ]*)\b.*\b(наш|ваш|чи[йяєї]|кому\s+належит[ьь]?|хто\s+(контролює|володіє)|російськ[а-яёіїєґ]+|українськ[а-яёіїєґ]+|китайськ[а-яёіїєґ]+|сербськ[а-яёіїєґ]+|держава|незалежн[а-яёіїєґ]+|росі[а-яёіїєґ]+|україн[а-яёіїєґ]+|кита[а-яёіїєґ]+|сербі[а-яёіїєґ]+)\b",
                re.IGNORECASE,
            ),
        ]

                # Sensitive real-world incidents / controversial public figures (EN, RU, UK)
        self._sensitive_real_world_patterns: List[Pattern] = [
            # English
            re.compile(
                r"\b("
                r"what\s+happened|what\s+occurred|what\s+took\s+place|"
                r"who\s+is|who\s+was|tell\s+me\s+about|"
                r"history\s+of|background\s+of|"
                r"why\s+did\s+.*\s+happen"
                r")\b.*\b("
                r"massacre|protest|riot|repression|crackdown|"
                r"terrorist\s+attack|terror\s+attack|shooting|"
                r"mass\s+killing|political\s+violence|"
                r"atrocity|uprising|coup|purge|"
                r"tiananmen|tiananmen\s+square|"
                r"genocide|war\s+crime"
                r")\b",
                re.IGNORECASE,
            ),

            # Russian
            re.compile(
                r"\b("
                r"что\s+случил[оа]|что\s+произошл[оа]|что\s+происходил[оа]|"
                r"что\s+там\s+был[оа]|что\s+произошло|"
                r"расскажи\s+о|расскажи\s+про|"
                r"история|событи[ея]|"
                r"кто\s+такой|кто\s+такая|кто\s+был|кто\s+была"
                r")\b.*\b("
                r"массов[а-яё]*\s+(убийств[а-яё]*|расстрел[а-яё]*|репресси[а-яё]*)|"
                r"протест[а-яё]*|митинг[а-яё]*|бунт[а-яё]*|восстани[а-яё]*|"
                r"разгон[а-яё]*|репресси[а-яё]*|репрессирован[а-яё]*|"
                r"теракт[а-яё]*|террористическ[а-яё]*\s+акт[а-яё]*|"
                r"стрельб[а-яё]*|убийств[а-яё]*|"
                r"резн[а-яё]*|переворот[а-яё]*|чистк[а-яё]*|"
                r"площад[а-яё]*\s+тяньаньмэнь|"
                r"тяньаньмэнь|"
                r"геноцид[а-яё]*|военн[а-яё]*\s+преступлени[а-яё]*"
                r")\b",
                re.IGNORECASE,
            ),

            # Ukrainian
            re.compile(
                r"\b("
                r"що\s+сталося|що\s+відбулося|що\s+відбувалося|"
                r"що\s+там\s+було|"
                r"розкажи\s+про|"
                r"історія|поді[ія]|"
                r"хто\s+такий|хто\s+така|хто\s+був|хто\s+була"
                r")\b.*\b("
                r"масов[а-яёіїєґ]*\s+(вбивств[а-яёіїєґ]*|розстріл[а-яёіїєґ]*)|"
                r"протест[а-яёіїєґ]*|мітинг[а-яёіїєґ]*|бунт[а-яёіїєґ]*|"
                r"повстанн[а-яёіїєґ]*|розгон[а-яёіїєґ]*|"
                r"репресі[а-яёіїєґ]*|теракт[а-яёіїєґ]*|"
                r"стрілянин[а-яёіїєґ]*|вбивств[а-яёіїєґ]*|"
                r"різн[а-яёіїєґ]*|переворот[а-яёіїєґ]*|чистк[а-яёіїєґ]*|"
                r"площа\s+тяньаньмень|тяньаньмень|"
                r"геноцид[а-яёіїєґ]*|воєнн[а-яёіїєґ]*\s+злочин[а-яёіїєґ]*"
                r")\b",
                re.IGNORECASE,
            ),
        ]

        # Twitch banned words / moderation filter / prohibited content patterns (EN, RU, UK)
        self._twitch_moderation_patterns: List[Pattern] = [
            # English
            re.compile(
                r"\b(twitch|stream\s+chat)\b.*\b(banned|prohibited|forbidden|blacklisted|blocked|disallowed|censored|restricted)\s+(words?|terms?|phrases?|vocabulary|list|content)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(banned|prohibited|forbidden|blacklisted|blocked|disallowed|censored|restricted)\s+(words?|terms?|phrases?|vocabulary|list|content)\b.*\b(on|in|by|for)\s+(twitch|stream\s+chat)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(what|which|list|tell|show|give|name)\b.*\b(words?|terms?|phrases?|things?|content)\b.*\b(banned|ban|bans|prohibit|prohibits|prohibited|forbidden|blocked|censored|not\s+allowed|illegal)\b.*\b(twitch|stream\s+chat)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(what|which|list|tell|show|give|name)\b.*\b(words?|terms?|phrases?|things?|content)\b.*\b(twitch|stream\s+chat)\b.*\b(banned|ban|bans|prohibit|prohibits|prohibited|forbidden|blocked|censored|not\s+allowed|illegal)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(what|which)\b.*\b(can\'?t|cannot|can\s+not|must\s+not|not\s+allowed\s+to)\s+(say|write|type|post|send|stream|speak)\b.*\b(on|in|by)\s+(twitch|stream\s+chat)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(twitch|stream\s+chat)\b.*\b(prohibits?|bans?|blocks?|censors?|filters?)\b.*\b(words?|terms?|phrases?|content)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(twitch|stream\s+chat)\b.*\b(automod|auto[- ]?moderation|moderation\s+filter|moderation\s+rules?|blacklist|word\s+filter|filter\s+list)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(words?|terms?|phrases?)\b.*\b(trigger|get\s+you\s+banned|cause\s+a\s+ban|filtered|blocked)\b.*\b(twitch|stream\s+chat)\b",
                re.IGNORECASE,
            ),
            # Russian
            re.compile(
                r"\b(твич[а-я]*|твиче|twitch|стрим[а-я]*)\b.*\b(запрещенн[а-я]+|забаненн[а-я]+|неразрешенн[а-я]+|недопустим[а-я]+|заблокированн[а-я]+|нежелательн[а-я]+)\s+(слов[а-я]*|выражени[а-я]*|фраз[а-я]*|термин[а-я]*|список|списк[а-я]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(запрещенн[а-я]+|забаненн[а-я]+|неразрешенн[а-я]+|недопустим[а-я]+|заблокированн[а-я]+|нежелательн[а-я]+)\s+(слов[а-я]*|выражени[а-я]*|фраз[а-я]*|термин[а-я]*|список|списк[а-я]*)\b.*\b(твич[а-я]*|твиче|twitch|стрим[а-я]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(какие|каких|список|перечисли|назови|покажи|дай|напиши|скажи)\b.*\b(слов[а-я]*|выражени[а-я]*|фраз[а-я]*|термин[а-я]*)\b.*\b(запрещен[а-я]*|запрещает[а-я]*|банят|банит|забан[а-я]*|блокиру[а-я]*|нельзя)\b.*\b(твич[а-я]*|твиче|twitch)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(какие|каких|список|перечисли|назови|покажи|дай|напиши|скажи)\b.*\b(слов[а-я]*|выражени[а-я]*|фраз[а-я]*|термин[а-я]*)\b.*\b(твич[а-я]*|твиче|twitch)\b.*\b(запрещен[а-я]*|запрещает[а-я]*|банят|банит|забан[а-я]*|блокиру[а-я]*|нельзя)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(что|какие\s+слова|какие\s+фразы)\s+нельзя\s+(писать|говорить|произносить|использовать|отправлять|стримить)\b.*\b(твич[а-я]*|твиче|twitch)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(за\s+какие\s+слова|за\s+какие\s+фразы|за\s+что)\s+(банят|дают\s+бан|мутят|блокируют)\b.*\b(твич[а-я]*|твиче|twitch)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(твич[а-яё]*|твиче|twitch)\b.*\b(черный\s+список|черном\s+списке|блэклист[а-яё]*|автомод[а-яё]*|фильтр[а-яё]*\s+слов|модераци[а-яё]*\s+слов)\b",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"\b(твіч[а-яёіїєґ\']*|твічі|twitch|стрім[а-яёіїєґ\']*)\b.*\b(заборонен[а-я]+|забанен[а-я]+|недозволен[а-я]+|неприпустим[а-я]+|заблокован[а-я]+|небажан[а-я]+)\s+(сл(ов|ів)[а-я]*|вираз[а-я]*|фраз[а-я]*|термін[а-я]*|список|списк[а-я]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(заборонен[а-я]+|забанен[а-я]+|недозволен[а-я]+|неприпустим[а-я]+|заблокован[а-я]+|небажан[а-я]+)\s+(сл(ов|ів)[а-я]*|вираз[а-я]*|фраз[а-я]*|термін[а-я]*|список|списк[а-я]*)\b.*\b(твіч[а-яёіїєґ\']*|твічі|twitch|стрім[а-яёіїєґ\']*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(які|яких|список|перелічи|назви|покажи|дай|напиши|скажи)\b.*\b(сл(ов|ів)[а-я]*|вираз[а-я]*|фраз[а-я]*|термін[а-я]*)\b.*\b(заборон[а-я]*|забороня[а-я]*|банять|банить|забан[а-я]*|блоку[а-я]*|не\s+можна)\b.*\b(твіч[а-яёіїєґ\']*|твічі|twitch)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(які|яких|список|перелічи|назви|покажи|дай|напиши|скажи)\b.*\b(твіч[а-яёіїєґ\']*|твічі|twitch)\b.*\b(заборон[а-я]*|забороня[а-я]*|банять|банить|забан[а-я]*|блоку[а-я]*|не\s+можна)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(що|які\s+слова|які\s+фрази)\s+не\s+можна\s+(писати|говорити|вимовляти|використовувати|надсилати|стрімити)\b.*\b(твіч[а-яёіїєґ\']*|твічі|twitch)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(за\s+які\s+слова|за\s+які\s+фрази|за\s+що)\s+(банять|дають\s+бан|мутять|блокують)\b.*\b(твіч[а-яёіїєґ\']*|твічі|twitch)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(твіч[а-яёіїєґ\']*|твічі|twitch)\b.*\b(забороняє|банить|блокує|фільтрує)\b.*\b(сл(ов|ів)[а-я]*|фраз[а-я]*|вираз[а-я]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(твіч[а-яёіїєґ\']*|твічі|twitch)\b.*\b(чорний\s+список|чорному\s+списку|блеклист[а-я]*|автомод[а-я]*|фільтр[а-я]*\s+слів|модераці[а-я]*\s+слів)\b",
                re.IGNORECASE,
            ),
        ]

        # Derogatory / insulting / provocative names/nicknames for countries or nationalities (EN, RU, UK)
        self._derogatory_nation_patterns: List[Pattern] = [
            # English
            re.compile(
                r"\b(insulting|offensive|derogatory|mocking|provocative|demeaning|pejorative|toxic|humiliating|disrespectful)\s+(names?|nicknames?|titles?|aliases?|labels?|slurs?)\b.*\b(countries|country|nations?|nationalit(y|ies)|ethnic(ity|ities)|peoples?|states?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(names?|nicknames?|titles?|aliases?|labels?|slurs?)\b.*\b(for|of)\s+(countries|country|nations?|nationalit(y|ies)|ethnic(ity|ities)|peoples?|states?)\b.*\b(insulting|offensive|derogatory|mocking|provocative|demeaning|pejorative|toxic|humiliating|disrespectful)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(how\s+to\s+(insult|mock|offend|demean|ridicule)|slurs?\s+(for|against))\s+(countries|country|nations?|nationalit(y|ies)|ethnic(ity|ities)|peoples?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(countries|country|nations?|nationalit(y|ies)|ethnic(ity|ities)|peoples?)\b.*\b(slurs?|derogatory\s+names?|insulting\s+names?|offensive\s+nicknames?)\b",
                re.IGNORECASE,
            ),
            # Russian
            re.compile(
                r"\b(провокационн[а-яё]+|обидн[а-яё]+|оскорбительн[а-яё]+|унизительн[а-яё]+|насмешлив[а-яё]+|дразнящ[а-яё]+|ругательн[а-яё]+|токсичн[а-яё]+|уничижительн[а-яё]+|стыдн[а-яё]+)\s+(названи[а-яё]*|наименовани[а-яё]*|прозвищ[а-яё]*|кликух[а-яё]*|кличк[а-яё]*|имен[а-яё]*|обозначени[а-яё]*)\b.*\b(стран[а-яё]*|государств[а-яё]*|наци[а-яё]*|национальност[а-яё]*|народ[а-яё]*|этнос[а-яё]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(названи[а-яё]*|наименовани[а-яё]*|прозвищ[а-яё]*|кликух[а-яё]*|кличк[а-яё]*|имен[а-яё]*)\s+(стран[а-яё]*|государств[а-яё]*|наци[а-яё]*|национальност[а-яё]*|народ[а-яё]*|этнос[а-яё]*)\b.*\b(провокационн[а-яё]+|обидн[а-яё]+|оскорбительн[а-яё]+|унизительн[а-яё]+|насмешлив[а-яё]+|дразнящ[а-яё]+|ругательн[а-яё]+|токсичн[а-яё]+|уничижительн[а-яё]+)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(как\s+(оскорбить|обозвать|подразнить|унизить))\s+(стран[а-яё]*|государств[а-яё]*|наци[а-яё]*|национальност[а-яё]*|народ[а-яё]*)\b",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"\b(провокаційн[а-яёіїєґ\']+|образлив[а-яёіїєґ\']+|зневажлив[а-яёіїєґ\']+|принизлив[а-яёіїєґ\']+|глузлив[а-яёіїєґ\']+|лайлив[а-яёіїєґ\']+|токсичн[а-яёіїєґ\']+)\s+(назв[а-яёіїєґ\']*|найменуванн[а-яёіїєґ\']*|прізвиськ[а-яёіїєґ\']*|кличк[а-яёіїєґ\']*|імен[а-яёіїєґ\']*|позначенн[а-яёіїєґ\']*)\b.*\b(країн[а-яёіїєґ\']*|держав[а-яёіїєґ\']*|наці[а-яёіїєґ\']*|національност[а-яёіїєґ\']*|народ[а-яёіїєґ\']*|етнос[а-яёіїєґ\']*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(назв[а-яёіїєґ\']*|найменуванн[а-яёіїєґ\']*|прізвиськ[а-яёіїєґ\']*|кличк[а-яёіїєґ\']*|імен[а-яёіїєґ\']*)\s+(країн[а-яёіїєґ\']*|держав[а-яёіїєґ\']*|наці[а-яёіїєґ\']*|національност[а-яёіїєґ\']*|народ[а-яёіїєґ\']*|етнос[а-яёіїєґ\']*)\b.*\b(провокаційн[а-яёіїєґ\']+|образлив[а-яёіїєґ\']+|зневажлив[а-яёіїєґ\']+|принизлив[а-яёіїєґ\']+|глузлив[а-яёіїєґ\']+|лайлив[а-яёіїєґ\']+|токсичн[а-яёіїєґ\']+)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(як\s+(образити|обізвати|подражнити|принизити))\s+(країн[а-яёіїєґ\']*|держав[а-яёіїєґ\']*|наці[а-яёіїєґ\']*|національност[а-яёіїєґ\']*|народ[а-яёіїєґ\']*)\b",
                re.IGNORECASE,
            ),
        ]

    def contains_restricted_content(self, text: str) -> bool:
        """Shared contextual boundary for requests and full generated responses.

        Local checks catch concrete signals; protected model instructions cover
        semantics that cannot be reliably inferred from short keyword patterns.
        Fiction only qualifies nearby topic words, never personal abuse or named
        real events. No editable prompt participates in this decision.
        """
        normalized = _normalize(text)
        # A complete arithmetic expression is not a reference to a tragedy.
        if _FRACTION_MATH.fullmatch(normalized.rstrip(" .?!")):
            return False
        if _PUBLIC_EVENTS.search(normalized):
            return True
        # A game title cannot turn references to actual leaders into fiction.
        if any(pattern.search(normalized) for pattern in self._political_patterns[1::2]):
            return True
        world_patterns = (
            self._ideology_patterns + self._political_patterns
            + self._conflict_patterns + self._territorial_patterns
            + self._sensitive_real_world_patterns + [_EVENT_TOPICS]
        )
        for clause in _CLAUSES.split(normalized):
            actions = _NEGATED_ACTION.sub("", clause)
            if _MINORS.search(clause) and (
                _SEXUAL.search(clause) or _DEMEANING.search(actions)
                or (_JOKING.search(clause) and _SUFFERING.search(clause))
            ):
                return True
            if _PROTECTED_TRAITS.search(_BENIGN_TRAITS.sub("", clause)) and _DEMEANING.search(actions):
                return True
            if _SELF_HARM.search(actions):
                return True
            if _TARGETED_HARASSMENT.search(actions):
                return True
            if _ADDRESS_DISCLOSURE.search(clause) or (
                _PRIVATE_DATA.search(clause) and _DISCLOSURE.search(actions)
            ):
                return True
            world_clause = _BENIGN_FIGURES.sub("", clause)
            has_real_context = _REAL_WORLD.search(world_clause) is not None
            for pattern in world_patterns + [_HARM_OR_HARASSMENT]:
                for match in pattern.finditer(world_clause):
                    before = world_clause[max(0, match.start() - 80):match.start()]
                    after = world_clause[match.end():match.end() + 80]
                    fictional = (
                        _FICTION_LINK.search(before) or _FICTION_LINK.search(after)
                        or _FICTION_PREFIX.search(before)
                    )
                    if pattern in self._ideology_patterns and not _GAME_ROLES.fullmatch(match[0]):
                        fictional = fictional and _EXPLICIT_FICTION.search(before + after)
                    if has_real_context or not fictional:
                        return True
        return False

    def check(self, prompt: str) -> PolicyDecision:
        """
        Check if an AI request should be allowed or ignored.

        Args:
            prompt: The user's question

        Returns:
            PolicyDecision.ALLOW if the request is acceptable,
            PolicyDecision.IGNORE if it should be blocked
        """
        clean_prompt = _normalize(prompt)
        if not clean_prompt:
            return PolicyDecision.IGNORE

        if self.contains_restricted_content(clean_prompt):
            return PolicyDecision.IGNORE

        # Check the specified sexual/fetish term and obvious evasions.
        for pattern in self._sexual_fetish_anchor_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        # Recipe and cooking-instruction requests are ignored regardless of context.
        for pattern in self._recipe_request_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        # Check explicit sexual / fetish requests.
        for pattern in self._sexual_fetish_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        # Check reveal / prompt injection / credential patterns
        for pattern in self._reveal_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        # Check operational controlled-substance requests.
        for pattern in self._controlled_substance_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        # Check Twitch banned words / moderation filter patterns
        for pattern in self._twitch_moderation_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        # Check derogatory country / nationality name patterns
        for pattern in self._derogatory_nation_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        return PolicyDecision.ALLOW
