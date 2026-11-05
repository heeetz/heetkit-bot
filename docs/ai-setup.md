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
3. In **Connected providers**, enter your key in the field for your provider.
4. Select **Connect key**. If you already saved a key, select **Replace key**.
   This action saves the key immediately.
5. In **Primary model**, select your **Provider**.
6. Select a **Model**.
7. If you changed the model or options, select **Save AI setup**.

**Check:** Check **AI provider** for the expected **Active model** and
**Configured for requests**. Then [test a prompt](#test-locally-with-ai-playground).

### If the provider or model is unavailable

- If you need more model choices, select **Discover primary models**.
  If you know the model ID, you can enter it under **Manual model ID**.
- Select **Test connection** to check the saved key. Discovery and this check
  cannot confirm that your account can generate a reply with the selected model.
- If the key works but the prompt fails, check model access, quota and billing
  in your provider account. Check **Logs** for the failed attempt.
- If the key says **Managed externally** on Server, change the key on the host
  and restart. See [credential storage](data-and-privacy.md#credentials-and-local-data).
- **Remove key** deletes the saved key immediately. On Desktop, an environment
  key can still supply the credential. **Cancel AI edits** discards model and
  length drafts only. Keep keys out of screenshots, chat and support messages.

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

## Conversation memory and account balance

Let HeetKit use earlier answers for a viewer in the same channel. You need AI
chat configured. One pair is a question and its successfully delivered answer.

**In HeetKit:** **AI > Conversation memory** on Desktop or Server.

1. Open **AI**.
2. Turn on **Conversation memory** using its switch. The switch saves immediately.
3. Set **Stored pairs (N)** to 1–500 per viewer per channel. The default is 100.
4. Set **Context pairs (M)** to 1–50. The default is 5. This value must be at most N.
5. Select **Save memory limits**. **A lower N immediately deletes older pairs
   above the new limit, including in recovery copies.**

**Check:** Reopen **AI** and check that the switch and both limits show your saved
values. In chat, try an allowed follow-up about an earlier answer from the same
account and channel. Leave enough time for the command cooldown.

Turning memory off stops new storage and use. Existing pairs remain subject to
the count limit and 60-day expiry. See [AI processing and memory](data-and-privacy.md#ai-processing-and-memory)
and [viewer opt-outs](data-and-privacy.md#privacy-notice-for-viewers).

To check DeepSeek credit, open **Analytics** and select **Refresh** on
**Provider balance**. HeetKit caches the account balance for at least 60 seconds.
It shows stale or unavailable data on failure. Gemini and OpenAI balance is
unavailable in HeetKit. Channel usage estimates are separate from account balance.

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
- Search **Off** prevents search calls. **On** allows search as needed.
  Keep Gemini search off for ordinary replies. Twitch and Playground cannot
  display Google's required Search Suggestions, so HeetKit withholds grounded
  replies that require them. HeetKit also withholds answers when required sources
  do not fit the answer limit.
- Unknown model IDs use provider defaults and have no search control. Imported
  cross-provider fallback needs consent again in the destination profile.
- Saved changes apply to new requests. A request in progress uses the settings
  and keys it started with.

See [OpenAI search](https://developers.openai.com/api/docs/guides/tools-web-search),
[DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode/),
[DeepSeek search](https://api-docs.deepseek.com/guides/search/),
[Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking)
and [Gemini grounding](https://ai.google.dev/gemini-api/docs/generate-content/google-search).

## Personality editing

Give the bot a reply style. You can select a built-in personality or create your
own. To check its replies, you need a working provider and model.

**In HeetKit:** **AI > Personality-specific prompt** on Desktop or Server.

1. Open **AI**.
2. Expand **Personality-specific prompt**.
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

**In HeetKit:** **AI > Profile instructions** on Desktop or Server.

1. Open **AI**.
2. Expand **Profile instructions**.
3. Enter the guidance in **Profile instructions**.
4. Select **Save** to keep the instructions across restarts. For a session-only
   change, select **Apply** instead.

**Check:** Check the saved or runtime status in the editor. Use **Open Playground**
to test a prompt that exercises the instruction.

## Shared instructions and character limits

Change the common AI instructions or control how long questions and answers can be.
You need a working provider and model to test your changes.

**In HeetKit:** **AI > Shared instructions** and **AI > AI setup** on Desktop or Server.

1. Open **AI**.
2. Expand **Shared instructions**.
3. Edit **Shared AI instructions**. Select **Restore default instructions** to
   put the default text in the draft.
4. Select **Save instructions**. Saving an empty field removes the shared text.
5. To change the length limits, expand **AI setup**.
6. Set **Input length limit** to 1–4000 characters. The default is 300.
7. Set **Output length limit** to 1–450 characters. The default is 220.
8. Select **Save AI setup**.

**Check:** Reopen each editor to check its saved values. Test an ordinary prompt
in Playground. If you changed the input limit, also test a question over that limit.

HeetKit replaces only `{current_datetime}`, `{ai_max_response_length}` and
`{response_language_instruction}` in shared instructions. **Save instructions**
and **Save AI setup** apply separate drafts. The input limit counts the trimmed
question. HeetKit rejects an overlong question. The reply and mention must fit
in one Twitch message.

## Response language

Let the bot follow the question's language or limit replies to selected languages.
You need a working provider and model to test the policy.

**In HeetKit:** **AI > AI response language** on Desktop or Server.

1. Open **AI**.
2. Expand **AI response language**.
3. Select **Auto** or **Limited** in **Response language mode**.
4. For **Limited**, select the **Allowed languages**.
5. For **Limited**, select a **Fallback language** from that list.
6. Select **Save language settings**.

**Check:** Check **Active policy**. In **AI Playground**, test a question in an
allowed language and, in **Limited** mode, one in an unsupported language.

**Auto** follows the question. In **Limited**, mixed input uses the clear majority
language if allowed. Tied, unclear, unsupported, emoji-only and code-only input
use the fallback. The policy guides replies, and a model can still choose the wrong language.
