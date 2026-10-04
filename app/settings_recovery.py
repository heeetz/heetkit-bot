"""Preserve profile data that a recovered settings snapshot cannot represent."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path


def _is_recovered(original: object, recovered: object) -> bool:
    if isinstance(original, dict):
        return isinstance(recovered, dict) and all(
            key in recovered and _is_recovered(value, recovered[key])
            for key, value in original.items()
        )
    if isinstance(original, list):
        return isinstance(recovered, (list, tuple)) and len(original) == len(recovered) and all(
            _is_recovered(left, right) for left, right in zip(original, recovered)
        )
    # JSON booleans must not compare equal to numeric settings.
    if isinstance(original, bool) != isinstance(recovered, bool):
        return False
    return original == recovered


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate settings key")
        result[key] = value
    return result


def preserve_settings_recovery(
    path: Path,
    recovered: dict[str, object] | None,
    *,
    version: int | None = None,
    allow_legacy: bool = False,
) -> None:
    """Preflight replacement; refuse unreadable/future files and copy lossy inputs.

    Call immediately before atomic replacement, while holding the store's lock.
    Unknown fields, skipped entries and externally changed values survive in a
    unique, exact-byte recovery file. Failure to preserve it aborts the save.
    """
    repair = (
        f"Cannot save {path.name}. Quit the app, back up and repair this profile file "
        "(or move it aside to reset), then restart."
    )
    try:
        original_bytes = path.read_bytes()
    except FileNotFoundError:
        return
    except OSError as error:
        raise ValueError(repair) from error
    try:
        original = json.loads(original_bytes.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError) as error:
        raise ValueError(repair) from error
    if not isinstance(original, dict):
        raise ValueError(repair)
    if version is not None and not (allow_legacy and "version" not in original):
        if type(original.get("version")) is not int or original["version"] != version:
            raise ValueError(repair)
    if allow_legacy and "version" not in original and recovered is not None:
        recovered = recovered.get("window")
    if _is_recovered(original, recovered):
        return

    recovery_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f"{path.name}.",
            suffix=".recovery", delete=False,
        ) as output:
            recovery_path = Path(output.name)
            output.write(original_bytes)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        if recovery_path is not None:
            recovery_path.unlink(missing_ok=True)
        raise
    logging.getLogger(__name__).warning(
        "Preserved unrecovered settings before save path=%s recovery=%s", path, recovery_path,
    )
