import sys
from importlib.util import find_spec

import pytest
import pytest_asyncio


# These cases live in modules reserved for the next slices.
_PYWEBVIEW_TESTS = {
    "test_configuration_transfer.py": {
        "test_desktop_export_server_preview_import_round_trip_and_restart",
        "test_native_export_cancel_and_errors_preserve_destination",
    },
    "test_webview_host.py": {
        "test_native_activity_export_is_bounded_explicit_and_atomic",
        "test_pywebview_dispatch_cannot_traverse_to_credentials",
        "test_exposed_operations_require_the_initial_frontend_origin",
    },
}


@pytest.fixture
def synthetic_default_profile(tmp_path, monkeypatch):
    from app.runtime_paths import DATA_DIR_ENV

    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    monkeypatch.setattr("app.runtime_paths.user_data_path", lambda *args, **kwargs: tmp_path)


def pytest_collection_modifyitems(items):
    has_pywebview = find_spec("webview") is not None
    for item in items:
        if getattr(item, "originalname", None) in _PYWEBVIEW_TESTS.get(item.path.name, ()):
            item.add_marker(pytest.mark.pywebview)
        if item.get_closest_marker("pywebview") and not has_pywebview:
            item.add_marker(pytest.mark.skip(reason="Requires the optional pywebview package"))
        if item.get_closest_marker("windows") and sys.platform != "win32":
            item.add_marker(pytest.mark.skip(reason="Requires the Windows runtime"))


@pytest_asyncio.fixture
async def database(tmp_path):
    """An initialized synthetic personal database that is closed after the test."""
    from app.database.database import Database

    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'personal.sqlite3'}")
    await database.initialize()
    yield database
    await database.close()
