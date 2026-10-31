# AI provider setup

AI is optional. Desktop and Server support Gemini, DeepSeek and OpenAI through the
same request pipeline. Start with a saved key and model, then use Playground to test.
A connected key does not guarantee model access, available credit or a working chat connection.

## Saved connections and model setup

Open **AI > AI setup**:

1. Under **Connected providers**, enter a key and choose **Connect key**. Replace,
   remove and test actions affect the saved credential immediately.
2. In **Primary model**, choose the provider and model. Discovery lists available
   IDs; you can also enter one. Listing a model does not prove generation access.
3. Choose supported thinking/search options. Unknown model IDs use provider defaults;
   HeetKit does not guess their capabilities.
4. Optionally configure **Fallback model**. A different provider needs its own key
   and explicit consent to send requests there.
5. Choose **Save AI setup**. Model/options drafts do not apply until saved.
   Cancel discards those drafts; it does not undo credential actions.

Desktop stores keys in the profile's OS keyring. Server uses its private credential
file. Host-provided environment/secret-file credentials are read-only in the panel;
rotate them on the host and restart. Keys are not returned to the page or included
in configuration exports. See [credential storage](data-and-privacy.md#credentials-and-local-data).

## Conversation memory and account balance

In **AI > Conversation memory**:

- The switch immediately enables/disables subsequent memory use and storage.
- **Stored pairs (N):** 1–500, default 100, per viewer/channel.
- **Context pairs (M):** 1–50, default 5, no greater than N.
- Save applies both limits; reducing N prunes older pairs immediately. Pairs also
  expire after 60 days. Disabling memory does not immediately erase prior pairs.

A pair is a question and its successfully delivered answer. Playground never uses
viewer memory. See [privacy and opt-outs](data-and-privacy.md#privacy-notice-for-viewers).

**Analytics > Provider balance** can refresh the account-wide DeepSeek balance.
It is cached for at least 60 seconds; failures show stale or unavailable values.
Gemini/OpenAI balance is unavailable. Balance is separate from channel spend estimates
and does not control generation.

## Thinking, search and fallback boundaries

Thinking and search are separate model-dependent choices. They can add cost and
latency. Search Off makes no search calls; On allows search when the request needs it.

- **OpenAI:** Responses API, `store: false`, no server conversation history. Search
  uses the selected key and at most two built-in tool calls.
- **DeepSeek:** direct requests and bounded provider Search/Fetch. Retrieved pages
  are untrusted context, not instructions to the bot or arbitrary host-side fetching.
- **Gemini:** supported thinking controls are available. Grounded output is withheld
  when Google's required Search Suggestions cannot be rendered in plain-text Twitch
  chat or Playground. Leave search Off for ordinary Gemini replies.

Source links must fit the answer limit; HeetKit withholds an answer if required
attribution cannot fit. It does not silently remove sources or downgrade search.
One shared 60-second deadline covers primary and fallback. At most one fallback
runs, and only after a model-unavailable (404) response. Quota, billing, credentials,
rate limits, refusals, filters and network errors do not trigger fallback.

Requests capture saved settings and credentials when they start. Later edits apply
to later requests. Imported cross-provider consent must be acknowledged again at
the destination before that fallback can run.

Provider references: [OpenAI search](https://developers.openai.com/api/docs/guides/tools-web-search),
[DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode/),
[DeepSeek search](https://api-docs.deepseek.com/guides/search/),
[Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking),
[Gemini grounding](https://ai.google.dev/gemini-api/docs/generate-content/google-search).

## Shared instructions and character limits

**AI > Shared instructions** applies across personalities. **Save instructions**
saves only that text; it does not save model drafts. Restore defaults changes the
text draft; Save applies it. Saving empty text deliberately removes the default text.

Only `{current_datetime}`, `{ai_max_response_length}` and
`{response_language_instruction}` are substituted. Other braces remain literal.

Question limit: 1–4000 characters, default 300; it measures the current trimmed
question, not instructions/memory. Overlong questions are rejected, not truncated.
Answer limit: 1–450 characters, default 220. Mentions must also fit Twitch's message
limit. Longer answers do not authorize multiple sends. Save limits with AI setup.

## Get a key and add it to HeetKit

Create a key in your chosen provider's dashboard, then connect it under **AI setup**:

| Provider | Key/account dashboard |
| --- | --- |
| Gemini | [Google AI Studio](https://aistudio.google.com/) |
| DeepSeek | [DeepSeek platform](https://platform.deepseek.com/) |
| OpenAI | [OpenAI API keys](https://platform.openai.com/api-keys) |

Treat a key like a password. Never post it in chat, screenshots, Git or support logs.
**Test connection** checks the saved credential; use Playground to test generation.

## Choose how the bot replies

Use **State** for AI command enablement and active status; its switch saves immediately.
Permissions/cooldowns remain in the `!ask` editor under Commands. **Conversation memory**
has its own switch and limits. The rest of the AI page controls saved request settings:

- **Personality:** a reusable reply style. Save its prompt and activate it separately.
- **Profile instructions:** guidance for every personality in this profile. Apply is
  session-only; Save applies and persists it.
- **Shared instructions:** common generation guidance, saved independently.
- **Response language:** Auto, or an explicit allowed list and fallback.

Editors keep unsaved drafts when collapsed. Opening Playground lets you choose
between saving/applying a supported draft and testing the currently applied setup.
Drafts are never silently included in a request.

## Test locally with AI Playground

Open **AI > Playground** on either host. A test makes a real provider request and can
consume paid quota, but sends nothing to Twitch. The bot can be stopped and `!ask`
disabled. Only one Playground request runs at once; cancel it or wait for the
60-second deadline.

Playground uses applied instructions/personality, saved model/thinking/search/language
settings and active filters. It excludes viewer memory, chat activity, stream context,
command permissions and cooldowns. Success proves that provider request only, not
Twitch delivery. Results show effective provider/model, fallback/search status and
available usage. Keys, provider error bodies, reasoning and tool payloads are excluded.

Server results belong to the initiating authenticated session. Cancel or leave the AI
page to request cancellation; stale results cannot appear in a later request. Closing
a tab without signing out relies on the request timeout or session expiry.

## AI question access

Use **Commands > User restrictions** to limit individual accounts. Choose a channel
rule or **Block AI questions across all channels in this profile**. These are local
access rules, not Twitch bans. Removing one rule does not override another active rule.
`!optout` concerns local storage and remains available under command restrictions.

## Response language

**Auto** follows the current question. **Limited** uses the selected allowed languages
and a fallback; save to apply. Language policy remains active regardless of personality
or shared-instruction wording. It is guidance for generation, not guaranteed detection.

## Personality editing

Create, save, activate and delete personalities in **AI > Personalities**. Saving a
prompt does not activate it; activating a personality does not save its draft.
Profile/shared instructions and language policy still apply. Editable prompts cannot
disable the application's protected safety checks, filters, credential boundaries or
management authentication. Do not put secrets or unnecessary personal data in prompts.

## Generation diagnostics

Logs distinguish request, provider attempt, fallback and delivery outcomes. Missing
usage is unknown, not zero; a generated answer is not proof it reached Twitch.
Use private Logs to inspect failures. Review any export before sharing it.

## Free Tier and billing

Provider limits, billing and data-use terms depend on the provider, account and model.
Check them before enabling AI for viewers; the app's estimates are not invoices.
See [provider/privacy considerations](data-and-privacy.md#legal-assessment-and-open-questions).
