# Twitch setup

You need a Twitch account to send as, a target channel and a Twitch Developer
application. The application gives HeetKit permission to connect; no coding is needed.
AI setup is separate and optional.

## Server browser setup

A fresh Server can be configured entirely through its authenticated
[private panel](management-api.md#docker-opt-in), without copying a Desktop profile.
Open **Settings > Application, account and channel**:

1. Register the application using the guidance below. Add the **exact callback URL
   displayed in Settings** to its Twitch redirect URLs. Local/SSH setup normally uses
   `http://localhost:8765/oauth/callback`; private HTTPS uses its configured server URL.
2. Enter Client ID, bot login/numeric ID and target login/numeric ID. Choose **Save
   Twitch settings**. Enter the client secret separately with **Add/Replace secret**.
   Test checks saved application credentials, not bot-account authorization.
3. Choose **Connect Twitch**. Check the application and expected bot account before
   approving in Twitch. Keep the original Settings tab signed in; it reports completion.
4. Verify Authorized account and Target channel, then use Dashboard. Manual needs
   Connect; Always On resumes automatically; Stream Only follows confirmed live status;
   Disabled stays stopped. These are operation modes, not authorization states.

If the browser blocks a tab, use **Open Twitch authorization**. If localhost points to
another computer rather than the server, use the documented
[callback paste fallback](management-api.md#local-twitch-callback) within five minutes.
Never share the callback URL: it contains a one-use authorization code. Private HTTPS
callbacks require the tailnet/proxy route to remain reachable.

Identity or client-secret changes stop the old session and invalidate local consent.
A target-only change keeps bot authorization but verifies the new channel before
reconnecting. Server changes do not require a process restart. Host-supplied secrets
are read-only in the panel: rotate them on the host and restart.

**Saved channels:** saving, selecting, renaming or deleting a preset does not switch
the active target. **Switch to saved channel** explicitly applies it after confirmation.
The bot account, app and authorization stay shared. Running Manual resumes after a
switch; stopped Manual/Disabled stays stopped. Automatic modes follow saved policy.

Only the initiating session owns its authorization attempt. Cancel or start a new
attempt after denial, expiry or failure. Closing the browser does not stop an already
authorized bot. For failures, inspect the [safe authorization diagnostic](management-api.md#twitch-authorization-diagnostics)
rather than posting tokens, callback URLs or profile files in an issue.

## Choose the accounts and register an application

1. Choose the sending account and target channel. Replies appear under the sending
   account's name. A dedicated bot or the broadcaster's account can be used; HeetKit
   excludes its own outgoing messages by Twitch message ID, not by matching text.
2. Open the [Twitch Developer Console](https://dev.twitch.tv/console/apps) and register
   a **Confidential** chat-bot application. Follow
   [Twitch's account requirements](https://dev.twitch.tv/docs/authentication/register-app/).
3. Register the callback shown by HeetKit. Desktop uses:

   ```text
   http://localhost:4343/oauth/callback
   ```

   Server uses its own management callback above. Keep both registered if you use both
   hosts. Scheme, hostname, port and path must match exactly.
4. Copy the Client ID and generate a Client Secret in the application's management
   page. Client ID identifies the app; Client Secret is a password. A replacement
   secret invalidates the old one. Never commit, screenshot or share it.

## Save the details in HeetKit

On Desktop, open **Settings > Twitch connection** and enter:

| Field | Meaning |
| --- | --- |
| Client ID | Your registered Twitch application's identifier |
| Bot login / user ID | Sending account's login and stable numeric Twitch ID |
| Target login / user ID | Channel owner's login and stable numeric Twitch ID |

A login is the account name without `@` or a URL; a display name is not a numeric ID.
Ensure each login matches its ID. Save Twitch settings, add/replace the secret using
its separate action, and restart Desktop when prompted. Saving identity fields does
not save a secret draft. The secret is not read back into the form.

## Give the bot channel access, then connect

The current connection model expects the sending account to be a moderator in the
target channel, unless it is the broadcaster. Grant that role through Twitch, then
use **Start Bot** and **Authorize Twitch** as the configured sending account.

Wait for **Connected**, not just Running. Reconnecting means the connection was lost;
Authorization required needs renewed consent. A token cache alone does not establish
valid authorization or successful delivery. Check Logs and account/channel/callback
settings if connection fails. Stop other instances using the same account or callback.

Highlighted announcements additionally need `moderator:manage:announcements` consent
and broadcaster/moderator role. On Desktop use **Renew Twitch authorization** in
Settings; on Server use **Connect Twitch**. Existing chat tokens still support Regular
messages. See [announcements](commands.md#scheduled-announcements).

Optional next step: [AI setup](ai-setup.md). Keep private profiles, tokens and
credentials out of support messages; see [data and privacy](data-and-privacy.md).
