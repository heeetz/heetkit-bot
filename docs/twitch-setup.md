# Twitch setup

Connect HeetKit to one Twitch channel using a bot account and a Twitch Developer
application: a registration that lets HeetKit connect to Twitch. No coding is needed.

## Choose the accounts and register an application

1. **Choose the bot account.** Use a dedicated bot account or another account you control.
   Replies appear under its name. The target channel is where you want it to respond.
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

Settings is ordered **Twitch connection → Gemini API key → Desktop behavior → Data & diagnostics**.
Twitch connection and Gemini API key start collapsed. Their
sidebar shortcuts expand and scroll to them; you can also select each card header.
Collapsing a section keeps unsaved input.

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
6. In the same **Settings → Twitch connection → Twitch application** section, under
   **Twitch client secret**, paste the secret into **New value** and select **Add secret**.
   If already configured, use **Replacement value → Replace secret**. It is saved in your
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
or reconnecting. Check **Twitch connection**, **Authorization** and **Next step** separately:
**Connecting** means startup is in progress; **Connected** means the chat connection is ready;
**Reconnecting** means the connection was lost and TwitchIO is attempting recovery.
**Authorization required** needs the configured bot account's approval. A token cache found
while stopped, connecting or disconnected is **Not verified** until the connection succeeds.
**Connection failed** points to Logs before another start. AI availability is separate and
optional. Filter Tester and AI Playground can be used while stopped; Playground needs Gemini.

If connection fails, check that each login matches its numeric ID, the callback matches
exactly, the bot has channel access and you authorized the bot account. Do not share your
local profile folder: it contains Twitch authorization credentials.

Optional: [AI / Gemini setup](ai-setup.md). [Back to README](../README.md#getting-started).
