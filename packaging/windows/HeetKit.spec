# Windows x64 onedir bundle. Inputs are staged by scripts/build_windows.py.
import os
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

root = Path(SPECPATH).parents[1]
stage = Path(os.environ["HEETKIT_BUILD_STAGE"])
version = os.environ["HEETKIT_BUILD_VERSION"]
version_tuple = tuple(int(part) for part in version.split(".")) + (0,)
data = [(str(path), str(path.parent.relative_to(stage))) for path in stage.rglob("*") if path.is_file()]
data += collect_data_files("pythonnet", includes=["runtime/Python.Runtime.runtimeconfig.json", "runtime/Python.Runtime.deps.json"])

metadata = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("040904B0", [StringStruct(key, value) for key, value in {
        "CompanyName": "heeetz", "FileDescription": "HeetKit — Desktop control center for Twitch chat",
        "FileVersion": version, "ProductName": "HeetKit", "ProductVersion": version,
        "OriginalFilename": "HeetKit.exe", "LegalCopyright": "Copyright © 2026 heeetz",
    }.items()])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
)
a = Analysis(
    [str(root / "packaging/windows/launcher.py")], pathex=[str(root)],
    binaries=[], datas=data,
    hiddenimports=["aiosqlite", "sqlalchemy.dialects.sqlite.aiosqlite", "keyring.backends.Windows", "clr"],
    hookspath=[str(root / "packaging/windows/hooks")],
    excludes=["pytest", "tkinter", "unittest", "pydoc", "pip", "setuptools"],
    module_collection_mode={"certifi": "py"},
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="HeetKit", console=False,
          icon=str(root / "app/resources/icon.ico"), version=metadata, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="HeetKit")
# CLR reads the process config beside the executable, not in PyInstaller's
# _internal data directory. Include it in both standalone and portable output.
shutil.copyfile(root / "packaging/windows/HeetKit.exe.config", Path(coll.name) / "HeetKit.exe.config")
