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
   Secure credentials UI below. A new secret invalidates the previous one.

## Save the details in HeetKit

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
6. Open **Settings → Secure credentials**. Under **Twitch client secret**, paste the
   secret into **Replacement value** and select **Replace**, even when adding it for the
   first time. It is saved in your system's secure storage (Windows Credential Manager
   on Windows).

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

If connection fails, check that each login matches its numeric ID, the callback matches
exactly, the bot has channel access and you authorized the bot account. Do not share your
local profile folder: it contains Twitch authorization credentials.

Optional: [AI / Gemini setup](ai-setup.md). [Back to README](../README.md#quick-start).
