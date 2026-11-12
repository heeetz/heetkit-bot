# Twitch setup

Connect HeetKit so it can read chat and reply in your channel. You need a target
channel, a Twitch account to send as, and a Twitch Developer application. The bot
can send as the broadcaster or as a separate account. A separate account needs
the moderator role in the target channel. Have the login and numeric Twitch user
ID for each account ready. The login is the account name without `@` or a URL.
If you need an ID, use a Twitch user ID lookup that accepts the account login.
The account that registers the application needs two-factor authentication.

On Desktop, start HeetKit. On Server, open and sign in to the
[private browser panel](#server-browser-setup). Server setup works without a
Desktop profile.

## Save the details in HeetKit

**In HeetKit:** **Settings > Application, account and channel** on Desktop or
Server. On Desktop, the **Twitch connection** shortcut opens this section.

1. Open **Settings**.
2. Expand **Application, account and channel**.
3. Copy **OAuth callback URL** from **Twitch application**.
4. Select **Open Twitch Developer Console**.
5. Start registering a **Confidential** application. Follow
   [Twitch's registration guide](https://dev.twitch.tv/docs/authentication/register-app/).
6. Add the copied URL under **OAuth Redirect URLs**. Desktop uses
   `http://localhost:4343/oauth/callback`. Server uses the URL shown in Settings.
   If you use both, register both. The scheme, host, port and path must match.
7. Copy the Client ID after you create the application.
8. On Desktop, paste the ID into **Twitch application client ID**. On Server,
   paste it into **Client ID**.
9. Enter **Bot account login**.
10. Enter the matching **Bot account user ID**.
11. Enter **Target channel login**.
12. Enter the broadcaster's numeric ID in **Target channel user ID**.
13. In **Authorization, status and save**, save the fields.

    - **Desktop:** Select **Save for later** if you are also about to add the
      secret. For an identity-only change, select **Save & restart** to apply it now.
    - **Server:** Select **Save Twitch settings**. Changing the Client ID or bot
      identity stops the current session and clears local authorization.

14. Select **New Secret** on the application's **Manage** page in Twitch.
    Generating a replacement invalidates the previous secret. Treat it like a password.
15. Paste the secret into **Twitch client secret**.
16. On Desktop, select **Add secret & restart** or **Replace secret & restart**
    to save and apply the secret and any pending identity changes. Use **Add secret**
    or **Replace secret** to defer applying it. **Restart now** in Settings or on
    Dashboard applies saved pending changes. HeetKit asks before discarding drafts
    in other editors and reopens with the bot's previous run intent.
17. On Server, select **Add secret** or **Replace secret**. The panel applies the
    change immediately, stops the session and clears authorization. Authorize the
    account again through Settings.

**Check:** On Server, check that **Setup** shows **Complete**. On Desktop, check
the bot account, target and **Client secret** status in **Authorization, status
and save** after restarting. On either host, **Test client secret** checks the
saved application credentials. Continue below to authorize the bot account.

## Give the bot channel access, then connect

Authorize HeetKit to send as the configured bot account. Complete the setup
above first. If the bot account differs from the broadcaster, give it the
moderator role in the target channel on Twitch before connecting.

**In HeetKit:** **Dashboard** on Desktop. On Server, start in **Settings >
Application, account and channel** and finish on **Dashboard**.

### Desktop

1. Open **Dashboard**.
2. If the bot is stopped, select **Start Bot** when ready to connect.
3. If prompted, select **Authorize Twitch**.
4. Sign in to Twitch as the configured bot account.
5. Approve access for the registered application.

### Server

1. Open **Settings**.
2. Expand **Application, account and channel**.
3. Select **Connect Twitch** in **Authorization, status and save**.
4. Sign in to Twitch as the configured bot account.
5. Approve access for the registered application.
6. Return to the original signed-in Settings tab. In callback paste mode, complete
   the attempt there using the [local callback steps](management-api.md#local-twitch-callback).
7. Check **Authorized account** and **Target channel**.
8. Open **Dashboard**.
9. In **Manual** mode, select **Connect**. **Always On** connects automatically.
   **Stream Only** waits for confirmed live status. **Disabled** keeps chat stopped.

**Check:** Wait for **Connected** under **Twitch connection** on **Dashboard**.
Send `!help` in the target channel from a permitted account. Check for a reply
from the bot account. The example assumes the default command name and prefix.

### If the bot does not connect

- If the browser blocks the Server authorization tab, select **Open Twitch
  authorization**. Keep the original signed-in tab open until the attempt finishes.
- If the local callback has no listener, use the
  [callback paste procedure](management-api.md#local-twitch-callback) within five
  minutes. A private HTTPS callback needs its private route to remain reachable.
  Keep the returned callback URL private. It contains a one-use code.
- If you see **Authorization required**, repeat authorization as the configured
  bot account. Check the callback URL, account and channel IDs, and moderator role.
  Stop any other instance using the same account or callback.
- If **Twitch client secret** shows **Managed externally**, rotate it on the Server
  host and restart. See [Docker secret provisioning](docker.md#prepare-private-storage-and-authorization).
- If **Reconnecting** persists, check **Logs** for the next action. See
  [Twitch authorization diagnostics](management-api.md#twitch-authorization-diagnostics)
  and [connection recovery](development.md#twitch-connection-ownership).

For highlighted announcements, the bot account also needs
`moderator:manage:announcements` consent. On Desktop, while connected, select
**Renew Twitch authorization** in **Authorization, status and save**. On Server,
select **Connect Twitch** again. See [Scheduled announcements](commands.md#scheduled-announcements).

## Save and switch channels

Save another target to reuse its channel details. You need its login and numeric
ID, and the same bot account needs access to the new channel.

**In HeetKit:** **Settings > Application, account and channel > Saved channels**
on Desktop or Server.

1. Open **Settings**.
2. Expand **Application, account and channel**.
3. In **Saved channel**, select **Unsaved target** on Desktop or **New saved channel**
   on Server.
4. Enter a **Saved channel name**.
5. Enter **Target channel login**.
6. Enter **Target channel user ID**.
7. Select **Save channel** on Desktop or **Save new channel** on Server. This
   stores the preset without switching the bot.
8. Select the preset in **Saved channel** when you want to use it.
9. Apply the target change.

   - **Desktop:** Select **Save & reconnect** while the bot runs, or **Save & apply**
     while it is stopped.
   - **Server:** Select **Switch to saved channel** and confirm. A running
     **Manual** session reconnects. A stopped **Manual** or **Disabled** session
     stays stopped. Automatic modes follow their saved policy.

**Check:** Check the channel on **Dashboard**. If the bot should be running,
wait for **Connected** before testing a command in the new channel.

**Update saved channel** and **Delete saved channel** change the preset list.
The app keeps the same Twitch application and bot authorization when you change
only the target. On Server, save or discard app/account edits before switching.
Use separate [profiles](data-and-privacy.md#profiles) for separate credentials.

## Choose when the Server connects

Keep chat connected, follow the stream's live status, or connect by hand. You
need a running Server and a [configured Twitch account](#save-the-details-in-heetkit).

**In HeetKit:** **Dashboard > Operation mode** on Server.

1. Open **Dashboard**.
2. Choose an **Operation mode**. The choice saves immediately.

   | Mode | What happens |
   | --- | --- |
   | **Always On** (default) | HeetKit connects at startup and stays connected when the stream is offline. |
   | **Stream Only** | HeetKit connects after it confirms the stream is live and disconnects after it confirms the stream is offline. |
   | **Manual** | HeetKit stops chat when you enter this mode. Use **Connect** and **Disconnect** to control the session. HeetKit starts stopped after a restart. |
   | **Disabled** | HeetKit stops chat and prevents new connections until you choose another mode. |

**Check:** Check the saved mode and **Twitch connection** on **Dashboard**.
In **Stream Only**, check **Broadcaster status**. HeetKit needs consecutive
successful checks before it acts on a live or offline transition.

**Switch to Manual & disconnect** saves **Manual** and stops chat. The private
panel remains available. See [operation mode details](management-api.md#operation-modes).

## Set Desktop startup and tray behavior

Choose whether the bot starts when you launch HeetKit and how its window
uses the Windows notification area. Configure Twitch before enabling bot
startup. The tray options need Windows tray support.

**In HeetKit:** **Settings > Desktop behavior** on Desktop.

1. Open **Settings**.
2. Find **Startup, window and tray behavior**.
3. Set **Start bot automatically** for the next launch.
4. Set **Start minimized** if you want the next launch to start in the tray.
5. Set **Minimize to tray** if you want the minimize button to hide the window
   in the tray.
6. Set **Close to tray** if you want the close button to hide the window and
   leave HeetKit running.

Each switch saves immediately. The last two settings apply to the next
minimize or close action.

**Check:** Minimize or close the window to check the action you changed. To
check startup, quit with **Exit** from the tray menu and launch HeetKit again.

## Server browser setup

Open the private panel before you configure Twitch. You need a running Server
with private management enabled and its management token. Follow
[Linux / Docker setup](docker.md) to start a new Server.

1. Open the management URL in your browser. For the default local setup, use
   `http://127.0.0.1:8765/`. For private HTTPS, use the configured private URL.
2. Enter your management token in **Administrator token**.
3. Select **Sign in**.

**Check:** Check that **Dashboard** opens. Go to [Save the details in
HeetKit](#save-the-details-in-heetkit) to enter your Twitch settings.

Use the [private management guide](management-api.md#enable-private-access)
for access and network requirements. Keep tokens, callback URLs and profile
files out of support messages. See [Data and privacy](data-and-privacy.md).
