# Linux Docker runtime

HeetKit's container runs the shared [headless backend](development.md#headless-runtime)
for one previously authorized Twitch bot. By default it has no window, dashboard,
HTTP listener, OAuth callback listener or published ports. An explicit
[private management API and browser panel overlay](management-api.md#docker-opt-in) is available.
Use a Linux amd64 Docker Engine with
Docker Compose v2, or Docker Desktop configured for Linux containers.

The canonical `Dockerfile` pins the official CPython 3.14.7 Debian slim image by
digest. `packaging/linux/requirements.txt` pins the complete backend wheel closure
with SHA-256 hashes. The build accepts wheels only, installs no GUI/build packages,
and copies allowlisted application sources and neutral defaults. A separate digest-pinned
official Node 24 build stage runs the existing locked React build. Only its production
page, icon and compiled assets enter the Python runtime; Node, frontend source/tests,
Windows tools, private profiles, dotenv files and development directories are excluded.
Other CPU architectures are not validated by this lock. Linux uses `multidict==6.9.1`
as a narrow exception to the older Windows pins, fixing the upstream
[items-view reference leak](https://github.com/aio-libs/multidict/security/advisories/GHSA-54p9-h82j-f925).
The existing Windows redistribution inventory is unchanged by this container task.

## Prepare private storage and authorization

Run the following examples from the repository root in a Linux Bash shell. They
operate on the default Compose project `heetkit`; keep that project name stable.

1. Configure and authorize the matching Twitch application/bot through the desktop,
   as described in [Twitch setup](twitch-setup.md). Stop the desktop before copying
   its profile or starting the container. Run only one instance per Twitch account;
   profile locks cannot coordinate separate hosts or copies of a profile.
2. Keep the entire stopped profile together: `config/` (including filters,
   commands and personalities), `auth/twitchio_tokens.json`, `data/heetkit.db` and
   any other profile files. Desktop keyring secrets are separate and must be
   provisioned again. Never put the profile in the build context or Git.
3. Create a private secrets directory outside the checkout:

   ```bash
   export HEETKIT_SECRETS_DIR="$HOME/.config/heetkit-secrets"
   install -d -m 700 "$HEETKIT_SECRETS_DIR"
   touch "$HEETKIT_SECRETS_DIR/twitch_client_secret" "$HEETKIT_SECRETS_DIR/gemini_api_key"
   chmod 600 "$HEETKIT_SECRETS_DIR/twitch_client_secret" "$HEETKIT_SECRETS_DIR/gemini_api_key"
   ```

   Put the Twitch client secret into `twitch_client_secret` using a trusted private
   editor/secret manager, without putting the value in a shell command or history.
   Put an optional Gemini API key into `gemini_api_key`, or leave that file empty
   to run without AI. After editing, run `chmod 444` on both secret files and keep
   their parent directory owner-only. On native Linux, Compose bind-mounts secret
   files with their host UID/mode; declaring a different secret `uid`/`mode` does
   not remap file-backed secrets. The private parent prevents other host users
   from traversing to the files, while the container's UID 10001 can read the
   individual mounted files. See [Docker's secret semantics](https://docs.docker.com/reference/compose-file/services/#secrets).

   Compose mounts only these two files under `/run/secrets/`; container metadata
   contains their paths, not their values. Headless reads `TWITCH_CLIENT_SECRET_FILE`
   and `GEMINI_API_KEY_FILE` directly into settings without exporting their contents
   into the process environment. Files must be regular UTF-8 files, at most 16 KiB,
   with one value and an optional trailing newline. Supplying a nonempty environment
   credential and its `_FILE` together fails explicitly. Direct private environment
   credentials remain supported for source/service usage.

Build, then import your **stopped, trusted** profile into the initially empty volume:

```bash
docker compose build
export HEETKIT_SOURCE_PROFILE=/absolute/private/path/to/stopped-profile
tar -C "$HEETKIT_SOURCE_PROFILE" -czf - . |
  docker compose run --rm --no-deps -T --entrypoint sh bot -c \
  'umask 077; tar --no-same-owner -xzf - -C /var/lib/heetkit'
```

Use this import only for the intended empty profile volume. The container extracts
as UID/GID 10001, so Windows/source ownership does not need privileged `chown` at
runtime. Never extract an untrusted archive. A fresh unconfigured profile exits
with actionable missing-configuration/authorization guidance; headless cannot
perform the initial browser authorization. No live profile migration happens during
the automated checks.

## Run and inspect

```bash
docker compose up -d
docker compose ps
docker compose logs --tail 50 bot
docker compose stop bot
docker compose start bot
```

The named volume `heetkit_profile` mounts at `/var/lib/heetkit`; all profile files,
OAuth rotations and SQLite state stay there across stop/start, image rebuilds and
`docker compose up -d --force-recreate`. `docker compose down` keeps the volume;
**`down --volumes` deletes it**. Avoid changing the project/volume name by accident.
Bind mounts are also possible with an override, but must already be writable by
UID/GID 10001 and private on the host. Do not share the profile among replicas.

The runtime uses UID/GID 10001, a read-only image filesystem, a small ephemeral
`/tmp`, no Linux capabilities and no privilege escalation. No Docker socket,
host networking or privileged mode is required. Outbound DNS/HTTPS/WebSocket access
is required for Twitch and optional providers. No inbound port is needed.

Compose uses `restart: unless-stopped`: a stopped service stays stopped; process
failures restart it. Authorization/configuration failures still require operator
repair; stop the service while fixing them. SIGINT/SIGTERM trigger the shared
bounded cleanup. The default application shutdown limit is 20 seconds plus bounded
cancellation grace, and Compose allows 30 seconds before force-killing. If overriding
`--shutdown-timeout`, increase `stop_grace_period` accordingly. Keep `--health-file
/tmp/heetkit-health.json` in any command override.

The Docker health check reads a local, atomic, ephemeral heartbeat. Healthy means
the supervisor recently observed the `connected` state; startup, reconnecting,
stale/hung supervision and terminal failures are unhealthy. It does not make a
provider request, open a port or prove that a particular chat message was delivered.
Docker reports health separately from process restart: an unhealthy status alone
does not restart a container. Check `docker compose ps` and the safe lifecycle logs.
Initial startup has a 75-second health grace; application startup defaults to 60
seconds. Log rotation bounds retained Docker logs; no private chat text, credentials
or raw provider errors are intentionally emitted by headless logging.

## Backup, restore and updates

Stop first so SQLite and token writes are quiescent. Back up the **whole** volume,
not just the database; OAuth refresh-token rotations make old backups stale.

```bash
docker compose stop bot
umask 077
docker compose run --rm --no-deps -T --entrypoint tar bot \
  -C /var/lib/heetkit -czf - . > /absolute/private/path/heetkit-profile.tar.gz
docker compose start bot
```

Store the archive and secret files privately, preferably encrypted and separately
from the checkout. The volume archive contains OAuth tokens and private user data;
the two mounted secret files are outside it and need their own secure backup.

Restore to a new empty volume with the target service stopped. For a recovery
rehearsal, use a distinct project name and **do not start its bot** while the original
account is active:

```bash
docker compose --project-name heetkit-restore run --rm --no-deps -T \
  --entrypoint sh bot -c 'umask 077; tar --no-same-owner -xzf - -C /var/lib/heetkit' \
  < /absolute/private/path/heetkit-profile.tar.gz
```

Inspect the restored private files before owner-controlled cutover. If authorization
has since rotated or been revoked, reauthorize through the desktop using the intended
profile and stop it before restarting headless. Never delete the current volume to
test a restore. For an update, stop, back up, retain the previous local image for
rollback, check out the intended revision, then `docker compose build` and
`docker compose up -d --force-recreate`. Roll back source/image and compatible profile
backup together if a future version changes profile formats. No registry publication,
automatic update or cloud deployment is configured.

## Troubleshooting and validation

- Missing secret directory/file: export `HEETKIT_SECRETS_DIR` in the shell that runs
  Compose and create both files. Do not paste secret values into Compose YAML.
- Cannot read `_FILE`: check host-file permissions for UID 10001; do not print the
  file into logs. Secret files are read on process startup; recreate/restart after
  replacement, including when an editor replaced the host inode.
- Missing/expired authorization: stop, repair the matching desktop authorization and
  private profile, stop the desktop, then restart. An existing JSON cache alone does
  not establish valid authorization.
- Permission/SQLite/lock failure: check volume ownership, free space and that another
  process does not own the profile. Use local storage with reliable SQLite locking;
  network filesystems are not validated.
- Unhealthy/reconnecting: inspect lifecycle logs, DNS, outbound network and account
  access. A running process is not sufficient evidence of a usable connection.

`python3 scripts/check_linux_container.py` builds the canonical Compose image and
uses a randomly named disposable project/volume with synthetic settings and secrets.
It stages tracked build inputs in a temporary context with synthetic excluded profile,
secret and generated-frontend decoys, checking that none appear in the image; it never reads
the checkout's ignored profile or secrets.
It disables container networking and replaces only the Twitch remote boundary.
It checks non-root execution, absence of GUI dependencies, real OS signals,
stop/start, container recreation, saved configuration/personality/filter loading,
SQLite persistence/integrity and the real atomic token-cache loading/rotation/flush
paths. It removes only its own test project/volume. The read-only Linux GitHub Actions
workflow runs that same script; it publishes no image or release. Live Twitch/Gemini
authorization, refresh and reconnect still require separately authorized account tests.

To refresh dependency pins, resolve the base `pyproject.toml` requirements for CPython
3.14 Linux amd64 with wheels only, constraining compatible shared versions to
`packaging/windows/requirements.txt`, retaining the documented `multidict>=6.9.1`
security override. Record every resolved wheel's SHA-256 in the
Linux lock, update the official base-image digest deliberately, and rerun the focused
container validation. Do not install the Windows packaging requirements into Linux.
