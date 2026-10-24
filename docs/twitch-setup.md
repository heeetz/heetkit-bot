# Twitch setup

Connect HeetKit to one Twitch channel using a bot account and a Twitch Developer
application: a registration that lets HeetKit connect to Twitch. No coding is needed.

## Server browser setup

A fresh Server does not need Desktop or a copied profile. Enable the authenticated
[management panel](management-api.md#docker-opt-in), sign in and open **Settings →
Application, account and channel**. Setup works in every operation mode, including Disabled.

1. Register a Confidential Twitch application using the account/registration guidance
   below. Register the **exact callback URL shown in Settings**. Local/SSH setup
   defaults to `http://localhost:8765/oauth/callback` on the management port;
   use Settings' displayed port if changed. Keep Desktop's separate 4343 callback
   registered if you also use Desktop. A server configured for
   [private remote HTTPS](management-api.md#private-remote-https) uses its explicitly
   configured `https://your-server-hostname/oauth/callback` instead. Twitch's
   [Authorization Code Grant](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#authorization-code-grant-flow)
   requires the registered redirect and exchange redirect to match.
2. Save the Client ID, expected bot login/numeric ID and target login/numeric ID.
   These fields are grouped under **Application**, **Bot account** and
   **Target channel**, with one **Save Twitch settings** action for the identity fields.
   The masked **Twitch client secret** draft is always visible beside Client ID under
   **Application**; enter a value and select **Add secret** or **Replace secret** below it.
   **Remove secret** deletes the stored credential
   after confirmation. **Test client secret** checks the saved application credentials,
   independently of bot-account authorization. Nonempty external secrets are
   read-only here; rotate them on the host and restart. Make the bot a moderator in
   the target channel as described below.
3. Select **Connect Twitch** (use **Open Twitch authorization** if the browser blocks
   the new tab). Check the application and expected bot account on
   Twitch before approving, keeping the original Settings tab signed in. With a
   default local callback, Twitch returns through the same management port.
   With a configured HTTPS callback, remain connected to the tailnet. Twitch returns to
   the server and Settings reports completion automatically. The result tab contains
   no credentials and can be closed. Alternate loopback/private access uses the
   [paste fallback](management-api.md#local-twitch-callback): localhost on your browsing
   computer may not reach the server. Stop other instances using that callback port,
   copy the full URL from the resulting error page into **Callback URL** in
   Settings, and complete within five minutes. Never share that one-use code URL.
4. Check **Authorized account** and **Target channel**. HeetKit verifies application,
   bot identity, target identity and the existing required chat/follower scopes before
   saving authorization. Then use Dashboard: Manual needs Connect, Always On resumes
   automatically, Stream Only follows confirmed live status, and Disabled stays stopped.
   Add/test an optional provider key in **AI → AI setup**.

Use Connect Twitch again after revocation, application/secret/account replacement
or a failed/expired attempt; Cancel abandons an attempt. Identity/secret changes
stop the old session and discard its local authorization. Change only the target
to retain the bot authorization; HeetKit stops the old session and verifies the new
channel before reconnecting. Server changes do not require a process restart.
Browser-managed credentials persist in the private server volume, not OS keyring or
portable ZIPs. See [storage and recovery](docker.md#backup-restore-and-updates).

In **Settings → Application, account and channel → Saved channels**, enter a channel login,
numeric ID and **Saved channel name**, then choose **Save new channel**. Select an
existing saved channel to edit its details or rename it with **Update saved channel**.
Names must be unique. **Delete saved channel** removes only the preset.
Selection, Save and Update leave the active target unchanged. **Switch to saved channel**
explicitly applies the stored target after confirmation; update or discard unsaved
preset edits first. Save or discard application/account edits separately.
The bot account, Client ID, Client Secret and valid OAuth authorization remain shared.
An active session closes before switching. Manual reconnects only if already running;
stopped Manual and Disabled stay stopped, while automatic modes follow their saved
policy. Presets persist in the Server profile across container recreation.
Only the initiating session can inspect its pending/completed attempt. Another
session cannot replace it until cancellation or expiry; sign-out/session eviction
invalidates it. Denial or failed exchange consumes it and requires a new attempt.
For an inaccessible callback check the exact registered redirect, published/tunneled
management port and host listener; for remote HTTPS also check the tailnet connection
and proxy. For an accepted callback followed by a failed attempt, use the
[safe operation diagnostic](management-api.md#twitch-authorization-diagnostics)
in private Server logs to distinguish exchange, token validation, lookup, storage
and cleanup failures. A later-stage failure does not establish a configuration error.
Neither tab closure nor management-network loss stops an already authorized bot.
Existing authorized-profile transfer is an optional advanced path: keep credentials,
OAuth state and private history separate from portable configuration ZIPs, stop the
source instance, and use the approved [whole-profile procedure](docker.md#prepare-private-storage-and-authorization).
The Desktop procedure below retains its existing restart and callback behavior.

## Choose the accounts and register an application

1. **Choose the bot account.** Use a dedicated bot account or the broadcaster's own account.
   Replies appear under its name. The target channel is where you want it to respond.
   Manual commands from a shared bot/broadcaster account work normally; HeetKit's
   own outgoing messages are excluded using their Twitch message IDs.
2. **Open the [Twitch Developer Console](https://dev.twitch.tv/console/apps).** Sign in
   with the developer account that will own the application. Twitch currently requires
   email verification and two-factor authentication (2FA), a second sign-in check alongside
   your password. Enable 2FA in Twitch's **Security and Privacy** settings, then refresh
   the console. See [Twitch's registration guide](https://dev.twitch.tv/docs/authentication/register-app/).
3. **Select Applications → Register Your Application.** Choose a unique application
   name, a chat bot category, and **Confidential** client type so you can generate the
   secret HeetKit requires. From **Settings → Twitch connection → Twitch application**
   in HeetKit, copy the callback into Twitch's **OAuth Redirect URLs** and select **Add**:

   ```text
   http://localhost:4343/oauth/callback
   ```

   This is the local address Twitch returns you to after authorization. Keep it exact,
   including `http` and `/oauth/callback`, then create the application.
4. **Open Manage for your application.** Copy its **Client ID**, then select **New Secret**
   to generate a **Client Secret**. The Client ID is an application identifier, not a password.
   The Client Secret is sensitive: never share or commit it. Enter it through HeetKit's
   Twitch connection section below. A new secret invalidates the previous one.

## Save the details in HeetKit

Settings contains **Desktop behavior**, **Twitch connection**, **Configuration transfer**
and **Data & diagnostics**. Twitch connection starts collapsed; its sidebar shortcut opens
and scrolls to it. Collapsing the section keeps unsaved input.

5. In **Settings → Twitch connection**, enter:

   | Field | What to enter |
   | --- | --- |
   | Twitch application client ID | The Client ID from your Developer application. |
   | Bot account login / user ID | The bot's Twitch login and its numeric account ID. |
   | Target channel login / user ID | The streamer's Twitch login and numeric broadcaster ID. |

   A login is the name in `twitch.tv/name`, without `@` or the URL. An ID is Twitch's numeric
   identifier for that account; broadcaster ID means the channel owner's user ID. For IDs,
   use a public lookup such as [StreamWeasels' converter](https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/).
   Give this third-party lookup only the public login, never credentials. HeetKit requires
   both names and IDs. Select **Save for later**.
6. In the same **Settings → Twitch connection → Twitch application** section, enter
   the secret in the always-visible masked **Twitch client secret** field and select
   **Add secret**. If already configured, enter the replacement in that field and select
   **Replace secret**. It is saved in your
   system's secure storage (Windows Credential Manager on Windows), never in ordinary settings.
   Client ID, bot identity and secret changes require an application restart;
   changing only the target channel requires reconnect instead.

## Give the bot channel access, then connect

7. **Make the bot a moderator in the target channel.** For the current EventSub/bot
   authorization setup, this is the easiest supported configuration. The channel owner
   should type `/mod bot_login` in that channel's chat, using your bot's actual login.

   EventSub delivers Twitch chat events to HeetKit. Moderator status meets the channel
   authorization requirement of this integration; HeetKit remains an entertainment and AI
   chat bot. Twitch also supports broadcaster-authorized `channel:bot` access (permission
   to join as a bot), but HeetKit does not implement that separate authorization flow.
   See [Twitch's chat authorization documentation](https://dev.twitch.tv/docs/chat/authenticating/)
   and [chat event authorization requirements](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/#channelchatmessage).
8. **Restart HeetKit.** Client ID, bot identity and Twitch secret changes require a
   restart. Use **Exit** from the Windows tray menu, then reopen HeetKit; closing the
   window may only hide it.
9. On the Dashboard, select **Start Bot**.
10. When HeetKit shows **Authorization required**, select **Authorize Twitch** on the
    Dashboard or in Settings. In your browser, sign in as the **configured bot account**,
    check the name and approve Twitch's permissions. This is OAuth: granting an application
    account access without giving it your password. Return to HeetKit, wait for
    **Connected**, then try `!help` from another account in the target chat.

To change only the target channel later, use **Save & reconnect** while the bot is
running, or **Save & apply** while stopped. **Save for later** persists the target
without changing the current session. Under **Saved channels**, enter a name and select
**Save channel** to save a target for later switching. Selecting a saved channel fills the
target fields; use **Save & reconnect** or **Save & apply** to apply it. All saved channels
share the configured bot account and authorization, and the bot needs access to each target.
Client ID, bot identity and client secret changes still require an application restart.

**Settings → Desktop behavior → Start bot automatically** saves whether
to connect on the next launch; it defaults to off and is independent of **Start minimized**.

Dashboard **Running** describes the bot session, which can be waiting for authorization
or reconnecting. Its Start/Stop row is followed by Twitch connection, channel/bot account
and session uptime panels, then AI controls. The question-mark help beside **Bot session**
explains the difference between a running session and a ready chat connection.
**Connecting** means startup is in progress; **Connected** means the chat connection is ready
and needs no further connection action;
**Reconnecting** means the connection was lost and TwitchIO is attempting recovery.
**Authorization required** needs the configured bot account's approval. A token cache found
while stopped, connecting or disconnected is **Not verified** until the connection succeeds;
authorization details are in the **Twitch connection** help. **Connection failed** provides
**Open Logs** and guidance before another start.

A fresh profile shows one required Twitch setup step with **Configure Twitch** opening
the correct Settings section. Pending application restarts and saved channel changes appear
as separate notices; a healthy connection can still have a channel change waiting to apply.
AI remains optional: commands-only users can skip AI and dismiss the setup guide.
**Manage AI** opens AI controls when needed. Filter Tester and AI Playground can be used
while stopped; Desktop Playground needs a configured AI provider.

If connection fails, check that each login matches its numeric ID, the callback matches
exactly, the bot has channel access and you authorized the bot account. Do not share your
local profile folder: it contains Twitch authorization credentials.

Optional: [AI provider setup](ai-setup.md). [Back to README](../README.md#getting-started).
