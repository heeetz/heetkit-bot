# Release process

Windows 10/11 x64 is the current distribution target. The installer is the primary
download and the portable ZIP is an alternative. Public downloads belong on
[GitHub Releases](https://github.com/heeetz/heetkit-bot/releases).

[Quick](https://github.com/heeetz/heetkit-bot/actions/workflows/quick.yml) is the only
workflow triggered by ordinary `main` pushes. [Full validation](https://github.com/heeetz/heetkit-bot/actions/workflows/full-validation.yml)
and [Build candidate](https://github.com/heeetz/heetkit-bot/actions/workflows/windows-build.yml)
are separate manual entry points. Both accept a branch, tag or commit SHA in `ref`
(blank uses the workflow commit), resolve it once and record the immutable SHA.
Every downstream checkout uses that SHA. Successful checks apply only to that commit.

[Publish](https://github.com/heeetz/heetkit-bot/actions/workflows/publish-release.yml)
is a separate manual entry point requiring an exact SHA, existing version tag,
successful candidate run ID and successful Full validation run ID. Dispatch all three
manual workflows **from main**, using their inputs to select source. Version-tag
pushes trigger no build or publication. Publish reuses the selected candidate's five
outputs without rebuilding; it cannot select a moving branch tip or a latest run.

## Check for updates

In **About → Updates**, choose **Check for updates** to compare the running version
with the latest stable public release. The card shows the current and latest versions,
the release title/date and a short preview of its notes. Only a greater stable
`major.minor.patch` version is offered as an update; an equal or older stable release
does not prompt a downgrade. A running beta can discover its final stable version.
Drafts and prereleases are excluded from update results.

The check uses GitHub's public API without signing in. If offline, temporarily limited
by GitHub, or unable to read a valid release response, the card reports the problem
and lets you retry while the rest of HeetKit remains usable. **Open release / downloads**
opens the official stable release page in your default browser, including when a check
fails. It provides the full notes and installer/portable downloads.

Checks run only when requested and leave saved settings and profiles unchanged.
HeetKit does not download or launch an installer, replace its executable, or check
automatically at startup. To install an update, download the installer from the release
page, quit HeetKit fully using **tray Exit**, then run setup. Existing settings are
retained; see the upgrade and retention guidance below.

## Build inputs and version

`app/version.py` is the canonical application version source. Runtime/About, Python
metadata, executable metadata and artifact names consume it. Do not maintain a separate
release version. Publication fails if the supplied tag differs from
`v<version>` or the version is invalid. Versions use `major.minor.patch`, optionally
followed by `-alpha.N`, `-beta.N` or `-rc.N`, for example `1.4.0-beta.1`.
Core components must fit Windows' 16-bit fields (0–65535); prerelease numbers are
1–9999, without leading zeros. Build metadata and other suffixes are not supported.

The full version remains visible in About, installer UI, tags, manifests and artifact
names. `app/version.py` derives numeric Windows metadata for executable resources
and installer downgrade checks: alpha revisions are 1–9999, beta 10001–19999,
rc 20001–29999 and stable 65535. This orders later betas and the final stable release
after earlier candidates of the same core version. Earlier stable builds used revision
zero; their lower core versions still upgrade normally.

The Windows builder requires Windows x64 CPython **3.14.7** and a Vite-compatible Node
version (**20.19+**; CI uses **24.20.0**). Python/runtime/build dependencies are pinned in
`packaging/windows/requirements.txt`; the frontend uses `npm ci` and its lockfile.
`packaging/python-bootstrap.txt` pins the SHA-256-verified pip installer used before
dependency acquisition, including its corrected vendored CA bundle.
Installer builds enforce [Inno Setup **6.7.3**](https://github.com/jrsoftware/issrc/releases/tag/is-6_7_3).
See [development setup](development.md#source-setup) for the source environment.

## Local build

From the repository root in PowerShell:

```powershell
.\scripts\build_windows.ps1
.\scripts\build_installer.ps1 -InnoCompiler 'C:\path\to\ISCC.exe'
```

The default bootstrap is `.venv\Scripts\python.exe`; use `-PythonPath` to select another
matching interpreter. The portable builder creates an isolated pinned environment under
`build/windows/`, builds/stages the frontend and licenses, freezes a PyInstaller onedir
bundle, inspects it, then creates the ZIP and checksum. Dependency acquisition needs
internet access.

Native redistribution evidence is pinned in `packaging/windows/redistribution.json`.
The builder downloads the exact hash-verified Windows SDK package for the reviewed
UCRT files and the official CPython 3.14.7 embeddable archive for the reviewed SQLite
DLL. Both are supplied explicitly to PyInstaller; freezing's DLL search path is limited
to the selected interpreter and Windows. The packaged SQLite DLL and `_sqlite3.pyd`
also pass isolated query, transaction and integrity checks before ZIP creation.
This prevents interpreter variants or unrelated tools from supplying unreviewed DLLs.
The finished bundle and installer input must match the reviewed native hashes and
preserved notice texts.
To check an extracted next-build payload independently:

```powershell
.venv\Scripts\python.exe scripts/windows_redistribution.py C:\path\to\HeetKit
```

Unexpected native files, altered/missing notices or changed binary hashes fail the
check. Review exact official sources and applicable terms before changing the policy;
never accept new hashes solely because a build produced them. Historical v1.1.0
evidence is retained separately in the catalogue. Passing this check verifies artifact
evidence and notice delivery; the open owner/legal findings in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md#next-windows-build-corrected-materials-and-remaining-blockers)
still block redistribution clearance. Existing published assets are not repaired by
this next-build check.

The installer wraps that exact ZIP without another freeze or frontend build.
`-PortableZip` selects an existing ZIP; its checksum, manifest, file inventory and
canonical version must pass inspection. The installer interpreter must have the pinned
PyInstaller available. Existing output files are never overwritten.

Outputs in `dist/` are:

- `HeetKit-<version>-windows-x64.zip` and `.zip.sha256`.
- `HeetKit-<version>-windows-x64-setup.exe` and `.exe.sha256`.
- `HeetKit-<version>-windows-x64-setup.exe.build.json` for input/compiler traceability.

Generated bundles and binaries stay out of Git. Local profiles, credentials, tokens,
databases, backups and private defaults must never become build inputs or release assets.

## GitHub Actions builds

CI uses pinned Python/Node toolchains, synthetic state and no personal secrets or
profiles. Choose the validation level explicitly:

- **Quick** runs on every `main` push, including prose-only pushes so its result can
  complete. `scripts/ci_checks.py` selects fixed groups from the entire push diff,
  including deletions/renames. If the old commit is unavailable, it uses all tracked
  inputs. Backend/tests/scripts/packaging/container changes select a small fixed Python
  smoke set (version, registry, cooldown, command settings and API authentication).
  Frontend changes select TypeScript checking. Python dependency changes select both;
  shared management/API/Desktop adapter changes also select TypeScript. Workflow
  changes select orchestration tests and TypeScript; scripts/packaging, version,
  release-note and issue-form changes select machine-input/publication-guard tests.
  Ordinary prose selects no application checks. The summary records each run/skip
  reason. Quick never runs the complete Python/Edge suites, Vite build, Docker build
  or Windows packaging. A new Quick run cancels superseded Quick runs on that branch.
- **Full validation** runs only through **Actions > Full validation > Run workflow**.
  Enter the intended ref; preferably use its exact SHA. It runs the complete Python
  suite, machine-input validation, production frontend build (including typecheck),
  complete Microsoft Edge suite and `scripts/check_linux_container.py` on native
  AMD64 and ARM64 Linux runners. The container workflow is reusable only, with the
  same resolved SHA passed to both runners. Full validation creates no Windows ZIP
  or installer. Its result fails if any required job fails, is cancelled or is skipped.
- **Build candidate** runs through **Actions > Build candidate > Run workflow**,
  dispatched from main with the intended SHA in `ref`. It never publishes.
  The canonical standalone builder, packaging/prerequisite/profile-isolation/
  publication checks, complete Edge suite and installer builder remain unchanged.
  The official Inno Setup download stays SHA-256 verified. Full/candidate/publication
  runs have no cancellation group and cannot be cancelled by newer Quick runs.

The stable required-check target for new branch rules is **Quick result**, which
requires successful selection and every selected job to succeed; only explicitly
unselected jobs may skip. Existing branch rules referencing the old checks must be
updated by the repository owner; source changes cannot update repository settings.
Observed completed job/step durations for the current attempt are added to the
Quick/Full/candidate summaries when Actions metadata is available; otherwise the
summary directs readers to the run timings. No duration budget is promised.

Only pip/npm dependency downloads are cached, keyed to
`packaging/windows/requirements.txt` and `frontend/package-lock.json` respectively.
Each selected job installs only its required tools in a clean environment; frontend
jobs run `npm ci` once;
virtual environments, `node_modules`, build trees, release artifacts and profiles are
never cached. Candidate tests and installer creation reuse the standalone builder's
isolated pinned Python environment. Test-only tools are installed after license
collection and freezing, so they are not shipped. Frontend tests reuse the dependencies
already installed for the production build. They use installed Microsoft Edge at
Playwright's standard Windows locations, installing it only when missing; the browser
channel remains `msedge`.
CI passes `--workers=2`, using file-level parallelism; tests within each file remain
sequential, with isolated browser contexts and synthetic bridge state. No sharding,
matrix or retries are added. Local `npm test` keeps its one-worker default; use
`npm test -- --workers=1` to compare CI behavior serially. See
[Playwright parallelism](https://playwright.dev/docs/test-parallel) and
[GitHub job concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

Candidate upload uses the Node-24-native
[upload-artifact v6](https://github.com/actions/upload-artifact/releases/tag/v6.0.0).
After a successful candidate build, download **HeetKit-<version>-windows-x64** from
**Artifacts** within its 14-day retention period. Extract the Actions download to
obtain the five files above. This payload artifact contains only those files;
the source archive tool is not part of this workflow.

Full and candidate runs also retain a small `full-evidence-<attempt>` or
`candidate-evidence-<attempt>` artifact for 14 days. These record the resolved source
SHA, repository, workflow commit/ref, run ID and attempt. Candidate evidence also
pins the version and payload artifact ID/digest. The workflow dispatch commit can
differ from the selected source SHA; publication checks the recorded selected SHA,
rather than assuming the run's `head_sha` identifies the packaged source.

`scripts/release_evidence.py` queries the
[Actions run](https://docs.github.com/en/rest/actions/workflow-runs) and
[artifact APIs](https://docs.github.com/en/rest/actions/artifacts) through the runner's
GitHub CLI. It requires successful completed manual runs of the expected workflows
from this repository's main branch and matching evidence from their current attempts.
It downloads the original candidate by ID, verifies its archive SHA-256 against both
the evidence and API digest, and copies only the five expected flat filenames.
Publication then rechecks the portable/installer sidecars, installer traceability
and exact-version curated notes. Existing canonical builder inspections, notice and
private-content/profile-isolation checks still gate candidate creation.

Missing, expired, ambiguous or changed artifacts, a different repository/ref/version/tag,
a failed/incomplete run or stale attempt evidence stop publication. Status/attempts
and the existing tag's exact commit are rechecked after download. Runs predating this
evidence protocol cannot be published through it. Use fresh workflow runs if evidence
is missing or a candidate rerun encounters an existing immutable artifact name.

## Publish a versioned release

1. Update `VERSION` in `app/version.py` to the intended release version.
2. Write user-facing notes in `docs/releases/v<version>.md`, starting with
   `# HeetKit v<version>`. These versioned files are the canonical release-notes
   source; describe actual changes since the previous stable release.
3. Commit and push the release-ready state to `main`. Wait for Quick, then manually
   run Full validation with that exact SHA. After it passes, run Build candidate with
   the same SHA. Verify the candidate artifacts and resolve the publication gates below.
   These are separate owner-requested operations, not automatic task completion.
4. Create the matching tag **at that verified SHA**, for example
   `git tag v1.4.1 <SHA>` for version `1.4.1`, then `git push origin v1.4.1`.
   This records traceability only; it starts no workflow.
5. After artifact/manual acceptance, explicitly run **Actions > Publish > Run workflow**
   from main with `sha`, `tag`, `candidate_run_id` and `full_run_id`. Publish verifies
   the identified evidence and original candidate, then creates the release with all
   five unchanged files and curated notes from that exact source commit.

Equivalent GitHub CLI commands (replace placeholders; each needs explicit owner scope):

```powershell
gh workflow run full-validation.yml --ref main -f ref=<SHA>
gh workflow run windows-build.yml --ref main -f ref=<SHA>
gh workflow run publish-release.yml --ref main -f sha=<SHA> -f tag=v<VERSION> -f candidate_run_id=<CANDIDATE_RUN_ID> -f full_run_id=<FULL_RUN_ID>
```

Wait for each selected run to succeed and retain its ID before proceeding. Any new
source commit needs fresh relevant validation and candidate evidence for its own SHA;
readiness never carries over from an older SHA. An explicitly selected older SHA is
checked as that exact SHA, never silently replaced by the current branch tip.

Versions below `1.0.0`, such as `v0.1.3`, and all explicit alpha/beta/rc versions
publish as pre-releases with `--prerelease --latest=false`. They do not replace the
latest stable release. Unsuffixed versions `v1.0.0` and later publish as stable releases.
Only the publication job receives `contents: write` through `GITHUB_TOKEN`; build and
validation remain read-only. A main push, tag push or manual candidate build never
publishes a release. Existing releases are not overwritten by this workflow.

[Stable v1.0.0](https://github.com/heeetz/heetkit-bot/releases/tag/v1.0.0) was published
on 5 October 2026 with all five release assets. Its
[tagged build and publication jobs](https://github.com/heeetz/heetkit-bot/actions/runs/37382468023)
completed successfully. Publication does not establish completion of manual artifact smoke
tests or artifact-specific redistribution review.

[Prerelease v1.1.0](https://github.com/heeetz/heetkit-bot/releases/tag/v1.1.0) was published
on 9 October 2026. The maintainer confirmed the complete published installer/portable
validation checklist passed in Windows Sandbox and on a second laptop, including
settings and credential retention, migration, profile isolation and update checking.
These are maintainer-reported manual results for v1.1.0. The separate
[artifact licensing review](../THIRD_PARTY_NOTICES.md#windows-v110-artifact-review)
records corrected next-build materials and remaining legal/provenance questions; redistribution
clearance remains open.

## Windows runtime and installation

Target machines need .NET Framework 4.6.2+ and
[WebView2 Evergreen](https://developer.microsoft.com/microsoft-edge/webview2/), with no
Python, Node or checkout. Setup provides Microsoft download/retry guidance for missing
runtimes. Use the WebView2 Evergreen Bootstrapper online or the x64 Standalone Installer
offline, following [Microsoft's deployment guidance](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution).
Complete any required Windows restart before retrying. The current Windows build process does not sign artifacts.

Setup installs per user, normally under `%LOCALAPPDATA%\Programs\HeetKit`, offers Start
Menu and optional desktop shortcuts, and can launch the app afterward. Quit via tray
Exit before an upgrade or reinstall. Same-version setup replaces application files;
downgrades are refused. To move the installation, uninstall first. Installed Apps
uninstall retains profiles, credentials and Microsoft runtimes.

For portable use, extract the whole `HeetKit` folder and retain `_internal` and
`HeetKit.exe.config` beside the executable. The adjacent config allows process-local
managed-library loading for downloaded bundles; it does not remove download markers or
change global Windows policy. If loading fails, first verify the complete extraction.
For a trusted ZIP only, **Properties → Unblock** followed by extraction into a fresh
folder is a last-resort fallback. Report any remaining loader detail to the maintainer.

## Before publication

Validate the actual downloadable installer/ZIP outside the checkout on a clean Windows
user or VM without development tooling. Check startup, Twitch authorization, optional
Gemini, saved commands/personalities/instructions/filters, restart, tray, version/icon,
upgrade and uninstall/reinstall retention. Use synthetic data or protected backups.
Verify checksums, complete extraction and the absence of private or development files.

Review the actual payload against [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
and bundled license texts; unresolved artifact-specific redistribution reviews block
publication. Keep release notes concise and user-facing. The maintainer updates the
version and creates/pushes each release tag manually using the steps above.

macOS/Linux builds must be produced and tested on those platforms with their native
renderer and credential backends before adding release automation or claiming support.

[Back to README](../README.md#documentation).
