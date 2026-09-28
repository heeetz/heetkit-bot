"""Focused tests for built-in AI personality selection."""

import pytest

from app.config.personalities import AI_PERSONALITY_PRESETS
from app.runtime_state import RuntimeState
from config import ACTIVE_AI_PERSONALITY, build_ai_system_instruction


def test_all_built_in_personalities_resolve() -> None:
    assert tuple(AI_PERSONALITY_PRESETS) == (
        "vas2",
        "vas",
        "anime_girl",
        "rapper",
        "neutral",
        "gopnik",
    )

    for name in AI_PERSONALITY_PRESETS:
        instruction = build_ai_system_instruction(name)
        assert "Current date and time:" in instruction
        assert "{current_datetime}" not in instruction
        assert "{ai_max_response_length}" not in instruction


def test_active_personality_remains_the_runtime_default() -> None:
    runtime_state = RuntimeState()

    assert runtime_state.active_ai_personality == ACTIVE_AI_PERSONALITY
    assert runtime_state.available_personalities == tuple(AI_PERSONALITY_PRESETS)


def test_runtime_personality_switching_and_validation_are_preserved() -> None:
    runtime_state = RuntimeState()

    runtime_state.set_active_ai_personality("neutral")
    assert runtime_state.active_ai_personality == "neutral"

    with pytest.raises(ValueError, match="Unknown AI personality"):
        runtime_state.set_active_ai_personality("missing")

    with pytest.raises(ValueError, match="Unknown AI personality"):
        build_ai_system_instruction("missing")
