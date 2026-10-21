# Release process

Windows 10/11 x64 is the current distribution target. The installer is the primary
download and the portable ZIP is an alternative. Public downloads belong on
[GitHub Releases](https://github.com/heeetz/heetkit-bot/releases).

The [Windows build workflow](https://github.com/heeetz/heetkit-bot/actions/workflows/windows-build.yml)
runs development checks on `main` pushes; documentation-only pushes remain ignored.
Manual runs create Windows candidate artifacts. A manually pushed matching version
tag runs the complete test/package pipeline and, after success, publishes its five
verified files as a GitHub Release. A successful build alone does not establish
public-release readiness.

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
release version. Tagged builds fail before publication if the tag differs from
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

CI uses `windows-2022` and the pinned Python/Node toolchains. It requires no personal
secrets or profile data. The workflow has two paths:

- **Regular development checks** run on `main` pushes: the Python test suite,
  frontend typecheck/production build and complete Edge browser suite. They create
  no frozen bundle, portable ZIP or installer. A newer regular push cancels superseded
  checks for the same branch. The existing documentation-only push filter is unchanged.
- **Test and package Windows x64** runs through **Actions → Windows build → Run workflow**
  (select the desired branch or tag), or on `v*` tag pushes. It runs the existing
  standalone builder, packaging/prerequisite/profile-isolation/publication tests,
  complete Edge suite and installer builder. The official Inno Setup download remains
  SHA-256 verified. These jobs and release publication have no cancellation group;
  newer pushes or manual builds cannot automatically cancel them.

Only pip/npm dependency downloads are cached, keyed to
`packaging/windows/requirements.txt` and `frontend/package-lock.json` respectively.
Each path installs Python runtime dependencies once into a clean environment and runs
`npm ci` once;
virtual environments, `node_modules`, build trees, release artifacts and profiles are
never cached. Candidate/tag tests and installer creation reuse the standalone builder's
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

Artifact transfer uses the Node-24-native
[upload-artifact v6](https://github.com/actions/upload-artifact/releases/tag/v6.0.0) and
[download-artifact v7](https://github.com/actions/download-artifact/releases/tag/v7.0.0)
actions. These retain the existing archive/download behavior and validation; the newer
download v8 changes digest-failure defaults and is outside this optimization.

After a successful candidate or tag build, download **HeetKit-<version>-windows-x64**
from **Artifacts** within its 14-day retention period. Extract the Actions download
to obtain the five files above.
Only those files are uploaded; the source archive tool is not part of this workflow.

## Publish a versioned release

1. Update `VERSION` in `app/version.py` to the intended release version.
2. Write user-facing notes in `docs/releases/v<version>.md`, starting with
   `# HeetKit v<version>`. These versioned files are the canonical release-notes
   source; describe actual changes since the previous stable release.
3. Commit and push the release-ready state to `main`. Wait for development checks,
   then manually run the Windows build for that commit's branch before tagging.
   Verify the candidate artifacts and resolve the publication gates below.
4. Create the matching tag, for example `git tag v0.1.3` for version `0.1.3`.
5. Push that tag: `git push origin v0.1.3`.
6. GitHub Actions tests and builds that tagged commit. If all checks pass, it downloads
   the five artifacts from that same run, verifies both SHA-256 checksums and installer
   traceability, and publishes them with the matching curated notes from that exact
   tagged checkout. Missing or mismatched notes stop publication. It does not rebuild.

Versions below `1.0.0`, such as `v0.1.3`, and all explicit alpha/beta/rc versions
publish as pre-releases with `--prerelease --latest=false`. They do not replace the
latest stable release. Unsuffixed versions `v1.0.0` and later publish as stable releases.
Only the publication job receives
`contents: write` through `GITHUB_TOKEN`; the build remains read-only. A `main` push
or manual build never publishes a release, even if the manual run selects a tag.
Failed builds, artifact checks or tag/version validation prevent publication.

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
