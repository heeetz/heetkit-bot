"""Exact documented capability/native parameter boundaries, without live providers."""

import pytest

from app.config.ai_capabilities import (
    KNOWN_MODELS, model_capabilities, native_thinking_parameters, validate_model_options,
)
from app.services.ai_provider import source_metadata


def test_unknown_and_lookalike_models_get_no_invented_controls():
    for provider, model in (("gemini", "gemini-3.8-flash-custom"), ("deepseek", "deepseek-flash-custom"),
                            ("openai", "gpt-6-luna-custom")):
        capability = model_capabilities(provider, model)
        assert capability["known"] is False
        assert [item["value"] for item in capability["thinking_options"]] == ["default"]
        assert not capability["search_supported"]
        assert native_thinking_parameters(provider, model, "default") == {}
        with pytest.raises(ValueError):
            validate_model_options(provider, model, "high", False)
        with pytest.raises(ValueError):
            validate_model_options(provider, model, "default", True)


@pytest.mark.parametrize("model", KNOWN_MODELS["deepseek"])
def test_deepseek_native_toggle_and_real_effort_values(model):
    assert native_thinking_parameters("deepseek", model, "off") == {"thinking": {"type": "disabled"}}
    assert native_thinking_parameters("deepseek", model, "max") == {
        "thinking": {"type": "enabled"}, "reasoning_effort": "max",
    }
    with pytest.raises(ValueError):
        validate_model_options("deepseek", model, "medium", False)


def test_gemini_native_minimum_and_maximum_do_not_invent_off():
    capability = model_capabilities("gemini", "gemini-2.5-pro")
    assert [item["value"] for item in capability["thinking_options"]] == [
        "default", "budget:128", "budget:32768",
    ]
    assert native_thinking_parameters("gemini", "gemini-2.5-pro", "budget:32768") == {
        "thinking_budget": 32768, "include_thoughts": False,
    }
    with pytest.raises(ValueError):
        validate_model_options("gemini", "gemini-2.5-pro", "off", False)
    with pytest.raises(ValueError):
        validate_model_options("gemini", "gemini-3.8-flash", "minimal", False)
    assert native_thinking_parameters("gemini", "gemini-3.6-flash", "minimal") == {
        "thinking_level": "minimal", "include_thoughts": False,
    }


def test_gemini_search_reports_plain_text_attribution_limitation():
    capability = model_capabilities("gemini", "gemini-3.5-flash-lite")
    assert capability["search_supported"] and capability["attribution_required"]
    assert "Twitch" in capability["search_reason"]
    assert "Suggestions" in capability["search_reason"]


def test_openai_exact_native_efforts_and_search():
    for model in KNOWN_MODELS["openai"]:
        capability = model_capabilities("openai", model)
        assert capability["known"] and capability["search_supported"]
        assert capability["api_version"] == "v1/responses"
        assert native_thinking_parameters("openai", model, "low") == {"reasoning": {"effort": "low"}}
        assert native_thinking_parameters("openai", model, "default") == {}
        for unsupported in ("off", "minimal", "ultra"):
            with pytest.raises(ValueError):
                validate_model_options("openai", model, unsupported, False)
    assert native_thinking_parameters("openai", "gpt-6-luna", "none") == {"reasoning": {"effort": "none"}}
    with pytest.raises(ValueError):
        validate_model_options("openai", "gpt-6.1-sol", "none", True)


def test_sources_are_bounded_public_url_metadata_without_control_characters():
    assert source_metadata("label", "https://user:password@example.test/") is None
    assert source_metadata("label", "javascript:alert(1)") is None
    assert source_metadata("label", "https://example.test/\n") is None
    assert source_metadata("label", "https://example.test:bad/") is None
    source = source_metadata("A\n title\x00", "https://example.test/page")
    assert source.title == "A title"
    assert len(source_metadata("x" * 500, "https://example.test/").title) == 200
