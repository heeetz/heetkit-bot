"""Only the x64 .NET Framework loader is required by this target."""

from pathlib import Path

from PyInstaller.utils.hooks import get_package_paths

_, package = get_package_paths("clr_loader")
source = Path(package) / "ffi/dlls/amd64/ClrLoader.dll"
if not source.is_file():
    raise RuntimeError("Required x64 CLR loader is missing")
binaries = [(str(source), "clr_loader/ffi/dlls/amd64")]
