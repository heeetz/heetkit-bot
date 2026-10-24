# Commands and customization

Configure built-in commands, create custom replies, and manage filters from HeetKit's
desktop or authenticated browser control panel. Examples below use the default `!` prefix.

Select **Commands**, **Filters**, **AI** or, on Desktop, **Settings** in the sidebar
to reveal subsection shortcuts. A shortcut opens the relevant section and scrolls to
it; selecting another page replaces the shortcuts. Commands follow **Your commands →
Built-in commands → Removed commands → Administrative commands → Advanced: reset all
built-ins**. AI follows **State → Playground → Personalities → Profile instructions →
Response language → Models → AI access → Built-in restrictions**. Conversation memory
is a panel in **State**, not a separate shortcut. Browser mode omits Playground and
Settings subsection shortcuts; see [browser capabilities](management-api.md#browser-panel).
Filters includes **Filter Tester** followed by its rule categories. Dashboard, Logs
and About remain direct page links.

Expandable headers use a chevron on the right. Select the header, or focus it and
press Enter or Space, to open or close it. Question-mark buttons beside labels give
extra help: hover briefly, focus with the keyboard, or select one to read it. Escape
closes the help; using help in a header does not open or close that section.
Mouse-opened help closes shortly after the pointer leaves both the button and its
text. Keyboard-opened help stays available until focus moves away or Escape is pressed.
Setup steps, errors, unsaved changes and reset/delete consequences remain visible.

## Built-in commands

These are the shipped permissions; saved settings can change them within protected
minimums. Hidden commands stay out of public help but remain usable by authorized
users when enabled. Disabled or removed commands also stay out of public help.

| Command | Purpose | Default permission |
| --- | --- | --- |
| `!ask <question>` | AI reply using the active personality and optional memory. | User |
| `!commands [page]` | List public command help entries. | Moderator |
| `!erase <username>` | Delete stored AI memory for a known user; hidden from help. | Broadcaster |
| `!followage` | Show how long the invoking user has followed the channel. | User |
| `!fate` | Return a random configured prediction. | User |
| `!help [page]` | List public command help entries. | User |
| `!ping` | Reply with `pong`. | Moderator |
| `!seen <username>` | Show when a known chatter was last seen. | User |
| `!tg [1-20]` | Send the configured community message once by default, or repeat up to its configured maximum, with optional Burst spacing. | Moderator |
| `!uptime` | Show how long the current HeetKit session has been running. | Moderator |
| `!weather <city>` | Current weather with English, Russian or Ukrainian localization. | User |

`!ask` requires a key for the selected Gemini or DeepSeek provider. See
[AI setup](ai-setup.md). Other commands work without AI. `!uptime` measures the bot
session, rather than the stream's uptime.

`!commands` and `!help` list enabled public built-ins and custom commands, including
their current aliases. Edits, removals and restores appear on the next request;
saved changes also survive restart. UI display names do not rename chat commands.
In Server, help also omits commands whose stream availability does not match a
confirmed live/offline state. Unknown or stale status does not filter the help list.
The list keeps each command's existing invocation permissions and omits hidden,
disabled and removed commands. Long lists use numbered pages within the Twitch
message limit; follow the displayed next-page command, for example `!commands 2`.
You can use the broadcaster's account as the bot account and type commands manually.
HeetKit correlates its own outgoing messages by Twitch message ID, so a command list
starting with `!ask` cannot launch another AI request. Identical manually typed text
has a different message ID and follows the normal permissions, filters and cooldowns.
If a response's HTTP result is lost or lacks an ID, delivery is uncertain. HeetKit
logs this and pauses input from that sending account for up to ten minutes to avoid
loops; other accounts continue normally. Explicitly rejected sends do not cause this pause.

## Permissions, cooldowns and responses

The Server browser command editor includes **Stream availability** for built-in
and custom commands, including newly created commands:

Expanded built-ins place Enabled above the paired Permission/Stream availability
and per-user/global cooldown fields. Narrow screens stack these fields.

| Setting | Execution while connected |
| --- | --- |
| Anytime (default) | Works live and offline, including when stream status is unknown. |
| Live only | Runs only with a recent successful live observation. |
| Offline only | Runs only with a recent successful offline observation. |

This setting is independent of Enabled, permissions and cooldowns. Aliases use
their parent command's setting. Unavailable commands silently ignore requests
without calling their handler, using external APIs or consuming cooldowns.
Save keeps the policy in the Server profile; Reset settings restores Anytime.
Windows Desktop has no availability control and ignores these restrictions.

[Operation Mode](management-api.md#operation-modes) controls the Twitch connection.
For example, Always On with `!ask` set to Live only stays connected offline;
Anytime commands still work and Ask makes no AI request. Stream Only retains its
existing connection/disconnection behavior.

Select a built-in command's header on **Commands** to edit its enabled state,
permission and per-user/global cooldowns. Opening the editor scrolls it into view
and focuses **Permission**. Most commands also accept alternate
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
For deletion of both activity and AI history, or a persistent local-storage opt-out,
follow the operator's [manual privacy-request procedure](data-and-privacy.md#manual-privacy-requests).

- **Save** immediately applies the settings and keeps them across restarts.
- **Reset settings** removes this command's saved settings override and restores the
  shipped settings, including its enabled state. Its message is kept.
- Select the command header again to collapse it; unsaved input is kept for when
  you expand the command again.

Expand **Fate** or **Tg** to edit their response text. One **Save command** saves edited
text and settings, applies them immediately and keeps them across restarts. Other
command drafts and the AI page's independent saves are kept. If settings save but
text fails, the error identifies the saved settings and retains the text draft;
use **Save command** to retry it. If settings fail, text is not saved. **Reset responses**
or **Reset message** restores only the text; other settings and their drafts are kept.
**Reset settings** retains saved text and any text draft. One editor footer places
**Remove and disable** on the left, with the applicable **Reset responses** or
**Reset message**, **Reset settings** and **Save command** on the right
(**Save** for commands without editable text). Actions wrap within the editor on
narrow windows, keeping Save last.
Fate accepts one non-empty response per line; blank
lines are ignored and commas stay in the text. Responses must fit within 450 UTF-8 bytes.
Other built-ins show a short **Dynamic response** note, with details in its question-mark
help. Their response cannot be edited as a text template. Editing settings never replaces the AI, weather,
memory-erasure or other built-in implementation.

**Remove and disable** saves the command as disabled and hides it from the active collection.
Its implementation is retained. The collapsed **Removed commands** list shows a count
and only removed commands. Disabled commands remain in the working list. Select
**Restore defaults and enable** to replace an individual removed command's settings
with defaults and enable it. Previous custom access, cooldowns, aliases and UI names
are not recovered; its saved message is kept. Removal discards that command's unsaved
draft after confirmation; cancel keeps it. Custom and administrative groups remain separate.
**Advanced: reset all built-ins** follows **Administrative commands**, matching the
sidebar shortcut order. Its **Restore all factory defaults** action asks for explicit
confirmation before restoring every built-in setting, enabled state and
the Fate/Tg messages, returns removed commands and discards built-in drafts;
custom commands are kept.
These settings belong to the selected profile and survive a restart.

### Burst limits and spacing

`!tg` with no argument makes exactly one send attempt. `!tg 1`, `!tg 5` and `!tg 20`
make exactly that many attempts when the count is allowed. In **Commands → Tg**,
set **Maximum repeat count** to a whole number from 1 to 20. Counts above this
command's saved maximum are rejected without starting a burst; 20 is the absolute
cap. The maximum defaults to 10, preserving the previous limit for existing profiles.
Loading older settings does not rewrite them or change their permissions, cooldowns,
message or spacing. **Reset settings** restores the maximum to 10.

Repeated delivery of the same Twitch chat event is ignored within the session's
recent-message cache, so it cannot start another burst. Separate chat messages with
the same text remain separate invocations, subject to the normal command cooldown.
Custom Burst commands retain their existing 1–10 count and optional argument override.

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
previous Twitch response. All requests in the permitted batch are managed and awaited together;
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

Select **New command** or an existing command's **Edit** button to bring its editor
into view and focus **Command name**. Keyboard focus surrounds the complete name
field, including the command prefix. Unsaved changes still require confirmation
before replacing or discarding a draft.

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
- **Random** selects one of 1–30 templates, entered one per non-empty line.
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

The starter file is copied only when missing; existing files are never replaced at
startup. UTF-8 files with or without a BOM are supported. Empty, malformed or unreadable
files disable reactions while other application functions remain available. **Logs**
identifies the file path and, for invalid JSON, the line, column and character position
without including reaction text. The original file stays in place for recovery: back
it up, correct the reported problem and restart HeetKit.

[Back to README](../README.md#documentation).
