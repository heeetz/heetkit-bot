# Third-party notices

HeetKit is licensed under Apache-2.0; dependencies retain their own licenses.
The source-inventory snapshot below is dated **2026-10-04**, for application version **0.1.0**.
It inventories the 54-package Windows runtime dependency closure in the existing
Python 3.14 environment and all 119 packages in `frontend/package-lock.json`.
The Python declarations support 3.12+ and mostly use version ranges: this snapshot
is evidence of inspected versions, not a Python lockfile or a released artifact.

Evidence: installed Python distribution `METADATA`, `Requires-Dist`, and shipped
license/NOTICE files; npm lockfile metadata and installed production-package licenses;
upstream sources for ambiguous entries. Full runtime texts and attributions copied
from those packages are in [third_party_licenses/](third_party_licenses/). That directory
also includes Vite's license because its module-preload helper can enter generated JS.
These notices do not relicense any dependency under the project's Apache license.

## Windows v1.1.0 artifact review

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

[Windows x64 v1.0.0](https://github.com/heeetz/heetkit-bot/releases/tag/v1.0.0) is published.
The canonical build uses CPython 3.14.7, PyInstaller 6.22.3 and hooks-contrib 2026.8.
Publication does not resolve the artifact-specific redistribution reviews below; the
source inventory remains its dated 0.1.0 snapshot, with v1.1.0 evidence recorded above.
Exact build/runtime pins are in `packaging/windows/requirements.txt`. The bundle includes
the Python license collection, these preserved texts and installed distribution license files
under `_internal/licenses/`. `BUILD-MANIFEST.json` records its file hashes.

The Windows installer uses Inno Setup **6.7.3** around the verified onedir payload. The compiler is pinned and its unmodified installer/uninstaller engine retains
upstream copyright/site notices. Its [license](https://github.com/jrsoftware/issrc/blob/is-6_7_3/license.txt)
is preserved in `third_party_licenses/inno-setup/LICENSE.txt`, shown in the setup notices,
and installed under `_internal/licenses/Inno-Setup-LICENSE.txt`. .NET Framework and
WebView2 Runtime installers are not bundled: missing prerequisites direct the user to
Microsoft's supported downloads. The remaining payload redistribution reviews below
are open; producing an installer does not establish public-release clearance.

The build keeps pystray's redistributed modules as exact, replaceable `.py` files outside
the frozen PYZ, alongside GPL/LGPL texts; no pystray modifications are made. certifi's Python
source and exact CA bundle are also supplied outside PYZ. WebView2 ships only its Core/WinForms
SDK DLLs and x64 loader; the other architecture directories contain placeholders required
by pywebview path discovery. CLR loading uses only the amd64 loader. The collected Python.NET
payload still includes the Microsoft/System/netstandard assemblies described below.

**Recheck this notice set against each actual packaged artifact**, including frozen imports,
native DLLs/extensions, Python's
standard library, generated JS, data files, and any bundled OS prerequisites. Resolve
the remaining items before distributing another binary; this review does not clear v1.1.0.

| Component | Status and required action |
| --- | --- |
| **pystray 0.19.5** | **Resolved for the v1.1.0 layout: LGPL-3.0-or-later.** All six redistributed `.py` modules match the official wheel, retain source headers and are absent from PYZ. GPLv3/LGPLv3 copies match the wheel. `_internal/pystray/` loads from disk through the frozen importer's normal file fallback, without source-integrity restrictions: edit or replace these files while HeetKit is stopped, then relaunch without rebuilding the executable. `PORTABLE.txt` describes replacement. This verifies the source/import layout; no new native modified-library smoke test was run. Preserve this layout and its notices. [Upstream license](https://github.com/moses-palmer/pystray/blob/v0.19.5/COPYING.LGPL), [versioned source](https://github.com/moses-palmer/pystray/tree/v0.19.5). |
| **proxy-tools 0.1.0** | **Resolved source attribution for v1.1.0: BSD-2-Clause; MIT metadata conflicts with the source grant.** The official sdist SHA-256 is `ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010`. Its module explicitly identifies BSD and credits Armin Ronacher/Jonathan Tushman. It is byte-identical to [upstream source at `db43f1e`](https://github.com/jtushman/proxy_tools/blob/db43f1e35d4f90a65c5a4d56d9e9af88212ec6e6/proxy_tools/__init__.py). The frozen code objects match that sdist after normalizing only source filenames. Shipped `UPSTREAM-LICENSE.txt` exactly matches that commit's [BSD notice](https://github.com/jtushman/proxy_tools/blob/db43f1e35d4f90a65c5a4d56d9e9af88212ec6e6/LICENSE.txt), including its malformed final line. Retain it unchanged; do not substitute generic MIT text. |
| **certifi 2026.7.22** | **Resolved source delivery for v1.1.0: MPL-2.0 CA bundle.** `_internal/certifi/` contains the exact wheel's `__init__.py`, `core.py`, `py.typed` and `cacert.pem`, outside PYZ. The shipped license matches the wheel, identifies the MPL-covered bundle and links the MPL text. `PORTABLE.txt` identifies the source/bundle location. No modifications were found. Preserve source/data delivery and notices. [Exact package/source downloads](https://pypi.org/project/certifi/2026.7.22/#files), [MPL responsibilities](https://www.mozilla.org/en-US/MPL/2.0/#responsibilities). |
| **WebView2 SDK 1.0.3856.49** | **Exact source and missing texts resolved for next-build staging.** The three shipped SDK DLLs match official NuGet `Microsoft.Web.WebView2` **1.0.3856.49**, archive SHA-256 `bc0f76eb911b569838dc4aa8f8d325269b966bedb592863d26211aef3a099f1a`. Its original Microsoft BSD license and full `NOTICE.txt` (including ANTLR and StringTemplate) are preserved in [versioned texts](third_party_licenses/native/webview2-1.0.3856.49/). They remain absent from the published v1.1.0 assets. No other native architecture or separately installed WebView2 Runtime is bundled. |
| **pythonnet 3.1.0 / clr-loader 0.3.1 and extra .NET assemblies** | **Provenance resolved; Microsoft obligations remain open.** Correction: the earlier comparison used the platform-neutral wheel. All **97** Python.NET DLLs, including the **96** compatibility files, exactly match the official Windows-specific wheel (SHA-256 `7bdd4de03df3547a48122a3989265c8b31d5be0d19dadffa009eec7df8085e0b`). All 96 also match the official .NET SDK **10.0.300** `Microsoft.NET.Build.Extensions/net461/lib` files. The exact SDK [LICENSE and ThirdPartyNotices](third_party_licenses/native/dotnet-sdk-10.0.300/) are supplied for the next build. They are Microsoft .NET Library terms, not a blanket MIT grant. Python.NET's own DLL and CLR loader retain their own MIT grants. See necessity and owner/legal review below. |
| **Native wheel/interpreter contents** | **Versioned notice delivery implemented; remaining questions listed below.** OpenSSL **3.5.7** and **4.0.2**, CFFI's embedded libffi, CPython's separate libffi **3.4.4**, Rust standard-library and candidate Windows crate notices are preserved from exact upstream sources. Pillow's existing full wheel collection is retained. The [artifact evidence catalogue](packaging/windows/redistribution.json) identifies binary hashes, distribution members, source archives, notice hashes, dependency scopes and unresolved findings. A crate lockfile or PE version alone is not used to claim binary linkage or licensing clearance. |
| **Future platform backends / bundlers** | Linux `python-xlib` has LGPLv2+ metadata and needs artifact-specific source/replacement review. Optional Qt/GTK/CEF backends and macOS frameworks are outside this Windows payload. Determine exact grants, exceptions and distribution contents before shipping another platform or bundler; the pywebview wrapper does not license its renderer. CPython and the current Windows bundler/installer are covered by the Windows evidence and remaining actions above. |

For MIT, BSD, MIT-CMU, PSF and similar permissive components, retain their individual
copyright, license terms and disclaimers in redistributed copies. Preserve the distinction
between `AND` (all terms apply) and `OR` (a permitted license choice). Apache components
require a license copy, retained applicable attribution/NOTICE contents and modification
notices when changed. Shipped NOTICE files from **propcache, requests and yarl** are copied
here; aiohttp's vendored llhttp MIT notice and Pillow's bundled notices are also retained.
The project's `NOTICE` credits heeetz; it does not replace those component notices.

## Next Windows build: corrected materials and remaining blockers

This is the current staging policy, separate from the **0.1.0 historical inventory**
and the immutable **published v1.1.0 evidence** above. The canonical builder recursively
copies `third_party_licenses/`; it now also delivers
`_internal/licenses/windows-redistribution.json`. The existing bundle inspector checks
the finished onedir payload before ZIP creation and again before installer compilation.
It requires the reviewed native inventory and byte-exact notice hashes, rejects new or
renamed PE/native files and changed binary versions/hashes, and compares the staged
catalogue with the trusted repository copy. It does **not** grant legal clearance.
The SDK UCRT inputs are now pinned to those exact published v1.1.0 files, with verified
download/member hashes and a restricted freezing search path. This prevents ambient
tool directories supplying different DLLs. No DLLs are removed, package versions upgraded,
runtime/profile behavior or publication rules changed. Updating the allowlist requires exact upstream review, never merely hashes
from a new build. Historical notice files may remain in staging; the catalogue separately
identifies the current required texts and their concrete evidence.

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
build/probe dependencies. Pydantic-core **2.46.5**'s wheel SBOM explicitly includes
**all targets**: its Cargo/feature analysis supplies a conservative possible Windows
runtime closure, not proof that every locked crate survived compilation. Build-only
and non-Windows dependencies are separately identified, with exact candidate runtime
license texts supplied. Both Rust extensions contain the compiler commit path
`88d9e12ae178fab0fb5cc050a94da85685d449ea`, mapped to Rust **1.98.0**.
That exact release's Apache/MIT/COPYRIGHT texts and evidenced standard-library
dependency notices are supplied; its source archive SHA-256 is
`271fa73d8174f53d713c46a8310da7bf7cfdcfb8b7cfd1c2b74b84a83ae9fb1e`.
Compiler tooling is not bundled as an application dependency.

**Redistribution clearance remains open. Owner/legal or upstream review is required:**

- Microsoft .NET Library **3.a.ii** requires protective distributor/end-user terms and
  indemnification. The app's current notice display/Apache project license does not
  demonstrate satisfaction. Determine the applicable grant and contractual treatment;
  do not assign Microsoft's assemblies Python.NET's MIT license.
- All **43** published UCRT files match `Microsoft.Windows.SDK.CPP` **10.0.26100.1742**
  (package SHA-256 `cea18bcdb33096a94e441a8fdf2db138e356b020a1b5f27d6ddfea1bcec48eb2`).
  Its exact package license URL's original [RTF terms](third_party_licenses/native/windows-sdk-10.0.26100.1742/LICENSE.rtf)
  are retained. Confirm REDIST-list coverage and the SDK **3.a.ii** contractual requirements.
  `VCRUNTIME140.dll`/`VCRUNTIME140_1.dll` match official CPython distributions, but their
  separate Microsoft redistribution terms also need confirmation.
- The published `sqlite3.dll` reports **3.50.4.0** and CPython selects that source version,
  but it does not match the inspected official CPython NuGet binary. Its exact binary
  distribution remains unproven; metadata does not supply the missing provenance.
  The next-build SQLite hash independently matches official CPython NuGet **3.14.7**;
  its current entry and the unresolved historical entry are kept separate.
- The retained pydantic/toolchain code lacks an upstream reproducible build/symbol map.
  Rust's standard-library lockfile identifies in-tree `compiler_builtins 0.1.160` without
  a registry checksum; the exact registry text is supplied conservatively, but that
  does not prove identity with the in-tree source. Confirm this relationship and whether
  generated macro output needs any additional attribution. Candidate inclusion is not
  a claim that build-only crates are shipped or that all linkage questions are closed.

## Python runtime inventory (Windows)

“Direct” means declared in `pyproject.toml`; other rows are recursively selected non-extra
runtime dependencies using Windows markers. Versions are installed distribution versions.
The linked package page identifies the exact version; local text links contain the inspected
licenses and notices. Runtime inclusion in a frozen bundle must be confirmed during packaging.

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

## Python development / installation tooling

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
| [setuptools](https://github.com/pypa/setuptools/blob/main/LICENSE) | >=69; isolated build version not pinned | MIT | Declared build backend; not a runtime dependency |

No license-audit tool has been added as a runtime dependency.

## Frontend production / bundled inventory

React, React DOM and Scheduler are the lockfile's three production packages. React's JSX
runtime is part of React. The generated module-preload helper is from Vite, so its text is
preserved despite Vite being a build dependency. No remote fonts/icon libraries are declared;
the app's tracked icon assets are project resources.

| Package | Locked version | License | Preserved text |
| --- | --- | --- | --- |
| react | 19.3.0 | MIT | [License](third_party_licenses/frontend/react/LICENSE) |
| react-dom | 19.3.0 | MIT | [License](third_party_licenses/frontend/react-dom/LICENSE) |
| scheduler | 0.28.0 | MIT | [License](third_party_licenses/frontend/scheduler/LICENSE) |
| vite (generated helper only) | 7.3.6 | MIT (Vite core); its own bundled-tool notices are also preserved | [License collection](third_party_licenses/frontend/vite/LICENSE.md) |

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
| source-map-js | 1.2.1 | BSD-3-Clause | No |
| tinyglobby | 0.2.17 | MIT | No |
| typescript | 5.9.3 | Apache-2.0 | No |
| undici-types | 7.8.0 | MIT | No |
| update-browserslist-db | 1.3.3 | MIT | No |
| vite | 7.3.6 | MIT | No |
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

This review does not establish binary redistribution clearance while the recorded
actions remain open. Verify corrected notices and provenance in the actual next
installer/ZIP; updating repository documentation does not change published artifacts.
