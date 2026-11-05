# Commands and customization

Use **Commands** and **Filters** on Desktop or Server. Chat examples use the
default `!` prefix and default command names. Select a section header to
expand it. Use the question-mark buttons for field help.

- [Create a custom reply](#custom-commands)
- [Edit a built-in command](#permissions-cooldowns-and-responses)
- [Schedule an announcement](#scheduled-announcements)
- [Restrict a user](#user-restrictions)
- [Set up and test filters](#filters)
- [Look up a built-in command](#built-in-commands)

## Custom commands

Add a command that replies with your own text. You can set it up with the bot
stopped. To test it in chat, [connect Twitch](twitch-setup.md#give-the-bot-channel-access-then-connect).

**In HeetKit:** **Commands > Your commands** on Desktop or Server.

1. Open **Commands**.
2. In **Your commands**, select **New command**.
3. In **Command name**, enter `hello` without the prefix.
4. In **Permission**, select **user** to let any viewer run it.
5. In **Response type**, select **Single**.
6. In **Message**, enter `Welcome, {sender}!`.
7. Check that the switch shows **Enabled**.
8. Select **Save command**. The change takes effect immediately.

**Check:** Find `!hello` in **Your commands**. Send it in the connected channel
from an allowed account. Check that the bot replies with your Twitch name.

### Optional replies and settings

- **Random** picks one of 1–30 responses. Enter one response per non-empty
  line in **Responses**. Commas stay in the text.
- **Burst** repeats one message. Set **Permission** to **moderator** or
  **broadcaster**. Set **Default repeat count** to 1–10. If you turn on
  **Allow argument count override**, `!promo 5` sends five copies.
  With `!promo 5 @alice`, the template sees `@alice` as the first argument.
  An invalid count produces no reply. See [Burst limits and spacing](#burst-limits-and-spacing).
- Use **Aliases** for alternate names. See [command name rules](#command-name-rules).
- Use **Per-user cooldown (seconds)** to limit repeats from one account. Use
  **Global cooldown (seconds)** to limit repeats across all accounts in the
  channel. Both start at 0 for a new custom command.
- On Server, use **Stream availability** to limit when the command runs.
  See [Server command availability](#server-command-availability).

Expand **Available variables** for templates. Each reply can use up to 450
UTF-8 bytes. A Burst renders the template once and repeats the same result.

| Variable | What HeetKit inserts |
| --- | --- |
| `{sender}` | The chatter who ran the command. |
| `{target}` | The first argument, or the sender if there is no argument. |
| `{args}` | All arguments. |
| `{arg1}` through `{arg9}` | Individual arguments. A missing argument becomes blank. See **Advanced variables**. |
| `{random_user}` | A chatter seen in the last 30 minutes, or the sender if there is none. |

Use **Edit** to change a saved command. **Discard and close** leaves the saved
command in place. A failed save leaves the draft open so you can correct it.
**Delete** permanently removes a custom command after confirmation.

## Permissions, cooldowns and responses

Choose who can use a built-in command and how often it can run. You can edit
with the bot stopped. To check the change, you need a connected channel and an
account with the chosen permission.

**In HeetKit:** **Commands > Built-in commands** on Desktop or Server. Find
`!erase` and storage opt-out controls under **Administrative commands**.

1. Open **Commands**.
2. Expand the command's row under **Built-in commands** or **Administrative commands**.
3. Set **Enabled**. For `!ask`, this switch saves immediately. Save the
   other `!ask` settings separately.
4. Select the minimum role in **Permission**.
5. Set **Per-user cooldown (seconds)**.
6. Set **Global cooldown (seconds)**.
7. Select **Save**. For Fate or Tg, select **Save command**.

**Check:** Reopen the command to check its saved settings. Try the command
from an account with the chosen role. If you set a cooldown, try it again
before and after the cooldown ends.

Roles from lowest to highest are User, Subscriber, VIP, Moderator and
Broadcaster. A higher role meets a lower requirement. Tg and Erase require
at least Moderator. On Server, check [Stream availability](#server-command-availability)
if an enabled command stays silent. Also check [filters](#filters) and
[user restrictions](#user-restrictions).

### Command name rules

In a built-in editor, **Primary chat name** changes the chat trigger.
Add the previous trigger to **Aliases** if you want both names to work.
**Name in UI** changes only the label in HeetKit. Save with the command.
Renaming keeps the command's behavior, including its minimum permission.

Each name or alias is one word of up to 40 characters without the prefix.
Enter up to ten aliases, separated by commas. Names and aliases ignore
case. They cannot conflict with another command, an alias, a reserved
factory name, or `optout`.

### Server command availability

On Server, select **Stream availability** in the built-in or custom editor.
Save with the command. This setting controls when a command can run while
the bot is connected. The [operation mode](twitch-setup.md#choose-when-the-server-connects)
controls the connection itself.

| Setting | When the command runs |
| --- | --- |
| **Anytime** (default) | Live or offline, including when stream status is unknown. |
| **Live only** | A recent successful check shows the stream is live. |
| **Offline only** | A recent successful check shows the stream is offline. |

An unavailable command stays silent and uses no cooldown or provider request.
Its aliases follow the same rule. Desktop ignores this setting for commands.
Announcements can use stream conditions on both hosts.

### Change Fate or Tg text

Use the same built-in editor for Fate or Tg. For Fate, enter one response per
non-empty line. For Tg, enter one message. Each line can use up to 450 UTF-8
bytes. **Save command** saves both text and settings. If settings save but
text fails, correct the text and use **Save command** again. Other built-ins
generate their own replies.

**Reset responses** or **Reset message** restores the default text.
**Reset settings** restores the shipped settings for that command and keeps
its saved text. See [prediction settings upgrades](data-and-privacy.md#existing-prediction-settings)
if you used `!forecast` in an older version.

### Remove or restore a built-in

Select **Remove and disable** in the command's editor. When you confirm, HeetKit
disables the command, hides it from the working list, and discards its draft.
To bring it back, open **Removed commands** and select **Restore defaults and
enable**. This restores default names, access and cooldowns and keeps any saved
response text. Restore `!ask` here before enabling it if you removed it earlier.

Under **Advanced: reset all built-ins**, **Restore all factory defaults**
restores all built-in settings and Fate/Tg text after confirmation. It also
returns removed commands and discards built-in drafts. Your custom commands,
user restrictions and storage opt-outs stay in place.

### Burst limits and spacing

In the Tg editor, set **Maximum repeat count** to 1–20. The default is 10.
Select **Save command**. With no argument, `!tg` makes one send attempt.
`!tg 5` makes five attempts when the saved maximum allows it.

In Tg or a custom Burst editor, set **Burst interval (ms)** to 0–1000.
At the default 0, HeetKit starts the sends together. At 200, it starts
them about 200 ms apart. Twitch controls when the messages appear and can
reject individual sends. Check **Logs** if only some messages arrive.

## Scheduled announcements

Send a reminder at regular intervals. You need a connected bot to see it in
chat. For **Highlighted**, the bot must be a moderator or the broadcaster
and have [announcement authorization](twitch-setup.md#give-the-bot-channel-access-then-connect).

**In HeetKit:** **Commands > Announcements** on Desktop or Server.

1. Open **Commands**.
2. In **Announcements**, select **New announcement**.
3. Enter a **Name**.
4. Set **Interval (s)** to 60–86400. The default is 900 seconds.
5. Set **Trigger after** to the minimum number of eligible chat messages per
   interval, from 0 to 1000. Use the default 0 to allow quiet chat.
6. Choose **Anytime**, **Live only** or **Offline only** in **Works when:**.
7. Choose **Single message** or **Random message** in **Message selection**.
8. Enter one line for **Single message** or 1–30 lines for **Random message**.
   Each line can use up to 450 UTF-8 bytes. HeetKit sends the text as entered.
9. Set **Announcement type**. **Regular message** uses ordinary chat.
   **Highlighted** is the default for new schedules and reaches every
   participating channel during Twitch Shared Chat.
10. Select **Save announcements**. Saving restarts enabled schedules with a
    full interval. HeetKit sends no catch-up messages.

**Check:** For a simple test, use **Regular message**, **Anytime** and a threshold
of 0. With the bot connected, wait a full interval. Check chat and **Last outcome**
in the help beside the saved schedule's name.

### If an announcement does not appear

- Check that the schedule is enabled and that the bot stayed **Connected** for
  the full interval. A reconnect, restart or channel change starts a new interval.
- Check the activity threshold. Only eligible chat messages the bot observes
  during that interval count. Its own output, duplicates, bot-marked messages
  and filtered or ignored input are excluded.
- A live or offline condition needs a fresh matching stream check on either
  host. Unknown status pauses restricted announcements.
- If **Highlighted** fails for access or authorization, renew consent and check
  the moderator role. HeetKit does not resend it as a **Regular message**.

Use **Edit** to change a schedule. A saved row's **Enable** and **Disable**
actions take effect immediately. **Delete** permanently removes the schedule
after confirmation. You can save up to 50 schedules.

## User restrictions

Prevent a Twitch account from using selected commands in the current channel,
or from using AI questions across the profile. You need the account's Twitch
username and a configured target for a channel rule. The rule only controls
HeetKit. The account can still chat and use self-service `!optout`.

**In HeetKit:** **Commands > User restrictions** on Desktop or Server.

1. Open **Commands**.
2. In **User restrictions**, select **Add restriction**.
3. Enter the **Twitch username**.
4. Choose **Affected commands**. Select individual commands or **All commands,
   including ordinary-message reactions** for a channel rule. For a profile-wide
   AI rule, select **Block AI questions across all channels in this profile** instead.
5. Choose **Expiry**. Use **Permanent**, **Duration** or **Local date and time**.
6. If the rule expires, set the duration or the local date and time.
7. Optionally enter a **Private note (one line)** of up to 200 characters.
8. Select **Save restriction**. HeetKit verifies the username before it applies
   a new rule. An unresolved username prevents the save.

**Check:** Find the rule in **Search restrictions**. Check the account, scope
and expiry. To test a rule for an account you control, run a restricted command
that works from a permitted account. The restricted request produces no reply.

Use **Edit** to change the commands, expiry or note. A change of account or
scope needs a new rule. **Remove** takes effect after confirmation. Other active
rules still apply. Expiry continues while the bot is stopped. For an older
unresolved AI rule, **Verify / edit** retries verification on save.

Renames and aliases do not bypass restrictions. Blocking `!ask` leaves existing
memory subject to the normal retention rules. See
[private command restrictions](data-and-privacy.md#private-command-restrictions)
for data and backup details.

## Filters

Stop HeetKit from processing matching chat messages or posting matching AI
replies. You can edit and test rules with the bot stopped. New profiles start
with empty rules. Filters control the bot's behavior in chat.

**In HeetKit:** **Filters > Bot filters** on Desktop or Server.

1. Open **Filters**.
2. Expand **Blocked words** to match whole words or **Blocked phrases** to
   match literal text snippets.
3. Enter one rule per line. HeetKit trims spaces at the ends of a rule.
   Blank lines and lines that start with `#` are ignored. Commas stay in the rule.
4. Use [Filter Tester](#test-filters-locally) with **Unsaved draft**.
5. Select **Save filters** to apply the rules and keep them across restarts.

**Check:** In **Filter Tester**, use **Active filters**. Test a sample that
should match and one that should pass.

For a temporary change, choose **Apply for session** in place of **Save
filters**. For a regular expression, expand **Regex patterns**, select
**Add rule**, and enter the pattern. If a rule fails validation, correct the
line or pattern shown before you save.

### Test filters locally

Check sample text without Twitch or a provider request. You need either an
active rule or a draft rule to test a match.

**In HeetKit:** **Filters > Filter Tester** on Desktop or Server.

1. Open **Filters**.
2. Enter a message in **Sample text**.
3. Under **Rules to test**, select **Active filters** or **Unsaved draft**.
4. Select **Test sample**.

**Check:** **User filter matched** (`BLOCK`) identifies the category and rule
when available. **User filters passed** (`ALLOW`) means no editable rule blocked
the sample. **Regex timeout** (`BLOCK`) means a pattern took too long to check.
The tester makes no changes and covers the editable filters. Protected AI
safety checks still apply to real AI requests.

## Built-in commands

These are the shipped chat names and permissions. See
[Permissions, cooldowns and responses](#permissions-cooldowns-and-responses)
to change the settings.

| Command | Purpose | Default permission |
| --- | --- | --- |
| `!ask <question>` | Get an AI reply. See [AI setup](ai-setup.md). | User |
| `!commands [page]` | List public command help. | Moderator |
| `!erase <username>` | Delete a known user's AI memory in this channel. Hidden from help. | Broadcaster (minimum Moderator) |
| `!followage` | Show how long you have followed the channel. | User |
| `!fate` | Get a random prediction from the saved responses. | User |
| `!help [page]` | List public command help. | User |
| `!optout` | Delete your presence and AI history across the profile and stop future identifying storage. | User (self-only) |
| `!ping` | Check for a `pong` reply. | Moderator |
| `!seen <username>` | Show when HeetKit last saw a known chatter in this channel. | User |
| `!tg [1-20]` | Send the saved community message, with an optional repeat count. | Moderator |
| `!uptime` | Show how long the current HeetKit session has run. | Moderator |
| `!weather <city>` | Get current weather in English, Russian or Ukrainian. | User |

Help lists enabled public commands once under their primary names. An alias
still works in chat. Server help omits commands that conflict with a confirmed
stream state. If there are more pages, follow the hint in chat, for example
`!help 2`. The last page includes `!optout`.

`!erase` removes AI memory for the named viewer in this channel only.
For a storage opt-out, see [Manage a storage opt-out in HeetKit](data-and-privacy.md#manage-a-storage-opt-out-in-heetkit).
For other presence deletion requests, see [manual privacy requests](data-and-privacy.md#manual-privacy-requests).
Fresh AI requests from opted-out viewers still reach the provider.

### Weather locations

Use `!weather New York`, `!weather Київ, Україна`, `!weather London, Ontario`
or `!weather Los Angeles, California, US`. Check the city and country in the
reply. Add a region or country if you get a result for the wrong place.

Country names in English, Ukrainian or Russian and two-letter country codes
work with or without a comma. Use commas for regions. In a two-part query,
a recognized country takes priority, so `CA` means Canada. To name a region
that is also a country name, use three parts, as in `Atlanta, Georgia, US`.

HeetKit looks for exact settlement names. It respects the region and country
you supply. If several places qualify, it uses the first eligible match in
its preferred language and the provider's order. Use the spelling and region
name in the [Open-Meteo location service](https://open-meteo.com/en/docs/geocoding-api).
For example, `Київ`, `Киев` and `Kyiv` find the Ukrainian capital.

HeetKit handles one weather request per channel at a time. An accepted request
starts the per-user cooldown even if it finds no city. The global cooldown
starts when Twitch confirms it sent the forecast. Overlapping requests,
invalid locations, missing matches and provider or delivery failures can be
silent in chat. Check **Logs** for the outcome.

## Reactions to ordinary messages

Make HeetKit reply to matching chat without a command prefix. This advanced
task needs access to the active [profile](data-and-privacy.md#profiles).
Back up the profile before editing its files.

**On the host:** Open `config/message_triggers.json` in the active profile.

1. Stop HeetKit.
2. Open `config/message_triggers.json` in a text editor.
3. Add an entry to the `triggers` list. Use a unique `id`, `enabled`,
   `match_mode` (`contains` or `exact`), `text`, `case_sensitive`,
   `probability` (0–1), `cooldown_seconds` (0–86400), and one to ten
   literal `responses`.
4. Save the file as UTF-8.
5. Start HeetKit.

**Check:** With the bot connected, send matching text from a permitted account.
For a test, use an enabled rule with probability 1 and cooldown 0. Keep its
reply within 450 UTF-8 bytes.

HeetKit checks rules in file order and sends at most one reaction per message.
It skips command-prefixed messages, bot messages and invalid rules. If no
reactions work, check **Logs** for a file or JSON error. HeetKit keeps the
original file for you to correct. See
[backups and recovery](data-and-privacy.md#backups-and-settings-recovery).

[Back to README](../README.md#documentation).
