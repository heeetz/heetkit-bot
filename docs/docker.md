# Linux Docker runtime

HeetKit's container runs the shared [headless backend](development.md#headless-runtime)
for one Twitch bot. By default it has no window, dashboard,
HTTP listener, OAuth callback listener or published ports. An explicit
[private management API and browser panel overlay](management-api.md#docker-opt-in) is available.
That overlay defaults to `127.0.0.1:8765`; its documented
`HEETKIT_MANAGEMENT_LOOPBACK` option changes the published loopback and accepted
Host together, with `127.0.0.1` as the fallback when alternate loopbacks are unsupported.
The default local [Twitch callback](management-api.md#local-twitch-callback) uses
`http://localhost:8765/oauth/callback` on that same published management port;
register it exactly in Twitch. Do not publish Desktop's callback port 4343.
For a Linux VM, the separate [private HTTPS reference](management-api.md#private-remote-https)
uses `compose.remote.yaml` with host-side Tailscale Serve and a loopback-only backend.
It supports remote browser Twitch authorization without Desktop; do not combine
the remote overlay with the Docker Desktop/local management overlay.
Use a Linux amd64 or arm64 Docker Engine with Docker Compose v2, or Docker
Desktop configured for Linux containers. Compose keeps **linux/amd64 as the
default**. On an ARM64 host, explicitly export `HEETKIT_PLATFORM=linux/arm64`
and retain that setting for every build, start, backup, restore and update.

The canonical Dockerfile builds the locked frontend, then copies its compiled assets
and allowlisted Python application into a non-root runtime. Node/build tools, private
profiles, secrets and Windows packaging tools do not enter the final image. Python
base images and backend wheels are pinned; use the tracked build path rather than a
separate Dockerfile. Native validation covers AMD64 and ARM64.

## Prepare private storage and authorization

For a **fresh browser-managed installation**, skip the Desktop/profile-copy steps
below. Create the two secret files in step 3 but leave them empty, keep their stated
permissions, generate a management token, and start with the
[management overlay](management-api.md#docker-opt-in). Sign in and follow
[Server browser setup](twitch-setup.md#server-browser-setup). The management token
and private persistent volume are the only required host-side bootstrap state.
The panel remains available while Twitch is unconfigured or Disabled. No Desktop
installation or profile-file editing is required. The rest of this section describes
the optional existing-profile/external-secret path; do not run two copied accounts.

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

   The backend also accepts `DEEPSEEK_API_KEY` or `DEEPSEEK_API_KEY_FILE` for direct
   DeepSeek use. The supplied Compose file retains its two existing secret mounts;
   a DeepSeek file needs an explicit private mount/environment override. Alternatively,
   save the DeepSeek key through authenticated credential operations when no external
   key is provisioned. See [DeepSeek backend configuration](ai-setup.md#saved-connections-and-model-setup).

   OpenAI also accepts `OPENAI_API_KEY` or `OPENAI_API_KEY_FILE`, or a key saved through
   authenticated AI setup when no external key is provisioned. A secret file needs an
   explicit private mount/environment override. See [AI provider setup](ai-setup.md).

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
runtime. Never extract an untrusted archive. Without management, an unconfigured
Always On profile exits with missing-configuration/authorization guidance. With
management enabled, configure and authorize through Settings instead. No live
profile migration happens during the automated checks.

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
Saved Server channel presets live in this same profile. Preset Save/Update and
selection do not switch the active channel; use the explicit Switch action in Settings.
Bind mounts are also possible with an override, but must already be writable by
UID/GID 10001 and private on the host. Do not share the profile among replicas.

The runtime uses UID/GID 10001, a read-only image filesystem, a small ephemeral
`/tmp`, no Linux capabilities and no privilege escalation. Base Compose requires
no Docker socket, host networking or privileged mode. The remote HTTPS overlay
deliberately uses host networking with a loopback-only listener. Outbound DNS/HTTPS/WebSocket access
is required for Twitch and optional providers. No inbound port is needed.

Compose uses `restart: unless-stopped`: a stopped service stays stopped; process
failures restart it. Authorization/configuration failures still require operator
repair; stop the service while fixing them. SIGINT/SIGTERM trigger the shared
bounded cleanup. The default application shutdown limit is 20 seconds plus bounded
cancellation grace, and Compose allows 30 seconds before force-killing. If overriding
`--shutdown-timeout`, increase `stop_grace_period` accordingly. Keep `--health-file
/tmp/heetkit-health.json` in any command override.

The saved [operation mode](management-api.md#operation-modes) controls connectivity
after container/host restart, independently of Compose's process restart policy.
Always On connects automatically; Stream Only monitors without a browser; Manual
and Disabled remain stopped. Disconnecting an automatic mode saves Manual first.
The management panel and mounted profile remain available while chat is stopped.

The Docker health check reads a local, atomic, ephemeral heartbeat. Healthy means
the supervisor recently observed `connected` or intentional `idle` policy state
(Manual, Disabled or waiting Stream Only); startup, reconnecting,
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
from the checkout. The volume archive contains OAuth tokens, browser-managed
`auth/server_credentials.json` and private user data;
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
has since rotated or been revoked, use Connect Twitch in the authenticated panel,
or reauthorize through the desktop using the intended profile and stop it before
restarting headless. Never delete the current volume to
test a restore. For the existing private ARM64 host, use the
[repeatable release update](#repeatable-release-update) below. For other hosts, prepare
the exact release image before stopping, preserve the previous image/configuration,
then stop, verify a whole-profile backup and recreate with the prepared image. Reuse
current state for backward-compatible rollback, retaining rotated OAuth tokens.
Incompatible state requires a reviewed recovery plan; never restore an older profile
unconditionally. No registry publication or automatic update is configured.

The channel-scoped database upgrade uses the same backend as Desktop. Before first
startup on legacy state, provide the private explicit channel mapping beside the
database; see [versioned upgrade and recovery](data-and-privacy.md#versioned-database-upgrade-and-recovery).
Its verified SQLite recovery snapshot expires seven days after creation and must
receive deletion/opt-out requests during that window. This schema change is not
compatible with older binaries: stop writers, preserve post-upgrade writes and current
privacy suppression, and use a compatible snapshot for any controlled rollback.
Whole-volume backups need their own fixed expiry (no later than 60 days) and privacy
handling; a live storage opt-out does not erase independent archives.

### Unpublished candidates

A successful **Full validation** run checks the selected source SHA on native AMD64
and ARM64 containers. **Build candidate** produces the Windows ZIP/installer for that
same SHA; it does not produce a server image or publish a release.

For a later server update without a release tag, retain that full SHA and its successful
run links. Prepare a separate clean checkout at the exact SHA, or extract a source
archive made with `scripts/package.ps1` from that clean checkout. Build the canonical
Dockerfile natively on the server using its existing platform and Compose inputs.
Keep the previous image/configuration, then follow the stopped-volume backup and
replacement procedure above, preserving the existing volume and external secrets.
Do not run a second bot against the same account to test the candidate.

The release helper below requires a published tag and deliberately rejects unpublished
candidates. Candidate preparation does not update the running server; cutover and
rollback compatibility still require an explicitly authorized deployment.

## Repeatable release update

The operator request `Deploy release v<VERSION> to heetkit` starts a **separate manual
deployment** of the existing host. Pushes, Quick, Full validation, candidate builds
and release publication never deploy. Preparation of this helper does not authorize
SSH, account checks or changes on the VM. The first live deployment must inspect the
existing private host wrapper before using or replacing it; its interface is not
assumed by the tracked scripts.

Use [scripts/deploy_release.sh](../scripts/deploy_release.sh), which launches the
standard-library [Python helper](../scripts/deploy_release.py) on the existing Linux
ARM64 host. It uses the canonical Dockerfile and the host's existing Compose inputs,
project `heetkit`, service `bot`, volume `heetkit_profile`, three external secret files
and private Tailscale HTTPS overlay. Docker/Compose, Git, Python 3.12+, `ss` and
Tailscale must already be installed and usable by the same operator. It provisions
nothing. Keep any required sudo setup outside Git; do not invoke a second copy with
another state directory, Docker context or user.

Before running it, the deploying agent must:

1. Resolve the explicitly requested published tag to a full commit SHA and read its
   release/migration notes. If the owner explicitly requests latest, resolve one
   published stable version once, then pass its explicit tag and SHA. The helper
   independently checks publication, fetches that tag into an isolated directory,
   requires the expected SHA and matches `app/version.py`; it never selects main tip.
   Check available same-SHA validation evidence; record historical/missing evidence
   honestly without dispatching Full, rebuilding Windows or publishing anything.
2. Connect through the existing SSH/Tailscale route, retaining host-key verification.
   Inspect the existing wrapper and actual Compose/environment paths without printing
   credentials or profile contents. Confirm there is no other bot using the same
   account outside this host. Preserve unrelated checkout work. Do not start a second
   bot to test a candidate. A VM-local lock cannot police other hosts or manual commands.
3. Review migration and rollback compatibility **before** permitting cutover. Add
   `--rollback-compatible` only when old code can safely use the current profile after
   the new release has run. Without it, a failed cutover leaves the candidate stopped
   for deliberate recovery. A failure before cutover can resume the unchanged original.

Keep host settings in an operator-owned mode-600 JSON file outside the checkout.
This example contains placeholders, not a VM provisioning or installation command:

```json
{
  "state_dir": "/absolute/private/deployment-state",
  "env_file": "/absolute/private/compose.env",
  "compose_files": [
    "/absolute/existing/checkout/compose.yaml",
    "/absolute/existing/checkout/compose.remote.yaml"
  ],
  "minimum_free_bytes": 4294967296,
  "minimum_available_memory_bytes": 536870912,
  "health_timeout_seconds": 180
}
```

The state directory must be operator-owned mode 700. The mode-600 `env_file` retains
the existing `HEETKIT_PLATFORM=linux/arm64`, `HEETKIT_SECRETS_DIR`,
`HEETKIT_MANAGEMENT_ORIGIN` and `HEETKIT_TWITCH_REDIRECT_URI` values. Secrets remain
file-backed outside Git; no bearer appears in arguments, environment or output.
The helper ignores inherited `HEETKIT_*`/`COMPOSE_*` overrides, checks resolved Compose
against the actual container, and refuses a changed volume, command, environment,
secret mount, public port or unexpected profile user. Use one stable state directory
for the host lock. Do not edit Compose inputs, secrets or bot policy during deployment.

On the host, with the checked helper version available:

```bash
bash /absolute/checked-helper/scripts/deploy_release.sh \
  --config /absolute/private/deploy.json \
  --release v<VERSION> --sha <FULL_RELEASE_SHA>
# Append --rollback-compatible only after the migration review above.
```

The helper checks disk space on both state and Docker storage and available memory,
then builds natively while the original service remains available. Adjust thresholds
upward for the actual profile/build size; defaults are minimum headroom checks, not a
capacity guarantee. Builds have a 30-minute bound. After safe archive extraction,
only archived public source directories are set to 755 and files to 644 (755 for
Git executables). This repairs the data filter's discarded directory modes under
umask 077 so UID 10001 can traverse Python packages. The attempt parent, Git metadata,
backups and private inputs retain restrictive permissions. A verified
already-running exact SHA/image is a no-op. Preparation failures leave the original
service alone.

Before cutover it preserves the previous image ID, resolved Compose configuration,
original input/secret copies and their mapping/checksums in a private attempt folder.
It stops the bot cleanly, checks that no running container mounts the profile, archives
the whole stopped volume with a network-disabled tar process in the old image, reads
every archive file, records modes/ownership/digests and verifies copied SQLite databases
with `integrity_check`. Links, special files and traversal paths are refused. A failed
stop/backup prevents replacement and attempts to resume the original service. The
archive includes OAuth tokens and user data; retain it only on host under the existing
private backup policy. This on-host copy does not replace independent off-host recovery.

Recreation targets only `bot`, with `--no-build --pull never`, the immutable prepared
image ID and the preserved resolved configuration. A stopped container stays stopped
and is recorded with health untested. For a running process, health/panel checks allow
180 seconds by default (90–600 configurable), including the 75-second Docker grace.
Checks cover Docker image/mounts/restarts/OOM, authenticated status, unchanged
mode/channel/account, panel assets, loopback listener and private HTTPS returning 401
without authentication. Persistent Tailscale Serve must proxy to that loopback and
Funnel must be disabled, using its [Serve configuration fields](https://github.com/tailscale/tailscale/blob/main/ipn/serve.go).
Manual reconnects only if it was connected immediately before stopping; Disabled and
stopped Manual stay disconnected. Automatic modes reconcile normally, so Stream Only
may follow a changed stream state. No chat message, AI request or new OAuth consent is
used as a check. Health does not prove message delivery or an independent external
network penetration test.

After verified success, `state_dir/active-compose.json` is the private pinned operational
configuration. Use `docker compose --project-name heetkit -f /absolute/private/deployment-state/active-compose.json ...`
for subsequent manual starts/stops; an old wrapper or unpinned checkout command could
otherwise select an older image. The original files are retained for future input
resolution; the helper always records the actual previous image. Retain all attempt
folders, rollback image tags and recovery artifacts until owner acceptance supersedes
them. No pruning is automatic.

Each attempt's `deployment.json` records tag/SHA, source release URL, old/new image IDs,
backup checksum, before/after policy, interruption timestamps and deployment/rollback
outcome. `profile-manifest.json`, `profile.tar.gz.sha256`, `inputs/manifest.json`, and
the previous/candidate Compose snapshots hold recovery evidence. On failed cutover,
`startup-diagnostics/` captures candidate state and the last 200 timestamped log lines
from stdout/stderr before rollback can replace the container. These mode-600 files
remain inside private host state: logs may contain private runtime data and must not
be uploaded or printed. Diagnostic failures are recorded and do not block recovery.
Commands and raw HTTP/provider/profile responses are not logged. A nonzero exit never claims deployment or
rollback success; inspect that private record. Process loss or an interrupted SSH
session requires inspecting the lock, record and actual container before retrying.

On failed cutover, the helper first stops and verifies the candidate. If compatibility
was explicitly established, it recreates the previous image/configuration with the
**current** profile and verifies recovery. It never extracts a backup into the live
volume or restores old external secrets. Incompatible migrations require an explicitly
reviewed stopped-state recovery plan and may need a separate volume. Old OAuth tokens
may already have rotated or been revoked; retain current token state where compatible,
otherwise report that owner reauthorization is required. If stopping, compatibility or
recovery verification is uncertain, keep the service stopped where possible and report
the gap; never start another bot or claim a healthy rollback.

## ARM64 builds and Oracle A1 preparation

Use the same Dockerfile and `compose.yaml` + `compose.remote.yaml` for Oracle's
Ampere A1. ARM64 is an explicit opt-in, preserving existing AMD64 installations:

```bash
export HEETKIT_PLATFORM=linux/arm64
```

Persist this non-secret value in the deployment shell file described under
[first boot](#compose-review-and-first-boot), including across sudo. A missing
selection on A1 would request AMD64 and could fail or run under emulation.
Do not remove the platform setting or silently substitute another architecture.

Build on a separate machine when runtime memory is limited. Select the target
platform there, run the canonical container check, then build the production image
with `docker compose build`. Transfer only an approved image archive and checksum,
using `docker image save --output heetkit-arm64.tar heetkit-headless:local` and
`docker image load --input heetkit-arm64.tar`; verify the archive checksum and inspect
the loaded image's architecture and use `dc up -d --no-build` on the destination.
Keep the same committed source revision, Compose files and image ID with the archive.
No registry publication or second Dockerfile is required. Node and build tools are
already absent from the final runtime. This reduces build-time RAM pressure; it does
not establish a runtime memory minimum. Measure host available memory, swap activity,
container memory, OOM events and disk usage during authorized native acceptance.

### Exact Oracle instance creation steps

VM creation is separate from running or updating HeetKit. Choose an OS/architecture,
size and private access route using your provider's current instructions. Confirm
availability and billing yourself; this guide does not promise free capacity.
On Oracle A1 use native ARM64 and the platform setting above.

## Azure VM deployment plan

The same Linux/Docker runtime works on an appropriately sized AMD64/ARM64 host.
This is not a requirement to provision Azure or change an existing working host.

### Student offer, availability and sizing

Check current account eligibility, region capacity and charges with the provider.
Measure actual workload, memory and disk needs; an introductory offer is not an
ongoing cost guarantee.

### Exact proposed configuration and costs

There is no universal machine size or reliable fixed cost table. Keep management
private, persistent state on reliable local storage, and enough space for the previous
image, a stopped-profile backup and the candidate build. Set an operator budget and
alerts before creating resources.

### Provisioning and network restrictions

Use an operator-controlled Linux host with Docker/Compose, verified SSH host keys and
private management access. Restrict inbound access; HeetKit needs outbound Twitch and
selected-provider access. Do not publish management to the Internet. Existing-host
updates do not require new VMs, DNS, OAuth consent or firewall exposure.

### Compose review and first boot

Follow [private storage/setup](#prepare-private-storage-and-authorization), then
[run and inspect](#run-and-inspect). Use the canonical Dockerfile and Compose files.
Pin the native platform explicitly on ARM64. Keep secret values outside Compose and
Git; preserve the mounted profile and runtime UID 10001 permissions.

Start only one bot instance for the account. Authenticate to the private panel,
configure Twitch, and choose the intended operation mode. Browser setup does not
require transferring a Desktop profile. A running container alone does not prove
that Twitch authorization or chat delivery works.

### Cutover and rollback

Prepare and validate the exact source/image first. Preserve lifecycle diagnostics
before stopping. Stop the current owner, verify it is stopped, then verify a private
whole-profile backup before migration or replacement. Reuse current credentials,
volume, restrictions and operation mode. Never start a second bot to test the update.

Follow [repeatable release update](#repeatable-release-update) for published releases
or [unpublished candidates](#unpublished-candidates) for an explicitly selected source.
For compatible rollback, keep current state and rotated tokens. If the database was
upgraded incompatibly, stop the candidate and use the reviewed schema-compatible
recovery plan. Never run old code against the upgraded database or blindly restore
an old whole profile over newer privacy state or OAuth tokens.

### Backup, recovery and ongoing operation

Use [backup, restore and updates](#backup-restore-and-updates). Keep image/revision,
Compose inputs, archive checksum/manifest and recovery evidence together privately.
Migration snapshots expire after seven days; independent archives need their own
fixed expiry (at most 60 days) and deletion/opt-out handling. Restore current privacy
requests before any restart. Test recovery without creating a competing live bot.

Monitor actual health, reconnect failures, disk/memory pressure and backup expiry.
Independent off-host backups and alert delivery require their own setup and checks;
a local archive or successful startup does not establish them.

### Owner inputs and approval checklist

Before provisioning, agree the host/provider, billing limit, architecture, private
access, storage/backup plan and account ownership. Before an existing-host update,
select the exact source and validation evidence, preserve current inputs, and review
migration/rollback compatibility. Publication and deployment are separate actions.

## Troubleshooting and validation

- Missing secret directory/file: export `HEETKIT_SECRETS_DIR` in the shell that runs
  Compose and create both files. Do not paste secret values into Compose YAML.
- Cannot read `_FILE`: check host-file permissions for UID 10001; do not print the
  file into logs. Secret files are read on process startup; recreate/restart after
  replacement, including when an editor replaced the host inode.
- Missing/expired authorization: stop, repair the matching desktop authorization and
  private profile, stop the desktop, then restart; or use Connect Twitch in Server
  Settings. An existing JSON cache alone does not establish valid authorization.
- Permission/SQLite/lock failure: check volume ownership, free space and that another
  process does not own the profile. Use local storage with reliable SQLite locking;
  network filesystems are not validated.
- Unhealthy/reconnecting: inspect lifecycle logs, DNS, outbound network and account
  access. A running process is not sufficient evidence of a usable connection.

Browser-managed secret rotation needs no process restart. External nonempty inputs
always win and cannot be changed by the browser; restart after host-side rotation.
After removing external inputs, a retained browser value becomes effective again.
Remove obsolete browser values before switching provisioning methods. Clearing a
browser credential atomically removes it from the current document but does not
revoke it with the provider or securely erase filesystem blocks, volume snapshots,
backups or browser history. Rotate/revoke at Twitch/Google when compromise is
suspected and handle retained copies separately. Use host/disk/backup encryption
where required; the application does not encrypt this document itself.

`python3 scripts/check_linux_container.py` builds the canonical Compose image and
uses a randomly named disposable project/volume with synthetic settings and secrets.
It stages tracked build inputs in a temporary context with synthetic excluded profile,
secret and generated-frontend decoys, checking that none appear in the image; it never reads
the checkout's ignored profile or secrets.
It disables container networking and replaces only the Twitch remote boundary.
It checks non-root execution, absence of GUI dependencies, real OS signals,
stop/start, container recreation in all operation modes, synthetic stream transitions
and monitoring failures, saved configuration/personality/filter loading,
SQLite persistence/integrity and the real atomic token-cache loading/rotation/flush
paths. It checks the built image and runtime architecture and reports native versus
emulated execution relative to the Docker Engine. Set `HEETKIT_PLATFORM=linux/arm64`
to check ARM64; the default check remains AMD64. An emulated pass is build/runtime
evidence, not native ARM64 or cloud acceptance. A native check on the chosen VM is
still required. It removes only its own test project/volume and uniquely tagged image,
and uses an empty env file rather than reading a checkout `.env`. The Linux GitHub Actions
workflow runs that same script on native AMD64 and ARM64 runners; it publishes no image
or release. Live Twitch/Gemini
authorization, refresh and reconnect still require separately authorized account tests.

To refresh dependency pins, resolve the base `pyproject.toml` requirements for CPython
3.14 Linux amd64 **and** arm64 with wheels only, constraining compatible shared versions to
`packaging/windows/requirements.txt`, retaining the security minimums declared in
`pyproject.toml`. Record every resolved wheel's SHA-256 in the
Linux lock, retaining both architectures' hashes for native packages. Pure-Python
wheels can share a hash. Verify hashes against the published PyPI files, update
the shared hash-locked `packaging/python-bootstrap.txt` installer when required, update
official multi-platform base-image digests deliberately, and rerun the focused
container validation for each platform. Do not install the Windows packaging requirements into Linux.
