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

The canonical `Dockerfile` pins the official CPython 3.14.7 Debian slim image by
digest. `packaging/linux/requirements.txt` pins the complete backend wheel closure
with SHA-256 hashes. The build accepts wheels only, installs no GUI/build packages,
and copies allowlisted application sources and neutral defaults. A separate digest-pinned
official Node 24 build stage runs the existing locked React build. Only its production
page, icon and compiled assets enter the Python runtime; Node, frontend source/tests,
Windows tools, private profiles, dotenv files and development directories are excluded.
Reopened build-input directories explicitly exclude their children before allowing
specific source files; the native probe also rejects unexpected production assets.
The pinned base digests are multi-platform indexes; the same wheel lock permits
the matching CPython amd64 and arm64 wheels without changing package versions.
Other architectures are not covered. Linux uses `multidict==6.9.1`
as a narrow exception to the older Windows pins, fixing the upstream
[items-view reference leak](https://github.com/aio-libs/multidict/security/advisories/GHSA-54p9-h82j-f925).
The existing Windows redistribution inventory is unchanged by this container task.

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
test a restore. For an update, stop, back up, retain the previous local image for
rollback, check out the intended revision, then `docker compose build` and
`docker compose up -d --force-recreate`. Roll back source/image and compatible profile
backup together if a future version changes profile formats. No registry publication,
automatic update or cloud deployment is configured.

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

These are **owner steps for a separately approved provisioning window**. Do not
create even networking resources during packaging/preflight. Oracle A1 is the first
candidate; [OVHcloud VPS-1](https://www.ovhcloud.com/en-gb/vps/) is the paid AMD64
fallback, requiring its own current VAT-inclusive quote and purchase approval.

1. The owner signs up/signs in privately, completes identity/card checks if required,
   enables MFA and records the tenancy's **home region**. Choose a nearby available
   European region at signup if suitable; UK student status does not require UK hosting.
   Existing tenancies must use their home region for free compute. Confirm account
   limits, existing usage and available A1 capacity; trial credit alone is not proof
   that a resource remains free. Do not upgrade billing or select paid substitutes.
2. Plan one `heetkit-01`: **VM.Standard.A1.Flex, 1 OCPU, 2 GB RAM**, Ubuntu **24.04
   LTS aarch64/ARM64** platform image (not Minimal Ubuntu) marked Always Free eligible,
   **50 GB Balanced boot volume**, no additional data disk. This is an initial sizing candidate, not
   a measured minimum. Record the image version. Use ordinary on-demand capacity,
   not preemptible, dedicated, reserved or a pool. Do not choose A2 or an AMD shape.
3. In Networking create a dedicated VCN `10.42.0.0/16`, regional public subnet
   `10.42.1.0/24`, Internet Gateway and `0.0.0.0/0` route to that gateway. Use one
   VNIC with an ephemeral public IPv4 for outbound access/bootstrap; no NAT Gateway,
   load balancer or bastion. A public management listener is unnecessary with
   Serve, but Tailscale/Twitch/package downloads still need an internet egress route.
4. Restrict stateful inbound TCP22 to the owner's current public IPv4 `/32` for
   bootstrap. Remove any default `0.0.0.0/0` SSH rule from **every attached security
   list** and check every NSG: OCI allows the union of their rules, so a restrictive
   NSG does not cancel a permissive subnet rule. Preserve necessary ICMP path-MTU
   rules and permit outbound DNS/HTTPS/NTP and Tailscale traffic with stateful replies.
   Do not add ingress for 80, 443, 8765 or 4343. After tailnet SSH is verified,
   remove public TCP22 from both OCI rules and the host firewall.
5. Console **Compute → Instances → Create instance**: choose the intended compartment,
   name and an available home-region availability domain. Change image to the Ubuntu
   ARM64 image above; Change shape → Virtual machine → Ampere → `VM.Standard.A1.Flex`;
   set **1 OCPU / 2 GB**. Select the prepared VCN/subnet and public IPv4. Upload only
   an OpenSSH **public** key; retain its private key locally. Ubuntu's login is `ubuntu`.
   Set the boot volume to 50 GB, default encryption and Balanced performance, with
   no higher paid performance tier or extra volumes. Leave cloud-init free of secrets
   and deployment scripts. Plan to preserve the boot volume on later termination.
6. On Review, confirm the free-eligible image/shape, aggregate compute/storage
   allowances and **$0 ongoing expected total**, including IP/egress and any selected
   monitoring/backups. Remove optional paid services. If the estimate is nonzero or
   eligibility is unclear, stop. Only explicit provisioning approval authorizes
   **Create**. If A1 is out of capacity, try another availability domain in the same
   home region later; do not change billing/region/shape automatically.

Oracle's [current Always Free limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
are 1,500 A1 OCPU-hours and 9,000 GB-hours monthly, 200 GB total boot/block storage
and five volume backups. One 1-OCPU/2-GB VM uses at most 744 OCPU-hours and 1,488
GB-hours in a 31-day month. Check shared usage before applying these allowances.
Use an off-account encrypted backup too. Capacity shortages and reclamation of
idle instances are material risks for a lightweight bot; do not manufacture load.
Oracle Free Tier has [no SLA](https://www.oracle.com/cloud/free/faq/).
See the official [instance creation guide](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/launchinginstance.htm)
and [security-rule semantics](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/securityrules.htm).
The [platform image list](https://docs.oracle.com/en-us/iaas/Content/Compute/References/images.htm)
specifies the standard Ubuntu image for Arm shapes.

After separate deployment approval, verify `uname -m` is `aarch64`, install Docker
Engine/Compose for Ubuntu arm64 and host-side Tailscale, and run the canonical
synthetic check **natively before adding private state**. Use the same
[fresh browser bootstrap](#compose-review-and-first-boot),
[one-bot cutover/rollback](#cutover-and-rollback) and
[stopped-volume backup/restore](#backup-restore-and-updates). Provider-specific
Azure budgets/health alerts below do not configure Oracle monitoring: arrange OCI
cost/usage notifications, disk/memory/health checks, backup-failure alerts and an
independent outage receiver within verified free limits, and test their delivery.
Provisioning does not authorize profile transfer, provider credentials, Twitch
redirect changes, OAuth consent or live cutover; those remain separate owner gates.

## Azure VM deployment plan

This is a provisioning runbook for one private browser-managed instance, not a
claim of cloud acceptance. Obtain explicit owner approval before creating resources,
using credit, accessing accounts/secrets, importing configuration or connecting Twitch.
The commands below are for the approved deployment window; preparing this plan does
not authorize running them. Keep the existing Python core and React presentation.
This retained Azure cost example is an optional alternative, not the selected
provider, region or a measured RAM requirement. Oracle A1 is the first candidate;
OVHcloud VPS-1 is the paid fallback. The Compose/bootstrap and cutover procedures
also apply to either provider with the explicit architecture selection above.

### Student offer, availability and sizing

Public information and unauthenticated UK South retail prices were checked on
**21 October 2026**. Personal eligibility, subscription balance/expiry, free-service
entitlements, allowed regions, quota and live capacity require an owner portal check.
No public price listing can establish that a particular student subscription can
allocate a VM. UK South below is only a priced example; student residence does not
establish a required hosting region. Requote eligible regions before choosing Azure.

[Azure for Students](https://azure.microsoft.com/en-gb/free/students/) advertises
USD100 credit usable within 12 months, annual renewal while eligible, and 750 hours
each per month of B1s, B2ats v2 and ARM-based B2pts v2 for eligible new customers.
750 hours covers a 744-hour month, but unused hours do not increase RAM or cover a
different SKU. The AMD64 choices in that free allowance have **1 GiB**, not 2/4 GiB.
B2pts v2 is ARM and needs separate Azure sizing/eligibility checks. Annual student
renewal must not be assumed to renew first-year free-service benefits.

The [offer terms](https://azure.microsoft.com/en-us/pricing/offers/ms-azr-0170p)
require age 18+, full-time attendance at an accredited degree-granting institution
and academic verification, with one subscription per eligible person. Students
Starter is a different offer and is not this VM plan. The
[education FAQ](https://learn.microsoft.com/en-us/azure/education-hub/faq) limits use
to education/teaching, noncommercial research, and developing/testing/demonstrating
applications for those purposes. A permanent production or monetized-channel bot
must not be assumed eligible: the owner must establish permitted use, obtaining
Microsoft clarification if necessary. Credit exhaustion/expiry can disable access;
renewal or conversion to paid billing is a separate owner decision.

| AMD64 Linux size | vCPU / RAM | USD/hour | VM only, 730 hours | Assessment |
| --- | --- | --- | --- | --- |
| Standard_B2ats_v2 | 2 / 1 GiB | 0.0106 | 7.74; 0 if eligible free hours apply | Free-tier experiment only; inadequate safety margin for builds/host/services without measurement |
| Standard_B1s | 1 / 1 GiB | 0.0118 | 8.61; 0 if eligible free hours apply | Legacy Bv1; same memory concern |
| Standard_B1ms | 1 / 2 GiB | 0.0236 | 17.23 | Lowest-cost candidate here for a temporary trial; tight build/RAM margin and legacy capacity risk |
| Standard_B2als_v2 | 2 / 4 GiB | 0.0425 | 31.03 | Retained 4 GiB cost example; not a measured minimum |
| Standard_B2ls_v2 | 2 / 4 GiB | 0.0472 | 34.46 | Intel x86-64 fallback if explicitly approved and allocatable |
| Standard_B2s | 2 / 4 GiB | 0.0472 | 34.46 | Legacy Bv1; no saving over the current 4 GiB options |

Rates came directly from Microsoft's public
[Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices):
filter `armRegionName eq 'uksouth'`, `serviceName eq 'Virtual Machines'`,
`priceType eq 'Consumption'` and the exact `armSkuName`; select `Virtual Machines`
products only, excluding Windows, Spot, Low Priority and Cloud Services meters.
For example, [the B2als v2 query](https://prices.azure.com/api/retail/prices?$filter=armRegionName%20eq%20%27uksouth%27%20and%20armSkuName%20eq%20%27Standard_B2als_v2%27%20and%20priceType%20eq%20%27Consumption%27)
includes several products, so inspect the product name as well as the price.

Microsoft marks [Bv1 as end of life](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/bv1-series),
with [retirement scheduled for 15 November 2028](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/lifecycle/retirement/retired-sizes-modernization-guide).
That makes B1ms a cost-saving compromise, not the preferred new deployment.
[Basv2](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/basv2-series)
uses AMD x86-64 and CPU credits; B2als v2 has a 30% normalized baseline. Sustained
builds can exhaust credits and slow down. These memory concerns are engineering
estimates, not measured HeetKit cloud benchmarks. Building off-host avoids frontend
build pressure; measure native runtime RAM before rejecting a smaller VM. A small
private swap file can help with temporary pressure but does not replace RAM.

### Exact proposed configuration and costs

This example uses **one Standard_B2als_v2, UK South, Ubuntu Server 24.04 LTS AMD64 Gen2**,
ordinary pay-as-you-go compute paid from student credit, no Spot or reservation.
Use [Canonical's free LTS image](https://ubuntu.com/azure/docs/azure-how-to/instances/find-ubuntu-images/)
`Canonical:ubuntu-24_04-lts:server:latest`; record the resolved image version at
creation. Select Trusted Launch/Secure Boot/vTPM where supported by the chosen SKU.
Use no availability zone preference initially (one VM is not high availability).

Proposed resource names: resource group `rg-heetkit-uksouth`, VM `heetkit-01`, one
VNet `10.42.0.0/16`, subnet `10.42.1.0/24`, one NIC/NSG and one Standard static
IPv4. Use one **32 GiB E4 Standard SSD LRS managed OS disk**, platform encryption,
with delete-with-VM disabled. Keep Docker's `heetkit_profile` named volume on this
persistent OS disk. No temporary/ephemeral disk, shared disk, second data disk,
load balancer, NAT Gateway, Bastion, paid Defender plan or Log Analytics workspace.
Build layers, logs and backups must fit alongside the OS; alert on disk usage.

| Component | Assumption | USD/month |
| --- | --- | ---: |
| VM | B2als v2, 730 × 0.0425 | 31.03 |
| Persistent disk | One E4 LRS, 32 GiB | 2.64 |
| Disk transactions | Assumed 1 million × 0.002 / 10,000 | 0.20 |
| Public IPv4 | One Standard address, 730 × 0.005 | 3.65 |
| Internet traffic | Assumed 10 GB/month outbound within unused 100 GB allowance; ingress free | 0.00 |
| Monitoring | Basic platform metrics, ≤10 static metric time series, activity/resource-health alerts and low-volume email; local guest checks | 0.00 |
| Encrypted backups | 10 GB Hot LRS Blob v2 × 0.0192 plus roughly 1,000 writes/reads and small listing allowance | 0.21 |
| Tailscale Serve | Personal plan only if eligible noncommercial use | 0.00 |
| **Expected total** | Sum before display rounding | **37.73** |
| **Planning budget** | About USD2 contingency; alerts are not a spending cap | **40.00** |

Disk, IPv4 and Blob rates use the same public API with UK South consumption meters:
`E4 LRS Disk`, `E4 LRS Disk Operations`, `Standard IPv4 Static Public IP`, and
`General Block Blob v2` / `Hot LRS` tier zero. The shared-disk **Disk Mount** meter
does not apply to this single-VM disk. See [disk pricing](https://azure.microsoft.com/en-us/pricing/details/managed-disks/),
[IPv4 pricing](https://azure.microsoft.com/en-us/pricing/details/ip-addresses/) and
[Blob pricing](https://azure.microsoft.com/en-us/pricing/details/storage/blobs/).
The transaction estimate is a workload assumption, not a maximum; builds, swap
and frequent writes can exceed it. Use actual first-week usage to revise the forecast.

[Internet egress](https://azure.microsoft.com/en-us/pricing/details/bandwidth/)
includes the first 100 GB/month; the next European tier is USD0.087/GB on Microsoft's
network. Allowance may already be consumed by other usage. No inter-region copy is
included. [Monitor pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/)
has free metric/notification amounts; dynamic thresholds, log ingestion, extra
series, SMS and commercial uptime services need a revised quote. Azure Backup
service and snapshots are **not enabled** in this estimate: stopped encrypted volume
archives are the backup method. An optional 10 GB Standard HDD LRS snapshot would
add about USD0.53/month; repeated retained snapshots add storage and are not an
independent off-account backup. [Tailscale Personal](https://tailscale.com/pricing)
is for noncommercial personal use; a paid plan would add costs outside Azure credit.
Gemini/provider usage is separate and not paid by the Azure credit.

At 744 hours the baseline is about **USD38.39**. At the 730-hour average, a full
USD100 lasts approximately **2.65 months**, or about **2.1 months before a USD20
reserve**. Annual baseline is about USD452.70. B1ms with the same ancillary costs
is about **USD23.93/month**, lasting 4.18 months before reserves, or 3.34 months to
the USD20 reserve. Neither 2 nor 4 GiB offers 12 months within USD100. Actual runway
is `(remaining credit - reserve - other planned spend) / monthly cost`, bounded by
the credit expiry date. Prices are USD retail estimates before any applicable tax;
GBP billing conversion and other subscription usage require an owner quote.

The [free-service catalogue](https://azure.microsoft.com/de-de/pricing/free-services/)
also lists first-year 2 × 64 GB P6 disks, 1 GB snapshots, 2 million disk operations
and 5 GB Hot LRS Blob storage with operation allowances. Do not apply those
allowances to E4 automatically. If the owner's Free services page confirms an
unused P6 entitlement for this subscription, **one 64 GiB P6 LRS OS disk** can
replace E4 and lower baseline to about **USD35.09** (or lower if disk operations
and Blob also qualify).
Otherwise that P6 costs **USD12.3499/month**, versus E4's USD2.64. Reconfirm entitlement
and expiry before choosing it; stop or switch disk tier before free coverage ends.
A free 1 GiB B2ats v2 plus paid E4/IPv4/backups would be about USD6.70/month while
eligible; its runtime memory margin needs measurement with the image built off-host.
Do not describe it as a proven reliable free year without that acceptance.

### Provisioning and network restrictions

1. **Owner gate:** confirm permitted student/Tailscale use, remaining credit and
   expiry, UK South allowed by policy, regional and Standard Basv2 family quota
   of at least two vCPUs, and selectable B2als v2 capacity. Read-only portal review
   or `az vm list-skus --location uksouth --size Standard_B2als_v2 --all` and
   `az vm list-usage --location uksouth` need owner account-access approval.
   Check SKU restrictions and Review + create validation, but do not click Create
   until provisioning is approved. Even successful validation does not reserve
   [capacity](https://learn.microsoft.com/en-us/azure/azure-resource-manager/troubleshooting/error-sku-not-available).
2. Set a USD40-equivalent monthly resource-group budget, actual alerts at 50/80/100%
   and forecast at 100%; verify owner email delivery. Monitor the subscription's
   remaining credit separately; plan shutdown/rollback at USD20 remaining or 30 days
   before expiry, whichever comes first. Keep the student spending protection;
   do not upgrade billing automatically. If budgets are unavailable for the offer,
   use Education Hub/Sponsorships credit checks and owner calendar reminders.
   [Budgets](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets)
   evaluate delayed usage and do not stop resources or impose a custom hard cap.
3. Create only the approved resources above. Create an SSH admin `heetadmin` with
   a dedicated passphrase-protected Ed25519 public key; keep the private key on the
   owner's computer. Disable password and root SSH login. Keep Azure account MFA
   enabled. Allow initial inbound TCP22 **only from the owner's current public /32**.
   Never allow TCP22 from the whole internet. Do not place private keys, provider
   secrets or management tokens in portal custom data/cloud-init or shell history.
4. NSG: initial allow TCP22 from that /32 at priority 100; deny all other inbound
   at priority 200, overriding default VNet inbound allowances. No inbound rules
   for TCP80, TCP443, TCP8765 or TCP4343, and no public IPv6. Keep normal outbound
   connectivity for DNS, NTP, OS/package downloads, HTTPS/WebSockets and Tailscale.
   The Standard public IPv4 supplies **explicit outbound connectivity**, even with
   all unsolicited ingress blocked; new Azure private subnets cannot rely on
   [implicit outbound access](https://learn.microsoft.com/en-us/azure/virtual-network/ip-services/default-outbound-access).
5. Verify the SSH host key through an independent Azure console/control-plane
   path before trusting it. Patch Ubuntu and reboot before application setup.
   Enable security updates with planned reboots. Use host firewall default-deny
   incoming/default-allow outgoing, allow only the bootstrap /32 SSH and later
   TCP22/TCP443 on `tailscale0`. Check effective nftables/iptables rules: Tailscale
   installs its own rules, so policy plus the loopback bind and Azure NSG remain
   essential. No `ufw allow 443` on the public interface. Keep a second SSH session
   open while testing firewall/login changes.
6. Install Docker Engine from its
   [signed Ubuntu repository](https://docs.docker.com/engine/install/ubuntu/):
   `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`.
   Ubuntu 24.04 x86-64 is supported. Enable Docker/containerd at boot, record package
   versions and verify Engine/Compose. Use sudo for Docker; docker-group membership
   grants root-equivalent power. Do not expose the Docker API or mount its socket.
7. Install Tailscale on the host using its signed Ubuntu packages. The owner signs
   in interactively and approves only the VM and intended computer/phone. Use
   neutral hostname `heetkit-01`; enable MagicDNS/HTTPS. The owner must accept
   [certificate-transparency disclosure](https://tailscale.com/docs/how-to/set-up-https-certificates)
   of its machine/tailnet DNS name. Restrict tailnet grants to the owner and this
   VM's TCP22/443, removing any broader matching default allow rule. Other devices
   must fail to connect. Use ordinary key-based OpenSSH over Tailscale, with no
   subnet routing, exit node or public Funnel. Review node key expiry; disabling
   expiry only for this trusted server requires an explicit owner choice.
8. Verify tailnet SSH from a new session, then remove the public TCP22 allow rule
   from NSG and host firewall. Retain the public IP for outbound only. Test DERP
   relay connectivity without adding inbound UDP; it may be slower but suffices
   for management. Follow [Tailscale's firewall guidance](https://tailscale.com/docs/reference/faq/firewall-ports)
   if troubleshooting outbound UDP/443. Record a break-glass procedure: owner MFA
   portal access restores a temporary /32 SSH rule, then removes it after repair.
   Preserve the OS disk on VM deletion and keep an encrypted off-account backup.

### Compose review and first boot

Source review finds no Ubuntu/Azure-specific application change required.
`compose.yaml` pins `linux/amd64`, UID/GID10001, the private named volume, read-only
root, dropped capabilities, PID/tmpfs bounds, log rotation and `unless-stopped`.
`compose.remote.yaml` uses native Linux host networking, binds **127.0.0.1:8765**,
trusts only proxy peer 127.0.0.1 and fixes the HTTPS origin/callback. It declares
no published ports. Host networking is deliberate for Serve's peer identity;
it also means the host must be trusted and the usual container network isolation
does not apply.
Do not use `compose.management.yaml` with the remote overlay or add `ports:`.
The Debian userspace image is compatible with an Ubuntu host kernel. Actual VM
build, permissions, Serve headers/certificate and restart behavior remain deployment
acceptance checks, not facts established by this source review.

1. Use a checkout/staging directory containing only the approved committed source
   revision; pin and record the agreed deployment commit.
   Build with the existing Dockerfile. No registry publishing or second build path.
   Retain the image ID/revision and prior image for future rollback. Never include
   Desktop profiles, local `.agent` files, secrets or acceptance resources in transfers.
2. In the admin home, create `~/.config/heetkit-secrets` mode700 outside the checkout.
   Create empty `twitch_client_secret` and `gemini_api_key` files for browser setup.
   Generate `management_token` using `secrets.token_urlsafe(32)` and exclusive file
   creation as in [Enable private access](management-api.md#enable-private-access),
   using Ubuntu's `python3`. Never print it into logs/chat. Set the three files
   mode444 under the mode700 parent so native Linux mounts are readable by UID10001.
   Retrieve the token into the owner's password manager through a trusted private
   SSH/secret workflow. Browser provider inputs stay empty until authenticated setup.
3. Store only the following **non-secret** values in a repeatable deployment shell
   file outside the checkout (private permissions). Replace the example origin with
   the actual Tailscale DNS name; no trailing slash. Source it for every operation.

   ```bash
   export HEETKIT_SECRETS_DIR="$HOME/.config/heetkit-secrets"
   export HEETKIT_PLATFORM=linux/amd64 # use linux/arm64 for Oracle A1
   export HEETKIT_MANAGEMENT_ORIGIN=https://heetkit-01.example-tailnet.ts.net
   export HEETKIT_TWITCH_REDIRECT_URI="$HEETKIT_MANAGEMENT_ORIGIN/oauth/callback"
   ```

   Use this same command prefix throughout, from the pinned checkout:

   ```bash
   dc() { sudo --preserve-env=HEETKIT_PLATFORM,HEETKIT_SECRETS_DIR,HEETKIT_MANAGEMENT_ORIGIN,HEETKIT_TWITCH_REDIRECT_URI docker compose --project-name heetkit -f compose.yaml -f compose.remote.yaml "$@"; }
   dc config --quiet
   dc build
   dc up -d
   sudo tailscale serve --bg http://127.0.0.1:8765
   tailscale serve status
   sudo ss -ltnp
   dc ps
   ```

4. Start with a **new empty** `heetkit_profile` volume. A fresh profile defaults to
   Always On but lacks identity/secrets/tokens, so it cannot connect. Immediately
   sign in through tailnet HTTPS and save **Disabled before entering any provider
   details**. Confirm Dashboard stopped. Empty external provider files allow browser
   credentials; nonempty external inputs would take precedence. The management token
   is independent of provider credentials; protect browser sessions and log out on
   shared devices. Verify authenticated access works on the owner's computer/phone
   and fails for unauthorized devices/public IP; confirm port8765 listens only on
   loopback. Do not weaken Host/Origin/proxy checks if Serve fails.
5. After the owner's transfer approval, export a portable configuration ZIP through
   the existing local panel, review it privately, then preview/confirm its import
   through cloud Settings. Do not copy a profile, OAuth cache, keyring or SQLite.
   [Portable transfer](data-and-privacy.md#portable-configuration-transfer) excludes
   identity, credentials, history, storage opt-outs and operation mode. Confirm
   Disabled remains saved. Review AI memory/retention choices and any outstanding
   privacy suppression obligations explicitly; a fresh database does not carry old
   suppression IDs. Keep AI disabled until those choices are resolved.
6. In Settings → Server configuration, save the intended Twitch Client ID, bot
   login/numeric ID and target channel login/numeric ID. The owner enters the client
   secret privately in Server credentials; optionally provision Gemini separately.
   Register **exactly** `https://<actual-machine>.<actual-tailnet>.ts.net/oauth/callback`
   in the Confidential Twitch application's Developer Console. Keep existing
   Desktop/local redirect registrations for rollback. No public DNS record,
   inbound HTTPS port or Desktop callback port is necessary: the tailnet-connected
   **browser** follows Twitch's redirect.
7. Complete the stopped-source cutover gate below **before Connect Twitch**. Then
   the owner approves a new Twitch authorization while signed in as the expected
   bot; keep the initiating Settings tab authenticated and on Tailscale. Check
   Authorized account and Target channel, with cloud still Disabled. Do not
   transfer or reuse the old cache. The existing
   [Server flow](twitch-setup.md#server-browser-setup) persists the new authorization
   privately; failed/expired/denied attempts need a new attempt. Never share a
   callback URL. Only after identity verification and explicit go-live approval
   select Manual/Connect for a supervised smoke check, then the approved Always On
   or Stream Only policy.

### Cutover and rollback

There is no cross-host Twitch-account lock. Treat **one active bot instance** as a manual
operating invariant. A closed management tab or lost tailnet connection does not
stop chat. Stopping only one of several Docker test presets is insufficient.

1. Agree a downtime window and inventory Desktop, configured/fresh Docker tests,
   services, scheduled launchers and other devices using this bot account. Save
   local work and turn off automatic startup/restart for those copies. Exit Desktop
   through tray Exit and stop all relevant local containers/services. Owner verifies
   stopped processes/containers; preserve their profiles/backups unchanged.
2. Cloud stays Disabled throughout preparation. Once every source is stopped,
   authorize the fresh cloud profile and perform the supervised check above.
   Verify one reply to an owner-approved test command, saved settings, expected
   account/channel and selected operation policy. Do not use a public test account
   or send chat automatically as part of preflight.
3. After approval of that result, save the intended automatic mode. Observe real
   refresh/reconnect, temporary network recovery, host reboot and container
   recreation; check Stream Only live/offline transitions if selected. Keep local
   copies stopped. A 24-hour soak should show no OOM, persistent swapping, declining
   CPU-credit balance or prolonged unhealthy state; confirm memory/disk headroom.
4. For rollback, first save cloud Disabled (if reachable), `dc stop bot`, and verify
   the container is stopped. Disable any external auto-start jobs. If unreachable,
   the owner must stop the VM through its provider console and verify its state **before**
   starting a local copy. Network uncertainty is not evidence of a stopped bot.
5. Reopen exactly one preserved local profile only after cloud shutdown is verified.
   Reauthorize locally if provider authorization has changed; do not copy rotated
   cloud tokens over old state. Any new private-state recovery needs separate
   approval. Accept that new cloud history/settings may require deliberate export
   or recovery; portable ZIP does not carry history or privacy suppression state.

### Backup, recovery and ongoing operation

- **Daily backup:** agree a short UTC maintenance window (for example 04:00 UTC;
  UK local time varies with daylight saving). Stop the whole container, then use
  the [whole-volume archive procedure](#backup-restore-and-updates) with `dc` in
  place of bare `docker compose`. Back up the three host secret files and non-secret
  deployment metadata separately. Browser credentials/OAuth/SQLite are in the volume.
  Use a fail-safe restart handler only if the container was running before backup;
  do not revive a deliberately stopped instance. Restart promptly after the archive
  is complete, then encrypt/checksum/upload. Report backup failures without retaining
  unencrypted temporary archives. Do not copy live SQLite/token files.
- **Azure backup storage example:** plan one UK South StorageV2 Hot LRS private container with no anonymous
  blob access, HTTPS only, minimum TLS1.2 and no shared-key auth. Grant the VM's
  system-assigned identity Blob Data Contributor only at that backup container scope;
  use the subnet's Storage service endpoint and selected-network restriction, not
  a public anonymous share. Encrypt archives before upload using the owner's public
  encryption recipient; keep its recovery private key off the VM. This storage and
  its permissions are additional provisioning requiring owner approval. Retain seven
  daily plus four weekly archives within the 10 GB estimate; measure sizes and alert
  on growth. Include retained versions/soft-deleted bytes in that limit. Keep a
  weekly encrypted copy outside the hosting account so expiry or suspension cannot block
  recovery. The owner chooses destination, encryption key and retention policy.
- **Restore rehearsal:** decrypt/checksum the archive privately; stop production for
  a full rehearsal or create a distinct empty restore project/volume without starting
  its application. Restore as UID10001, verify expected files and SQLite integrity
  using a no-network helper with its entrypoint overridden. Never overwrite/delete
  the current volume. Before any restored runtime can start, set saved Disabled
  while stopped and verify it; then use the same one-instance cutover gate. Apply
  current deletion/opt-out obligations before connection. Old OAuth may require new
  browser authorization. Target RPO24h and RTO2h are goals requiring a measured
  rehearsal, not guarantees.
- **Restart:** enable Docker and tailscaled at boot. Compose `unless-stopped` resumes
  an existing running service after reboot; saved Manual/Disabled stays chat-stopped,
  and an explicitly stopped container stays stopped. Serve's
  [`--bg` configuration persists](https://tailscale.com/docs/reference/tailscale-cli/serve)
  across reboot. Verify these behaviors on the VM. Docker health does not itself
  restart an unhealthy container. Investigate auth/disk/network errors before
  supervised restart; avoid restart loops that hide the cause.
- **Monitoring:** sample container running/health/OOM state, host disk/memory and
  last successful backup every minute with a host-side systemd timer. Alert after
  five minutes unhealthy/missing, OOM immediately, free disk below 20%, sustained
  available RAM below 256 MiB or backup age above 26 hours. Maintenance must suppress
  expected short backup downtime without hiding a failed restart. Docker's private
  heartbeat distinguishes connected/intentional idle from failure; it is not chat
  delivery proof. Alert separately on repeated Stream Only unknown-monitor results
  rather than treating unknown as confirmed offline. No authenticated API token
  needs to be placed in a public uptime checker.
- **Off-host detection:** configure Azure Resource Health/Service Health email alerts
  plus CPU-credit/static CPU alerts within the free metric allowance. A host timer
  cannot detect its own dead VM: choose an owner-approved external dead-man heartbeat
  receiver and notification route, with an opaque identifier and no logs/secrets,
  or explicitly accept this monitoring gap. Its plan/notification cost must fit the
  quote before enabling it. Test unhealthy, backup-failure and missing-heartbeat
  notification delivery before unattended operation. Host/backup checks and alert
  jobs are deployment work to prepare/test later; they do not exist merely because
  the Compose healthcheck does.
- **Maintenance:** review credit weekly and usage daily during the first week;
  notify at USD50/USD30/USD20 remaining and 30/14/7 days to expiry. Log in to Azure
  at least every 90 days under the offer's inactivity policy. Patch/reboot in a
  maintenance window after a verified backup. For image updates, stop/back up,
  retain the prior image ID/source revision, build with the canonical Dockerfile
  and recreate with both Compose files and the same project/volume. Verify saved
  policy, private access and persistence. Roll back to the prior image; restore
  a matching backup only if formats changed, accounting for newer privacy deletions
  and OAuth rotations. Do not start a second copy to test rollback.
- **Cost stop:** stop the application and deallocate the VM before the reserve/expiry
  deadline if no further funding is approved. Guest shutdown alone may still bill
  compute; deallocation stops compute but retained disk, IP, storage and snapshots
  can still cost money. Export/rehearse an off-account backup first. Deletion of
  chargeable retained resources requires explicit owner approval and verified
  recovery copies; never delete the sole profile/backup to reduce cost.

### Owner inputs and approval checklist

Before provisioning, obtain all of:

- [ ] Owner confirmation of student eligibility, permitted project use and Tailscale
  plan suitability; Microsoft clarification if production/commercial use is uncertain.
- [ ] Approved read-only account check or owner-supplied non-secret results: correct
  subscription/offer, remaining credit, expiry, existing usage, free P6/Blob benefits,
  allowed regions, Basv2/regional quota and selected-SKU availability.
- [ ] Explicit approval for the exact VM/disk/network/storage/identity/monitoring
  resources and estimated USD37.73/month (USD40 budget), limited credit runway,
  USD20 shutdown reserve and downtime; no paid billing conversion by implication.
- [ ] Chosen SSH public key/admin access, source /32, recovery route, tailnet owner
  and allowed devices; HTTPS hostname disclosure and node-key-expiry choice.
- [ ] Backup recipient/recovery key, independent destination, retention/window and
  alert recipient/dead-man service. Accept or resolve any uncosted monitoring gap.

Separate later approvals/actions are required for:

- [ ] Portable ZIP export/import (it can contain private authored text/account blocks);
  no whole-profile/SQLite/keyring/OAuth migration under this plan.
- [ ] Owner-only entry of provider secrets, Twitch console redirect changes and new
  bot-account OAuth consent. Never paste these secrets or code URLs into chat/Git.
- [ ] Verified shutdown of every local copy and explicit cloud go-live/command delivery,
  real refresh/network/reboot/Stream Only checks, and the unattended operating mode.
- [ ] Any fallback region/size, paid Tailscale/provider service, quota/billing upgrade,
  restore of private state or deletion of retained chargeable resources.

Stop after preflight until provisioning is approved. Provisioning approval alone
does not authorize credentials, data transfer or live cutover unless expressly included.

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
workflow runs that same script; it publishes no image or release. Live Twitch/Gemini
authorization, refresh and reconnect still require separately authorized account tests.

To refresh dependency pins, resolve the base `pyproject.toml` requirements for CPython
3.14 Linux amd64 **and** arm64 with wheels only, constraining compatible shared versions to
`packaging/windows/requirements.txt`, retaining the documented `multidict>=6.9.1`
security override. Record every resolved wheel's SHA-256 in the
Linux lock, retaining both architectures' hashes for native packages. Pure-Python
wheels can share a hash. Verify hashes against the published PyPI files, update
official multi-platform base-image digests deliberately, and rerun the focused
container validation for each platform. Do not install the Windows packaging requirements into Linux.
