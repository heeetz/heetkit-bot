"""Profile-owned AI instructions, personality overrides and selection."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from app.config.personalities import AI_PERSONALITY_PROMPTS
from app.settings_recovery import preserve_settings_recovery

logger = logging.getLogger(__name__)

MAX_PERSONALITY_PROMPT_LENGTH = 50_000
MAX_PERSONALITY_NAME_LENGTH = 64


@dataclass(frozen=True, slots=True)
class PersonalitySettings:
    active_personality: str
    overrides: dict[str, str]
    profile_instructions: str = ""


def validate_personality_name(name: object) -> str:
    if not isinstance(name, str):
        raise ValueError("Personality name must be text.")
    name = name.strip()
    if not name:
        raise ValueError("Personality name must not be empty.")
    if len(name) > MAX_PERSONALITY_NAME_LENGTH:
        raise ValueError(
            f"Personality name must not exceed {MAX_PERSONALITY_NAME_LENGTH} characters."
        )
    return name


def validate_personality_prompt(prompt: object) -> str:
    if not isinstance(prompt, str):
        raise TypeError("Personality prompt must be text.")
    if len(prompt) > MAX_PERSONALITY_PROMPT_LENGTH:
        raise ValueError(
            f"Personality prompt must not exceed {MAX_PERSONALITY_PROMPT_LENGTH} characters."
        )
    return prompt


def validate_profile_instructions(instructions: object) -> str:
    if not isinstance(instructions, str):
        raise TypeError("Profile instructions must be text.")
    if len(instructions) > MAX_PERSONALITY_PROMPT_LENGTH:
        raise ValueError(
            f"Profile instructions must not exceed {MAX_PERSONALITY_PROMPT_LENGTH} characters."
        )
    return instructions


def load_personality_settings(
    path: Path,
    built_in_prompts: Mapping[str, str],
    default_active: str,
) -> PersonalitySettings:
    if not path.exists():
        return PersonalitySettings(default_active, {})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        logger.warning(
            "Could not load personality settings path=%s error=%s; using defaults",
            path,
            type(error).__name__,
        )
        return PersonalitySettings(default_active, {})
    if not isinstance(payload, dict):
        logger.warning("Personality settings file must contain a JSON object; using defaults")
        return PersonalitySettings(default_active, {})

    raw_overrides = payload.get("overrides", {})
    if not isinstance(raw_overrides, dict):
        logger.warning("Ignoring malformed AI personality overrides")
        raw_overrides = {}
    overrides: dict[str, str] = {}
    for name, prompt in raw_overrides.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 64:
            logger.warning("Ignoring invalid AI personality name")
            continue
        try:
            parsed_prompt = validate_personality_prompt(prompt)
        except (TypeError, ValueError) as error:
            logger.warning(
                "Ignoring invalid AI personality override name=%s error=%s",
                name,
                str(error),
            )
            continue
        # Retain explicit saved entries, even when they match a shipped default.
        # Saving profile instructions must not normalize unrelated personalities.
        overrides[name] = parsed_prompt
    active = payload.get("active_personality", default_active)
    if not isinstance(active, str) or active not in (built_in_prompts.keys() | overrides.keys()):
        logger.warning("Ignoring unknown active AI personality name=%r", active)
        active = default_active
    try:
        profile_instructions = validate_profile_instructions(payload.get("profile_instructions", ""))
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid AI profile instructions")
        profile_instructions = ""
    return PersonalitySettings(active, overrides, profile_instructions)


def save_personality_settings(
    path: Path, settings: PersonalitySettings, *, recovered_settings: PersonalitySettings | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_personality": settings.active_personality,
        "overrides": dict(sorted(settings.overrides.items())),
        "profile_instructions": settings.profile_instructions,
    }
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(payload, temporary_file, indent=2, sort_keys=True, ensure_ascii=False)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        preserve_settings_recovery(
            path,
            None if recovered_settings is None else {
                "active_personality": recovered_settings.active_personality,
                "overrides": {**AI_PERSONALITY_PROMPTS, **recovered_settings.overrides},
                "profile_instructions": recovered_settings.profile_instructions,
            },
        )
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
