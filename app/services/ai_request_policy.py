"""AI request policy for determining if an !ask request should be processed."""

import re
from enum import Enum
from typing import List, Pattern


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
                r"(?<![а-яёіїєґ])(?:рецепт[а-яёіїєґ]*|как\s+приготовить|"
                r"как\s+сделать(?!\s+(?:сайт|скриншот|программ\w*|приложени\w*|"
                r"майнкрафт\s+мод|мод\s+майнкрафт)))"
                r"(?![а-яёіїєґ])",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?<![а-яёіїєґ])(?:рецепт[а-яёіїєґ]*|як\s+приготувати|"
                r"як\s+зробити(?!\s+(?:сайт|скриншот|програм\w*|додаток\w*|"
                r"майнкрафт\s+мод|мод\s+майнкрафт)))"
                r"(?![а-яёіїєґ])",
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
                r"(?<![А-Яа-яЁёІіЇїЄєҐґ])кук[\s_-]*олд[а-яёіїєґ]*"
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
                r"\b(наци(зм|ст|сты|стов|стам|стами|стах|стск[а-я]+)?|неонаци(зм|ст|сты|стов)?|фаши(зм|ст|сты|стов|стск[а-я]+)?|гитлер[а-я]*|сталин[а-я]*|муссолини|геббельс[а-я]*|свастик[а-я]*|трет(ий|ьего|ьем)\s+рейх[а-я]*|холокост[а-я]*|геноцид[а-я]*|концлагер[а-я]*|военн[ыех]+\s+преступлени[а-я]*|экстреми(зм|ст|сты|стов)?|террори(зм|ст|сты|стов|стическ[а-я]+)?|антисемити(зм|ст|сты|стов)?)\b",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"\b(наци(зм|ст|сти|стів|стам|стами|стах|стськ[а-я]+)?|неонаци(зм|ст|сти|стів)?|фаши(зм|ст|сти|стів|стськ[а-я]+)?|гітлер[а-я]*|сталін[а-я]*|муссоліні|геббельс[а-я]*|свастик[а-я]*|трет(ій|ього|ьому)\s+рейх[а-я]*|голокост[а-я]*|геноцид[а-я]*|концтабір|концтабор[а-я]*|воєнн[іих]+\s+злочин[а-я]*|екстремі(зм|ст|сти|стів)?|терори(зм|ст|сти|стів|стичн[а-я]+)?|антисеміти(зм|ст|сти|стів)?)\b",
                re.IGNORECASE,
            ),
        ]

        # Politics / Leaders / Elections / Government / Parties patterns (EN, RU, UK)
        self._political_patterns: List[Pattern] = [
            # English
            re.compile(
                r"\b(polit(ic|ician|ics|ical)|government|elections?|vote|voting|voters?|candidates?|congress|senat(e|or|ors)?|parliament|presidents?|prime\s+ministers?|chancellors?|dictators?|monarchs?|republicans?|democrats?|communism|socialism|liberalism|conservatism|geopolitics?)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(putin|biden|trump|zelensky|zelenskiy|obama|macron|scholz|lukashenko|xi\s+jinping|poroshenko)\b",
                re.IGNORECASE,
            ),
            # Russian
            re.compile(
                r"\b(политик[а-я]*|политическ[а-я]+|правительств[а-я]*|выбор[ыоа-я]*|голосовани[а-я]*|депутат[а-я]*|кандидат[а-я]*|парламент[а-я]*|конгресс[а-я]*|сенат[а-я]*|госдум[а-я]*|президент[а-я]*|премьер[- ]министр[а-я]*|канцлер[а-я]*|диктатор[а-я]*|монарх[а-я]*|политпарти[а-я]*|оппозици[а-я]*|министерств[а-я]*|геополитик[а-я]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(путин[а-я]*|байден[а-я]*|трамп[а-я]*|зеленск(ий|ого|ому|им|ом)|обам[а-я]*|макрон[а-я]*|шольц[а-я]*|лукашенк[а-я]*|си\s+цзиньпин[а-я]*|порошенк[а-я]*)\b",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"\b(політик[а-я]*|політичн[а-я]+|уряд[а-я]*|вибор[иіа-я]*|голосуванн[а-я]*|депутат[а-я]*|кандидат[а-я]*|парламент[а-я]*|сенат[а-я]*|верховн[а-я]+\s+рад[а-я]*|держдум[а-я]*|президент[а-я]*|прем'єр[- ]міністр[а-я]*|диктатор[а-я]*|монарх[а-я]*|політпарті[а-я]*|опозиці[а-я]*|міністерств[а-я]*|геополітик[а-я]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(путін[а-я]*|байден[а-я]*|трамп[а-я]*|зеленськ(ий|ого|ому|им|ому)|обам[а-я]*|макрон[а-я]*|шольц[а-я]*|лукашенк[а-я]*|сі\s+цзіньпін[а-я]*|порошенк[а-я]*)\b",
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
                r"\b(войн[а-я]*|военн[а-я]+|боевы[ехм]+\s+действи[а-я]*|сво|спецопераци[а-я]*|вторжени[а-я]*|арми[а-я]*|солдат[а-я]*|войск[а-я]*|фронт[а-я]*|окоп[а-я]*|обстрел[а-я]*|бомбардировк[а-я]*|ракетирован[а-я]*|артиллери[а-я]*|мобилизаци[а-я]*|конфликт[а-я]*|боевик[а-я]*|всу|вс\s+рф)\b",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"\b(війн[а-я]*|воєнн[а-я]+|військов[а-я]+|бойов[іиа-я]+\s+ді[а-я]*|вторгненн[а-я]*|армі[а-я]*|солдат[а-я]*|військ[а-я]*|фронт[а-я]*|окоп[а-я]*|обстріл[а-я]*|бомбардуванн[а-я]*|артилері[а-я]*|мобілізаці[а-я]*|зсу)\b",
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
                r"\b(аннекси[а-я]*|оккупаци[а-я]*|деоккупаци[а-я]*|территориальн[а-я]+\s+(статус|спор[а-я]*|претензи[а-я]*|принадлежност[а-я]*|целостност[а-я]*)|спорн[а-я]+\s+территори[а-я]*|непризнанн[а-я]+\s+(государств[а-я]*|республик[а-я]*)|сепарати(зм|ст|сты)[а-я]*|суверенитет[а-я]*\s+над|днр|лнр)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(че[йяеёи]|кому\s+принадлеж[а-я]+|кто\s+(контролирует|владеет|оккупировал|аннексировал)|под\s+чьим\s+(контролем|управлением)|статус)\b.*\b(крым[а-я]*|донбасс[а-я]*|тайван[а-я]*|косов[а-я]*|курил[а-я]*|карабах[а-я]*|арцах[а-я]*|абхази[а-я]*|осети[а-я]*|приднестровь[а-я]*|севастопол[а-я]*|палестин[а-я]*|газ[а-я]*|голан[а-я]*|гибралтар[а-я]*|фолкленд[а-я]*|кашмир[а-я]*|тибет[а-я]*|донецк[а-я]*|луганск[а-я]*|запорожь[а-я]*|херсон[а-я]*|бахмут[а-я]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(крым[а-я]*|донбасс[а-я]*|тайван[а-я]*|косов[а-я]*|курил[а-я]*|карабах[а-я]*|арцах[а-я]*|абхази[а-я]*|осети[а-я]*|приднестровь[а-я]*|севастопол[а-я]*|палестин[а-я]*|донецк[а-я]*|луганск[а-я]*|запорожь[а-я]*|херсон[а-я]*|бахмут[а-я]*)\b.*\b(наш|ваш|че[йяеёи]|кому\s+принадлеж[а-я]+|кто\s+(контролирует|владеет)|российск[а-я]+|украинск[а-я]+|китайск[а-я]+|сербск[а-я]+|государство|независим[а-я]+|росси[а-я]+|украин[а-я]+|кита[а-я]+|серби[а-я]+)\b",
                re.IGNORECASE,
            ),
            # Ukrainian
            re.compile(
                r"\b(анексі[а-я]*|окупаці[а-я]*|деокупаці[а-я]*|територіальн[а-я]+\s+(статус|спір[а-я]*|суперечк[а-я]*|претензі[а-я]*|приналежніст[а-я]*|цілісніст[а-я]*)|спірн[а-я]+\s+територі[а-я]*|невизнан[а-я]+\s+(держав[а-я]*|республік[а-я]*)|сепарати(зм|ст|сти)[а-я]*|суверенітет[а-я]*\s+над)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(чи[йяєї]|кому\s+належит[ьь]?|хто\s+(контролює|володіє|окупував|анексував)|під\s+чиїм\s+(контролем|управлінням)|статус)\b.*\b(крим[а-я]*|донбас[а-я]*|тайван[а-я]*|косов[а-я]*|курил[а-я]*|карабах[а-я]*|арцах[а-я]*|абхазі[а-я]*|осеті[а-я]*|придністров[а-я]*|севастопол[а-я]*|палестин[а-я]*|газ[а-я]*|голан[а-я]*|гібралтар[а-я]*|фолкленд[а-я]*|кашмір[а-я]*|тибет[а-я]*|донецьк[а-я]*|луганськ[а-я]*|запоріжж[а-я]*|херсон[а-я]*|бахмут[а-я]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(крим[а-я]*|донбас[а-я]*|тайван[а-я]*|косов[а-я]*|курил[а-я]*|карабах[а-я]*|арцах[а-я]*|абхазі[а-я]*|осеті[а-я]*|придністров[а-я]*|севастопол[а-я]*|палестин[а-я]*|донецьк[а-я]*|луганськ[а-я]*|запоріжж[а-я]*|херсон[а-я]*|бахмут[а-я]*)\b.*\b(наш|ваш|чи[йяєї]|кому\s+належит[ьь]?|хто\s+(контролює|володіє)|російськ[а-я]+|українськ[а-я]+|китайськ[а-я]+|сербськ[а-я]+|держава|незалежн[а-я]+|росі[а-я]+|україн[а-я]+|кита[а-я]+|сербі[а-я]+)\b",
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
                r"\b(твіч[а-яёіїєґ\']*|твічі|twitch|стрім[а-яёіїєґ\']*)\b.*\b(заборонен[а-яёіїєґ]+|забанен[а-яёіїєґ]+|недозволен[а-яёіїєґ]+|неприпустим[а-яёіїєґ]+|заблокован[а-яёіїєґ]+|небажан[а-яёіїєґ]+)\s+(сл(ов|ів)[а-яёіїєґ]*|вираз[а-яёіїєґ]*|фраз[а-яёіїєґ]*|термін[а-яёіїєґ]*|список|списк[а-яёіїєґ]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(заборонен[а-яёіїєґ]+|забанен[а-яёіїєґ]+|недозволен[а-яёіїєґ]+|неприпустим[а-яёіїєґ]+|заблокован[а-яёіїєґ]+|небажан[а-яёіїєґ]+)\s+(сл(ов|ів)[а-яёіїєґ]*|вираз[а-яёіїєґ]*|фраз[а-яёіїєґ]*|термін[а-яёіїєґ]*|список|списк[а-яёіїєґ]*)\b.*\b(твіч[а-яёіїєґ\']*|твічі|twitch|стрім[а-яёіїєґ\']*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(які|яких|список|перелічи|назви|покажи|дай|напиши|скажи)\b.*\b(сл(ов|ів)[а-яёіїєґ]*|вираз[а-яёіїєґ]*|фраз[а-яёіїєґ]*|термін[а-яёіїєґ]*)\b.*\b(заборон[а-яёіїєґ]*|забороня[а-яёіїєґ]*|банять|банить|забан[а-яёіїєґ]*|блоку[а-яёіїєґ]*|не\s+можна)\b.*\b(твіч[а-яёіїєґ\']*|твічі|twitch)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(які|яких|список|перелічи|назви|покажи|дай|напиши|скажи)\b.*\b(твіч[а-яёіїєґ\']*|твічі|twitch)\b.*\b(заборон[а-яёіїєґ]*|забороня[а-яёіїєґ]*|банять|банить|забан[а-яёіїєґ]*|блоку[а-яёіїєґ]*|не\s+можна)\b",
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
                r"\b(твіч[а-яёіїєґ\']*|твічі|twitch)\b.*\b(забороняє|банить|блокує|фільтрує)\b.*\b(сл(ов|ів)[а-яёіїєґ]*|фраз[а-яёіїєґ]*|вираз[а-яёіїєґ]*)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(твіч[а-яёіїєґ\']*|твічі|twitch)\b.*\b(чорний\s+список|чорному\s+списку|блеклист[а-яёіїєґ]*|автомод[а-яёіїєґ]*|фільтр[а-яёіїєґ]*\s+слів|модераці[а-яёіїєґ]*\s+слів)\b",
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

    def check(self, prompt: str) -> PolicyDecision:
        """
        Check if an AI request should be allowed or ignored.

        Args:
            prompt: The user's question

        Returns:
            PolicyDecision.ALLOW if the request is acceptable,
            PolicyDecision.IGNORE if it should be blocked
        """
        clean_prompt = prompt.strip()
        if not clean_prompt:
            return PolicyDecision.IGNORE

        # Global hard block for explicitly prohibited terms, regardless of context.
        hard_block_pattern = re.compile(
            r"(?<![A-Za-zА-Яа-яЁёІіЇїЄєҐґ0-9_])"
            r"(?:niger|nigeria|нигер|нигерия|нігер|нігерія)"
            r"(?![A-Za-zА-Яа-яЁёІіЇїЄєҐґ0-9_])",
            re.IGNORECASE,
        )
        if hard_block_pattern.search(clean_prompt):
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

        # Check ideological / extremist patterns
        for pattern in self._ideology_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        # Check political patterns
        for pattern in self._political_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        # Check conflict / military patterns
        for pattern in self._conflict_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        # Check territorial / geopolitical patterns
        for pattern in self._territorial_patterns:
            if pattern.search(clean_prompt):
                return PolicyDecision.IGNORE

        # Check sensitive real-world incidents / controversial public figures
        for pattern in self._sensitive_real_world_patterns:
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
