# Third-party notices

HeetKit is licensed under Apache-2.0. Dependencies retain their own licenses.
Preserved upstream texts and attributions are in [third_party_licenses/](third_party_licenses/).

## Published Windows x64 release v1.5.4

The release was built from `3eff9eaf071d5d23af19c36e9a0721c1ce1731ec`.
Both retained release artifacts matched their SHA-256 sidecars. The portable ZIP
matched all **617** file hashes in its `BUILD-MANIFEST.json` and the catalogue
hashes for **197** native components and **270** required notice files.
See the [v1.5.4 release](https://github.com/heeetz/heetkit-bot/releases/tag/v1.5.4)
and [packaging catalogue](packaging/windows/redistribution.json).

- **Portable ZIP, inspected directly.** `_internal/` contains `LICENSE`, `NOTICE`,
  the release's `THIRD_PARTY_NOTICES.md` and `PORTABLE.txt`.
  `_internal/third_party_licenses/` contains the preserved native, Python, React,
  React DOM, Scheduler, Vite, Unicode CLDR and Inno Setup texts. This includes the
  WebView2 SDK license and `NOTICE.txt`, .NET SDK license and `ThirdPartyNotices.txt`,
  Windows SDK RTF terms, and OpenSSL, libffi and Rust attributions.
  `_internal/licenses/` contains the CPython license collection, installed distribution
  notices (including Pillow, aiohttp's llhttp, pystray and certifi), and
  `windows-redistribution.json`. The ZIP contains replaceable pystray modules and
  certifi source and CA data outside the frozen PYZ.
- **Installer, verified by traceability.** The Setup `.build.json` binds the exact
  installer SHA-256 to the verified portable ZIP and its `BUILD-MANIFEST.json`.
  The build script verifies and stages that payload. The Inno Setup recipe installs it
  recursively, adds `INSTALLER.txt` and a separate `_internal/licenses/Inno-Setup-LICENSE.txt`,
  and displays the generated notice page. The file-by-file inspection covers the ZIP.
  See the [installer build script](scripts/build_installer.py) and
  [Inno Setup recipe](packaging/windows/HeetKit.iss).

[Redistribution questions remain open](#windows-redistribution-evidence-and-open-questions).
This refresh documents the published files, which retain the notices from their release build.

## Weather country names

Weather country qualifiers use English, Ukrainian and Russian territory names
from [Unicode CLDR 48](https://github.com/unicode-org/cldr/tree/release-48).
The derived [country table](app/services/weather_countries.py) and the bundled
[Unicode-3.0 notice](third_party_licenses/data/Unicode-CLDR-48-LICENSE.txt)
carry the copyright and permission terms.

## Historical Windows v1.1.0 artifact review

Reviewed on **2026-10-09** against the downloaded
[v1.1.0 prerelease](https://github.com/heeetz/heetkit-bot/releases/tag/v1.1.0), built at
`9641e85`. This review supersedes the earlier open questions only where the evidence
below resolves them. **Redistribution clearance remains open.**

| Evidence | SHA-256 |
| --- | --- |
| `HeetKit-1.1.0-windows-x64.zip` | `b4727006408f2e0174a0de42f79e6d411f99d372e1b61af2430ceeee11542df9` |
| `HeetKit-1.1.0-windows-x64-setup.exe` | `577c50889519ac9d2089a6c07ce96a6ace2a74d199bfdc792e0af463bdbbc771` |
| Portable `BUILD-MANIFEST.json`, also identified by installer traceability | `c1ca317455234b12ed902d489ba11e4ef4287f59a0a8b2aa280f3254fdb1eab4` |

Both checksum sidecars and all **447** manifest file hashes passed. The canonical
bundle inspector passed on the extracted payload: **448 files** including the manifest,
**1,582 frozen modules**, no prohibited private/development paths or frozen pystray modules.
`LICENSE`, `NOTICE`, the earlier `THIRD_PARTY_NOTICES.md` and `PORTABLE.txt` are accessible
offline and matched the pre-review repository texts, allowing for line endings.
The installed-license collection retains exact wheel GPL/LGPL, certifi, Pillow and CFFI
texts. The copied source inventory remains historical; for example, the packaging pin
for urllib3 is now **2.8.0**, rather than the inventory's **2.7.0**.

The exact distribution of the v1.1.0 `sqlite3.dll` remains unproven. It reports
**3.50.4.0**, the version selected by CPython, and its hash differs from the
inspected official CPython NuGet binary.

Exact official PyPI wheels were downloaded with their PyPI SHA-256 verified. Shipped
files matched pystray 0.19.5 (six Python modules), certifi 2026.7.22 (four source/data
files), pywebview 6.2.1 (three SDK DLLs and six JS files), pythonnet 3.1.0 (runtime DLL,
deps and XML files), clr-loader 0.3.1 (amd64 loader), cryptography 50.0.1
(`cp311-abi3-win_amd64` Rust extension and both SBOMs), Pillow 12.3.0 (six extensions),
CFFI 2.1.1 and pydantic-core 2.46.5 (their `cp314-cp314-win_amd64` extensions).
Only redistributed files were compared; this does not claim complete wheel inclusion.

The component table below records resolved checks and concrete remaining actions.
This documentation update does not replace the notice files inside the already
published v1.1.0 installer or ZIP.

## Redistribution requirements and manual review

The v1.5.4 build uses CPython 3.14.7, PyInstaller 6.22.3 and hooks-contrib 2026.8.
See the [Windows build and runtime pins](packaging/windows/requirements.txt).

The Windows installer uses Inno Setup **6.7.3** around the verified onedir payload.
The pinned, unmodified installer/uninstaller engine retains upstream copyright/site notices.
The [Inno Setup license](https://github.com/jrsoftware/issrc/blob/is-6_7_3/license.txt)
is preserved in `third_party_licenses/inno-setup/LICENSE.txt`.
Setup directs users with missing .NET Framework or WebView2 Runtime prerequisites to
Microsoft's supported downloads. Those runtime installers are separate downloads.

The build keeps pystray's redistributed modules as exact, replaceable `.py` files outside
the frozen PYZ, alongside GPL/LGPL texts. certifi's Python source and exact CA bundle
are also supplied outside PYZ. WebView2 ships only its Core/WinForms
SDK DLLs and x64 loader; the other architecture directories contain placeholders required
by pywebview path discovery. CLR loading uses only the amd64 loader. The collected Python.NET
payload still includes the Microsoft/System/netstandard assemblies described below.

**Recheck this notice set against each actual packaged artifact**, including frozen imports,
native DLLs/extensions, Python's
standard library, generated JS, data files, and any bundled OS prerequisites. Resolve
the remaining items before distributing another binary.

| Component | Status and required action |
| --- | --- |
| **pystray 0.19.5** | **Resolved for the v1.1.0 layout: LGPL-3.0-or-later.** All six redistributed `.py` modules match the official wheel, retain source headers and are absent from PYZ. GPLv3/LGPLv3 copies match the wheel. `_internal/pystray/` loads from disk through the frozen importer's normal file fallback, without source-integrity restrictions: edit or replace these files while HeetKit is stopped, then relaunch without rebuilding the executable. `PORTABLE.txt` describes replacement. This verifies the source/import layout; no new native modified-library smoke test was run. Preserve this layout and its notices. [Upstream license](https://github.com/moses-palmer/pystray/blob/v0.19.5/COPYING.LGPL), [versioned source](https://github.com/moses-palmer/pystray/tree/v0.19.5). |
| **proxy-tools 0.1.0** | **Resolved source attribution for v1.1.0: BSD-2-Clause; MIT metadata conflicts with the source grant.** The official sdist SHA-256 is `ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010`. Its module explicitly identifies BSD and credits Armin Ronacher/Jonathan Tushman. It is byte-identical to [upstream source at `db43f1e`](https://github.com/jtushman/proxy_tools/blob/db43f1e35d4f90a65c5a4d56d9e9af88212ec6e6/proxy_tools/__init__.py). The frozen code objects match that sdist after normalizing only source filenames. Shipped `UPSTREAM-LICENSE.txt` exactly matches that commit's [BSD notice](https://github.com/jtushman/proxy_tools/blob/db43f1e35d4f90a65c5a4d56d9e9af88212ec6e6/LICENSE.txt), including its malformed final line. Retain it unchanged; do not substitute generic MIT text. |
| **certifi 2026.7.22** | **Resolved source delivery for v1.1.0: MPL-2.0 CA bundle.** `_internal/certifi/` contains the exact wheel's `__init__.py`, `core.py`, `py.typed` and `cacert.pem`, outside PYZ. The shipped license matches the wheel, identifies the MPL-covered bundle and links the MPL text. `PORTABLE.txt` identifies the source/bundle location. No modifications were found. Preserve source/data delivery and notices. [Exact package/source downloads](https://pypi.org/project/certifi/2026.7.22/#files), [MPL responsibilities](https://www.mozilla.org/en-US/MPL/2.0/#responsibilities). |
| **WebView2 SDK 1.0.3856.49** | **Exact source verified and notices shipped in v1.5.4.** The three shipped SDK DLLs match official NuGet `Microsoft.Web.WebView2` **1.0.3856.49**, archive SHA-256 `bc0f76eb911b569838dc4aa8f8d325269b966bedb592863d26211aef3a099f1a`. The original Microsoft BSD license and full `NOTICE.txt` (including ANTLR and StringTemplate) were absent from the published v1.1.0 assets. The v1.5.4 ZIP includes both [versioned texts](third_party_licenses/native/webview2-1.0.3856.49/). No other native architecture or separately installed WebView2 Runtime is bundled. |
| **pythonnet 3.1.0 / clr-loader 0.3.1 and extra .NET assemblies** | **Provenance verified. Microsoft obligations remain open.** The earlier comparison used the platform-neutral wheel. All **97** Python.NET DLLs, including the **96** compatibility files, exactly match the official Windows-specific wheel (SHA-256 `7bdd4de03df3547a48122a3989265c8b31d5be0d19dadffa009eec7df8085e0b`). All 96 also match the official .NET SDK **10.0.300** `Microsoft.NET.Build.Extensions/net461/lib` files. The v1.5.4 ZIP contains the exact SDK [LICENSE and ThirdPartyNotices](third_party_licenses/native/dotnet-sdk-10.0.300/), including the Microsoft .NET Library terms. Python.NET's own DLL and CLR loader retain their own MIT grants. See necessity and owner/legal review below. |
| **Native wheel/interpreter contents** | **Versioned notices shipped in v1.5.4.** The ZIP includes OpenSSL **3.5.7** and **4.0.2**, CFFI's embedded libffi, CPython's separate libffi **3.4.4**, Rust standard-library and candidate Windows crate notices, and Pillow's full wheel notice collection. The [artifact evidence catalogue](packaging/windows/redistribution.json) identifies binary hashes, distribution members, source archives, notice hashes, dependency scopes and unresolved findings. Binary linkage and redistribution conclusions require evidence beyond crate lockfiles and PE versions. |
| **Future platform backends / bundlers** | Linux `python-xlib` has LGPLv2+ metadata and needs artifact-specific source/replacement review. Optional Qt/GTK/CEF backends and macOS frameworks are outside this Windows payload. Determine exact grants, exceptions and distribution contents before shipping another platform or bundler; the pywebview wrapper does not license its renderer. CPython and the current Windows bundler/installer are covered by the Windows evidence and remaining actions above. |

For MIT, BSD, MIT-CMU, PSF and similar permissive components, retain their individual
copyright, license terms and disclaimers in redistributed copies. Preserve the distinction
between `AND` (all terms apply) and `OR` (a permitted license choice). Apache components
require a license copy, retained applicable attribution/NOTICE contents and modification
notices when changed. Shipped NOTICE files from **propcache, requests and yarl** are copied
here; aiohttp's vendored llhttp MIT notice and Pillow's bundled notices are also retained.
The project's `NOTICE` credits heeetz; it does not replace those component notices.

## Windows redistribution evidence and open questions

The v1.5.4 portable ZIP contains the staged `third_party_licenses/` tree and
`_internal/licenses/windows-redistribution.json`. The bundle inspector checks
the finished onedir payload before ZIP creation and again before installer compilation.
It requires the reviewed native inventory and byte-exact notice hashes, rejects new or
renamed PE/native files and changed binary versions/hashes, and compares the staged
catalogue with the trusted repository copy. Redistribution clearance remains open.
The v1.5.4 SDK UCRT inputs match the exact published v1.1.0 files, with verified
download/member hashes and a restricted freezing search path. This prevents ambient
tool directories supplying different DLLs. Updating the allowlist requires exact
upstream review. The catalogue identifies required texts and their evidence.

The v1.5.4 build uses official PyPI wheels for aiohttp **3.14.4**,
certifi **2026.10.19**, multidict **6.9.1**, Pillow **13.0.0** and yarl **1.25.1**.
The catalogue records their verified archive hashes, the eleven shipped native member
hashes and exact installed notices, including Pillow's complete bundled-library
license collection and aiohttp's llhttp notice. Historical native sources retain
their previous distribution URLs/hashes. certifi's source and updated CA bundle remain
replaceable outside PYZ. These updates do not resolve the legal findings below.
Pillow's unused `ImageMath` module and `_imagingmath` extension are no longer reached
by the frozen application's imports; the current native inventory reflects that removal.

The Windows wheel's compatibility build is explicit in Python.NET **3.1.0** source
(`--net46-support`, `src/compat/Python.Runtime.Compat.csproj`; source archive SHA-256
`7b34c382905d10a371509ffafd64cae0416305c28817738a9cd138336f4e9991`).
Microsoft's SDK targets copy this set for .NET Standard dependencies on older .NET
Framework targets. This explains its purpose for HeetKit's existing .NET **4.6.2+**
minimum. Individual DLL redundancy across every supported runtime is not established:
all 96 are retained, with no unvalidated removal or minimum-runtime change. The official
[SDK archive](https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.300/dotnet-sdk-10.0.300-win-x64.zip)
was verified against its published SHA-512
`32446eddffc5a485f58f9d79cdab3a1a9adab4adc2ef0e4c787cfbb2465020d50beaadc54d40f0850e2e0089edd09864d12d6c19c526319819d57a4c00d38518`.
Exact per-file hashes and source members are in the catalogue.

CPython **3.14.7** source selectors name OpenSSL **3.5.7**; the interpreter/SSL binaries
match official CPython distributions. Its OpenSSL source archive SHA-256 is
`a8c0d28a529ca480f9f36cf5792e2cd21984552a3c8e4aa11a24aa31aeac98e8`.
Cryptography **50.0.1**'s exact wheel/native extension and SBOM bind its statically linked
OpenSSL **4.0.2** to source SHA-256
`736b467530f916737b7031310ccb21d8218c6229e61e8e160cd1d3458cd543a8`.
Both releases supply `LICENSE.txt`, `AUTHORS.md` and `README.md`; neither contains a
NOTICE file. Those actual attribution files are preserved unchanged in their versioned
[3.5.7](third_party_licenses/native/openssl-3.5.7/) and
[4.0.2](third_party_licenses/native/openssl-4.0.2/) directories.

CFFI **2.1.1**'s exact Windows source build statically compiles its bundled
`libffi_x86_x64` copy; its original `ffi.h` permission/copyright block is preserved.
The header calls it **2.00-beta**, not CPython's libffi version. `_cffi_backend` has no
libffi DLL import; `_ctypes.pyd` imports the separate `libffi-8.dll`, which matches the
official CPython **3.14.7** embeddable package and its **3.4.4** source selector.
Both notices and CFFI's own MIT-0 text are delivered.

Cryptography's wheel SBOM/Cargo source distinguishes runtime, procedural-macro and
build/probe dependencies. The Cargo SBOMs for the **cryptography 50.0.1** and
**pydantic-core 2.46.5** Windows x64 wheels both mark their scope as all targets.
The v1.5.4 ZIP carries cryptography's two SBOMs. The pydantic-core SBOM was inspected
from its wheel evidence. The catalogue records the Windows runtime candidates and
their preserved licenses. PyPI provides a publishing attestation for the exact
cryptography wheel and lists the pydantic-core wheel without a provenance attestation.
See the exact wheel records for
[cryptography 50.0.1](https://pypi.org/project/cryptography/50.0.1/) and
[pydantic-core 2.46.5](https://pypi.org/project/pydantic_core/2.46.5/).

Both shipped extensions retain source paths for `core`, `alloc`, `std` and
`panic_unwind` from commit `88d9e12ae178fab0fb5cc050a94da85685d449ea`.
The ZIP includes that release's Apache, MIT and COPYRIGHT texts and the evidenced
standard-library dependency notices. The Rust source archive SHA-256 is
`271fa73d8174f53d713c46a8310da7bf7cfdcfb8b7cfd1c2b74b84a83ae9fb1e`.
See the [Rust 1.98.0 release](https://github.com/rust-lang/rust/releases/tag/1.98.0)
and [shipped Rust notices](third_party_licenses/native/rust/).

The in-tree `compiler_builtins` manifest and standard-library lockfile identify
version **0.1.160**. Its `src/lib.rs` differs from the crates.io 0.1.160 package.
The two `LICENSE.txt` files are byte-identical, including the MIT terms and the Apache
2.0 terms with the LLVM exception. The v1.5.4 ZIP carries that exact text
(SHA-256 `ab6eec6caf0fa5775e411c7a8bc6a45c4ef2956b0980b157ab74fc5cd62a928b`).
See the [in-tree manifest](https://raw.githubusercontent.com/rust-lang/rust/88d9e12ae178fab0fb5cc050a94da85685d449ea/library/compiler-builtins/compiler-builtins/Cargo.toml),
[in-tree source](https://github.com/rust-lang/rust/tree/88d9e12ae178fab0fb5cc050a94da85685d449ea/library/compiler-builtins)
and [in-tree license](https://raw.githubusercontent.com/rust-lang/rust/88d9e12ae178fab0fb5cc050a94da85685d449ea/library/compiler-builtins/LICENSE.txt).

Exact linked objects and generated macro attribution remain open. Both extensions
reference PDBs, and the ZIP contains neither PDB. Ask the PyCA and Pydantic maintainers
for linker maps or matching PDBs and build inputs for the exact Windows x64 wheels.
Use those to identify retained intrinsics, any LLVM compiler-rt objects and generated
code, then check their attribution against the notices already shipped.

### Microsoft runtime redistribution

The file inventory below was verified directly in the v1.5.4 portable ZIP.
The installer traceability identifies the same application payload.
Redistribution clearance remains open.

- **.NET Framework compatibility.** `_internal/pythonnet/runtime/` contains
  `Python.Runtime.dll` and 96 compatibility DLLs (94 `System.*.dll` files,
  `Microsoft.Win32.Primitives.dll` and `netstandard.dll`). Python.NET and the
  separate amd64 `ClrLoader.dll` let pywebview use WinForms/WebView2 with the
  system .NET Framework. The 96 files support older Framework installations
  consuming .NET Standard 2.0 and match the .NET SDK **10.0.300** files identified
  above. The saved Microsoft .NET Library terms §3(a)(ii) require substantial
  application functionality, a valid copyright notice, protective terms accepted
  by downstream distributors and external users, and publisher indemnification.
  Setup displays notices and portable users can extract the ZIP directly.
  The owner and counsel need to establish the applicable grant for these exact
  files and review assent and indemnification for both formats. Microsoft can
  clarify the grant and Python.NET maintainers can confirm how the set is produced.
  See the [SDK terms](third_party_licenses/native/dotnet-sdk-10.0.300/LICENSE.txt)
  and [Python.NET 3.1.0 compatibility project](https://raw.githubusercontent.com/pythonnet/pythonnet/v3.1.0/src/compat/Python.Runtime.Compat.csproj).
- **Windows SDK/UCRT.** The 43 DLLs under `_internal/` are `ucrtbase.dll` and
  42 API-set forwarders (29 `api-ms-win-core-*` and 13 `api-ms-win-crt-*`).
  Native modules such as `python314.dll` import the C runtime through CRT API sets.
  All 43 byte-match the x64 UCRT Redist members of `Microsoft.Windows.SDK.CPP`
  **10.0.26100.1742** (package SHA-256
  `cea18bcdb33096a94e441a8fdf2db138e356b020a1b5f27d6ddfea1bcec48eb2`).
  Section 3(a)(i) of the package terms links to Microsoft's REDIST list.
  Its x64 UCRT section names **39 of the 43** shipped files. The four unmatched
  names are `api-ms-win-core-fibers-l1-1-0.dll`,
  `api-ms-win-core-fibers-l1-1-1.dll`,
  `api-ms-win-core-kernel32-legacy-l1-1-1.dll` and
  `api-ms-win-core-sysinfo-l1-2-0.dll`. The exact NuGet archive carries no
  `REDIST.TXT` to establish additional coverage. If retaining the DLLs, obtain
  the exact SDK's applicable list or written coverage for those four from
  Microsoft. Counsel still needs to review §3(a)(ii), including protective
  assent, copyright notice and indemnification, for both formats.
  See the [package](https://www.nuget.org/packages/Microsoft.Windows.SDK.CPP/10.0.26100.1742),
  [saved SDK terms](third_party_licenses/native/windows-sdk-10.0.26100.1742/LICENSE.rtf)
  and [Microsoft Windows SDK REDIST list](https://learn.microsoft.com/en-us/legal/windows-sdk/redist).
- **Visual C++ Runtime.** `_internal/VCRUNTIME140.dll` and
  `_internal/VCRUNTIME140_1.dll` are both **14.51.36247.0** and match the
  CPython **3.14.7** embeddable and NuGet distributions. The native imports
  show `python314.dll` using the first and CPython's `_wmi.pyd` using the second.
  The Visual C++ v14 Runtime terms grant installation and use and restrict
  onward distribution. Microsoft documents a separate route under applicable
  Visual Studio license terms for licensed users to distribute eligible,
  unmodified Redist files. If retaining the DLLs, the owner and counsel need
  to establish that grant and match the hashes to the exact x64 Microsoft Redist.
  CPython's release maintainers can confirm the source toolset and Microsoft can
  confirm coverage for the exact files.
  See [CPython 3.14.7](https://www.python.org/downloads/release/python-3147/),
  the [Visual Studio 2026 Redist list](https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution)
  and [Visual C++ v14 Runtime terms](https://visualstudio.microsoft.com/license-terms/vs2026-ga-visualcpp-v14-redist-runtime/).

### Runtime options for a future Windows build

- **.NET Framework.** Test a .NET Framework **4.8+** baseline using the system
  Framework and the Python.NET wheel without the older compatibility set.
  Confirm managed dependency resolution and binding on the minimum supported
  Windows version. The .NET Framework runtime installer is available online and
  offline. Setup could detect the higher minimum and direct users to Microsoft.
  Portable users would need it installed before launch. The modern .NET SDK
  and Desktop Runtime serve a different host, so a CoreCLR migration would
  require its own Python.NET and pywebview compatibility review.
  See [Python.NET runtime selection](https://github.com/pythonnet/pythonnet/blob/v3.1.0/doc/source/python.rst),
  [Framework support for .NET Standard](https://learn.microsoft.com/en-us/dotnet/standard/net-standard)
  and the [Microsoft .NET Framework 4.8 runtime](https://dotnet.microsoft.com/en-us/download/dotnet-framework/net48).
- **UCRT.** Test dropping the app-local UCRT set for both formats. Windows 10
  and 11 load the system UCRT even when an app-local copy exists. That path
  needs neither an SDK install nor a separate UCRT setup step. Verify the
  imported API sets resolve on the oldest Windows build HeetKit supports.
  See [Microsoft UCRT deployment guidance](https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment).
- **Visual C++ Runtime.** Test using the Microsoft-installed x64 v14 runtime.
  Select a version that satisfies the newest MSVC build tools used by the
  payload. Per-user Setup could detect a missing or outdated runtime and
  direct the user to the Microsoft installer, which can require elevation.
  Portable users would need to install it beforehand, including obtaining the
  Microsoft installer separately for offline machines. Hosting or bundling that
  installer would require its own verified redistribution grant.
  See [Microsoft's Visual C++ Redistributable downloads and version rules](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist).

Validate each removal independently on clean x64 Windows 10 and 11, including
the oldest Windows build retained in the support baseline. Use a standard user
without developer tools. Test both Setup and a fresh Explorer extraction, with
missing, outdated and supported prerequisites where applicable. Check download
and retry, offline preparation, elevation and restart paths. Run `HeetKit.exe --check`
and open the WinForms/WebView2 UI. Exercise _wmi, TLS, SQLite and the two Rust
extensions, and record loaded DLL paths and managed assembly binding. Test an
upgrade from v1.5.4 to ensure old DLLs cannot mask missing dependencies, then
verify the candidate inventory and uninstall behavior.

**SQLite provenance.** The v1.5.4 ZIP's `sqlite3.dll` hash matches the catalogue's
verified CPython **3.14.7** embeddable and NuGet binaries.

## Historical Python runtime inventory (Windows)

This inventory began as a **2026-10-04** snapshot for HeetKit **0.1.0**, covering
the 54-package Windows runtime dependency closure. Later corrections are identified
in the table. Versions and license findings came from installed distribution
`METADATA`, `Requires-Dist`, shipped license and notice files, and upstream sources
for ambiguous entries. The source declarations support Python 3.12+ and mostly use
version ranges. For the published v1.5.4 payload, see the artifact evidence above.

“Direct” means declared in `pyproject.toml`. Other rows are recursively selected
non-extra runtime dependencies using Windows markers. Package links identify the
inspected versions and local links point to the preserved licenses and notices.

| Package | Version | Relationship | License evidence | Preserved text |
| --- | --- | --- | --- | --- |
| [aiohappyeyeballs](https://pypi.org/project/aiohappyeyeballs/2.7.1/) | 2.7.1 | Transitive | PSF-2.0 | [Texts](third_party_licenses/python/aiohappyeyeballs/) |
| [aiohttp](https://pypi.org/project/aiohttp/3.14.3/) | 3.14.3 | Transitive | Apache-2.0 AND MIT | [Texts](third_party_licenses/python/aiohttp/) |
| [aiosignal](https://pypi.org/project/aiosignal/1.4.0/) | 1.4.0 | Transitive | Apache-2.0 | [Texts](third_party_licenses/python/aiosignal/) |
| [aiosqlite](https://pypi.org/project/aiosqlite/0.22.1/) | 0.22.1 | Direct | MIT | [Texts](third_party_licenses/python/aiosqlite/) |
| [annotated-types](https://pypi.org/project/annotated-types/0.8.0/) | 0.8.0 | Transitive | MIT | [Texts](third_party_licenses/python/annotated-types/) |
| [anyio](https://pypi.org/project/anyio/4.15.1/) | 4.15.1 | Transitive | MIT | [Texts](third_party_licenses/python/anyio/) |
| [attrs](https://pypi.org/project/attrs/26.1.0/) | 26.1.0 | Transitive | MIT | [Texts](third_party_licenses/python/attrs/) |
| [bottle](https://pypi.org/project/bottle/0.13.4/) | 0.13.4 | Transitive | MIT | [Texts](third_party_licenses/python/bottle/) |
| [certifi](https://pypi.org/project/certifi/2026.7.22/) | 2026.7.22 | Transitive | MPL-2.0 | [Texts](third_party_licenses/python/certifi/) |
| [cffi](https://pypi.org/project/cffi/2.1.1/) | 2.1.1 | Transitive | MIT-0 | [Texts](third_party_licenses/python/cffi/) |
| [charset-normalizer](https://pypi.org/project/charset-normalizer/3.5.1/) | 3.5.1 | Transitive | MIT | [Texts](third_party_licenses/python/charset-normalizer/) |
| [clr-loader](https://pypi.org/project/clr-loader/0.3.1/) | 0.3.1 | Transitive | MIT | [Texts](third_party_licenses/python/clr-loader/) |
| [cryptography](https://pypi.org/project/cryptography/50.0.1/) | 50.0.1 | Transitive | Apache-2.0 OR BSD-3-Clause | [Texts](third_party_licenses/python/cryptography/) |
| [distro](https://pypi.org/project/distro/1.9.0/) | 1.9.0 | Transitive | Apache-2.0 | [Texts](third_party_licenses/python/distro/) |
| [frozenlist](https://pypi.org/project/frozenlist/1.8.0/) | 1.8.0 | Transitive | Apache-2.0 | [Texts](third_party_licenses/python/frozenlist/) |
| [google-auth](https://pypi.org/project/google-auth/2.57.1/) | 2.57.1 | Transitive | Apache-2.0 | [Texts](third_party_licenses/python/google-auth/) |
| [google-genai](https://pypi.org/project/google-genai/1.75.0/) | 1.75.0 | Direct | Apache-2.0 | [Texts](third_party_licenses/python/google-genai/) |
| [greenlet](https://pypi.org/project/greenlet/3.5.5/) | 3.5.5 | Transitive | MIT AND PSF-2.0 | [Texts](third_party_licenses/python/greenlet/) |
| [h11](https://pypi.org/project/h11/0.16.0/) | 0.16.0 | Transitive | MIT | [Texts](third_party_licenses/python/h11/) |
| [httpcore](https://pypi.org/project/httpcore/1.0.9/) | 1.0.9 | Transitive | BSD-3-Clause | [Texts](third_party_licenses/python/httpcore/) |
| [httpx](https://pypi.org/project/httpx/0.28.1/) | 0.28.1 | Direct | BSD-3-Clause | [Texts](third_party_licenses/python/httpx/) |
| [idna](https://pypi.org/project/idna/3.19/) | 3.19 | Transitive | BSD-3-Clause | [Texts](third_party_licenses/python/idna/) |
| [jaraco-classes](https://pypi.org/project/jaraco-classes/3.4.0/) | 3.4.0 | Transitive | MIT | [Texts](third_party_licenses/python/jaraco-classes/) |
| [jaraco-context](https://pypi.org/project/jaraco-context/6.1.2/) | 6.1.2 | Transitive | MIT | [Texts](third_party_licenses/python/jaraco-context/) |
| [jaraco-functools](https://pypi.org/project/jaraco-functools/4.6.0/) | 4.6.0 | Transitive | MIT | [Texts](third_party_licenses/python/jaraco-functools/) |
| [keyring](https://pypi.org/project/keyring/25.7.0/) | 25.7.0 | Direct | MIT | [Texts](third_party_licenses/python/keyring/) |
| [more-itertools](https://pypi.org/project/more-itertools/11.1.0/) | 11.1.0 | Transitive | MIT | [Texts](third_party_licenses/python/more-itertools/) |
| [multidict](https://pypi.org/project/multidict/6.7.1/) | 6.7.1 | Transitive | Apache-2.0 | [Texts](third_party_licenses/python/multidict/) |
| [pillow](https://pypi.org/project/pillow/12.3.0/) | 12.3.0 | Transitive | MIT-CMU | [Texts](third_party_licenses/python/pillow/) |
| [platformdirs](https://pypi.org/project/platformdirs/4.12.2/) | 4.12.2 | Direct | MIT | [Texts](third_party_licenses/python/platformdirs/) |
| [propcache](https://pypi.org/project/propcache/0.5.2/) | 0.5.2 | Transitive | Apache-2.0 | [Texts](third_party_licenses/python/propcache/) |
| [proxy-tools](https://pypi.org/project/proxy-tools/0.1.0/) | 0.1.0 | Transitive | BSD-2-Clause source grant; conflicting MIT metadata; v1.1.0 source match verified above | [Texts](third_party_licenses/python/proxy-tools/) |
| [pyasn1](https://pypi.org/project/pyasn1/0.6.4/) | 0.6.4 | Transitive | BSD-2-Clause | [Texts](third_party_licenses/python/pyasn1/) |
| [pyasn1-modules](https://pypi.org/project/pyasn1-modules/0.4.2/) | 0.4.2 | Transitive | BSD-2-Clause | [Texts](third_party_licenses/python/pyasn1-modules/) |
| [pycparser](https://pypi.org/project/pycparser/3.0/) | 3.0 | Transitive | BSD-3-Clause | [Texts](third_party_licenses/python/pycparser/) |
| [pydantic](https://pypi.org/project/pydantic/2.13.5/) | 2.13.5 | Direct | MIT | [Texts](third_party_licenses/python/pydantic/) |
| [pydantic-core](https://pypi.org/project/pydantic-core/2.46.5/) | 2.46.5 | Transitive | MIT | [Texts](third_party_licenses/python/pydantic-core/) |
| [pydantic-settings](https://pypi.org/project/pydantic-settings/2.15.0/) | 2.15.0 | Direct | MIT | [Texts](third_party_licenses/python/pydantic-settings/) |
| [pystray](https://pypi.org/project/pystray/0.19.5/) | 0.19.5 | Direct | LGPL-3.0-or-later | [Texts](third_party_licenses/python/pystray/) |
| [python-dotenv](https://pypi.org/project/python-dotenv/1.2.3/) | 1.2.3 | Transitive | BSD-3-Clause | [Texts](third_party_licenses/python/python-dotenv/) |
| [pythonnet](https://pypi.org/project/pythonnet/3.1.0/) | 3.1.0 | Transitive | MIT | [Texts](third_party_licenses/python/pythonnet/) |
| [pywebview](https://pypi.org/project/pywebview/6.2.1/) | 6.2.1 | Direct | BSD-3-Clause | [Texts](third_party_licenses/python/pywebview/) |
| [pywin32-ctypes](https://pypi.org/project/pywin32-ctypes/0.2.3/) | 0.2.3 | Transitive | BSD-3-Clause | [Texts](third_party_licenses/python/pywin32-ctypes/) |
| [requests](https://pypi.org/project/requests/2.34.2/) | 2.34.2 | Transitive | Apache-2.0 | [Texts](third_party_licenses/python/requests/) |
| [regex](https://pypi.org/project/regex/2026.9.29/) | 2026.9.29 | Direct (security hardening, 2026-10-05) | Apache-2.0 AND CNRI-Python | [Text](third_party_licenses/python/regex/LICENSE.txt) |
| [six](https://pypi.org/project/six/1.17.0/) | 1.17.0 | Transitive | MIT | [Texts](third_party_licenses/python/six/) |
| [sniffio](https://pypi.org/project/sniffio/1.3.1/) | 1.3.1 | Transitive | MIT OR Apache-2.0 | [Texts](third_party_licenses/python/sniffio/) |
| [sqlalchemy](https://pypi.org/project/sqlalchemy/2.0.52/) | 2.0.52 | Direct | MIT | [Texts](third_party_licenses/python/sqlalchemy/) |
| [tenacity](https://pypi.org/project/tenacity/9.1.4/) | 9.1.4 | Transitive | Apache-2.0 | [Texts](third_party_licenses/python/tenacity/) |
| [twitchio](https://pypi.org/project/twitchio/3.3.2/) | 3.3.2 | Direct | MIT | [Texts](third_party_licenses/python/twitchio/) |
| [typing-extensions](https://pypi.org/project/typing-extensions/4.16.0/) | 4.16.0 | Transitive | PSF-2.0 | [Texts](third_party_licenses/python/typing-extensions/) |
| [typing-inspection](https://pypi.org/project/typing-inspection/0.4.4/) | 0.4.4 | Transitive | MIT | [Texts](third_party_licenses/python/typing-inspection/) |
| [urllib3](https://pypi.org/project/urllib3/2.7.0/) | 2.7.0 | Transitive | MIT | [Texts](third_party_licenses/python/urllib3/) |
| [websockets](https://pypi.org/project/websockets/14.2/) | 14.2 | Transitive | BSD-3-Clause | [Texts](third_party_licenses/python/websockets/) |
| [yarl](https://pypi.org/project/yarl/1.24.5/) | 1.24.5 | Transitive | Apache-2.0 | [Texts](third_party_licenses/python/yarl/) |

`clr-loader` has no license field/classifier in the inspected metadata: its shipped
MIT text, checked against [upstream](https://github.com/pythonnet/clr-loader/blob/main/LICENSE),
establishes the listed grant. `pyasn1-modules`' generic “BSD” metadata is resolved by its
shipped two-clause text. `pystray`'s source headers resolve “or later”. `proxy-tools`' source
grant and exact v1.1.0 code match are recorded above. No license was assigned from a package name alone.

### Conditional runtime dependencies (not in the Windows inventory)

The following PyPI metadata versions were checked for the platform markers declared by
keyring, pystray and pywebview. These versions are reference evidence, not resolved or
installed macOS/Linux distributions. Their non-extra transitive dependencies are noted;
the native platform artifact must collect exact license texts and any additional dependencies.

| Package | Metadata version checked | Platform / relationship | License evidence |
| --- | --- | --- | --- |
| [SecretStorage](https://pypi.org/project/SecretStorage/3.5.0/) | 3.5.0 | Linux: keyring; depends on cryptography + jeepney | BSD-3-Clause |
| [jeepney](https://pypi.org/project/jeepney/0.9.0/) | 0.9.0 | Linux: keyring / SecretStorage; no non-extra dependencies | MIT |
| [python-xlib](https://pypi.org/project/python-xlib/0.33/) | 0.33 | Linux: pystray; depends on six | LGPLv2+ metadata; manual review of exact LGPL terms before shipping |
| [pyobjc-core](https://pypi.org/project/pyobjc-core/12.2.2/) | 12.2.2 | macOS: pywebview; no non-extra Python dependencies | MIT |
| [pyobjc-framework-Cocoa](https://pypi.org/project/pyobjc-framework-Cocoa/12.2.2/) | 12.2.2 | macOS: pywebview / pystray; depends on PyObjC core/Cocoa where declared | MIT |
| [pyobjc-framework-Quartz](https://pypi.org/project/pyobjc-framework-Quartz/12.2.2/) | 12.2.2 | macOS: pywebview / pystray; depends on PyObjC core/Cocoa where declared | MIT |
| [pyobjc-framework-WebKit](https://pypi.org/project/pyobjc-framework-WebKit/12.2.2/) | 12.2.2 | macOS: pywebview / pystray; depends on PyObjC core/Cocoa where declared | MIT |
| [pyobjc-framework-Security](https://pypi.org/project/pyobjc-framework-Security/12.2.2/) | 12.2.2 | macOS: pywebview / pystray; depends on PyObjC core/Cocoa where declared | MIT |
| [pyobjc-framework-UniformTypeIdentifiers](https://pypi.org/project/pyobjc-framework-UniformTypeIdentifiers/12.2.2/) | 12.2.2 | macOS: pywebview / pystray; depends on PyObjC core/Cocoa where declared | MIT |

Python <3.12 backports are outside this project's supported runtime. Optional dependency
extras for test/docs, alternate renderers and development are not runtime dependencies of
the default Windows application.

## Historical Python development / installation tooling

These inspected environment packages are not selected by the default runtime closure.
They must stay out of application bundles unless actual frozen imports demonstrate otherwise.
Package installation tooling is not a reason to distribute the entire virtual environment.

| Package | Inspected version | License | Role |
| --- | --- | --- | --- |
| [colorama](https://pypi.org/project/colorama/0.4.6/) | 0.4.6 | BSD-3-Clause | Test/audit tooling; not selected by runtime requirements |
| [iniconfig](https://pypi.org/project/iniconfig/2.3.0/) | 2.3.0 | MIT | Test/audit tooling; not selected by runtime requirements |
| [packaging](https://pypi.org/project/packaging/26.3/) | 26.3 | Apache-2.0 OR BSD-2-Clause | Test/audit tooling; not selected by runtime requirements |
| [pip](https://pypi.org/project/pip/26.2.1/) | 26.2.1 | MIT | Installation tooling (includes separately licensed vendored modules) |
| [pluggy](https://pypi.org/project/pluggy/1.6.0/) | 1.6.0 | MIT | Test/audit tooling; not selected by runtime requirements |
| [pygments](https://pypi.org/project/pygments/2.21.0/) | 2.21.0 | BSD-2-Clause | Test/audit tooling; not selected by runtime requirements |
| [pytest](https://pypi.org/project/pytest/8.4.2/) | 8.4.2 | MIT | Direct test dependency |
| [pytest-asyncio](https://pypi.org/project/pytest-asyncio/0.26.0/) | 0.26.0 | Apache-2.0 | Direct test dependency |
| [setuptools](https://github.com/pypa/setuptools/blob/main/LICENSE) | >=69 for source; Windows build pins 84.0.0 | MIT | Declared build backend; not a runtime dependency |

No license-audit tool has been added as a runtime dependency.

## Frontend production / bundled inventory

The tables were checked against [the frontend lockfile](frontend/package-lock.json)
(**125 packages**). React, React DOM and Scheduler are its three production packages.
React's JSX runtime is part of React. The v1.5.4 ZIP's generated JavaScript includes
Vite's module-preload helper. The preserved Vite license matches the installed 7.3.7
package's license byte for byte. No remote fonts or icon libraries are declared.
The app's tracked icon assets are project resources.

| Package | Locked version | License | Preserved text |
| --- | --- | --- | --- |
| react | 19.3.0 | MIT | [License](third_party_licenses/frontend/react/LICENSE) |
| react-dom | 19.3.0 | MIT | [License](third_party_licenses/frontend/react-dom/LICENSE) |
| scheduler | 0.28.0 | MIT | [License](third_party_licenses/frontend/scheduler/LICENSE) |
| vite (generated helper only) | 7.3.7 | MIT (Vite core), with bundled-tool notices preserved | [License collection](third_party_licenses/frontend/vite/LICENSE.md) |

### Frontend development / build-only lockfile inventory

All remaining 122 lockfile packages are listed below, including optional platform binary
variants. Licenses are the exact npm lockfile metadata. They are not deployed wholesale in
the production frontend; generated output must still be checked for incorporated code.
`@vitejs/plugin-react` generates calls into React; react-refresh/Babel tooling is development
or build work. The browser-support data `caniuse-lite` is CC-BY-4.0; distributing that dataset
or the build toolchain requires its attribution. TypeScript is Apache-2.0.
Vite's own package bundles tools under additional licenses listed in its copied LICENSE.md.
Playwright and its optional dependency support development browser tests only; neither the
test runner nor test browsers are part of the application frontend bundle.

| Package | Locked version | License metadata | Optional platform variant |
| --- | --- | --- | --- |
| @babel/code-frame | 7.29.7 | MIT | No |
| @babel/compat-data | 7.29.7 | MIT | No |
| @babel/core | 7.29.7 | MIT | No |
| @babel/generator | 7.29.8 | MIT | No |
| @babel/helper-compilation-targets | 7.29.7 | MIT | No |
| @babel/helper-globals | 7.29.7 | MIT | No |
| @babel/helper-module-imports | 7.29.7 | MIT | No |
| @babel/helper-module-transforms | 7.29.7 | MIT | No |
| @babel/helper-plugin-utils | 7.29.7 | MIT | No |
| @babel/helper-string-parser | 7.29.7 | MIT | No |
| @babel/helper-validator-identifier | 7.29.7 | MIT | No |
| @babel/helper-validator-option | 7.29.7 | MIT | No |
| @babel/helpers | 7.29.7 | MIT | No |
| @babel/parser | 7.29.9 | MIT | No |
| @babel/plugin-transform-react-jsx-self | 7.29.7 | MIT | No |
| @babel/plugin-transform-react-jsx-source | 7.29.7 | MIT | No |
| @babel/template | 7.29.7 | MIT | No |
| @babel/traverse | 7.29.8 | MIT | No |
| @babel/types | 7.29.8 | MIT | No |
| @esbuild/aix-ppc64 | 0.28.2 | MIT | Yes |
| @esbuild/android-arm | 0.28.2 | MIT | Yes |
| @esbuild/android-arm64 | 0.28.2 | MIT | Yes |
| @esbuild/android-x64 | 0.28.2 | MIT | Yes |
| @esbuild/darwin-arm64 | 0.28.2 | MIT | Yes |
| @esbuild/darwin-x64 | 0.28.2 | MIT | Yes |
| @esbuild/freebsd-arm64 | 0.28.2 | MIT | Yes |
| @esbuild/freebsd-x64 | 0.28.2 | MIT | Yes |
| @esbuild/linux-arm | 0.28.2 | MIT | Yes |
| @esbuild/linux-arm64 | 0.28.2 | MIT | Yes |
| @esbuild/linux-ia32 | 0.28.2 | MIT | Yes |
| @esbuild/linux-loong64 | 0.28.2 | MIT | Yes |
| @esbuild/linux-mips64el | 0.28.2 | MIT | Yes |
| @esbuild/linux-ppc64 | 0.28.2 | MIT | Yes |
| @esbuild/linux-riscv64 | 0.28.2 | MIT | Yes |
| @esbuild/linux-s390x | 0.28.2 | MIT | Yes |
| @esbuild/linux-x64 | 0.28.2 | MIT | Yes |
| @esbuild/netbsd-arm64 | 0.28.2 | MIT | Yes |
| @esbuild/netbsd-x64 | 0.28.2 | MIT | Yes |
| @esbuild/openbsd-arm64 | 0.28.2 | MIT | Yes |
| @esbuild/openbsd-x64 | 0.28.2 | MIT | Yes |
| @esbuild/openharmony-arm64 | 0.28.2 | MIT | Yes |
| @esbuild/sunos-x64 | 0.28.2 | MIT | Yes |
| @esbuild/win32-arm64 | 0.28.2 | MIT | Yes |
| @esbuild/win32-ia32 | 0.28.2 | MIT | Yes |
| @esbuild/win32-x64 | 0.28.2 | MIT | Yes |
| @jridgewell/gen-mapping | 0.3.13 | MIT | No |
| @jridgewell/remapping | 2.3.5 | MIT | No |
| @jridgewell/resolve-uri | 3.1.2 | MIT | No |
| @jridgewell/sourcemap-codec | 1.6.0 | MIT | No |
| @jridgewell/trace-mapping | 0.3.31 | MIT | No |
| @napi-rs/lzma-linux-x64-gnu | 1.5.1 | MIT | Yes |
| @playwright/test | 1.62.1 | Apache-2.0 | No |
| @rolldown/pluginutils | 1.0.0-rc.3 | MIT | No |
| @rollup/rollup-android-arm-eabi | 4.63.5 | MIT | Yes |
| @rollup/rollup-android-arm64 | 4.63.5 | MIT | Yes |
| @rollup/rollup-darwin-arm64 | 4.63.5 | MIT | Yes |
| @rollup/rollup-darwin-x64 | 4.63.5 | MIT | Yes |
| @rollup/rollup-freebsd-arm64 | 4.63.5 | MIT | Yes |
| @rollup/rollup-freebsd-x64 | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-arm-gnueabihf | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-arm-musleabihf | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-arm64-gnu | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-arm64-musl | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-loong64-gnu | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-loong64-musl | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-ppc64-gnu | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-ppc64-musl | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-riscv64-gnu | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-riscv64-musl | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-s390x-gnu | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-x64-gnu | 4.63.5 | MIT | Yes |
| @rollup/rollup-linux-x64-musl | 4.63.5 | MIT | Yes |
| @rollup/rollup-openbsd-x64 | 4.63.5 | MIT | Yes |
| @rollup/rollup-openharmony-arm64 | 4.63.5 | MIT | Yes |
| @rollup/rollup-win32-arm64-msvc | 4.63.5 | MIT | Yes |
| @rollup/rollup-win32-ia32-msvc | 4.63.5 | MIT | Yes |
| @rollup/rollup-win32-x64-gnu | 4.63.5 | MIT | Yes |
| @rollup/rollup-win32-x64-msvc | 4.63.5 | MIT | Yes |
| @types/babel__core | 7.20.5 | MIT | No |
| @types/babel__generator | 7.27.0 | MIT | No |
| @types/babel__template | 7.4.4 | MIT | No |
| @types/babel__traverse | 7.28.0 | MIT | No |
| @types/estree | 1.0.9 | MIT | No |
| @types/node | 24.0.0 | MIT | No |
| @types/react | 19.3.0 | MIT | No |
| @types/react-dom | 19.3.0 | MIT | No |
| @vitejs/plugin-react | 5.2.0 | MIT | No |
| baseline-browser-mapping | 2.11.26 | Apache-2.0 | No |
| browserslist | 4.29.2 | MIT | No |
| caniuse-lite | 1.0.30001813 | CC-BY-4.0 | No |
| convert-source-map | 2.0.0 | MIT | No |
| csstype | 3.2.3 | MIT | No |
| debug | 4.4.3 | MIT | No |
| electron-to-chromium | 1.5.439 | ISC | No |
| esbuild | 0.28.2 | MIT | No |
| escalade | 3.2.0 | MIT | No |
| fdir | 6.5.0 | MIT | No |
| fsevents | 2.3.3 | MIT | Yes |
| gensync | 1.0.0-beta.2 | MIT | No |
| js-tokens | 4.0.0 | MIT | No |
| jsesc | 3.1.0 | MIT | No |
| json5 | 2.2.3 | MIT | No |
| lru-cache | 5.1.1 | ISC | No |
| ms | 2.1.3 | MIT | No |
| nanoid | 3.3.19 | MIT | No |
| node-releases | 2.0.57 | MIT | No |
| picocolors | 1.1.1 | ISC | No |
| picomatch | 4.0.7 | MIT | No |
| playwright | 1.62.1 | Apache-2.0 | No |
| playwright-core | 1.62.1 | Apache-2.0 | No |
| playwright/node_modules/fsevents | 2.3.2 | MIT | Yes |
| postcss | 8.5.28 | MIT | No |
| react-refresh | 0.18.0 | MIT | No |
| rollup | 4.63.5 | MIT | No |
| semver | 6.3.1 | ISC | No |
| source-map-js | 1.2.2 | BSD-3-Clause | No |
| tinyglobby | 0.2.17 | MIT | No |
| typescript | 5.9.3 | Apache-2.0 | No |
| undici-types | 7.8.0 | MIT | No |
| update-browserslist-db | 1.3.3 | MIT | No |
| vite | 7.3.7 | MIT | No |
| yallist | 3.1.1 | ISC | No |

## Rechecking a distribution

1. Resolve dependencies for the target OS/Python version and record exact versions and hashes.
   Compare the frozen/imported file list and final JS to this inventory, not the whole venv.
2. Inventory native payloads and embedded dependencies; resolve every manual-review item above
   with upstream/package license evidence. Include source/rebuild materials where required.
3. Deliver `LICENSE`, `NOTICE`, this file, and applicable `third_party_licenses/` texts with the
   artifact, accessible offline. Preserve copied NOTICE/copyrights; add texts for new versions.
4. Verify the actual artifact's About links/version and notice access. Exclude private profiles,
   credentials, caches and development context. A repository link alone does not satisfy
   delivery of required license texts with a binary.

Verify notice delivery and provenance in each new installer and ZIP. The recorded
redistribution questions require separate resolution.
