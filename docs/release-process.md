# Release process

Windows 10/11 x64 is the current distribution target. The installer is the primary
download and the portable ZIP is an alternative. Public downloads belong on
[GitHub Releases](https://github.com/heeetz/heetkit-bot/releases).

The current [Windows build workflow](https://github.com/heeetz/heetkit-bot/actions/workflows/windows-build.yml)
creates test artifacts on `main` pushes and manual runs. It does not create tags or
publish GitHub Releases. Tagged release publication and in-app update checking remain
unimplemented; a successful build alone does not establish public-release readiness.

## Build inputs and version

`app/version.py` is the canonical application version source. Runtime/About, Python
metadata, executable metadata and artifact names consume it. Do not maintain a separate
release version. Any future tagged-release workflow must reject a tag/version mismatch.

The Windows builder requires Windows x64 CPython **3.14.7** and a Vite-compatible Node
version (**20.19+**; CI uses **24.20.0**). Python/runtime/build dependencies are pinned in
`packaging/windows/requirements.txt`; the frontend uses `npm ci` and its lockfile.
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

Open **Actions → Windows build → Run workflow** to start a manual build, or inspect the
run for a `main` push. CI uses `windows-2022`, the pinned Python/Node toolchains and a
SHA-256-verified official Inno Setup download. It requires no personal secrets or profile
data, and dependency caching is disabled.

CI runs focused Python packaging/prerequisite/profile-isolation tests, the existing
standalone builder, frontend tests in Edge and the installer builder. After a successful
run, download **HeetKit-<version>-windows-x64** from **Artifacts** within its 14-day
retention period. Extract the Actions download to obtain the five files above.
Only those files are uploaded; the source archive tool is not part of this workflow.

## Windows runtime and installation

Target machines need .NET Framework 4.6.2+ and
[WebView2 Evergreen](https://developer.microsoft.com/microsoft-edge/webview2/), with no
Python, Node or checkout. Setup provides Microsoft download/retry guidance for missing
runtimes. Use the WebView2 Evergreen Bootstrapper online or the x64 Standalone Installer
offline, following [Microsoft's deployment guidance](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution).
Complete any required Windows restart before retrying. Current candidates are unsigned.

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
publication. Keep release notes concise and user-facing. Tag creation or publication
needs a separately authorized release task; this workflow currently uploads candidates only.

macOS/Linux builds must be produced and tested on those platforms with their native
renderer and credential backends before adding release automation or claiming support.

[Back to README](../README.md#documentation).
