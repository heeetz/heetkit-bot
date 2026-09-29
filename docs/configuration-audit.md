# Current configuration map

This audit describes the repository at TODO-002. It is a map and recommendation only; it
does not change configuration or runtime behavior.

Classifications used below:

- **A** — source-controlled default or application resource
- **B** — local, non-secret user setting
- **C** — secret or credential
- **D** — runtime-only state

Where a row has more than one classification, it describes an intentional pipeline such as
an A default, a B saved override, and a D effective value. Those layers are not duplicate
sources of truth by themselves.

| Value or group | Current source/default | Current persistence | Runtime owner | UI editable | Class | Recommended future owner | Current ownership |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `start_minimized`, `minimize_to_tray`, `close_to_tray` | `AppSettings` defaults in `app/app_settings.py` | `data/app_settings.json` | `AppSettingsStore`; `DesktopController` consumes snapshots | Yes, Settings page | A → B | Window/tray section of cohesive local app settings | Correct, but isolated from other ordinary app settings |
| Twitch client ID | Required `Settings.twitch_client_id`, normally `.env` | `.env` | `Settings`; `TwitchChatBot` | No | B | Local app setting or developer environment fallback | Mixed into the same file as secrets |
| Twitch client secret | Required `SecretStr` in `Settings`, normally `.env` | `.env` plaintext | `Settings`; passed to TwitchIO | No | C | OS credential store, with `.env` only as a developer/backward-compatible fallback | Secret is correctly excluded from Git, but plaintext storage is weak |
| Bot user ID/name and target channel user ID/name | Required `TWITCH_BOT_USER_ID`, `TWITCH_BOT_USERNAME`, `TWITCH_CHANNEL_USER_ID`, `TWITCH_CHANNEL` | `.env` | `Settings.primary_account`; Twitch bot/API service | No; displayed read-only on Dashboard | B | Twitch section of local app settings | Scattered with credentials and not editable in the product UI |
| OAuth callback and scopes | `OAUTH_REDIRECT_URI` and `CHAT_SCOPES` in `app/twitch/client.py` | Source only | `TwitchChatBot` | No | A | Keep application-owned unless supported Twitch behavior changes | Correct |
| Twitch access/refresh tokens | TwitchIO authorization flow | `data/twitchio_tokens.json` or `TWITCH_TOKEN_FILE` | TwitchIO through `TwitchChatBot` | No | C | Dedicated protected token/auth storage; keep separate from ordinary settings | Correct separation, although file protection is best-effort on Windows |
| Twitch token file path | `Settings.twitch_token_file = "data/twitchio_tokens.json"` | Optional `.env` override | `TwitchChatBot` | No | A/B | Application-owned storage location; advanced deployment override only if still needed | Correct but exposed alongside user-facing values |
| Stream-category cache TTL | `CATEGORY_CACHE_TTL_SECONDS = 90.0` | Source only | `TwitchAPIService` | No | A | Keep as an internal operational default | Correct |
| Internal operational limits | Gemini request timeout 60s, shared HTTP timeout 8s, output interval 5s, personality prompt maximum 50,000 characters, recent-log limit 500 | Source only | Relevant services and validators | No | A | Keep source-owned unless a concrete product need makes one user-facing | Correct; these are safety/operational constraints rather than ordinary preferences |
| Gemini API key | Optional `SecretStr` in `Settings`, normally `.env` | `.env` plaintext | `GeminiAIService` | No | C | OS credential store, with `.env` fallback for development | Secret is excluded from Git but mixed with ordinary settings |
| Gemini model | `Settings.gemini_model = "gemini-3.5-flash-lite"` | Optional `.env` override | `Settings`; `GeminiAIService` | No; displayed read-only on AI page | A → B | AI/provider section of local app settings, with a tracked known-good default | Ownership is clear but product configuration is incomplete; no fallback model exists |
| AI response length and memory retention count | `AI_MAX_RESPONSE_LENGTH = 220`, `AI_MEMORY_MAX_ENTRIES = 5` in root `config.py` | Source only | Prompt builder/Gemini response truncation; `AIMemoryService` | No | A | Tracked behavior defaults; expose later only if there is a real UX need | Correct, source-owned policy |
| AI memory enabled | `AI_MEMORY_ENABLED = True` in root `config.py` | Not persisted after UI changes | `RuntimeState._ai_memory_enabled` | Yes, AI page | A → D | A tracked default plus a B local AI preference if restart persistence is intended | Ambiguous UX: editable in the UI but always returns to the code default on restart |
| AI command enabled | Registered `ask.enabled_by_default = True` | Optional `ask.enabled` in `data/command_settings.json`; AI-page changes are unsaved | Canonical `RuntimeState` command settings (`ai_enabled` is an alias for `ask`) | Yes, AI page and Commands page | A → B/D | Keep in canonical command settings; make the persistence semantics explicit in UI | One runtime owner, not duplicated, but two UI surfaces provide different save semantics |
| AI cooldown-bypass user ID | `Settings.ai_cooldown_bypass_user_id = None` | Optional `.env` override | `CommandDispatcher` | No | B | Local non-secret advanced AI/command setting | Scattered into deployment settings |
| Active personality | `ACTIVE_AI_PERSONALITY = "vas2"` in root `config.py` | `active_personality` in `data/personality_settings.json` when saved | `RuntimeState` | Yes, AI page | A → B/D | Keep tracked default plus local saved selection and runtime effective state | Correct layering |
| Built-in personality IDs/prompts (`vas2`, `vas`, `anime_girl`, `rapper`, `neutral`, `gopnik`) | `AI_PERSONALITY_PRESETS` / `AI_PERSONALITY_PROMPTS` in `app/config/personalities.py` | Source only | `RuntimeState` and prompt builder | Prompt text can be overridden, not rewritten | A | Tracked data resource plus application-owned loader | Clear ownership, but large data definitions live in Python source |
| Shared AI instructions and AI request/response safety rules | `SHARED_AI_INSTRUCTIONS`, `AIRequestPolicy`, and hard-coded Gemini response filters | Source only | Prompt builder, request policy, `GeminiAIService` | No | A | Keep application-owned and protected, separate from user personality text | Correct; these are policy, not ordinary user settings |
| Personality prompt overrides | Built-in prompt is the fallback | `overrides` in `data/personality_settings.json` | `RuntimeState` | Yes, AI page Apply/Save/Reset | B/D | Keep dedicated local personality override data | Correct layering and separation from shared instructions |
| Command enabled/cooldown/permission | `CommandDefinition.default_settings`, derived from registry metadata and root cooldown constants | Partial overrides in `data/command_settings.json` | Canonical `RuntimeState`; dispatcher consumes effective values | Yes, Commands page Apply/Save/Reset | A → B/D | Keep registry defaults, dedicated override file, and runtime effective state | Correct; these are layers, not duplicated ownership |
| Command aliases, help text, hidden flag, validators, and handler-specific behavior | Command decorators/handlers | Source only | `CommandRegistry` / dispatcher | No | A | Keep source-owned command definition metadata | Correct |
| Command prefix and maximum argument length | `Settings.command_prefix = "!"`; `command_max_arguments_length = 300` | Optional `.env` overrides | `CommandDispatcher`; prefix also passed to TwitchIO | No | A → B | General/advanced local app settings with tracked defaults, or developer-only settings if intentionally unsupported | Clear at runtime, but ordinary values are mixed into `.env` |
| Static command content and Telegram burst delay | `TG_MESSAGE`, `TG_BURST_DELAY` in root `config.py`; `FORECASTS` in `app/commands/fun.py` | Source only | `tg` and `forecast` command handlers | No | A | Tracked command behavior/content until custom-command work defines a data model | Correct for current built-ins, but related content is scattered across source files |
| Global filter rules | `data/filters/blocked_words.txt`, `blocked_phrases.txt`, `blocked_patterns.txt` | The same tracked text files | `FilterManager`, loaded at application startup | No | A (currently also treated as user-editable data) | Tracked default filter resources plus a distinct local override/user file when TODO-011 adds editing | Ambiguous: distributable defaults and local edits share the same tracked files |
| Filter directory path | `FILTERS_DIRECTORY` in root `config.py` | Source only | Application startup/filter loader | No | A | Application-owned resource/default location | Correct |
| Weather provider behavior | Open-Meteo URLs, Celsius/km/h units, language selection, and shared HTTP timeout are source constants/code | None | `OpenMeteoWeatherService`; shared `httpx.AsyncClient` | No; city is per-command input only | A | Keep provider mechanics source-owned; add a local setting only if provider/units become real product choices | Correct; there is currently no weather credential or persisted user setting |
| Database location | `Settings.database_url = "sqlite+aiosqlite:///./data/twitch_bot.db"` | Optional `.env` override; database itself is local runtime data | `Database` | No | A/B; database contents are runtime data | Keep application-owned default path with advanced deployment override | Clear, but stored beside unrelated `.env` settings |
| Log level | `Settings.log_level = "INFO"` | Optional `.env` override | Logging setup | No | A → B | General/diagnostics local app setting or developer environment override | Clear, but not available through product settings |
| Bot running, Twitch connected, uptime/session timestamps | Runtime initialization only | None | `RuntimeState` / `BotRuntime` | Start/Stop is editable; status is displayed | D | Keep runtime-only | Correct |
| Unsaved command/personality Apply values and frontend form drafts | Registry/personality effective state seeds the forms | None | `RuntimeState` for applied values; React component state for unsubmitted drafts | Yes | D | Keep runtime-only and clearly label dirty/applied state | Correct; React is not a competing source of truth |
| Recent category/log/cooldown caches | Source-owned limits/TTLs (`90s` category, bounded logs, in-memory cooldown timestamps) | None | Respective services/managers | No | D with A limits | Keep runtime-only with source defaults | Correct |
| Data/settings paths (`COMMAND_SETTINGS_PATH`, `PERSONALITY_SETTINGS_PATH`, `APP_SETTINGS_PATH`) | Root `config.py` | Source only | Composition root / desktop host | No | A | Central application path constants or a small paths module if later warranted | Clear; moving them alone would not improve user configuration |

## Command default map

All registered commands currently default to enabled. The registry remains the authoritative
command list; this table only records the audited state.

| Command | Built-in permission | Built-in cooldown | Saved/runtime override |
| --- | --- | --- | --- |
| `ask` | `USER` | global 25s | `data/command_settings.json` / `RuntimeState` |
| `erase` (hidden) | `BROADCASTER` | none | same canonical path |
| `ping` | `MODERATOR` | global 10s | same canonical path |
| `tg` | `MODERATOR` | none | same canonical path; OutputLimiter bypass remains handler-specific |
| `forecast` | `USER` | global 15s | same canonical path |
| `weather` | `USER` | global 15s | same canonical path |
| `help` | `USER` | global 10s | same canonical path |
| `commands` | `MODERATOR` | global 15s | same canonical path |
| `uptime` | `MODERATOR` | global 15s | same canonical path |
| `followage` | `USER` | global 10s | same canonical path |
| `seen` | `USER` | global 15s | same canonical path |

## Problems found

1. **Ordinary settings are scattered.** Window/tray preferences use `app_settings.json`,
   identity and operational values use `.env`, and behavioral defaults require editing
   `config.py`. Each path works, but there is no single obvious home for ordinary local
   application preferences.
2. **`.env` mixes classifications.** Twitch/Gemini secrets, non-secret account/channel
   identity, model selection, logging, database location, and command parsing values share
   one file. Git hygiene is correct, but ownership and future UI behavior are not.
3. **AI memory persistence is unclear.** The AI page can toggle memory, but the value is
   runtime-only and returns to `AI_MEMORY_ENABLED` after restart.
4. **AI enablement has ambiguous UI semantics.** Both AI and Commands pages update the same
   canonical `ask` setting, which is good, but only the Commands page exposes Save/Reset.
   The difference is not obvious from ownership alone.
5. **Filter defaults and local customization are conflated.** The three filter files are
   tracked resources and also the only manual editing surface. A future UI must not overwrite
   distributable defaults without a separate local override model.
6. **Built-in personality data is embedded in Python.** Runtime ownership is not duplicated,
   but source data changes require Python edits and releases rather than resource updates.
7. **Provider/model configuration is incomplete for product use.** The Gemini model is an
   environment value displayed read-only, credentials are plaintext in `.env`, and there is
   no explicit fallback model.

No duplicate runtime owner was found for command settings, personality settings, or desktop
settings. Their default/override/effective layers are intentional and should be preserved.

# Recommended target structure

Keep the model small and explicit:

```text
tracked defaults and resources
    - behavioral defaults
    - command registry metadata
    - built-in personalities
    - default filter rules
              ↓
local non-secret app settings
    - window/tray
    - Twitch channel/account identity
    - AI model and memory preference
    - general/diagnostic preferences
              ↓
dedicated domain overrides
    - command_settings.json
    - personality_settings.json
              ↓
runtime effective state
    - RuntimeState / AppSettingsStore
    - unsaved Apply values
    - connection/session/cache state
```

Keep credentials outside that flow:

- Twitch client secret and Gemini API key: OS-backed credential store.
- Twitch OAuth access/refresh tokens: dedicated protected auth storage managed through the
  Twitch adapter.
- `.env`: supported as a developer/deployment fallback, not the long-term desktop settings UI.

The local database remains application data, not a configuration store. React form state
remains temporary presentation state, never a domain source of truth. The existing dedicated
command and personality override files should not be folded into a generic settings engine.

# Migration order

1. **TODO-003:** introduce one versioned local file for ordinary non-secret app settings,
   initially absorbing window/tray and selected non-secret preferences with compatible
   fallbacks. Leave command/personality overrides and all secrets alone.
2. **TODO-004:** move built-in personality text to tracked data resources while preserving
   IDs, shared protected instructions, and override/reset behavior.
3. **TODO-005:** add OS-backed credential ownership for provider secrets; retain `.env` as a
   documented fallback during migration.
4. **TODO-006:** expose Twitch identity/channel settings and connection status, clearly
   separating reconnect-required changes from credentials and OAuth tokens.
5. **TODO-007:** add Gemini model/fallback configuration and credential status using backend
   values rather than frontend lists.
6. **TODO-008:** make apply timing and persistence explicit across Settings, AI, and Commands.
7. **TODO-011:** add filter editing only after tracked defaults and local overrides have a
   clear separation.
