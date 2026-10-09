# Commands and customization

Configure built-in commands, create custom replies, and manage filters from HeetKit's
desktop control panel. Examples below use the default `!` prefix.

Select **Commands**, **Filters**, **AI** or **Settings** in the sidebar to open that
page and reveal its subsection shortcuts. A shortcut scrolls to the corresponding
card and keeps the list open; selecting another page replaces the shortcuts.
Dashboard, Logs and About remain direct page links.

## Built-in commands

These are the shipped permissions; saved settings can change them. Hidden commands
stay out of public help but remain usable by authorized users when enabled.

| Command | Purpose | Default permission |
| --- | --- | --- |
| `!ask <question>` | Gemini reply using the active personality and optional memory. | User |
| `!commands` | List public command help entries. | Moderator |
| `!erase <username>` | Delete stored AI memory for a known user; hidden from help. | Broadcaster |
| `!followage` | Show how long the invoking user has followed the channel. | User |
| `!fate` | Return a random configured prediction. | User |
| `!help` | List public command help entries. | User |
| `!ping` | Reply with `pong`. | Moderator |
| `!seen <username>` | Show when a known chatter was last seen. | User |
| `!tg <1-10>` | Send the configured community message one to ten times. | Moderator |
| `!uptime` | Show how long the current HeetKit session has been running. | Moderator |
| `!weather <city>` | Current weather with English, Russian or Ukrainian localization. | User |

`!ask` requires a Gemini key. See [AI setup](ai-setup.md). Other commands work without
Gemini. `!uptime` measures the bot session, rather than the stream's uptime.

## Permissions, cooldowns and responses

Expand a built-in command on **Commands** to edit its enabled state, permission and
per-user/global cooldowns. The permission order is User → Subscriber → VIP → Moderator
→ Broadcaster; higher roles also satisfy lower requirements.

- **Apply** changes this session.
- **Save** keeps the settings across restarts.
- **Reset** removes the saved override and restores the shipped defaults.

Expand **Fate** or **Tg** to edit their response text. These editors have their own
Apply, Save and Reset actions. Fate accepts one non-empty response per line; blank
lines are ignored and commas stay in the text. Responses must fit within 450 UTF-8 bytes.
Weather and uptime use runtime data rather than editable response lists.

### Existing prediction settings

`!fate` replaces `!forecast`; the old command has no alias. On normal startup, each
selected profile (including `--data-dir`) automatically renames `forecast` to `fate`
in `config/command_settings.json` and `forecasts` to `fates` in version-1
`config/fun_settings.json`. Saved enabled state, cooldowns, permissions and response
text are retained, along with unknown and unrelated JSON fields.

If both keys exist, the complete new value wins, even if empty or invalid; values
are not merged and invalid settings follow the usual default fallback. The old key
is removed from the active file. Before replacement, an exact original is kept
beside it as `<filename>.<unique-id>.recovery`, including any conflicting old value.
Once renamed, startup leaves that file untouched. `--check` performs no migration.
Malformed or unsupported files stay intact. A failed backup or replacement keeps
the original on disk and uses the renamed values for that session; resolve the
reported file problem with HeetKit stopped before restarting.

Apply, Save and Reset still work independently for settings and responses. Ordinary
command-setting saves retain their existing recovery behavior for unknown fields
or external edits; protect recovery copies like the profile itself. See
[backups and settings recovery](data-and-privacy.md#backups-and-settings-recovery).

## Custom commands

Use **Custom Commands** to create a name, optional aliases, required permission,
per-user/global cooldowns and one to ten response templates. Custom command changes
save immediately. Names and aliases cannot conflict with built-in commands.

Enter one template per non-empty line. Multiple templates are selected at random;
commas remain literal text. Templates support:

| Variable | Value |
| --- | --- |
| `{sender}` | The invoking chatter. |
| `{target}` | First argument, or the sender when absent. |
| `{args}` | All arguments. |
| `{arg1}` through `{arg9}` | Individual arguments; missing values become blank. |
| `{random_user}` | A chatter seen in the last 30 minutes, or the sender if none exists. |

For example, a `!hello` response could be `Welcome, {sender}!`.
Unknown variables are rejected. Templates never execute code, and replies are limited
to 450 UTF-8 bytes. Custom replies use the normal shared output limiter.

## Filters

On **Filters**, expand a category to edit whole words, literal phrases or regular
expressions. Words and phrases use one non-empty rule per line, with surrounding
whitespace trimmed; commas remain text. Regex rules have individual validation.
**Apply** changes the running session and **Save** keeps validated rules across restarts.
New profiles start with empty filter rules. Filters apply to incoming chat and AI replies.

## Reactions to ordinary messages

Advanced users can edit `config/message_triggers.json` in the
[current profile](data-and-privacy.md#profiles), then restart. The starter has an empty
`triggers` list. Each entry needs a unique `id`, `enabled`, `match_mode` (`contains` or
`exact`), `text`, `case_sensitive`, `probability` (0–1), `cooldown_seconds` (0–86400)
and one to ten literal `responses`.

Matching follows file order, with at most one reaction per message. Bot messages and
command-prefixed messages are excluded. Replies share the output limiter and 450-byte
limit. Invalid entries are skipped. Keep a backup before editing profile files.

[Back to README](../README.md#documentation).
