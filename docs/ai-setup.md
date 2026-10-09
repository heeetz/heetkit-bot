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
5. In HeetKit, open **Settings → Credentials**. Under **Gemini API key**, paste it
   into **Replacement value** and select **Replace**, even for the first key. HeetKit
   stores it securely through your operating system. It applies immediately; no restart
   is needed.
6. Select **Test** beside the credential to check access with Google. This verifies the
   key; model access and usage limits still apply.

## Choose how the bot replies

7. Open the **AI** page. Under **Models and fallback**, optionally choose a **Selected model**
   and **Fallback model**, then **Save models**. Use the supplied choices or **Discover
   models** to check availability with Google. For free usage, check your model's Free
   Tier support. Fallback handles unavailable models, not quota or billing errors.
8. Configure your AI style:

   - **Response language:** on the **AI** page, keep **Auto** to match the current
     question without language restrictions, or choose **Limited**, select allowed
     languages and a fallback, then **Save language settings**. Changes apply to the next AI
     request and are saved for this profile. The initial Limited selection is English,
     Ukrainian and Russian, with English fallback; Auto remains the default.
   - **Personality:** choose the supplied `neutral` personality or use **New personality**
     to create your own named style.
   - **Personality prompt:** describe the tone and behavior you want, such as
     “Keep replies short, playful and welcoming.” Choose **Save**, then **Set active**.
     Creating or selecting a personality in the editor alone does not activate it.
   - **Profile instructions:** optionally add guidance that applies to every personality
     in this local profile, such as your community's vocabulary. Choose **Save**
     to keep it across restarts; **Apply** affects only this session.
   - **Conversation memory:** choose whether recent successful exchanges for each chatter
     are saved locally and included in later AI requests. Turning memory off stops that
     context from being used; it does not erase stored exchanges. Do not put secrets or
     private information in prompts or chat sent to Google.

9. With Twitch connected, check that **AI command** is enabled and try
   `!ask Say hello to chat` from another account in the target channel. If you enable the
   command here, save the Ask command on **Commands** to keep it enabled after restart.
   Permissions, cooldowns and filters still apply.

## Response language

In **Limited**, a clearly identified input language is used when it is allowed;
otherwise the bot uses the selected fallback. The allowed set must contain at least
one language, and the fallback must belong to it. The AI page shows the saved active
policy separately from any unsaved selection.

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

## Personality editing

**Save** keeps a prompt without changing the active personality. **Set active** saves
the selection separately and uses it for future replies; it does not save an unsaved
prompt draft. **New personality** creates a local name and prompt without activating it.
Custom personalities can be renamed or deleted; deleting the active one selects
`neutral`. Built-ins cannot be renamed or deleted, but their prompts can be overridden;
**Reset** restores the shipped prompt.

Profile instructions apply to every personality in the current profile. **Reset** clears
that field without changing personality prompts or selection. Protected shared
instructions are read-only. Separate profiles keep their own styles and instructions.

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
