# AI provider setup

AI is optional. Normal Twitch commands work without it. Gemini remains the default;
Desktop and Server share saved connections for Gemini, direct DeepSeek and direct OpenAI.
Dashboard's optional setup guide can be dismissed/resumed, and AI can be skipped or
configured before Twitch. Its summary shows saved setup and the current Twitch
connection without treating an untested provider as a setup failure. The guide and
summary disappear once Twitch settings and its client secret, plus a key for at
least one AI provider, are configured. This includes an unselected provider and
does not require chat to be running or connected. Skipping AI alone does not hide
the summary. Setup remains accessible from Settings and AI. Configured
credentials, authorization and a connected chat session are separate states; the
guide never authorizes an account itself.

## Saved connections and model setup

Open **AI → AI setup** on either host:

1. Enter a masked draft in the provider row, then use **Connect key** or
   **Replace key** in **Connected providers**. **Test connection**
   checks the saved key. These operations
   apply immediately, independently of model drafts; Cancel AI edits cannot undo a saved key. Removing an in-use key warns that
   requests will become unavailable, and never selects another provider automatically.
2. In **Primary model**, choose a provider and type/search a model ID. Discover queries
   that provider's captured credential; failed or stale discovery retains selections.
   A model listing or credential test does not prove generation access or tool support.
3. Select Thinking and Internet search independently. Unsupported saved options remain
   visible until explicitly corrected; unknown/manual IDs receive provider-default
   generation only, with no invented thinking levels or search capability.
4. Enable **Fallback model** to configure its provider, model, thinking and search
   in the parallel card. Cross-provider routing requires an
   acknowledgement that questions, instructions and permitted memory may go to that
   provider. Missing keys remain unavailable; another provider's key is never borrowed.
5. **Save AI setup** validates and saves the non-secret choices together. Until then,
   requests use saved settings. Cancel restores the model and length draft. Each slot
   retains its choices when switching providers; other provider keys remain connected.

Desktop keys use the profile's OS keyring with intentional environment fallback.
Server keys use the private credential file; nonempty environment/secret-file inputs
are read-only in the panel and require host-side rotation/restart. Keys are never read
back to React or exported. See [management credentials](management-api.md#requests-and-operations).
`AI_PROVIDER`, `GEMINI_MODEL`, `DEEPSEEK_MODEL`, `OPENAI_MODEL` and their fallback counterparts remain
unsaved process defaults until profile selections override them.

## Thinking, search and fallback boundaries

OpenAI uses the Responses API. Its economical preset is `gpt-6-luna`; the independent
fallback preset is `gpt-6.1-sol`. This selection compares documented Standard text
prices and capabilities, checked 2026-10-26: Luna is $0.10 input/$0.50 output per
million tokens, versus Sol at $2/$10. Both support web search; Luna is intended for
focused, high-volume tasks. These prices and capabilities motivate the default for
short chat replies; they do not predict quality or latency for a particular prompt.
See the [Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna),
[Sol model](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and
[current pricing](https://developers.openai.com/api/docs/pricing).

Luna exposes None, Low, Medium, High, Xhigh and Max; Sol exposes Low through Max.
Provider default omits the effort field (both currently default to Medium).
Unknown IDs expose only Provider default and no search. OpenAI requests set
`store: false`, use no server conversation history and have no adapter retries.
Output is capped at 1,024 tokens with None, otherwise 4,096 including reasoning;
the existing shared 60-second deadline covers primary and fallback together.

OpenAI Web Search uses the captured OpenAI key, low search context and at most two
built-in tool calls in one Responses request. Only search selected by the shared
freshness policy sends the tool; that request requires tool use. Search costs
$10 per 1,000 calls plus model-rate search content tokens at the checked prices.
Failed/incomplete search produces no fresh answer. Native citation positions become
visible inline URLs, clickable in Playground and Twitch. Cited answers are kept whole;
if text plus URLs exceeds the saved character limit, the answer is withheld.
No host-side fetches, hidden source removal or silent search downgrade occurs. See
[OpenAI search and attribution](https://developers.openai.com/api/docs/guides/tools-web-search).
Playground reports the effective returned model and bounded input/output token counts;
safe request events record usage without prompts, keys, reasoning or tool bodies.

Thinking options come from exact documented model/API mappings. DeepSeek exposes
Off, Low, High and Max plus Provider default; Off sends its explicit disabled toggle.
Gemini models expose supported native levels or numeric budget boundaries. Models
that cannot disable thinking do not offer Off. Thinking/output token caps and the
60-second total request deadline are separate from the character limits below.
Unknown IDs omit thinking parameters; unsupported choices are rejected before work.
See [DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode/) and
[Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking).

Search Off sends no search tools or calls. On permits search when relevant; not every
reply searches. DeepSeek Search/Fetch uses the same captured key and fixed provider
endpoints, never arbitrary fetching from this host. Limits are three tool rounds,
four calls, 64 KiB of returned context and 12 seconds per tool within the total
deadline. Retrieved pages are untrusted context. Failures produce no purported fresh
answer. Only final answer text and safe source metadata leave an adapter; transient
reasoning/tool continuation is never chat, memory or diagnostic history.
[DeepSeek Search/Fetch](https://api-docs.deepseek.com/guides/search/) documents the service.

DeepSeek source URLs are appended within the configured answer bound. If required attribution
cannot fit, the answer is withheld rather than losing its sources. Gemini Google Search
remains implemented, but its required Search Suggestions cannot be rendered in plain
Twitch chat: grounded output is withheld with an attribution-unavailable result.
The UI explains this limitation. Leave Gemini search Off for ordinary Twitch replies;
this also applies to the plain-text Playground on Desktop and Server. See
[Google's grounding/display requirements](https://ai.google.dev/gemini-api/docs/generate-content/google-search).
Thinking and search may add provider charges; consult the provider rather than relying
on a price table in the app.

The shared owner allows at most one fallback, only after a model-unavailable (404)
response. Credential, billing/quota, rate-limit, network, refusal, filter and bad-parameter
failures never trigger it. Fallback uses its own effort and search choice. If requested
search is unavailable there, no downgraded answer is sent. Both selections, credentials,
instructions and permitted context are captured before awaiting; later edits affect
subsequent requests. Cancellation and existing privacy/late-result checks still apply.

Portable configuration includes the selections, per-provider choices, instructions and
lengths without credentials. Old same-provider fields/archives remain accepted. Imported
cross-provider consent is cleared: acknowledge and Save in the destination before it
can route a fallback. The primary can still run. Legacy model operations accept a model
pair; after advanced setup exists, provider-only switching must use the setup operation
so independent settings cannot be silently lost.

## Shared instructions and character limits

Open **AI → Shared instructions**, below **Profile instructions**. Both this editor and
**AI setup** are collapsed until opened manually or through a sidebar/setup shortcut.
**Save instructions** persists only the shared text, preserving model and length drafts.
**Save AI setup** preserves unsaved instruction edits. Empty deliberately removes the
shipped text. **Restore default instructions** changes the draft; Save applies it.
**Cancel instruction edits** restores the saved text. Only the documented
`{current_datetime}`, `{ai_max_response_length}` and `{response_language_instruction}`
placeholders are substituted; other braces remain literal.

The input/output length limits stay together inside **AI setup** and save with the model
choices. Maximum question length is 1–4000 characters (default 300); only the current trimmed
question counts, not instructions or memory. Overlong questions are rejected before AI
memory/provider work, rather than truncated. Maximum answer length is 1–450 characters
(default 220 for existing profiles), enforced in the prompt and final output. Language
policy, local request/full-output checks and profile filters remain explicit independent
restrictions; editing shared text does not disable those checks. Their scope is shown
beside the editor and described under [Personality editing](#personality-editing).
Provider policies, credential isolation and management authentication remain in force.
The outgoing mention must also fit Twitch's 500-character envelope and valid UTF-8;
longer answers never authorize split sends. See [Send Chat Message](https://dev.twitch.tv/docs/api/reference/#send-chat-message).

## Get a key and add it to HeetKit

For OpenAI, create a project API key in the [OpenAI platform](https://platform.openai.com/api-keys),
enter it in **AI → AI setup → Connected providers → OpenAI**, and choose **Connect key**.
Choose OpenAI as primary or fallback, select the model and native effort, then
**Save AI setup**. Credential testing and discovery only probe `/v1/models`; they do
not establish generation/search access or available quota. Desktop uses its existing
profile keyring with `OPENAI_API_KEY` as an environment fallback. Server supports
the private credential file or authoritative `OPENAI_API_KEY` / `OPENAI_API_KEY_FILE`.

For DeepSeek, create an API key in the [DeepSeek platform](https://platform.deepseek.com/),
then enter it in **AI → AI setup → Connected providers → DeepSeek** and select
**Connect key**. Choose **DeepSeek** in **Primary provider**, choose a model and
**Save AI setup**. The key is separate from a Gemini key. **Test connection** checks
the saved credential; generation still depends on model access and provider limits.

For Google Gemini:

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
5. In HeetKit, open **AI → AI setup**. Enter the key in the masked **Google Gemini API key**
   field, then select **Connect key**. For an existing key, enter its
   replacement in the same field and select **Replace key**. HeetKit
   stores it securely through your operating system. It applies immediately; no restart
   is needed.
6. Select **Test connection** beside the key to check access with Google. This verifies the
   key; model access and usage limits still apply.

The masked key field and its actions are in **AI setup**. The question-mark help explains
validation and generation testing.

## Choose how the bot replies

Open **AI**. AI setup comes first; existing State, Playground, Personality,
Profile instructions, Shared instructions and Response language sections
remain available.
Sidebar shortcuts scroll to each section. Collapsing editors retains their drafts;
Enter/Space operates disclosure headers. State shows AI command/memory preferences,
active model availability and personality. Command and memory switches save immediately.

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
   - **Models:** use the primary/fallback cards in AI setup above, then Save AI setup.
     Playground uses the saved configuration and warns while editor drafts exist.
   - **Conversation memory** in **AI → State:** choose whether successful `!ask` exchanges are kept locally
     and included in later requests for that viewer in the same channel. Each exchange
     expires after 60 days, with a default cap of 100 stored pairs and five context pairs
     per viewer/channel. Validated backend N/M limits and the self-only `!optout` route
     are described in the [privacy notice](data-and-privacy.md#privacy-notice-for-viewers).
     Turning memory off
     stops subsequent use and storage; automatic expiry still applies to prior exchanges.
     See [privacy requests and provider restrictions](data-and-privacy.md) before using AI
     with viewers. Do not put secrets or private information in prompts or chat sent to Google.

Provider keys can be connected and tested in AI setup. Testing a key does not establish
model access or quota.

9. With Twitch connected, check that **AI command** is enabled and try
   `!ask Say hello to chat` from another account in the target channel. The enabled switch
   on **Dashboard**, **AI** or **Commands** saves immediately and survives restarts;
   all three views stay synchronized. A save failure keeps the previous value and shows
   an error. Other drafts, permissions and cooldowns still need their own Save/Apply.
   Permissions, cooldowns and filters still apply. Open the existing `!ask` editor in
   **Commands** when you need to change its permission or cooldowns. Manage individual
   account access through **User restrictions** on that page.

## Test locally with AI Playground

On Desktop or the authenticated Server panel, open **AI → Playground** and enter a prompt to make a real provider request without
posting to Twitch. Testing can consume real provider API usage. The Playground uses the
active filters and personality, applied profile instructions, and saved primary/fallback,
thinking, search and response-language settings. It does not automatically use editor drafts: explicitly
save a personality, model or language draft first; apply or save a profile-instruction
draft. Choosing **Use current applied settings** keeps all editor drafts out of the test.

Each prompt is independent of viewer memory, Twitch chat activity, stream context,
`!ask` permissions and command cooldowns. The bot may be stopped and `!ask` may be
disabled. A successful result confirms only this provider path; it does not prove
that Twitch is connected or that a chat reply can be delivered. Only one Playground
request runs at a time; you can cancel it, and it times out after 60 seconds. The result
distinguishes a successful response, editable-filter or protected-policy input and output
blocks, filter timeouts, provider/model unavailability, configuration/search/attribution
failures, API errors, timeouts and cancellation.
Protected decisions do not reveal hidden instructions.

Results show the effective provider, model, thinking selection, fallback use and
Search/Fetch outcome reported by the shared pipeline. Provider error bodies, keys,
reasoning and tool payloads are never displayed. Grounded Gemini output still has
the plain-text attribution restriction described above.

Server requests run on the backend through authenticated management operations.
Only the bearer session that started a request can inspect or cancel it. Signing out,
session expiry or eviction cancels its work and removes access to its result, even
without another poll. Application shutdown also cancels Playground work before closing
provider clients. Leaving the AI page requests cancellation on either host. Closing
a browser tab without signing out relies on the 60-second deadline or session expiry.
Cancellation keeps the single slot occupied until provider cleanup finishes; late
responses after cancellation or timeout are discarded. No prompt/result history is saved.

Playground and `!ask` share the same backend generation policy. Each request captures
its applied instructions, personality, language, context, model choices and key before
provider work begins; model fallback uses that same snapshot. Settings edits apply to
subsequent requests. Full responses pass the output checks before the saved
answer character limit is applied, using any global filter changes active when
the response arrives. Existing profiles continue to use Gemini without migration.

## AI question access

Manage per-account AI access in **Commands > User restrictions**. Select the current
`!ask` command for channel scope, or choose **Block AI questions across all channels
in this profile**. Stable command/account IDs preserve enforcement across aliases and
renames. Rules combine; removing one does not override another active rule.

The former AI Access list migrates to permanent channel `!ask` rules. Unresolved
legacy names stay visible and removable with safe login compatibility until identity
can be verified. See [User restrictions](commands.md#user-restrictions) for migration
and scope details. Playground remains unchanged and independent of chat access rules.
Access restrictions do not erase history or ban users on Twitch. Use `!erase` for
channel AI-memory deletion, or Administrative commands' **!optout** card for profile-wide
storage opt-out/deletion and confirmed withdrawal.

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
personality prompts or selection. Shared instruction text is editable in its own
Shared instructions section; the disclosed local checks remain enabled. Separate
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

## Generation diagnostics

Semantic AI events link to the command request and identify requested and effective
provider/model, attempt number, fallback use and elapsed time. All adapters normalize
reported numeric usage, including failed/fallback attempts and tool continuations.
Cached input and reasoning are subsets of inclusive input/output totals; missing usage
stays unknown. Events exclude keys, prompts, response payloads and reasoning content;
storage opt-outs suppress these request diagnostics along with command/send events.
Generation and handler completion are separate from confirmed Twitch delivery. A failed
or uncertain send is not saved as delivered AI memory. Existing Desktop diagnostics and
Server lifecycle-log visibility remain as described in [data and privacy](data-and-privacy.md).
Separate [daily local aggregates](data-and-privacy.md#daily-local-aggregates) retain
bounded usage/latency counters and incomplete dated spend estimates, without saved
exchanges or provider payloads. Playground usage is separate from channel usage.

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
