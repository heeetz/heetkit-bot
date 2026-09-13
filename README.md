# Twitch Bot

## Overview

Python Twitch chatbot built with TwitchIO 3/EventSub, async SQLAlchemy, SQLite, Open-Meteo, and optional Gemini AI. It connects one bot account to one channel, persists seen users, filters incoming messages, and dispatches commands through a central registry.filters incoming messages, and dispatches commands through a central registry.

Starting the bot also opens a small local Tkinter control panel. The panel runs in its own thread and lets the operator enable or disable selected commands, AI, AI memory, and the active personality without restarting the bot.

## Project structure

```text
app/
├── main.py                         Application entry point and CLI (`--check`).
├── container.py                    Dependency wiring and application lifecycle.
├── control_panel.py                Local dark Tkinter runtime control panel.
├── runtime_state.py                Thread-safe runtime command, AI, memory, and personality state.
├── commands/
│   ├── ai.py                       Registers `!ask` and its memory flow.
│   ├── fun.py                      Registers `!ping`, `!tg`, `!forecast`, and `!weather`.
│   ├── info.py                     Registers `!help`, `!commands`, and `!uptime`.
│   ├── social.py                   Registers `!followage` and `!seen`.
│   ├── memory.py                   Private owner-only memory maintenance command wiring.
│   └── registry.py                 Command definitions, visibility, permissions, cooldowns, and dispatch.
├── config/
│   └── settings.py                 Environment-backed typed configuration.
├── database/
│   ├── database.py                 Async SQLAlchemy engine and schema lifecycle.
│   ├── models.py                   User and recent AI-memory models.
│   └── repository.py               User and AI-memory queries.
├── services/
│   ├── contracts.py                Service protocols and response data classes.
│   ├── facade.py                   Services passed to command handlers.
│   ├── memory.py                   Last-five successful `!ask` exchange service.
│   ├── runtime.py                  Application uptime tracking.
│   ├── user_service.py             User-facing operations over the repository.
│   ├── twitch.py                   Adapter for authenticated Twitch API lookups.
│   ├── weather.py                  Open-Meteo geocoding, matching, and current weather.
│   ├── ai_request_policy.py        Pre-request policy for unsafe or unwanted `!ask` requests.
│   ├── gemini_ai_service.py        Optional Gemini generation and local response filtering.
│   ├── filter_manager.py           In-memory blocked-word, phrase, and pattern checks.
│   ├── filter_loader.py            Loads filter rules from `data/filters/`.
│   ├── moderation.py               Baseline allow-all moderation service.
│   └── web_search.py               Disabled web-search service placeholder.
├── twitch/
│   ├── client.py                   TwitchIO client, OAuth, EventSub, and message adaptation.
│   ├── events.py                   Transport-neutral chat message data classes.
│   └── permissions.py              Twitch-role permission resolution.
└── utils/
    ├── cooldown.py                 In-memory command cooldown tracking.
    ├── logging.py                  Logging configuration helpers.
    ├── output_limiter.py            Global outgoing-message rate limiter.
    └── text.py                     Text, command, and duration formatting helpers.

config.py                           User-editable non-secret behavior and AI settings.
data/filters/                        Runtime blocked-word, phrase, and regex lists.
tests/                              Lightweight project tests.
pyproject.toml                      Package metadata and dependencies.
.env.example                        Example environment configuration.
```

The SQLite database and TwitchIO token file are local runtime artifacts. Do not commit `.env`, tokens, secrets, `.venv/`, caches, or generated package metadata.

## Setup

Install Python 3.12 or newer, create the environment, and install the project:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and provide the required Twitch settings. The application reads `.env` automatically.

## Configuration

Required environment settings:

- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`
- `TWITCH_BOT_USER_ID`
- `TWITCH_BOT_USERNAME`
- `TWITCH_CHANNEL_USER_ID`
- `TWITCH_CHANNEL`

Useful optional settings include `TWITCH_TOKEN_FILE`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `AI_COOLDOWN_BYPASS_USER_ID`, `DATABASE_URL`, `LOG_LEVEL`, `COMMAND_PREFIX`, and `COMMAND_MAX_ARGUMENTS_LENGTH`.

The root `config.py` contains non-secret behavior settings such as cooldowns, `TG_BURST_DELAY`, `AI_MAX_RESPONSE_LENGTH`, `AI_MEMORY_ENABLED`, `AI_MEMORY_MAX_ENTRIES`, `ACTIVE_AI_PERSONALITY`, and the personality presets:

- `vas`
- `anime_girl`
- `rapper`
- `neutral`
- `gopnik`

The default database is `data/twitch_bot.db`; the default TwitchIO token file is `data/twitchio_tokens.json`.

## Run

Check configuration and initialize the database without connecting to Twitch:

```powershell
python -m app.main --check
```

Start the bot and local control panel:

```powershell
python -m app.main
```

On first use, authorize the bot through TwitchIO's local OAuth page at `http://localhost:4343/oauth`. The callback is `http://localhost:4343/oauth/callback`.

Closing the control panel does not directly terminate the bot. The panel's Stop Bot action requests an orderly application shutdown.

## Commands and access

The table shows the normal global cooldown for each command. A command must also be enabled in the control panel. Invalid arguments are ignored without consuming cooldown.

| Command                 | Access    | Cooldown | Purpose |
| ---                     | ---       | ---:     | --- |
| `!ping`                 | Moderator | 10 s     | Replies with `pong`. |
| `!tg <1-10>`            | Moderator | None     | Sends the configured Telegram message 1–10 times; bypasses only the global outgoing-message limiter. |
| `!help`                 | Everyone  | 10 s     | Lists public command help entries. |
| `!commands`             | Moderator | 15 s     | Lists registered public commands. |
| `!uptime`               | Moderator | 15 s     | Shows application uptime. |
| `!followage`            | Everyone  | 10 s     | Shows how long the invoking user has followed the channel. |
| `!seen <username>`      | Everyone  | 15 s     | Shows when a known chat user was last seen. |
| `!forecast`             | Everyone  | 15 s     | Sends a random forecast. |
| `!weather <location>`   | Everyone  | 30 s     | Shows current temperature, condition, and wind through Open-Meteo. Russian, Ukrainian, and English queries are supported. |
| `!ask <question>`       | Everyone  | 35 s     | Requests a Gemini reply when configured and allowed by the request policy. |

The private `!erase <username>` command is broadcaster-only and hidden from public help. It removes that user’s stored AI memory. The configured AI cooldown bypass user may bypass the normal `!ask` cooldown.

The dispatcher applies runtime command toggles, argument limits, permissions, cooldowns, and the global output limiter. Disabled commands are ignored before permission and cooldown processing.
## AI and memory

`!ask` uses the following flow:

```text
request policy
  -> load up to 5 recent exchanges for the Twitch user
  -> Gemini with optional Google Search grounding
  -> local response filter
  -> response length limit and output limiter
  -> Twitch response
  -> save only a successfully delivered exchange
```

AI request policy checks include prompt-injection and credential requests, selected moderation-sensitive topics, prohibited-substance operations, recipe/preparation requests, explicit sexual/fetish requests, and configured hard-block terms. Gemini responses are also checked locally before being sent to Twitch.

Memory is stored in SQLite in `ai_memory_entries`, keyed by stable Twitch user ID. Each entry contains only the recent `!ask` request, successful response, and timestamp. The oldest entries are pruned so each user keeps at most five. Memory is labeled as untrusted historical context; current system instructions and the current request have priority. The private owner-only memory erase command is intentionally not listed in public documentation or help output.

## Runtime control panel

The Tkinter panel provides controls for:

- `ask`, `weather`, `forecast`, and `tg` command availability;
- AI enable/disable;
- AI memory enable/disable;
- active AI personality selection;
- bot status, uptime, and orderly stop.

The GUI uses only the Python standard library and communicates with the async bot through the thread-safe runtime state.

## Message flow

```text
Twitch EventSub message
  -> Twitch client adapter
  -> global blocked-message filter
  -> seen-user persistence
  -> runtime command gate
  -> permission and argument checks
  -> pre-check and cooldown
  -> command handler
  -> Twitch response
```

## Validation

Lightweight validation:

```powershell
python -m compileall -q app tests
```
