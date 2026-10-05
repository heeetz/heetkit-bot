# Third-party notices

HeetKit is licensed under Apache-2.0; dependencies retain their own licenses.
This audit snapshot is dated **2026-10-04**, for application version **0.1.0**.
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

## Redistribution requirements and manual review

No standalone application has been built. **Recheck this notice set against the actual
TODO-014 packaged artifact**, including frozen imports, native DLLs/extensions, Python's
standard library, generated JS, data files, and any bundled OS prerequisites. Resolve
the following items before distributing binaries; this source audit is not binary clearance.

| Component | Status and required action |
| --- | --- |
| **pystray 0.19.5** | **Manual review: LGPL-3.0-or-later.** Source headers establish the later-version option; PyPI says LGPLv3. Keep its copyright notice plus both GPLv3 and LGPLv3 texts (copied here). Supply the exact library source and any modifications; ensure users can modify/replace/recombine it and debug those modifications. A frozen PYZ/onefile arrangement needs a reviewed source/rebuild or suitable replacement mechanism; a source URL alone is not a compliance plan. [Upstream license](https://github.com/moses-palmer/pystray/blob/v0.19.5/COPYING.LGPL), [versioned source](https://github.com/moses-palmer/pystray/tree/v0.19.5). |
| **proxy-tools 0.1.0** | **Manual review: conflicting attribution/license evidence.** The exact PyPI wheel/sdist metadata says MIT, and neither includes a license file. The [upstream LICENSE.txt](https://github.com/jtushman/proxy_tools/blob/master/LICENSE.txt) instead contains a BSD two-clause notice crediting Armin Ronacher and Jonathan Tushman, with a malformed final line. Its README describes extraction from Werkzeug. The upstream text is preserved as `UPSTREAM-LICENSE.txt`, not asserted to resolve the release's grant. Obtain authoritative confirmation for the exact redistributed code and preserve the original attribution. Do not substitute a generic MIT license. |
| **certifi 2026.7.22** | MPL-2.0 CA bundle. Keep its shipped notice; identify and make the exact covered source/bundle available to recipients, including changes. Keep MPL-covered files under MPL-2.0; the larger application may retain its own license. Confirm the release's source delivery approach during packaging. [Exact package/source downloads](https://pypi.org/project/certifi/2026.7.22/#files), [MPL responsibilities](https://www.mozilla.org/en-US/MPL/2.0/#responsibilities). |
| **pywebview 6.2.1 Windows DLLs** | **Manual review: pywebview's BSD license does not establish the Microsoft SDK's terms.** The inspected wheel includes `Microsoft.Web.WebView2.Core.dll` / `WinForms.dll` version **1.0.3856.49** and x86/x64/arm64 `WebView2Loader.dll`, plus `WebBrowserInterop` DLLs. Match each shipped DLL to its source/package, retain the applicable Microsoft SDK terms/notices, and select only required architectures. The installed WebView2 Runtime is an OS prerequisite, not React code. Review separately if a runtime/bootstrapper is redistributed. [Microsoft SDK package](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.3856.49), [Microsoft distribution guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution). |
| **pythonnet 3.1.0 / clr-loader 0.3.1 native payload** | Their own licenses are MIT and copied here. **Manual review** of additional Microsoft/System/netstandard assemblies in `pythonnet/runtime/` is still required: record actual file versions and NuGet/source provenance and retain their own terms; do not infer all DLL licenses from Python.NET's MIT metadata. `Python.Runtime.deps.json` records additional package dependencies. A bundled CLR/.NET runtime would require a separate inventory. |
| **Native wheel contents** | **Manual review** of embedded dependencies in `cryptography` (OpenSSL/Rust), Pillow (image codecs and its extensive bundled-library notices), CFFI (libffi), pydantic-core and other compiled extensions: inspect the exact wheel/artifact, retain embedded license/NOTICE texts, and add missing source/license evidence. Top-level Python metadata does not enumerate every compiled-in library. Pillow's full shipped license collection is retained here. |
| **Future platform backends / bundlers** | Linux `python-xlib` has LGPLv2+ metadata and needs the same artifact-specific source/replacement review. Optional Qt/GTK/CEF backends, their native libraries, macOS frameworks, the Python interpreter and any future freezing/installer tool are not shipped by this task. Determine selected versions, exact grants, exceptions and distribution contents when used; do not assume the pywebview wrapper licenses its renderer. |

For MIT, BSD, MIT-CMU, PSF and similar permissive components, retain their individual
copyright, license terms and disclaimers in redistributed copies. Preserve the distinction
between `AND` (all terms apply) and `OR` (a permitted license choice). Apache components
require a license copy, retained applicable attribution/NOTICE contents and modification
notices when changed. Shipped NOTICE files from **propcache, requests and yarl** are copied
here; aiohttp's vendored llhttp MIT notice and Pillow's bundled notices are also retained.
The project's `NOTICE` credits heeetz; it does not replace those component notices.

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
| [proxy-tools](https://pypi.org/project/proxy-tools/0.1.0/) | 0.1.0 | Transitive | CONFLICT: MIT metadata / BSD-2-Clause upstream; manual review | [Texts](third_party_licenses/python/proxy-tools/) |
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
shipped two-clause text. `pystray`'s source headers resolve “or later”. `proxy-tools` remains
unresolved as explained above. No license was assigned from a package name alone.

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

This audit deliberately does not build an installer, freeze Python or declare a binary release
ready. Artifact verification remains TODO-014 and later distribution work.
