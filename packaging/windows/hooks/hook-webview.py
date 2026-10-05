"""Windows x64 renderer only; exclude unused backend payloads."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, get_package_paths

_, package = get_package_paths("webview")
root = Path(package)
datas = collect_data_files("webview", includes=["js/**/*.js"])
for relative in (
    "lib/Microsoft.Web.WebView2.Core.dll",
    "lib/Microsoft.Web.WebView2.WinForms.dll",
    "lib/runtimes/win-x64/native/WebView2Loader.dll",
):
    source = root / relative
    if not source.is_file():
        raise RuntimeError(f"Required WebView2 payload is missing: {relative}")
    datas.append((str(source), "webview/" + str(Path(relative).parent)))
hiddenimports = ["webview.platforms.winforms", "webview.platforms.edgechromium"]
# pywebview 6.2.1 resolves all three directory names before choosing the x64 DLL.
# Preserve empty directory structure without shipping unused native architectures.
for architecture in ("win-arm64", "win-x86"):
    datas.append((str(Path(__file__).with_name("runtime-directory.txt")),
                  f"webview/lib/runtimes/{architecture}/native"))
excludedimports = ["webview.platforms." + name for name in (
    "android", "cef", "cocoa", "gtk", "qt", "mshtml", "edgehtml",
)]
