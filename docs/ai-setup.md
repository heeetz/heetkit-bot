# AI provider setup

## Saved connections and model setup

Connect Gemini, DeepSeek or OpenAI so HeetKit can answer `!ask` questions. You need
an API key for a provider account with access to the model you want to use. Check
the provider's limits, charges and data-use terms before you enable AI for viewers.

| Provider | Where to get a key |
| --- | --- |
| Gemini | [Google AI Studio](https://aistudio.google.com/) |
| DeepSeek | [DeepSeek platform](https://platform.deepseek.com/) |
| OpenAI | [OpenAI API keys](https://platform.openai.com/api-keys) |

**In HeetKit:** **AI > AI setup** on Desktop or Server.

1. Open **AI**.
2. Expand **AI setup**.
3. In **Providers**, select **Add provider** and choose Google, DeepSeek, OpenAI or
   Custom.
4. Optionally enter a **Name**, for example `Backup`, enter the **API key** and select
   **Add**. The key is saved immediately.
5. In **Primary model**, select your **Provider**.
6. Select a **Model**.
7. If you changed the model or options, select **Save AI setup**.

You can add several providers of the same type, for example two DeepSeek accounts.
Each one needs its own key: HeetKit refuses a key that another provider already
uses. The list stays grouped by type; a provider without a name is shown as its type
with a number, such as **DeepSeek 2**. **Edit** changes the name or replaces the key
(leave the key empty to keep it); **Remove** deletes the provider and its key.

**Check:** Check the AI controls on **Dashboard** for the active model and
[test a prompt](#test-locally-with-ai-playground).

### If the provider or model is unavailable

- In **Primary model** or **Fallback model**, select **Discover models** to load
  IDs for that card's provider. Enter a known ID in **Manual model ID**.
- Select **Test connection** to check the saved key. Discovery and this check
  cannot confirm that your account can generate a reply with the selected model.
- If the key works but the prompt fails, check model access, quota and billing
  in your provider account. Check **Logs** for the failed attempt.
- If the key says **Managed externally** on Server, change the key on the host
  and restart. See [credential storage](data-and-privacy.md#credentials-and-local-data).
- **Remove** deletes the provider and its saved key immediately. If the primary or
  fallback model uses it, the confirmation warns you; those requests then fail until
  you choose another provider. On Desktop, an environment key can still supply the
  first provider of its type. **Cancel AI edits** discards model and
  length drafts only. Keep keys out of screenshots, chat and support messages.

### Use your own OpenAI-compatible server

Run a local model, for example in LM Studio, or use another server that offers the
OpenAI `chat/completions` API. HeetKit sends one non-streaming request per question
and posts only the final answer; reasoning blocks are removed, and a reply with
reasoning only counts as a failure.

1. In **Providers**, select **Add provider > Custom**.
2. Enter the **Server address**. For LM Studio on the same PC, enter
   `http://localhost:1234/v1`. For a server on your home network or over Tailscale,
   turn on **Private networks**. See [the address rules](#custom-server-addresses-and-private-networks).
   Redirects are not followed.
3. Enter an **API key** only if the server requires one, then select **Add**.
   Editing the address to another host or port removes the saved key; enter it again.
4. Select **Test**. It lists the server's models; it cannot prove that a
   model generates replies.
5. In **Primary model**, select the custom provider, then select a
   discovered model or enter its ID in **Manual model ID**. Select **Save AI setup**.
6. [Test a prompt](#test-locally-with-ai-playground) in Playground.

The custom provider can be the primary model only. Thinking controls and internet
search are not available for it. Providers, names and addresses stay in this
profile: configuration export does not include them or the keys.

#### Custom server addresses and private networks

On Desktop, **Private networks** off allows HTTPS anywhere and HTTP only to this
computer. Turn it on for each custom provider that runs on another device in your
home network or Tailscale; then those addresses work over HTTP too.

HeetKit Server connects only to public addresses over HTTPS by default. It checks
every address a name resolves to on each connection and connects only to a checked
address. Link-local addresses (cloud metadata such as `169.254.169.254`), multicast
and reserved addresses are always refused.

To reach a model on a private network, such as LM Studio on your PC over
[Tailscale](https://tailscale.com/), the host owner first allows it: set
`HEETKIT_CUSTOM_AI_PRIVATE_NETWORKS=true` in the Server process environment (the
`bot` service's `environment` for Compose) and restart. Without it, the **Private
networks** switch stays off and disabled. Then turn on **Private networks** for that
custom provider: loopback, home-network and Tailscale (`100.64.0.0/10`) addresses are
allowed over HTTP or HTTPS for it only; other custom providers stay public-only. For LM Studio, turn on serving on the local network,
then enter its Tailscale address, for example `http://100.101.102.103:1234/v1`.
Tailscale encrypts that traffic. The optional key is saved in
`auth/server_credentials.json`, like the other Server keys.

## Test locally with AI Playground

Send a test prompt to your saved provider without posting to Twitch. You need a
[configured provider and model](#saved-connections-and-model-setup). You can test
with the bot stopped and the AI command disabled.

**In HeetKit:** **AI > AI Playground** on Desktop or Server.

1. Open **AI**.
2. Find **AI Playground**.
3. Enter a short prompt such as `What is the capital of France?`.
4. Select **Test prompt**. The test can use paid API quota.

**Check:** Look for the reply and the provider and model that answered. If the
test fails, use the error and **Logs** to check the provider settings.

Playground uses the active personality, applied instructions, saved language and
model settings, and active filters. It excludes viewer memory, stream context,
command permissions and cooldowns. For a draft opened via **Open Playground**,
choose whether to apply or save that draft, or select **Use current applied settings**.

Only one test runs at a time. Select **Cancel request** or leave **AI** to request
cancellation. Server results belong to the session that starts the test. If you
close the tab without signing out, the test can continue until it ends or expires.

## Enable AI questions in chat

Let viewers use `!ask`. You need a successful Playground test and a
[connected Twitch bot](twitch-setup.md#give-the-bot-channel-access-then-connect).

**In HeetKit:** **Dashboard > AI controls** on Desktop or Server.

1. Open **Dashboard**.
2. Turn on **AI command**. The switch saves immediately.

**Check:** From an account allowed to use the command, send `!ask What is the capital of France?`
in the target channel. Check for a reply from the bot account.

If Playground works but chat does not, check **Connected** on **Dashboard** and
the `!ask` permissions, availability and cooldowns under **Commands**. Check
[filters](commands.md#filters) and [user restrictions](commands.md#user-restrictions)
if only some prompts or users fail. **Logs** can distinguish generation from
delivery. Missing usage in a log or result means the usage is unknown.

## Conversation memory

Let HeetKit use earlier answers for a viewer in the same channel. You need AI
chat configured. One pair is a question and its successfully delivered answer.

**In HeetKit:** **AI > Conversation memory** on Desktop or Server.

1. Open **AI**.
2. Find **Conversation memory** below **AI behavior** and turn on the switch.
   The switch saves immediately.
3. Set **Stored pairs** to 1–500 per viewer per channel. The default is 100.
4. Set **Pairs in context** to 1–50, up to the stored-pair limit. The default is 5.
5. Select **Save memory limits**. **A lower stored-pair limit immediately deletes older pairs
   above the new limit, including in recovery copies.**

**Check:** Reopen the AI page and check that the switch and both limits show your saved
values. In chat, try an allowed follow-up about an earlier answer from the same
account and channel. Leave enough time for the command cooldown.

Turning memory off stops new storage and use. Existing pairs remain subject to
the count limit and 60-day expiry. See [AI processing and memory](data-and-privacy.md#ai-processing-and-memory)
and [viewer opt-outs](data-and-privacy.md#privacy-notice-for-viewers).

## Thinking, search and fallback boundaries

Adjust how the model works or add a backup model for a missing primary model.
You need a saved primary model and a key for any additional provider.

**In HeetKit:** **AI > AI setup** on Desktop or Server.

1. Open **AI**.
2. Expand **AI setup**.
3. If your model supports it, select a **Thinking effort**.
4. If your model supports it, set **Internet search**. Search and thinking can
   add time and cost.
5. If you want a backup model, turn on **Enable fallback**.
6. Under **Fallback model**, select its **Provider**.
7. Select its **Model**.
8. If the provider differs from the primary provider, check the consent box.
   When fallback runs, the other provider may receive the question, instructions
   and permitted conversation memory.
9. Select **Save AI setup**.

**Check:** Reopen **AI setup** to check the saved options. Run a Playground test
and check the reported provider, model and search status. A successful primary
request leaves the fallback unused.

- HeetKit tries fallback once, only when the primary model is unavailable (404).
  Both attempts share a 60-second deadline. Key, billing, quota, rate limit,
  refusal, filter and network failures do not trigger fallback.
- Search **Off** prevents search calls. With search **On**, the model can look up
  unfamiliar people, products, events and specific facts. It forms its own query
  from your wording and can skip search for banter, translations and simple math.
- Each selection uses its own saved Search setting. For an explicit lookup with
  search enabled on the primary, HeetKit reports the lookup unavailable if the
  primary is missing and fallback search is off. When an explicit lookup is sent
  with search enabled, a response without confirmed search is reported as a failure.
- DeepSeek can return searched answers to Twitch and Playground. OpenAI keeps
  the required citation links inline on both surfaces and withholds answers that
  exceed the saved length limit with citations included. Twitch channel link
  moderation applies. HeetKit leaves out the appended URL list.
- An AI answer that contains a link (a URL or a bare domain) to a site that is not
  one of its search sources is not sent; Activity shows reason `foreign_link`.
  Without search, any link blocks the answer.
  [Twitch link moderation](https://help.twitch.tv/s/article/how-to-manage-harassment-in-chat)
- Gemini can run Google Search, but Twitch and the current Playground lack the
  required Google Search Suggestions display. HeetKit withholds grounded replies
  and names the attribution requirement in Playground. Replies that do not use
  search can still be shown. [Google Search grounding terms](https://ai.google.dev/gemini-api/terms#grounding-with-google-search)
- Unknown model IDs use provider defaults and have no search control. Imported
  cross-provider fallback needs consent again in the destination profile.
- Saved changes apply to new requests. A request in progress uses the settings
  and keys it started with.

See [OpenAI search](https://developers.openai.com/api/docs/guides/tools-web-search),
[DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode/),
[DeepSeek search](https://api-docs.deepseek.com/guides/search/),
[Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking)
and [Gemini grounding](https://ai.google.dev/gemini-api/docs/generate-content/google-search).

**Dashboard** also lets you switch the active **Personality** and the **Main model**
without opening AI setup. Each change saves immediately.

## Personality editing

Give the bot a reply style. You can select a built-in personality or create your
own. To check its replies, you need a working provider and model.

**In HeetKit:** **AI > AI behavior > Edit personalities** on Desktop or Server.

The editor keeps drafts as you switch sections. Closing with unsaved changes
asks whether to discard them. Each section saves its own settings.

1. Open **AI**.
2. On **AI behavior**, select **Edit personalities**.
3. Choose a **Personality**.
4. To change its prompt, edit **Editable prompt**.
5. If you edited the prompt, select **Save**.
6. Select **Set active** to use the selected personality. This action uses the
   applied prompt and leaves any unsaved edit in the editor.

**Check:** Look for **Active** next to the selected personality. Test a prompt
in **AI Playground** that lets you check its style.

To create your own personality, select **New personality** in the same panel.

1. Enter a **Name**.
2. Enter a **Prompt**.
3. Select **Create**. This saves the new personality. Use **Set active** when
   you are ready to use it.

Use **Rename** or **Delete** for custom personalities. Keep secrets and
unnecessary personal data out of prompts. Profile instructions, language policy,
filters and protected safety checks still apply.

## Profile instructions

Give every personality in this profile the same guidance. You need a working
provider and model to test its effect.

**In HeetKit:** **AI > AI behavior > Edit profile instructions** on Desktop or Server.

1. Open **AI**.
2. On **AI behavior**, select **Edit profile instructions**.
3. Enter the guidance in **Profile instructions**.
4. Select **Save** to keep the instructions across restarts. For a session-only
   change, select **Apply** instead.

**Check:** Check the saved or runtime status in the editor. Use **Open Playground**
to test a prompt that exercises the instruction.

## Shared instructions and character limits

Change the common AI instructions or control how long questions and answers can be.
You need a working provider and model to test your changes.

**In HeetKit:** **AI > AI behavior > Edit shared instructions** and **AI > AI setup** on Desktop or Server.

1. Open **AI**.
2. On **AI behavior**, select **Edit shared instructions**.
3. Edit **Shared AI instructions**. Select **Reset** to
   put the default text in the draft.
4. Select **Save**. Saving an empty field removes the shared text.
5. To change the length limits, close the editor and expand **AI setup**.
6. Set **Input length limit** to 1–4000 characters. The default is 300.
7. Set **Output length limit** to 1–450 characters. The default is 220.
8. Select **Save AI setup**.

**Check:** Reopen each editor to check its saved values. Test an ordinary prompt
in Playground. If you changed the input limit, also test a question over that limit.

HeetKit replaces only `{current_datetime}`, `{ai_max_response_length}` and
`{response_language_instruction}` in shared instructions. **Save**
and **Save AI setup** apply separate drafts. The input limit counts the trimmed
question. HeetKit rejects an overlong question. The reply and mention must fit
in one Twitch message.

## Response language

Let the bot follow the question's language or limit replies to selected languages.
You need a working provider and model to test the policy.

**In HeetKit:** **AI > AI behavior > Edit response languages** on Desktop or Server.

1. Open **AI**.
2. On **AI behavior**, select **Edit response languages**.
3. Select **Auto** or **Limited** in **Response language mode**.
4. For **Limited**, select the **Allowed languages**.
5. For **Limited**, select a **Fallback language** from that list.
6. Select **Save**.

**Check:** Check **Active policy**. In **AI Playground**, test a question in an
allowed language and, in **Limited** mode, one in an unsupported language.

**Auto** follows the question. In **Limited**, mixed input uses the clear majority
language if allowed. Tied, unclear, unsupported, emoji-only and code-only input
use the fallback. The policy guides replies, and a model can still choose the wrong language.
