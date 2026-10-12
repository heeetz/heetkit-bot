# Commands and customization

Configure built-in commands, create custom replies, and manage filters from HeetKit's
desktop control panel. Examples below use the default `!` prefix.

Select **Commands**, **Filters**, **AI** or **Settings** in the sidebar to open that
page and reveal its subsection shortcuts. A shortcut scrolls to the corresponding
card and keeps the list open; selecting another page replaces the shortcuts.
Shortcuts follow the page's block order, including **Filter Tester** and the AI page's
**State**, **Playground**, **Conversation memory**, **AI access** and **Built-in
restrictions** sections.
Dashboard, Logs and About remain direct page links.

## Built-in commands

These are the shipped permissions; saved settings can change them within protected
minimums. Hidden commands stay out of public help but remain usable by authorized
users when enabled. Disabled or removed commands also stay out of public help.

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
| `!tg <1-10>` | Send the configured community message one to ten times, with optional Burst spacing. | Moderator |
| `!uptime` | Show how long the current HeetKit session has been running. | Moderator |
| `!weather <city>` | Current weather with English, Russian or Ukrainian localization. | User |

`!ask` requires a Gemini key. See [AI setup](ai-setup.md). Other commands work without
Gemini. `!uptime` measures the bot session, rather than the stream's uptime.

## Permissions, cooldowns and responses

Select **Edit** on a built-in command on **Commands** to edit its enabled state,
permission and per-user/global cooldowns. Most commands also accept alternate
aliases and **Name in UI**. This label does not rename the chat command: its original
name stays available. Enter up to ten comma-separated aliases; each is a single
command word of at most 40 characters, without the prefix. Names and aliases are
case-insensitive. Those already reserved by another built-in or custom command are
rejected, including removed factory commands.

The permission order is User → Subscriber → VIP → Moderator → Broadcaster; higher
roles also satisfy lower requirements. `!tg` requires at least Moderator and `!erase`
requires Broadcaster. `!ask` keeps its fixed identity. Protected commands appear in
the separate **Administrative commands** section with fixed identities and no text
template editor.

The `!ask` enabled switch saves immediately on **Dashboard**, **AI** and **Commands**.
All three views share the same saved value, which survives restarts; no extra Commands
Save is needed. If saving fails, the previous enabled state stays active and an error
is shown. Toggling `!ask` keeps other drafts and does not save permissions, cooldowns,
messages or AI editor changes. Use **Save** for those settings as usual. A removed
`!ask` must first be restored from **Removed commands**. **AI → AI access** links to
this existing `!ask` editor for permission and cooldown changes.

`!erase` is restricted to the broadcaster and accepts a known username. It deletes only
that viewer's stored AI conversation memory. It does not remove activity history, Twitch
messages or an AI block, and blocking a user from `!ask` does not erase their existing
memory or ban them from Twitch chat.

- **Save** immediately applies the settings and keeps them across restarts.
- **Reset settings** removes this command's saved settings override and restores the
  shipped settings, including its enabled state. Its message is kept.
- **Collapse editor** keeps unsaved input for when you expand the command again.

Expand **Fate** or **Tg** to edit their response text. One **Save command** saves edited
text and settings, applies them immediately and keeps them across restarts. Other
command drafts and the AI page's independent saves are kept. If settings save but
text fails, the error identifies the saved settings and retains the text draft;
use **Save command** to retry it. If settings fail, text is not saved. **Reset responses**
or **Reset message** restores only the text; other settings and their drafts are kept.
**Reset settings** retains saved text and any text draft. Settings actions appear in
the order **Remove and disable**, **Collapse editor**, **Reset settings**, **Save command**
(**Save** for commands without editable text).
Fate accepts one non-empty response per line; blank
lines are ignored and commas stay in the text. Responses must fit within 450 UTF-8 bytes.
Other built-ins keep their original behavior and show a note when their response
cannot be edited as a text template. Editing settings never replaces the AI, weather,
memory-erasure or other built-in implementation.

**Remove and disable** saves the command as disabled and hides it from the active collection.
Its implementation is retained. The collapsed **Removed commands** list shows a count
and only removed commands. Disabled commands remain in the working list. Select
**Restore defaults and enable** to replace an individual removed command's settings
with defaults and enable it. Previous custom access, cooldowns, aliases and UI names
are not recovered; its saved message is kept. Removal discards that command's unsaved
draft after confirmation; cancel keeps it. Custom and administrative groups remain separate.
Under **Advanced: reset all built-ins**, **Restore all factory defaults** restores every built-in setting, enabled state and
the Fate/Tg messages, returns removed commands and discards built-in drafts;
custom commands are kept.
These settings belong to the selected profile and survive a restart.

### Burst spacing

`!tg` and each custom Burst command have a separate **Burst interval (ms)** setting,
accepting whole numbers from 0 to 1000. The default is 0. Settings are saved with the
command and remain isolated between profiles.

| Interval | Dispatch behavior |
| --- | --- |
| 0 ms | Start all requests concurrently. |
| 50 ms | Start requests approximately 50 ms apart. |
| 200 ms | Start requests approximately 200 ms apart. |
| 1000 ms | Start requests approximately one second apart. |

Spacing controls when a send request begins. A later request does not wait for the
previous Twitch response. All one to ten sends are managed and awaited together;
cancellation stops pending starts and cleans up active sends. Twitch controls when
messages appear and may reject or rate limit individual requests. Successful sends
are retained when another send fails; failures appear in the logs without an
application retry. Actual delivery and message order are not guaranteed.

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

Fate/Tg use one **Save command** for text and settings; their resets remain independent. Ordinary
command-setting saves retain their existing recovery behavior for unknown fields
or external edits; protect recovery copies like the profile itself. See
[backups and settings recovery](data-and-privacy.md#backups-and-settings-recovery).

## Custom commands

Use **Custom Commands** to edit **Name → Response type → Text → Access → Cooldowns →
Aliases & advanced options**. Variable help stays beside the text; Burst count,
spacing and argument override follow aliases. **Save command** applies changes
immediately and keeps them across restarts. Names and aliases use the same case-insensitive, single-word,
40-character limit as built-ins, with at most ten aliases and no prefix in the editor.
They cannot conflict with built-in commands.
The top **New command** control becomes **Discard draft** while editing;
**Discard and close** is also available inside. Discarding or switching commands asks to discard
changes only when the draft was edited. A successful save closes the editor; a failed
save retains the draft and shows the error. Commands use styled confirmations with
Confirm and Cancel actions; Escape dismisses without executing. Built-in removal
is reversible through Removed commands; custom deletion is permanent.

- **Single** sends one configured message.
- **Random** selects one of 1–10 templates, entered one per non-empty line.
- **Burst** repeats one configured message using the Burst interval, with a default count of
  1–10. Burst requires Moderator or Broadcaster permission. Enable argument count
  override to let `!promo 10` send ten copies instead of the default, for example five.
  Invalid counts send nothing. With override enabled, a target can follow the count:
  `!promo 5 @alice`; template variables see `@alice`, after the count is removed.

Commas remain literal text. Templates support:

| Variable | Value |
| --- | --- |
| `{sender}` | The invoking chatter. |
| `{target}` | First argument, or the sender when absent. |
| `{args}` | All arguments. |
| `{arg1}` through `{arg9}` | Individual arguments; missing values become blank. |
| `{random_user}` | A chatter seen in the last 30 minutes, or the sender if none exists. |

For example, a `!hello` response could be `Welcome, {sender}!`.
Common variables appear beside the message; positional arguments are under the
collapsed **Advanced variables** section. Unknown variables are rejected. Templates
never execute code, and replies are limited to 450 UTF-8 bytes. Burst renders the
template once and repeats the same result, including the same random chatter.

Single and Random use the shared output limiter. Only Burst and `!tg` bypass it;
both await every send, using only the configured spacing between request starts.
Existing saved commands retain Single/Random behavior. The saved format upgrades
only when edited, retaining atomic saves and settings recovery. Existing Burst
commands with no interval setting retain simultaneous dispatch at 0 ms.

## Filters

On **Filters**, **Bot filters** control bot processing: matching incoming messages
are ignored by the bot and matching generated AI replies are blocked. These rules
do not delete Twitch messages or ban users. Expand a category to edit whole words, literal phrases or regular
expressions. Words and phrases use one non-empty rule per line, with surrounding
whitespace trimmed; commas remain text. Regex is an advanced, collapsed category
with individual validation and evaluation time limits.
**Apply** changes the running session and **Save** keeps validated rules across restarts.
New profiles start with empty filter rules. Filters apply to incoming chat and AI replies.

### Test filters locally

Use **Filter Tester** to check sample text without posting to Twitch or making an API
request. Choose **Active filters** to test the rules currently used by the session, or
**Unsaved draft** to test the editors exactly as shown without applying or saving them.
The result shows **User filters passed** (`ALLOW`), **User filter matched** (`BLOCK`)
with its category and editable rule when available, or **Regex timeout** (`BLOCK`)
without claiming a matched rule. Passing user filters does not guarantee an AI
request or reply will pass protected AI safety. Tests do not
change the active or saved rules and cover only editable global filters, not the separate
protected AI safety policy.

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
