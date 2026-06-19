"""Unit tests for agent/core/model.py — multi-provider factory."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def reset_model_cache():
    """Reset cached model singletons between tests to avoid cross-test contamination."""
    from agent.core import model as m
    prior_model, prior_triage = m._model, m._triage_model
    yield
    m._model = prior_model
    m._triage_model = prior_triage


# ---------------------------------------------------------------------------
# Provider selected from config
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_model_config_selects_google_genai():
    from agent.core.model import get_model
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        config = {"configurable": {"provider": "google_genai", "provider_key": "gkey-123"}}
        result = get_model(config)
    args, kwargs = mock_init.call_args
    assert kwargs["model_provider"] == "google_genai"
    assert kwargs["google_api_key"] == "gkey-123"
    assert result is fake


@pytest.mark.unit
def test_get_model_config_selects_openai():
    from agent.core.model import get_model
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        config = {"configurable": {"provider": "openai", "provider_key": "sk-openai"}}
        result = get_model(config)
    args, kwargs = mock_init.call_args
    assert kwargs["model_provider"] == "openai"
    assert kwargs["openai_api_key"] == "sk-openai"
    assert result is fake


@pytest.mark.unit
def test_get_model_config_selects_anthropic():
    from agent.core.model import get_model
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        config = {"configurable": {"provider": "anthropic", "provider_key": "sk-ant-test"}}
        result = get_model(config)
    args, kwargs = mock_init.call_args
    assert kwargs["model_provider"] == "anthropic"
    assert kwargs["anthropic_api_key"] == "sk-ant-test"
    assert result is fake


@pytest.mark.unit
def test_get_model_config_uses_model_override():
    from agent.core.model import get_model
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        config = {"configurable": {
            "provider": "openai",
            "provider_key": "sk-test",
            "model": "gpt-4o-mini",
        }}
        get_model(config)
    args, kwargs = mock_init.call_args
    assert args[0] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Env-var fallback
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_model_falls_back_to_env(monkeypatch):
    from agent.core import model as m
    monkeypatch.setenv("RHIZOME_MODEL_PROVIDER", "google_genai")
    monkeypatch.setenv("RHIZOME_MODEL", "gemini-1.5-flash")
    monkeypatch.setenv("GOOGLE_API_KEY", "env-gkey")
    m._model = None
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        result = m.get_model()  # no config
    args, kwargs = mock_init.call_args
    assert args[0] == "gemini-1.5-flash"
    assert kwargs["model_provider"] == "google_genai"
    assert kwargs["google_api_key"] == "env-gkey"
    assert result is fake


@pytest.mark.unit
def test_get_model_uses_provider_default_model_when_rhizome_model_unset(monkeypatch):
    from agent.core import model as m
    monkeypatch.setenv("RHIZOME_MODEL_PROVIDER", "openai")
    monkeypatch.delenv("RHIZOME_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "env-oaikey")
    m._model = None
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        m.get_model()
    args, kwargs = mock_init.call_args
    assert args[0] == "gpt-4o"


@pytest.mark.unit
def test_get_model_provider_key_in_config_uses_env_provider(monkeypatch):
    """provider_key alone in config should use the env-var provider."""
    from agent.core.model import get_model
    monkeypatch.setenv("RHIZOME_MODEL_PROVIDER", "google_genai")
    monkeypatch.setenv("RHIZOME_MODEL", "gemini-2.0-flash")
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        config = {"configurable": {"provider_key": "injected-key"}}
        get_model(config)
    args, kwargs = mock_init.call_args
    assert kwargs["model_provider"] == "google_genai"
    assert kwargs["google_api_key"] == "injected-key"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_model_unsupported_provider_raises():
    from agent.core.model import get_model
    config = {"configurable": {"provider": "ollama", "provider_key": "x"}}
    with pytest.raises(ValueError, match="Unsupported provider"):
        get_model(config)


@pytest.mark.unit
def test_get_model_missing_api_key_raises(monkeypatch):
    from agent.core.model import get_model
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = {"configurable": {"provider": "openai"}}  # no provider_key
    with pytest.raises(ValueError, match="No API key for provider"):
        get_model(config)


@pytest.mark.unit
def test_get_model_missing_env_key_raises(monkeypatch):
    from agent.core import model as m
    monkeypatch.setenv("RHIZOME_MODEL_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    m._model = None
    with pytest.raises(ValueError, match="No API key for provider"):
        m.get_model()


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_model_env_path_caches_singleton(monkeypatch):
    from agent.core import model as m
    monkeypatch.setenv("GOOGLE_API_KEY", "env-gkey")
    monkeypatch.delenv("RHIZOME_MODEL_PROVIDER", raising=False)
    m._model = None
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        result1 = m.get_model()
        result2 = m.get_model()
    assert mock_init.call_count == 1
    assert result1 is result2


@pytest.mark.unit
def test_get_model_per_request_bypasses_cache():
    from agent.core import model as m
    fake1, fake2 = MagicMock(), MagicMock()
    config = {"configurable": {"provider": "openai", "provider_key": "sk-test"}}
    with patch("langchain.chat_models.init_chat_model", side_effect=[fake1, fake2]):
        r1 = m.get_model(config)
        r2 = m.get_model(config)
    assert r1 is not r2  # new instance each call


# ---------------------------------------------------------------------------
# Triage model
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_triage_model_prefers_rhizome_triage_model_env(monkeypatch):
    from agent.core import model as m
    monkeypatch.setenv("RHIZOME_TRIAGE_MODEL", "gemini-2.0-flash-lite")
    monkeypatch.setenv("RHIZOME_MODEL", "gemini-2.0-flash")
    monkeypatch.setenv("GOOGLE_API_KEY", "env-gkey")
    monkeypatch.delenv("RHIZOME_MODEL_PROVIDER", raising=False)
    m._triage_model = None
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        m.get_triage_model()
    args, kwargs = mock_init.call_args
    assert args[0] == "gemini-2.0-flash-lite"


@pytest.mark.unit
def test_get_triage_model_falls_back_to_rhizome_model(monkeypatch):
    from agent.core import model as m
    monkeypatch.delenv("RHIZOME_TRIAGE_MODEL", raising=False)
    monkeypatch.setenv("RHIZOME_MODEL", "gemini-1.5-flash")
    monkeypatch.setenv("GOOGLE_API_KEY", "env-gkey")
    monkeypatch.delenv("RHIZOME_MODEL_PROVIDER", raising=False)
    m._triage_model = None
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        m.get_triage_model()
    args, kwargs = mock_init.call_args
    assert args[0] == "gemini-1.5-flash"


@pytest.mark.unit
def test_get_triage_model_config_selects_provider():
    from agent.core.model import get_triage_model
    fake = MagicMock()
    with patch("langchain.chat_models.init_chat_model", return_value=fake) as mock_init:
        config = {"configurable": {"provider": "anthropic", "provider_key": "sk-ant-test"}}
        result = get_triage_model(config)
    args, kwargs = mock_init.call_args
    assert kwargs["model_provider"] == "anthropic"
    assert kwargs["anthropic_api_key"] == "sk-ant-test"
    assert result is fake
