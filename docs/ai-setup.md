# AI / Gemini setup

Gemini is **optional**. Normal Twitch commands, including weather, followage and custom
commands, work without it. For AI replies through `!ask`, add an API key: a private
credential that lets HeetKit send requests to Google's Gemini service.

## Get a key and add it to HeetKit

1. Open [Google AI Studio](https://aistudio.google.com/) and sign in with your Google account.
2. Open the dashboard's **API Keys / Projects** area. New users may already have a default
   project and key after accepting Google's terms. A project groups keys, usage limits
   and billing settings.
3. If you do not have a key, choose **Create API key** on **API Keys**, then create or
   select a project. To use an existing Google Cloud project, first import it through
   **Projects → Import projects**.
   Google's [API key guide](https://ai.google.dev/gemini-api/docs/api-key) covers the current steps.
4. Copy the key. Treat it like a password: never share it, post it in chat, commit it to
   Git or include it in screenshots.
5. In HeetKit, open **Settings → Gemini API key**. Paste it into **New value** and
   select **Add key**. For an existing key, use **Replacement value → Replace key**. HeetKit
   stores it securely through your operating system. It applies immediately; no restart
   is needed.
6. Select **Test credential** beside the credential to check access with Google. This verifies the
   key; model access and usage limits still apply.

The key field spans the section. **Return to AI Playground** and the key actions
share its footer; the question-mark help explains validation and generation testing.

## Choose how the bot replies

Open **AI**. Its sections follow the working order **State → Playground → Personality
and profile instructions → Language → Models → AI access → Built-in
restrictions**. Use the AI sidebar shortcuts to open and scroll to a section. Collapsing
an editor keeps its draft. Editor headers also open or close with Enter or Space.
Use the question-mark buttons for extra explanations; focus or select one for
immediate help, or hover briefly. Escape dismisses help without changing your draft.

**State** contains four compact panels: **AI command**, **Conversation memory**,
**Gemini** and **Active personality**. The command and memory switches save immediately.
Gemini shows availability and the active model together; **Manage** opens its key in
Settings. State's help explains key validation and memory retention.

7. Configure the instructions used for generation:

   - **Personality:** choose the supplied `neutral` personality or use **New personality**
     to create a saved custom style without activating it. Editing a prompt creates a draft;
     the draft is not used until you save it. Saving a personality prompt does not make
     that personality active. Setting a personality active does not save an unsaved prompt
     draft.
   - **Profile instructions:** optionally add guidance that applies to every personality in
     this local profile, such as your community's vocabulary. Apply/use the draft for the
     current session, or save it to apply it now and keep it across restarts. Personality
     prompt, active-personality and profile-instruction saves are independent.
   - Personality and profile editors place **Open Playground** on the left of the
     same footer as their save/apply/reset actions. With a draft, choose whether to save it
     before opening Playground or use the current applied settings and keep the draft.
     Profile instructions also offer a session-only apply choice. To test an inactive
     personality, save its prompt and set that personality active separately.

8. Configure the remaining saved request settings:

   - **Response language:** keep **Auto** to match the current question without language
     restrictions, or choose **Limited**, select allowed languages and a fallback, then
     **Save language settings**. The initial Limited selection is English, Ukrainian and
     Russian, with English fallback; Auto remains the default.
   - **Models:** the primary model is shown directly. Custom primary-model selection and
     the fallback model are advanced controls. Save model changes before testing them.
     **Discover models** lists compatible text-generation models visible through Google.
     It shares an action row with **Open Playground** and **Save models**; opening
     Playground with a draft still requires an explicit choice.
     The fallback is tried only when a request to the primary model returns 404. Key,
     network, policy, quota, rate-limit and billing failures do not trigger it.
   - **Conversation memory** in **AI → State:** choose whether successful `!ask` exchanges are kept locally
     and included in later requests for that viewer. Successful history expires after 90 days;
     only the five most recent unexpired exchanges are used as context. Turning memory off
     stops subsequent use and storage; automatic expiry still applies to prior exchanges.
     See [privacy requests and provider restrictions](data-and-privacy.md) before using AI
     with viewers. Do not put secrets or private information in prompts or chat sent to Google.

The Gemini key is managed only under **Settings → Gemini API key**; AI provides a link
there and Settings provides a return path. **Test credential** checks access with Google,
but it does not prove that a generation request, selected model or quota will succeed.

9. With Twitch connected, check that **AI command** is enabled and try
   `!ask Say hello to chat` from another account in the target channel. The enabled switch
   on **Dashboard**, **AI** or **Commands** saves immediately and survives restarts;
   all three views stay synchronized. A save failure keeps the previous value and shows
   an error. Other drafts, permissions and cooldowns still need their own Save/Apply.
   Permissions, cooldowns and filters still apply. Use **AI access** to open the existing
   `!ask` editor in Commands when you need to change its permission or cooldowns.

## Test locally with AI Playground

Open **AI → Playground** and enter a prompt to make a real Gemini request without
posting to Twitch. Testing can consume real Gemini API quota. The Playground uses the
active filters and personality, applied profile instructions, and saved model and
response-language settings. It does not automatically use editor drafts: explicitly
save a personality, model or language draft first; apply or save a profile-instruction
draft. Choosing **Use current applied settings** keeps all editor drafts out of the test.

Each prompt is independent of viewer memory, Twitch chat activity, stream context,
`!ask` permissions and command cooldowns. The bot may be stopped and `!ask` may be
disabled. A successful result confirms only this local Gemini path; it does not prove
that Twitch is connected or that a chat reply can be delivered. Only one Playground
request runs at a time; you can cancel it, and it times out after 60 seconds. The result
distinguishes a successful response, editable-filter or protected-policy input and output
blocks, filter timeouts, provider unavailability, API errors, timeouts and cancellation.
Protected decisions do not reveal hidden instructions.

## Blocked AI users

Open **AI → AI access**. Enter a **Twitch username** and select
**Block user**. An optional `@` and surrounding whitespace are accepted; names are
case-insensitive. Empty, duplicate or invalid login names are rejected. Select
**Unblock** beside an entry to restore access. Changes apply immediately, save for
the selected profile and survive a restart; the user does not need to be online.
Blocking and unblocking also work while the bot is stopped. If a change fails,
feedback beside the form explains the next action; the entered username and previous
list remain available. A timed-out block requests cancellation. Check **Logs** and
reopen the AI page to refresh the saved list before retrying, since work that already
finished saving may complete after the deadline.

The footer's **Edit !ask access and cooldowns** opens the command's existing settings.
Use the help beside **AI access** for the distinction between AI blocking and Twitch bans.

When available, HeetKit resolves the account ID through its existing Twitch connection
or previously observed chatter records. Otherwise it keeps the normalized login and
captures a verified account ID on the first matching blocked request. ID-based blocks
follow the account after a rename and do not block another account merely using its
old login or display name. An unresolved login remains a username fallback until
a verified ID becomes available.

Blocked `!ask` requests, including aliases, are silently ignored before AI cooldowns,
conversation memory, Gemini calls or prompt-text logging. A minimal `ai_user_blocked`
event may appear in Logs. Other commands and ordinary chat are unaffected, and the
local **AI Playground** remains available to the owner. This list does not ban users
from Twitch chat, delete Twitch messages or erase existing activity or AI memory. Use the
broadcaster-only `!erase <username>` command to delete stored AI memory for a known user;
it does not delete the user's activity record. AI blocking, Twitch moderation and data
deletion are separate actions.

## Response language

In **Limited**, a clearly identified input language is used when it is allowed;
otherwise the bot uses the selected fallback. The allowed set must contain at least
one language, and the fallback must belong to it. The AI page shows one saved active
policy description when unchanged, and compares it with the draft when edited.

Language selection uses prose in the current question. Clear short greetings such as
“Привіт” or “Привет” identify Ukrainian or Russian. Mixed or code-switching messages
use a language only when it has a clear strict majority of the language-bearing words;
an unsupported majority uses fallback. Ties (for example “Hello Привіт”), unclear short
text such as “ok”, emoji-only and code-only messages use fallback. Quoted text, code,
URLs, names and numbers do not determine the language.

Conversation memory, stream context, editable personalities, profile instructions and
requests to switch language cannot override the protected response-language policy.
Gemini interprets these rules within the existing generation request: no separate
language-detector service or extra model call is used. These are prompt instructions,
not a guarantee of perfect detection or output language. Literal names, code and
necessary quotations may retain their original text. Non-AI commands are unaffected.

The language footer shows the saved/draft state beside **Open Playground** and
**Save language settings**. Its question-mark help holds the detailed policy explanation.

## Personality editing

An editor change starts as a draft and is unused until saved. **Save** persists the prompt
and updates that personality's runtime copy without changing which personality is active.
Future replies use it when that personality is active. **Set active** persists the
personality selection separately; it does not save an unsaved prompt draft.
**New personality** creates a saved local name and prompt without activating it.
Custom personalities can be renamed or deleted; deleting the active one selects
`neutral`. Built-ins cannot be renamed or deleted, but their prompts can be overridden;
**Reset** restores the shipped prompt.

Profile instructions apply to every personality in the current profile. Applying a draft
uses it for this session; saving uses it now and persists it. Neither action saves a
personality prompt or active selection. **Reset** clears that field without changing
personality prompts or selection. Protected shared instructions are read-only. Separate
profiles keep their own styles and instructions.

The protected policy allows gaming trash talk, sarcasm and light swearing about
behavior, plus neutral discussion of children, disabilities and illness. It excludes
sexual or cruel content involving minors, abuse based on personal characteristics,
self-harm encouragement, real-world threats, stalking and disclosure of personal
information. The bot also stays out of real-world wars, terrorist attacks, tragedies
and political protests or revolutions, including the Orange Revolution and Revolution
of Dignity. Harmless game mechanics, fiction and unrelated metaphors remain allowed.

Restricted `!ask` requests are silently ignored. Blocked generated replies are discarded
without a substitute reply or inclusion in chat, conversation memory or logs. Editable
styles and profile instructions cannot disable these safeguards. Protected instructions
and local context checks reduce unsafe replies; they do not guarantee perfect detection.

See [data and privacy](data-and-privacy.md) for memory, provider processing and backups,
and [commands](commands.md) for filters, permissions and cooldowns.

## Free Tier and billing

Google provides a **Gemini API Free Tier** for supported models within their limits.
Payment is unnecessary when that tier supports your model and use case. See Google's
[current model pricing](https://ai.google.dev/gemini-api/docs/pricing).

If you choose paid usage, use **Set up billing** for your project in Google AI Studio to
link a billing account. Requirements, minimum prepay amounts and model prices can change.
Before enabling paid usage, check the live
[Gemini billing guide](https://ai.google.dev/gemini-api/docs/billing) and pricing page
for current requirements. API usage is billed by **Google**, not HeetKit.

If `!ask` fails, test the key, check the model and Google's quota/billing status, and read
HeetKit's Logs for the error. Normal commands remain available without Gemini.

[Twitch setup](twitch-setup.md) · [Back to README](../README.md#getting-started).
