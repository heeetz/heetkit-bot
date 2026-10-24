# Private management API

The headless runtime has an optional HTTP API for one administrator managing one
bot. It reuses the desktop's application operations, command namespace, validation,
configuration stores and active runtime. The same listener serves the existing
React interface for browsers and an explicit JSON API for native clients.

## Enable private access

The API can start with a fresh, unconfigured profile. It is disabled by default.
Enable it with `--management-api`; the
default bind is `127.0.0.1:8765`. Supply `HEETKIT_MANAGEMENT_TOKEN_FILE` pointing to
a private ASCII file, or `HEETKIT_MANAGEMENT_TOKEN` through a private service
environment. Providing both fails. Files must be regular, at most 1 KiB, and contain
43–128 URL-safe characters with an optional trailing newline. Generate the value
from at least 32 random bytes. There is no default token, token in a URL/CLI option,
public registration or cookie authentication. Setup requires authentication from
the first request, including on a fresh installation.

For example, on Linux, create a new file outside the checkout without printing
its contents or placing the secret in shell history:

```bash
install -d -m 700 "$HOME/.config/heetkit-secrets"
python - <<'PY'
import os, secrets
from pathlib import Path
path = Path.home() / ".config/heetkit-secrets/management_token"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="ascii") as output:
    output.write(secrets.token_urlsafe(32) + "\n")
PY
export HEETKIT_MANAGEMENT_TOKEN_FILE="$HOME/.config/heetkit-secrets/management_token"
python -m app.headless --data-dir /absolute/private/profile --management-api
```

On Windows, create the secret file under a private directory with owner-only ACLs
and set the same environment variable to its absolute path. The token grants full
management authority. Protect it like the profile's other secrets. Rotate it by
replacing the private file and restarting the process; existing values remain in
memory until restart. No token content is exported to the environment from a file.

`--management-host` accepts a literal loopback or private bind IP;
`--management-port` sets port 1–65535. Outside HTTPS proxy mode, an explicit
all-interface bind additionally requires `--management-allowed-host IP:port`, an
exact trusted HTTP Host authority. Loopback's default Host allowlist accepts its
configured IP and `localhost`, with the configured port. Forwarding headers are
rejected outside explicitly configured proxy mode. IPv6 authorities use `[address]:port`.
For a different local IPv4 loopback, pass `--management-host 127.0.0.2` and open
`http://127.0.0.2:8765/`. HTTP browser access recognizes IPv4 loopback addresses
in `127.0.0.0/8`, `localhost` and IPv6 `::1`, but still requires an exact allowed
Host and matching Origin, including the published port.

Keep this service on loopback or an explicitly trusted private interface. Do not
publish it to the internet. HTTP carries the bearer token in each request: use an
SSH tunnel or a protected private network when accessing another machine. This
feature does not provision TLS, tunnels, proxies, cloud resources or firewall rules.

## Local Twitch callback

Local Server authorization returns to `http://localhost:8765/oauth/callback` by
default, on the existing management listener. Register that **exact URL** in the
Twitch Developer Console and start a new Connect Twitch attempt after changing it.
Use the callback displayed in Settings when the management/published port differs.
Twitch's [Authorization Code Grant](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#authorization-code-grant-flow)
supports localhost HTTP callbacks; the registered URL, authorization request and
server-side code exchange must match, including port and path. Keep Desktop's
`http://localhost:4343/oauth/callback` registration if you also use Desktop.
Server no longer sends authorization to that Desktop listener.

With the default Docker management overlay, Twitch redirects the browser to the
already published loopback port; no second listener or port publication is needed.
Keep the initiating Settings tab signed in. The callback validates its pending state,
exchanges the code and persists verified authorization on the server, then redirects
to an inert `/oauth/result` page. Settings reports success/failure automatically.
Only these two routes accept the exact `localhost:published-port` callback authority
when the management Host is an explicit `127.0.0.1:published-port`; this does not
add localhost to the API's Host allowlist. Existing Host/Origin/proxy checks remain.

Automatic localhost callbacks apply to `127.0.0.1` or `::1` access, including an SSH
tunnel on the displayed port. An alternate loopback such as `127.0.0.2` does not
necessarily receive localhost traffic. Those configurations retain authenticated
paste completion using the displayed localhost callback **on the management port**:
copy the full error-page URL into the initiating Settings tab within five minutes.
Keep other HeetKit instances on that callback port stopped. For automatic completion,
use the default loopback binding or configure private remote HTTPS below. Never
publish port 4343 or a public listener to repair a Server callback.

### Twitch authorization diagnostics

If Twitch returns a code and Settings reports a failed attempt, inspect the private
Server stderr/container logs. Each failure identifies the operation, exception class
and an HTTP status (or `none` when unavailable), for example:

```text
Server Twitch OAuth failed operation=user_lookup exception=HTTPException http_status=403
```

| Operation | Meaning |
| --- | --- |
| `callback_response`, `client_create` | Denial/invalid code, or temporary client construction |
| `code_exchange` | Server exchanged the authorization code with Twitch |
| `token_registration` | TwitchIO registered, validated or refreshed the user token |
| `account_verification` | Application, bot ID/login and required scopes were checked |
| `user_lookup`, `target_verification` | Authenticated Twitch user lookup, then bot/channel identity matching |
| `session_validation` | Initiating session and attempt were checked again before saving |
| `token_persistence` | Atomic private token-cache write |
| `client_cleanup` | Temporary HTTP client/token-validation task cleanup |
| `runtime_reconciliation` | Runtime connection status was reconciled after cleanup |

An accepted callback is distinct from a successful exchange, lookup or save. Use
the failing operation to investigate; a later-stage failure does not by itself mean
the registered redirect or credentials are wrong. Cleanup failures are recorded
separately when another operation already failed. The normal browser log feed
uses an allowlisted activity projection; callback diagnostics remain in private Server logs.
No exception text, traceback, response body, code, token, secret or callback query
is logged. Failed attempts consume their state; start a new Connect Twitch attempt
after addressing the identified failure rather than replaying a callback URL.

## Private remote HTTPS

The preferred Linux server reference uses host-side **Tailscale Serve**, providing
HTTPS to authorized devices on the tailnet. Use Serve, not public Funnel. Install
and authenticate Tailscale on the host and browsing devices, enable tailnet HTTPS,
and restrict access to the intended administrator through tailnet policy. See the
[Serve command](https://tailscale.com/docs/reference/tailscale-cli/serve).
HeetKit still requires its management token; Tailscale identity grants no API authority.

First create the private secret directory, two provider secret files (empty is
valid for browser setup), and random management token as described in
[Docker preparation](docker.md#prepare-private-storage-and-authorization) and above.
Keep the parent directory mode 700 and the three mounted files readable by UID
10001 (mode 444 under that parent). No profile import is needed for a fresh server.
From a Linux checkout with Docker Engine/Compose and Tailscale already installed:

```bash
export HEETKIT_SECRETS_DIR="$HOME/.config/heetkit-secrets"
export HEETKIT_MANAGEMENT_ORIGIN=https://server.example-tailnet.ts.net
export HEETKIT_TWITCH_REDIRECT_URI="$HEETKIT_MANAGEMENT_ORIGIN/oauth/callback"
docker compose -f compose.yaml -f compose.remote.yaml up -d --build
sudo tailscale serve --bg http://127.0.0.1:8765
tailscale serve status
```

Replace the example hostname with the exact HTTPS name reported by your host's
Tailscale configuration. Open that HTTPS origin from an authorized tailnet device
(including a phone), sign in with the privately retrieved management token, and
follow [Server setup](twitch-setup.md#server-browser-setup). Keep these non-secret
variables set for subsequent Compose operations. This overlay uses **Linux host
networking** so the application binds only host `127.0.0.1:8765` and sees Serve's
actual socket peer as `127.0.0.1`. It adds no published ports, DNS, certificates or
cloud resources. Do not combine it with `compose.management.yaml`; that separate
bridge-network overlay remains the Docker Desktop/local/SSH option. Base profile,
UID, read-only filesystem, secrets and restart protections remain in use. Verify
the listener with `ss -ltn` on the host. Reserve this port for this one instance.

For source/service installations the equivalent options are:

```bash
python -m app.headless --data-dir /absolute/private/profile --management-api \
  --management-host 127.0.0.1 \
  --management-trusted-origin https://server.example-tailnet.ts.net \
  --management-trusted-proxy 127.0.0.1 \
  --twitch-redirect-uri https://server.example-tailnet.ts.net/oauth/callback
```

The origin is an exact lowercase ASCII DNS HTTPS origin with no trailing slash,
path, credentials, query or fragment. Wildcards, DNS suffixes and IP origins are
refused. Omit default port 443; an explicit other port is part of both Host and
Origin. Proxy mode replaces `--management-allowed-host` and accepts only that
external Host and Origin. `--management-trusted-proxy` accepts repeatable exact
socket IPs, never networks; there is no default trust. The listener requires that
peer and exactly one `X-Forwarded-Proto: https`. Preserve the original Host and
Origin; overwrite `X-Forwarded-Host` with that same external authority if supplied,
and overwrite `X-Forwarded-For` with one client IP if supplied. Multiple values,
chains, mismatches, `Forwarded` and other `X-Forwarded-*` fields are rejected.
These values never select a redirect or grant authentication. Tailscale Serve
[preserves Host and replaces these headers](https://github.com/tailscale/tailscale/blob/main/ipn/ipnlocal/serve.go).
Local processes sharing the trusted proxy's socket IP are inside this boundary;
use a controlled host and prevent direct access to the backend from other networks.

Another HTTPS reverse proxy, including an intentionally public one, is optional
and must meet the same header/peer contract, enforce its own TLS/access policy,
and keep the backend private. Never enable public access merely to make Twitch's
redirect reachable: the **browser**, connected to Tailscale, follows that redirect.
Configure proxy access/error logging to omit callback query strings and sensitive
headers; do not log full request URLs. HeetKit disables HTTP access logs and
returns no-referrer/no-store responses. It cannot erase provider/browser/proxy
history: a code reaches the browser in the initial redirect before the fixed clean
redirect to `/oauth/result`. Do not share or bookmark callback URLs.

Incorrect Host/Origin, missing HTTPS forwarding or an unexpected peer returns a
fixed 403 diagnostic. If the callback is inaccessible, check tailnet connectivity,
Serve status, the host loopback listener and the exact registered redirect. If
Twitch rejects the redirect, register precisely the URL displayed in Settings,
including scheme, hostname, optional port and `/oauth/callback`. The application
can validate configuration syntax, but cannot verify your Twitch registration or
external reachability without a real browser/provider test.

For SSH fallback use the local management overlay and the tunnel below. Its
default localhost callback uses the same forwarded management port and completes
automatically; alternate loopbacks retain the paste procedure described above.
The tunnel does not turn localhost into the configured remote HTTPS name.
To retain automatic HTTPS callbacks the
browser must still reach the exact registered HTTPS origin through a correctly
configured trusted proxy. Choose one access configuration and restart to change it.
Closing the management browser or leaving Tailscale does not disconnect chat.
An unfinished OAuth attempt expires after five minutes even without browser polling.
Actual VM provisioning, monitoring, live migration and account acceptance are
separate operator-controlled deployment work.

## Browser panel

Open [the local panel](http://127.0.0.1:8765/) after enabling management. Source
installs need `npm ci` and `npm run build` in `frontend/` first; installed packages
use their staged frontend. The Docker image builds the same React source itself.
A missing build returns a safe 503 message without affecting native API access.
The desktop continues to use its normal pywebview bridge and build process.

Enter the management token in the password field. It is exchanged for a random
session token held only in this tab's memory. Neither token is stored in browser
storage, cookies or URLs. Sessions expire after one hour without automatic renewal;
reload requires signing in again. Sign out clears the interface and drafts immediately
and revokes the session on the server when reachable. At most eight sessions exist;
another login replaces the oldest when full. Restart invalidates every session;
rotating the administrator token still requires restart. A disconnected sign-out
clears local access, but its unreachable server session lasts until expiry/restart.

Unrelated cookies from other services on the same local host do not prevent loading
or signing in, including in Firefox. The server ignores cookies on both asset and
API requests; they never authenticate a request or select a session. The panel's
API fetches omit cookies, and HeetKit never sets or clears another service's cookies.
The normal bounded-header limits still apply.

Use loopback HTTP (including an SSH tunnel) or HTTPS. Plain HTTP to a private LAN
address cannot sign in. Browser requests must use the exact same origin as the page;
there is no CORS access or remote-server address field. An existing private HTTPS
proxy must preserve the exact configured Host including port. The corresponding
`https://IP:port` origin is accepted; forwarded headers do not establish trust.
DNS hostname authorities remain unsupported. Do not expose this service publicly.

Commands, response pools, custom commands, filters/tester, personalities, instructions,
AI enablement/memory/language/models, blocked users, Dashboard and operator activity
reuse the existing pages and server operations. Apply retains the existing session-only
meaning; Save persists and applies. Bot stop/start keeps the panel available.
Settings supports [first-run Twitch setup and saved channel presets](twitch-setup.md#server-browser-setup),
explicit channel switching and credential creation, replacement, testing and removal. It shows
presence/source and last validation status, never stored values. Gemini is optional.
Saving, renaming, selecting or deleting a preset does not change the bot target or
connection. Switch applies a stored target through controlled session shutdown,
preserving credentials, authorization and mode. An already-running Manual session
resumes; a stopped one stays stopped. Automatic modes reconcile the new target.
Native folders/tray actions, desktop update checks and the local
AI Playground are unavailable in browser mode. Ordinary project links remain available.

Settings also supports [portable configuration export/import](data-and-privacy.md#portable-configuration-transfer)
using the same ZIP as Desktop, with upload, preview and explicit confirmation.
Imported configuration applies live; secrets, authorization, history and deployment
settings remain local to the destination.

Browser status/AI share one snapshot every five seconds; logs refresh every five
seconds only while open. Hidden tabs pause polling. Requests do not overlap within
each polling loop. Errors identify unavailable servers or expired sessions; a 401
clears access and returns to sign-in. Mutations are never automatically retried.

## Docker opt-in

The default Compose file still publishes no ports. Create the normal Twitch/Gemini
secret files (leave both empty for browser-managed setup), then create
`management_token` in `HEETKIT_SECRETS_DIR` as
above. Follow [Docker secret file permissions](docker.md#prepare-private-storage-and-authorization):
the private parent stays mode 700; make the mounted token file readable by UID
10001 (mode 444 under that private parent is sufficient for native Compose).

```bash
chmod 444 "$HEETKIT_SECRETS_DIR/management_token"
docker compose -f compose.yaml -f compose.management.yaml up -d --build
```

The overlay mounts that one additional secret, enables the API inside the
container and defaults to **only host loopback** `127.0.0.1:8765`. Set the optional
`HEETKIT_MANAGEMENT_LOOPBACK` to another literal IPv4 loopback address to change
both Docker's published address and the API's exact accepted Host together:

```bash
export HEETKIT_MANAGEMENT_LOOPBACK=127.0.0.2
docker compose -f compose.yaml -f compose.management.yaml up -d --build
```

Open `http://127.0.0.2:8765/` in that example. Keep the variable set for subsequent
Compose operations. Use only a loopback IP here; never set `0.0.0.0` or a public/LAN
address. Alternative loopback publication depends on the host OS and Docker Desktop
networking. Verify the page is reachable on your host. If the alternative binding
fails, retain the supported default by running `unset HEETKIT_MANAGEMENT_LOOPBACK`
and recreating with both Compose files, then open `http://127.0.0.1:8765/`.
PowerShell uses `$env:HEETKIT_MANAGEMENT_LOOPBACK = '127.0.0.2'` to select it and
`Remove-Item Env:HEETKIT_MANAGEMENT_LOOPBACK` to return to the default.

SSH access uses the same exact browser authority, without trusting forwarded headers.
For the default on both machines, run
`ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 user@server` and open
`http://127.0.0.1:8765/` locally. For an alternative address, use that same address
for the local tunnel bind, server-side destination and configured allowed Host.
Keep tunnels bound to loopback; there is no need for a public management listener.
Container root/filesystem/UID, capability, profile-volume and restart protections stay in
the base Compose configuration. Use both Compose files for subsequent operations
on this configuration. Removing the overlay and recreating the container disables
HTTP access. No live profile migration is performed by enabling the API.

## Requests and operations

Every JSON route requires `Authorization: Bearer <private token or session token>`.
The optional GET `/oauth/callback` is the sole exception: it accepts only a pending,
single-use state belonging to a still-authorized initiating session, exchanges the
code on the server and redirects to the fixed `/oauth/result` page. It grants no
management session. Cross-site navigation is allowed for that callback and its
fixed inert result page; management/assets retain the same-origin checks below.
Requests must use the
exact path without query parameters, JSON objects for POST, and an explicit
Content-Length. JSON duplicate keys, non-finite values, compressed/chunked bodies,
unknown operation arguments and invalid domain settings are rejected. GET has no
body. Cross-origin/same-site browser requests and preflights are rejected;
an exact trusted same-origin browser request is allowed, with unrelated cookies
ignored. A cookie alone cannot authorize reads, login or mutations. No CORS policy or cookie
is issued. Public static assets carry no configuration or credentials, refuse
cross-site loading, and use a restrictive content security policy. Only the entry
page, icon and named compiled JS/CSS assets can be served; profiles, source maps
and arbitrary paths are excluded. Assets are limited to 4 MiB each.

This native Python example reads the private token into memory and does not print
it. It also avoids environment-configured HTTP proxies:

```python
import json, os
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler

token = Path(os.environ["HEETKIT_MANAGEMENT_TOKEN_FILE"]).read_text(encoding="ascii").strip()
client = build_opener(ProxyHandler({}))

def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request("http://127.0.0.1:8765/v1/" + path, data=data,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with client.open(req, timeout=30) as response:
        return json.load(response)

print(request("status"))
print(request("ai/memory", {"enabled": False}))
print(request("bot/stop", {}))  # API stays available; profile stays locked
print(request("bot/start", {}))
```

All paths below start with `/v1/`. GET results retain the shared application's
resource shape. Successful POST operations return `ok: true`; reads may omit `ok`.
POST writes persist and apply immediately unless stated otherwise.

| Method and path | JSON arguments / result |
|---|---|
| POST `twitch/presets/save` | `preset_id` (`null` creates), `display_name`, `channel`, `channel_user_id`; stores a unique named target without applying it |
| POST `twitch/presets/delete` | `preset_id`; deletes the preset without changing target or connectivity |
| POST `twitch/presets/switch` | `preset_id`; explicitly applies the stored target through controlled shutdown and mode reconciliation, retaining bot credentials and OAuth |
| POST `session` | `{}` with administrator bearer only; returns `token`, `expires_in` (3600 seconds) |
| GET `session` / POST `session/logout` | Check current session / revoke it with `{}` |
| GET `snapshot` | Combined `status` and `ai_status` for browser polling |
| GET `setup`, `about` | Effective non-secret setup status (including fixed management/callback URLs, `authorization_mode` and this session's `authorization_attempt`) / shared application metadata |
| POST `twitch/settings` | `client_id`, `bot_username`, `bot_user_id`, `channel`, `channel_user_id`; save/apply after stopping the old session |
| POST `credentials/replace` | `name` (`twitch_client_secret`, `gemini_api_key` or `deepseek_api_key`), `value`; browser-managed credentials only |
| POST `credentials/remove`, `credentials/test` | `name`; remove the browser value / check the effective value against its provider |
| POST `twitch/authorization/begin` | `{}`; checks application credentials, stops the old session and returns Twitch's `url`, `expires_in` (300 seconds) |
| POST `twitch/authorization/complete` | `callback_url`; authenticated paste completion for this session and the fixed configured redirect, returning no tokens; default local and configured HTTPS modes complete through GET `/oauth/callback` |
| POST `twitch/authorization/cancel` | `{}`; cancels this session's pending attempt |
| GET `status` | Running, Twitch connection state, session uptime, account/channel and `operation` policy/monitor status |
| POST `configuration/export` | `{}`; returns `filename` and ZIP `archive_base64` |
| POST `configuration/preview` | `archive_base64`; validates ZIP and returns a ten-minute `preview_token`, source `application_version`, `format_version`, replacement `sections` with counts/details, `effects` and `preserved` settings |
| POST `configuration/import` | The same `archive_base64`, `preview_token` and `confirmed: true`; saves/applies only after revalidation against the preview and unchanged destination |
| POST `bot/start`, `bot/stop` | `{}`; policy-aware connect/disconnect intent, `changed` and current `operation`; completion is asynchronous |
| POST `bot/mode` | `mode`: `always_on`, `stream_only`, `manual` or `disabled`; persist and reconcile without process restart |
| GET `commands` | Built-ins, effective/default settings, aliases, permissions, cooldowns and response pools |
| POST `commands/save` | `command_name`, `enabled`, `per_user_seconds`, `global_seconds`, `permission`; optional `options` with `aliases`, `display_name`, `burst_interval_ms`, `burst_max_count` |
| POST `commands/reset`, `commands/remove`, `commands/restore` | `command_name`; factory administrative permission floors remain enforced |
| POST `commands/apply` / `commands/reset-all` | Same arguments as Save but session-only / `{}` to restore all factory settings/responses, never custom commands |
| POST `commands/responses/save` | `name` (`fate` or `tg`), `responses` (list of text) |
| POST `commands/responses/reset` | `name` |
| POST `commands/responses/apply` | Same as responses Save, session-only |
| GET `custom-commands` | Commands, allowed template variables and permissions |
| POST `custom-commands/save` | `command` object in the existing command format: `name`, `enabled`, `responses`, `permission`, `per_user_seconds`, `global_seconds`, `aliases`; an existing `id` edits that command; existing optional response-mode/burst fields are supported |
| POST `custom-commands/delete` | `identifier` (saved command ID) |
| GET `ai` | AI availability, enablement, memory, model and active personality |
| POST `ai/enabled`, `ai/memory` | Boolean `enabled` |
| GET / POST `ai/models` | GET: active `provider_id`, selected/fallback models, presets and credential status, no secret values. POST: optional `provider` (`gemini` default or `deepseek`); supply distinct `selected_model`, `fallback_model` to save that provider's choices, or omit both to switch to its retained choices |
| GET / POST `ai/setup` | GET: typed primary/fallback selections, connection status, documented capabilities, default shared instructions and retained restrictions. POST: `settings` containing `primary`, nullable `fallback` (each `provider`, `model`, `thinking`, `search`), `cross_provider_acknowledged`, `max_question_length` (1–4000), `max_answer_length` (1–450), nullable `shared_instructions` (empty is deliberate), and `provider_drafts`. Atomic non-secret save; credential operations remain separate. Imported cross-provider routing requires a fresh acknowledgement. After advanced setup exists, legacy `ai/models` needs both models; use this operation for provider switches. |
| GET / POST `setup/guide` | Profile-local dismiss/resume and optional-AI skip preferences. POST requires boolean `dismissed`, `ai_skipped`; this does not configure or authorize Twitch. |
| POST `ai/models/discover` | Optional `provider` (otherwise active); bounded discovery with that provider's configured key, returns `provider_id` and `models`. An empty list is valid; listing does not prove generation/tool access and never changes saved models |
| GET / POST `ai/language` | POST: `mode` (`auto` or `limited`), `allowed_languages` (codes), `fallback_language` |
| GET `personalities` | Prompts, saved state, active personality and protected instructions |
| POST `personalities/create` | `name`, `prompt` |
| POST `personalities/rename` | `personality`, `name` |
| POST `personalities/delete`, `personalities/activate`, `personalities/reset` | `personality` |
| POST `personalities/save` | `personality`, `prompt` |
| POST `personalities/apply` | `personality`, `prompt`; session-only |
| POST `ai/instructions/save` / `ai/instructions/reset` | `prompt` / `{}` |
| POST `ai/instructions/apply` | `prompt`; session-only |
| GET `filters` | Active/saved word, phrase and pattern rules |
| POST `filters/save` | `payload` object containing `words`, `phrases`, `patterns` lists |
| POST `filters/apply` | Same as filters Save, session-only |
| POST `filters/test` | `text`, `source` (`active` or `draft`), `payload` (`null` for active; filter object for draft) |
| GET `blocked-users` | AI-blocked usernames and whether a verified ID is recorded |
| POST `blocked-users/block`, `blocked-users/unblock` | `username` |
| GET / POST `triggers` | GET: ordinary-message reactions. POST: complete `triggers` list, at most 100 unique IDs |
| POST `logs/recent` | Optional integer `after_id` (default 0), `limit` (1–200, default 100); allowlisted operator activity plus `next_after_id` advancing across excluded entries; authentication required |
| GET `diagnostics` | Process uptime, desired session state and settings/restart boundaries |

Each trigger has `id` (1–40 ASCII letters/digits/underscore/hyphen), boolean
`enabled` and `case_sensitive`, `match_mode` (`exact` or `contains`), `text`
(one nonempty line, at most 100 characters), `probability` (0–1),
`cooldown_seconds` (0–86400) and `responses` (1–10 nonempty single lines,
at most 450 UTF-8 bytes each). Reactions stay literal text; templates, expressions
and AI are not executed. Existing command templates use their fixed variable
allowlist and cannot run code. Filters retain their shared regex execution budget.

## Operation modes

The browser Dashboard selects a headless policy independently of the actual Twitch
connection state. The policy is stored as `startup.operation_mode` in the existing
profile `config/app_settings.json`; the profile volume must be retained across
container/host restarts. Desktop continues to use its own auto-start preference.
Portable configuration import/export preserves the destination operation policy.

| Mode | Startup and controls |
| --- | --- |
| Always On | Connect on process start and retain TwitchIO's existing connection recovery. This is the default for profiles without a mode setting. |
| Stream Only | Start monitoring while chat is disconnected; connect on confirmed live status and disconnect on confirmed offline status. Monitoring runs without a browser. |
| Manual | Start stopped after every process restart. Connect/Disconnect explicitly controls this process's session. |
| Disabled | Stay disconnected across restarts. Start is rejected until the mode changes. |

Disconnect in an automatic mode first saves Manual, then stops the session, so a
later stream change or process restart cannot undo an intentional stop. The button
states this mode change explicitly. `bot/start` is accepted only in Manual.
Entering Manual or Disabled stops the current session; entering Always On requests
connection. Entering Stream Only retains a currently desired active session while
confirming the broadcaster state. Pending close/token flush finishes before a new
session can start; subsequent mode changes replace pending intent. The `operation`
projection includes `mode`, `desired_running`, `pending`, `error`, `stream_status`,
`last_known_stream_status` and UTC `last_checked_at`. Inspect it after mutations;
an accepted request does not prove Twitch readiness.

Stream Only checks Twitch's supported [Get Streams API](https://dev.twitch.tv/docs/api/reference/#get-streams)
for the configured broadcaster ID using TwitchIO's app authentication and the
existing client ID/secret. No new user scopes, second bot, EventSub session or
OAuth token-file writer is introduced. Two consecutive successful matching samples,
normally 60 seconds apart, confirm either transition. An unknown result resets
confirmation, retains the desired connection and last known live/offline status,
and backs off checks from 120 seconds to at most 900 seconds. Each check has a
15-second deadline; TwitchIO retains its rate-limit handling. Timing and confirmation
thresholds are internal constructor settings for controlled testing/operation.
The same single monitor also runs in Always On and connected Manual when any
built-in or custom command has a stream restriction. Those observations only gate
command execution; they never connect or disconnect chat in these modes. Manual
while stopped, Disabled, and Always On without restrictions need no command polls.
Command settings edits wake monitoring only when this demand changes, preserving
poll intervals and backoff. Desktop never starts this monitoring.

For command execution, a successful Get Streams response confirms the current
state until a failed check, monitoring stops, configuration/mode changes, or the
observation reaches 135 seconds old (two polling intervals plus the request
deadline). Unknown/stale status blocks both restricted policies while Anytime
commands continue. The two-sample Stream Only connection confirmation is unchanged.
Safe lifecycle codes expose polls, confirmed transitions,
mode changes and connection failures without credentials or provider payloads.

Monitoring errors never prove a stream ended. Once confirmed offline, closing may
allow an already-running command/provider request to finish under the existing
session cleanup rules. Terminal chat authorization/storage failures pause automatic
connectivity and show `connection_failed`; management stays available for repair.
Choose Manual and Connect after repair, or change to another automatic mode.
Invalid mode values and corrupt/unsupported settings fail closed for headless
connectivity; repair the profile file before saving if recovery preflight refuses it.
Live broadcaster transition/refresh/reconnection acceptance remains a separately
approved check before cloud deployment.

## Persistence, limits and failures

Management requests serialize on the core asyncio loop, including awaited
operations. Existing store locks, immutable snapshots and atomic replacements
protect state shared with Twitch events. Settings publish after successful saves;
invalid/failed saves retain prior active values. Trigger writes use the existing
recovery preflight and preserve unknown/external valid data in recovery files.
Malformed/unreadable/future-version trigger files require repair before editing.
Normal UTF-8 and Windows UTF-8 BOM trigger files are supported.

Commands, responses, AI enablement/memory/models/language, personality selection
and prompts, filters, blocks and triggers apply to subsequent processing immediately.
Already-running command/provider requests may finish with their earlier snapshot.
Stopping the bot leaves the API, database and profile lock alive; starting it uses
the same core/state. Intentional idle modes have a healthy supervised heartbeat;
connecting/reconnecting and terminal connection errors are unhealthy. Compose does
not restart a container merely for being unhealthy. Terminal Twitch failures keep
enabled management available with a fixed error; without management they exit headless.

Twitch edits wait for session close/token flushing. Application/account/secret changes
discard the old local OAuth cache before persistence and require Connect Twitch again;
a failed save may therefore require reauthorization. Channel changes retain bot tokens
but verify the target login/ID again before subscribing. Always On resumes when setup
is valid, Stream Only waits for confirmed live status, Manual needs Connect, and
Disabled stays stopped. No duplicate session or process restart is needed. Gemini
changes apply to subsequent requests; in-flight requests can finish with the old key.
External secret and API bind/token or privacy/storage policy changes still require
host-side configuration and process restart. No OAuth/access/refresh token, keyring content, local
folder operation or raw provider exception is returned. Logs expose bounded command
inputs, permitted reply attempts, semantic outcomes/context and fixed lifecycle messages,
with the same projection as Desktop. Ordinary chat and raw log prose are excluded.
The feed remains in memory (500 events / 1 MiB, 16 KiB per event; text capped at 4 KiB
with an explicit truncation marker), independent of AI memory. Level, command, outcome,
source and local-time range filters apply to retained entries; request details link
related events. Cooldown remaining time and uncertain delivery stay visible.
Clear view is display-only. Export requires confirmation and saves only the filtered
snapshot; the resulting private JSON copy has no automatic expiry. Desktop uses a native Save dialog;
the authenticated Server view downloads its confirmed snapshot in the browser. See
[activity privacy and retention](data-and-privacy.md#credentials-and-local-data).
All responses disable caching.

Server credentials live in private `auth/server_credentials.json`, separate from
portable configuration. Nonempty environment/`_FILE` inputs take priority and reject
browser replace/remove; clearing them and restarting reveals any previously saved
browser value. Rotate through the same external source, or remove the old browser
value before switching provisioning methods. Empty secret files permit browser setup.
Saved non-secret Twitch settings retain their existing precedence over environment
defaults. Validation results are process-local and reset after edits/restart.

Authorization attempts are single-use, expire after five minutes, and are bound to
the initiating bearer session. Another session cannot finish or replace an active
attempt. Logout cancels its attempt; restarting loses all pending state. Configuration
changes cancel pending attempts. A failed exchange or denied authorization requires
a new attempt. The code exchange, application/account/scope validation and writable
token cache use TwitchIO; the management token and provider secrets never enter the
authorization URL. There is no unauthenticated OAuth callback route. Treat the pasted
callback URL as sensitive, close its browser tab afterwards, and remove it from
browser history when practical. Remote HTTPS callback automation is not supported.

Limits are 64 KiB per JSON request, except AI setup allows 256 KiB for escaped Unicode
instructions, and configuration preview/import allow
1,399,128 bytes for a base64-encoded ZIP of at most 1 MiB and its fixed arguments.
Configuration export retains the 2 MiB response limit. Format version 1 requires
exactly `manifest.json` and `configuration.json`, with a validated byte size/SHA-256
manifest record, source application version and supported configuration schema;
the hash detects corruption, not source authenticity. Schema/collection validation
uses the destination's existing registry and validators, so incompatible versions
are rejected rather than partially imported. Previews are one-use, expire after ten
minutes, and at most eight are retained per process. Uploads and previews are held
in memory, with no arbitrary extraction or caller-selected server paths.

Other limits are 2 MiB per response, 16 active requests,
120 requests per minute per instance (including failed authentication), 32 open
connections, bounded HTTP header fields/count, five seconds to read a body,
25 seconds per operation including queue time, and a 35-second absolute connection
lifetime. Responses close their connection. API cleanup gets up to five seconds
plus cancellation grace before the existing bounded core shutdown proceeds.

Errors use safe fixed text: 400 rejected input/operation, 401 authentication required,
403 untrusted Host/browser origin, 404 unknown resource, 405 unsupported method,
413 body limit, 415 content type, 429 request limit, 500 operation/storage failure,
503 missing/oversized frontend asset, 504 deadline. After a timeout or disconnect, inspect current state before retrying:
an operation may already have committed. The token authenticates the administrator;
it does not defend an exposed service against network denial of service.

Focused integration tests use disposable profiles, real loopback HTTP, SQLite and
synthetic Twitch boundaries. They cover authentication/browser protections, private
response shapes, validation, permissions, persisted/live changes, concurrent writes,
limits, lifecycle stop/start and cleanup. They do not establish live Twitch/Gemini
or an internet-facing deployment. Focused browser checks cover transport/session
behavior, desktop regressions, mobile layout and built-interface access to a synthetic
server; they do not establish live account or native packaged-desktop acceptance.
The opt-in Chrome/Firefox matrix in `frontend/` runs with
`npx playwright test --config playwright.compatibility.config.ts` after building the
frontend. It requires installed Google Chrome and Playwright's Firefox runtime
(`npx playwright install firefox`). It exercises both `127.0.0.1` and `127.0.0.2`
using synthetic profiles and cookies from another local port. It does not validate
Docker port forwarding; check that separately on the intended Docker host.
