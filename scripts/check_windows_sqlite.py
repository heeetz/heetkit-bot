"""Exercise the actual packaged CPython SQLite pair in an isolated process."""

import ctypes
import importlib.util
import os
from pathlib import Path
import sys


def check(bundle: Path) -> None:
    internal = bundle.resolve() / "_internal"
    dll = internal / "sqlite3.dll"
    # Load the exact artifact DLL before importing its extension; avoid host SQLite.
    with os.add_dll_directory(str(internal)):
        library = ctypes.WinDLL(str(dll))
        filename = ctypes.create_unicode_buffer(32768)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
        if not kernel.GetModuleFileNameW(library._handle, filename, len(filename)):
            raise ctypes.WinError(ctypes.get_last_error())
        if Path(filename.value).resolve() != dll:
            raise RuntimeError(f"SQLite loaded from unexpected path: {filename.value}")
        spec = importlib.util.spec_from_file_location("_sqlite3", internal / "_sqlite3.pyd")
        sqlite = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sqlite)
        connection = sqlite.connect(":memory:")
        try:
            connection.execute("create table smoke (value text)")
            connection.execute("insert into smoke values (?)", ("verified",))
            connection.commit()
            if connection.execute("select value from smoke").fetchone() != ("verified",):
                raise RuntimeError("Packaged SQLite query failed")
            connection.execute("insert into smoke values (?)", ("rollback",))
            connection.rollback()
            if connection.execute("select count(*) from smoke").fetchone() != (1,):
                raise RuntimeError("Packaged SQLite transaction failed")
            version = connection.execute("select sqlite_version()").fetchone()[0]
            if version != "3.50.4" or connection.execute("pragma integrity_check").fetchone() != ("ok",):
                raise RuntimeError(f"Unexpected packaged SQLite runtime: {version}")
        finally:
            connection.close()
    print(f"Packaged SQLite compatibility passed: {filename.value}; SQLite {version}")


if __name__ == "__main__":
    check(Path(sys.argv[1]))
