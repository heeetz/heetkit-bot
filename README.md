# Twitch Bot

## Overview

This is a single-channel Twitch chatbot with a local Windows-friendly control panel. It receives chat through TwitchIO EventSub, records when users were last seen, applies global and AI-specific filters, and dispatches commands with permission and cooldown checks.

Major features include:

- Twitch chat commands, role-based permissions, cooldowns, and output limiting;
- current weather through Open-Meteo;
- followage lookups through the Twitch API;
- optional Gemini responses with conditional Google Search grounding;
- per-user Gemini conversation memory in SQLite;
- configurable blocked words, phrases, and regular expressions;
- a Tkinter control panel for command, AI, memory, personality, status, and shutdown controls.

The application uses Python, TwitchIO 3, asyncio, SQLAlchemy 2 with SQLite, HTTPX, Pydantic Settings, Google Gen AI, Open-Meteo, and Tkinter.

## Requirements

- Python 3.12 or newer. Python 3.12 is the recommended baseline.
- A Twitch account for the bot and a Twitch Developer application.
- The numeric Twitch user IDs for the bot account and target channel.
- A Gemini API key only if `!ask` should produce AI responses.
- Tkinter for the local control panel. It is included with normal Windows Python installations; some Linux distributions require a separate `python3-tk` package.

## Installation

From Windows PowerShell:

```powershell
cd "C:\path\to\Twitch Bot"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` with the required Twitch values, then validate configuration and local startup:

```powershell
python -m app.main --check
```

Start the bot and control panel with either supported entry point:

```powershell
python -m app.main
```

```powershell
twitch-bot
```

## Configuration

Configuration has three distinct owners:

- `.env` contains deployment values, account identity, credentials, local paths, and logging settings. It is loaded by `app/config/settings.py` and must remain private.
- `config.py` contains non-secret behavioral settings, including cooldowns, the Telegram message, AI response length, memory limits, and personality prompts.
- The control panel changes process-local runtime state. Its command, AI, memory, and personality changes last only until the process exits.

The environment variables supported by the current application are:

| Variable | Required | Purpose |
| --- | --- | --- |
| `TWITCH_CLIENT_ID` | Yes | Twitch Developer application client ID. |
| `TWITCH_CLIENT_SECRET` | Yes | Twitch Developer application client secret. |
| `TWITCH_BOT_USER_ID` | Yes | Numeric user ID of the bot account. |
| `TWITCH_BOT_USERNAME` | Yes | Login name of the bot account. |
| `TWITCH_CHANNEL_USER_ID` | Yes | Numeric user ID of the channel receiving the bot. |
| `TWITCH_CHANNEL` | Yes | Channel login name. |
| `TWITCH_TOKEN_FILE` | No | TwitchIO token storage; defaults to `data/twitchio_tokens.json`. |
| `GEMINI_API_KEY` | No | Enables Gemini-backed `!ask` replies. |
| `GEMINI_MODEL` | No | Gemini model; defaults to `gemini-3.5-flash-lite`. |
| `AI_COOLDOWN_BYPASS_USER_ID` | No | One Twitch user ID allowed to bypass only the `!ask` cooldown. |
| `DATABASE_URL` | No | SQLAlchemy URL; defaults to local SQLite at `data/twitch_bot.db`. |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `COMMAND_PREFIX` | No | Command prefix; defaults to `!`. |
| `COMMAND_MAX_ARGUMENTS_LENGTH` | No | Maximum command-argument length, from 1 to 450. |

Global message filters live in `data/filters/`:

- `blocked_words.txt` contains whole-word matches;
- `blocked_phrases.txt` contains literal phrase matches;
- `blocked_patterns.txt` contains regular expressions.

Blank lines and lines beginning with `#` are ignored. These text files are distributable behavior configuration, not secret runtime state. Review custom filter content before sharing it.

Cooldown values and AI personalities are edited in root `config.py`. Available personality names currently are `vas2`, `vas`, `anime_girl`, `rapper`, `neutral`, and `gopnik`; `ACTIVE_AI_PERSONALITY` selects the startup default.

## Twitch setup

1. Create a Twitch Developer application and place its client ID and secret in `.env`.
2. Register this exact OAuth callback URL in the Twitch Developer Console:

   ```text
   http://localhost:4343/oauth/callback
   ```

3. Set the bot account username/user ID and destination channel name/user ID in `.env`.
4. Start the application. If authorization is required, the log prints the local TwitchIO authorization URL served on port `4343`.
5. Authorize the configured bot account. The application requests chat read/write, bot, and follower-read scopes used by the current implementation.

TwitchIO stores generated access and refresh tokens in `TWITCH_TOKEN_FILE`. The default is `data/twitchio_tokens.json`. Token files contain credentials: never commit, publish, email, or include them in a manually created ZIP.

## AI setup

Set `GEMINI_API_KEY` in `.env` to enable AI replies. `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite` and can be overridden through the environment.

`!ask` applies the local AI request policy before contacting Gemini. Requests involving current, changing, comparison, event, or named-opinion information can enable Google Search grounding. Provider responses then pass through the local response policy and configured response-length limit before delivery.

When AI memory is enabled, up to `AI_MEMORY_MAX_ENTRIES` successful exchanges per Twitch user are stored in SQLite and supplied as untrusted conversation context. The control panel can disable memory without disabling Gemini. Personality prompts and the default personality are configured in `config.py`.

## Commands

All commands are runtime-toggleable from the local control panel. Hidden commands are omitted from public `!help` output but remain available to authorized users when enabled.

| Command | Purpose | Permission | Hidden | Runtime toggle |
| --- | --- | --- | --- | --- |
| `!ask <question>` | Generate a filtered Gemini response and optionally use/save memory. | User | No | Yes |
| `!commands` | List public command help entries. | Moderator | No | Yes |
| `!erase <username>` | Delete stored AI memory for a known Twitch user. | Broadcaster | Yes | Yes |
| `!followage` | Show how long the invoking user has followed the channel. | User | No | Yes |
| `!forecast` | Return a random configured forecast. | User | No | Yes |
| `!help` | List public command help entries. | User | No | Yes |
| `!ping` | Reply with `pong`. | Moderator | No | Yes |
| `!seen <username>` | Show when a known chat user was last seen. | User | No | Yes |
| `!tg <1-10>` | Send the configured Telegram message from one to ten times. | Moderator | No | Yes |
| `!uptime` | Show elapsed time since application composition. | Moderator | No | Yes |
| `!weather <city>` | Show current weather with English, Russian, or Ukrainian localization. | User | No | Yes |

Cooldowns come from `config.py`. `!tg` and hidden `!erase` currently have no command cooldown; all other cooldown values are explicitly configured there.

## Control panel

Starting the normal application opens a compact Tkinter control panel. It displays every canonical registered command in a grid, including hidden runtime-toggleable commands. The command list comes from the command registry through `RuntimeState`, so the UI does not maintain a separate command-name list.

The panel also provides:

- global AI enable/disable;
- AI memory enable/disable;
- active personality selection;
- bot running state and connection-session uptime;
- an orderly Stop Bot action.

Closing the window or pressing Stop Bot signals the asyncio application to stop. Tk objects are shut down and finalized on their owning GUI thread before process teardown.

## Runtime data and privacy

Generated local files include:

| Path | Classification | Share? |
| --- | --- | --- |
| `.env` and other local `.env.*` files | Secrets and machine-specific deployment configuration | Never |
| `data/twitchio_tokens.json` or custom token path | Twitch access/refresh credentials | Never |
| `data/twitch_bot.db` or other SQLite files | Local user activity and AI memory | Never |
| `data/filters/*.txt` | Intended filter configuration/defaults | Yes, after reviewing custom content |
| `.venv/`, caches, build output, logs, IDE metadata | Generated local development state | No |

The database may contain Twitch user IDs, usernames, last-seen timestamps, and recent AI exchanges. Treat it as private even if it contains no API secrets.

## Safe project sharing

Do not ZIP the project directory manually. `.gitignore` protects Git operations but does not protect a manual archive.

Create a validated shareable archive from PowerShell:

```powershell
.\scripts\package.ps1 -OutputPath .\twitch-bot-share.zip
```

The script packages tracked and non-ignored project files from the current working tree, so it includes current source/documentation changes. It uses a temporary staging directory and defensively excludes environment files, tokens, databases, virtual environments, caches, logs, IDE metadata, build artifacts, and existing archives. It preserves `.env.example`, source, tests, filter defaults, `README.md`, `config.py`, and `pyproject.toml`.

The command refuses to overwrite an existing ZIP. Delete or rename an old archive before rerunning it.

## Testing

Install development dependencies with `python -m pip install -e ".[dev]"`, then run:

```powershell
python -m pytest -q
python -m compileall -q app tests
git diff --check
```

## Troubleshooting

- Missing or invalid `.env`: copy `.env.example`, fill every required Twitch value, and run `python -m app.main --check` to see validation errors.
- Twitch authentication failure: verify the client credentials, numeric account IDs, callback URL, and that the intended bot account completed OAuth. Remove a stale local token file only when you intentionally want to authorize again.
- Import or command not found: activate `.venv` and rerun `python -m pip install -e ".[dev]"`.
- No control panel: verify Tkinter is installed and that the process has access to a graphical desktop. `python -m app.main --check` intentionally does not open the GUI.
- Gemini unavailable: verify `GEMINI_API_KEY`, the selected model, network access, and package installation. Other non-AI commands continue to work without Gemini.
