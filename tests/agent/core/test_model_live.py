"""
Live endpoint smoke tests for the model factory.

These tests hit real provider APIs and are intentionally excluded from the
normal CI suite. Run them explicitly:

    python -m pytest -m live -v

Each test skips automatically if the required key is not in the environment.
"""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()


def _get_model_live(provider, key_env, model_name):
    """Build a model via the per-request config path and return it."""
    from agent.core.model import get_model
    key = os.getenv(key_env)
    if not key:
        pytest.skip(f"{key_env} not set")
    return get_model({
        "configurable": {
            "provider": provider,
            "provider_key": key,
            "model": model_name,
        }
    })


def _assert_text_response(model, prompt="Reply with a single word: hello"):
    """Invoke the model and assert a non-empty text response comes back."""
    response = model.invoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)
    assert isinstance(content, str), f"Expected str content, got {type(content)}"
    assert content.strip(), "Model returned an empty response"
    return content


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_google_genai_live_roundtrip():
    """Gemini endpoint responds with a non-empty string via per-request config."""
    model = _get_model_live("google_genai", "GOOGLE_API_KEY", "gemini-2.5-flash")
    content = _assert_text_response(model)
    print(f"\n[google_genai] response: {content!r}")


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_openai_live_roundtrip():
    """OpenAI endpoint responds with a non-empty string via per-request config."""
    model = _get_model_live("openai", "OPENAI_API_KEY", "gpt-4o-mini")
    content = _assert_text_response(model)
    print(f"\n[openai] response: {content!r}")


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_anthropic_live_roundtrip():
    """Anthropic endpoint responds with a non-empty string via per-request config."""
    model = _get_model_live("anthropic", "ANTHROPIC_API_KEY", "claude-haiku-4-5-20251001")
    content = _assert_text_response(model)
    print(f"\n[anthropic] response: {content!r}")
