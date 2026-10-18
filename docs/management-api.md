# Private management API

The headless runtime has an optional HTTP API for one administrator managing one
bot. It reuses the desktop's application operations, command namespace, validation,
configuration stores and active runtime. The same listener serves the existing
React interface for browsers and an explicit JSON API for native clients.

## Enable private access

Provision the [headless profile and Twitch authorization](development.md#headless-runtime)
first. The API is disabled by default. Enable it with `--management-api`; the
default bind is `127.0.0.1:8765`. Supply `HEETKIT_MANAGEMENT_TOKEN_FILE` pointing to
a private ASCII file, or `HEETKIT_MANAGEMENT_TOKEN` through a private service
environment. Providing both fails. Files must be regular, at most 1 KiB, and contain
43–128 URL-safe characters with an optional trailing newline. Generate the value
from at least 32 random bytes. There is no default token, token in a URL/CLI option,
public registration, cookie authentication or OAuth credential-management endpoint.

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
`--management-port` sets port 1–65535. An explicit all-interface bind additionally
requires `--management-allowed-host IP:port`, an exact trusted HTTP Host authority.
Hostnames and wildcard Host allowlists are unsupported. Loopback's default Host
allowlist accepts its configured IP and `localhost`, with the configured port.
Forwarded headers are ignored. IPv6 authorities use `[address]:port`.

Keep this service on loopback or an explicitly trusted private interface. Do not
publish it to the internet. HTTP carries the bearer token in each request: use an
SSH tunnel or a protected private network when accessing another machine. This
feature does not provision TLS, tunnels, proxies, cloud resources or firewall rules.

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

Use loopback HTTP (including an SSH tunnel) or HTTPS. Plain HTTP to a private LAN
address cannot sign in. Browser requests must use the exact same origin as the page;
there is no CORS access or remote-server address field. An existing private HTTPS
proxy must preserve the exact configured Host including port. The corresponding
`https://IP:port` origin is accepted; forwarded headers do not establish trust.
DNS hostname authorities remain unsupported. Do not expose this service publicly.

Commands, response pools, custom commands, filters/tester, personalities, instructions,
AI enablement/memory/language/models, blocked users, Dashboard and safe lifecycle logs
reuse the existing pages and server operations. Apply retains the existing session-only
meaning; Save persists and applies. Bot stop/start keeps the panel available.
Settings shows server configuration status and guidance: provision Twitch identity,
authorization, secrets and privacy settings on the server, then restart as required.
Native folders/tray actions, credential editors, desktop update checks and the local
AI Playground are unavailable in browser mode. Ordinary project links remain available.

Browser status/AI share one snapshot every five seconds; logs refresh every five
seconds only while open. Hidden tabs pause polling. Requests do not overlap within
each polling loop. Errors identify unavailable servers or expired sessions; a 401
clears access and returns to sign-in. Mutations are never automatically retried.

## Docker opt-in

The default Compose file still publishes no ports. After provisioning the normal
Twitch/Gemini secret files, create `management_token` in `HEETKIT_SECRETS_DIR` as
above. Follow [Docker secret file permissions](docker.md#prepare-private-storage-and-authorization):
the private parent stays mode 700; make the mounted token file readable by UID
10001 (mode 444 under that private parent is sufficient for native Compose).

```bash
chmod 444 "$HEETKIT_SECRETS_DIR/management_token"
docker compose -f compose.yaml -f compose.management.yaml up -d --build
```

The overlay mounts that one additional secret, enables the API inside the
container and publishes **only host loopback** `127.0.0.1:8765`. The exact required
Host is `127.0.0.1:8765`. Use that address, including through a tunnel. Container
root/filesystem/UID, capability, profile-volume and restart protections stay in
the base Compose configuration. Use both Compose files for subsequent operations
on this configuration. Removing the overlay and recreating the container disables
HTTP access. No live profile migration is performed by enabling the API.

## Requests and operations

Every JSON route requires `Authorization: Bearer <private token or session token>`.
Requests must use the
exact path without query parameters, JSON objects for POST, and an explicit
Content-Length. JSON duplicate keys, non-finite values, compressed/chunked bodies,
unknown operation arguments and invalid domain settings are rejected. GET has no
body. Cookies, cross-origin/same-site browser requests and preflights are rejected;
an exact trusted same-origin browser request is allowed. No CORS policy or cookie
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
| POST `session` | `{}` with administrator bearer only; returns `token`, `expires_in` (3600 seconds) |
| GET `session` / POST `session/logout` | Check current session / revoke it with `{}` |
| GET `snapshot` | Combined `status` and `ai_status` for browser polling |
| GET `setup`, `about` | Effective non-secret setup status / shared application metadata |
| GET `status` | Running, Twitch connection state, session uptime, account and channel |
| POST `bot/start`, `bot/stop` | `{}`; returns whether the session changed |
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
| GET / POST `ai/models` | GET: selected/fallback model and presets, no secret values. POST: `selected_model`, `fallback_model` (distinct valid model IDs) |
| POST `ai/models/discover` | `{}`; existing bounded provider model discovery |
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
| POST `logs/recent` | Optional integer `after_id` (default 0), `limit` (1–200, default 100); safe lifecycle entries plus `next_after_id` advancing across excluded private entries |
| GET `diagnostics` | Process uptime, desired session state and settings/restart boundaries |

Each trigger has `id` (1–40 ASCII letters/digits/underscore/hyphen), boolean
`enabled` and `case_sensitive`, `match_mode` (`exact` or `contains`), `text`
(one nonempty line, at most 100 characters), `probability` (0–1),
`cooldown_seconds` (0–86400) and `responses` (1–10 nonempty single lines,
at most 450 UTF-8 bytes each). Reactions stay literal text; templates, expressions
and AI are not executed. Existing command templates use their fixed variable
allowlist and cannot run code. Filters retain their shared regex execution budget.

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
the same core/state. A deliberately stopped bot is unhealthy under the existing
connection health check; Compose does not restart a container merely for being
unhealthy. Unexpected terminal Twitch failures still exit headless with an error.

Twitch identity/client credentials, provider secrets, privacy/storage policy and API
bind/token changes require process restart and are configured outside this API.
Target-channel changes require reconnection and are also configured outside this
initial API while stopped. No OAuth/access/refresh token, keyring content, local
folder operation or raw provider exception is returned. Logs expose only fixed
lifecycle messages, timestamps, levels and IDs; private chat and raw log text are
excluded. All responses disable caching.

Limits are 64 KiB per JSON request, 2 MiB per response, 16 active requests,
120 requests per minute per instance (including failed authentication), 32 open
connections, bounded HTTP header fields/count, five seconds to read a body,
25 seconds per operation including queue time, and a 35-second absolute connection
lifetime. Responses close their connection. API cleanup gets up to five seconds
plus cancellation grace before the existing bounded core shutdown proceeds.

Errors use safe fixed text: 400 rejected input/operation, 401 authentication required,
403 untrusted Host/browser origin/cookies, 404 unknown resource, 405 unsupported method,
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
