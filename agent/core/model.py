"""
Model factory for Rhizome.

All model access must go through get_model() and get_triage_model().
Never instantiate a model client directly or at import time anywhere else.

Configuration (environment variables, used when no per-request config is provided):
  RHIZOME_MODEL          — primary model name; defaults per provider if not set
  RHIZOME_MODEL_PROVIDER — provider key: google_genai | openai | anthropic (default: google_genai)
  RHIZOME_TRIAGE_MODEL   — triage model name; falls back to RHIZOME_MODEL
  GOOGLE_API_KEY         — API key for google_genai provider
  OPENAI_API_KEY         — API key for openai provider
  ANTHROPIC_API_KEY      — API key for anthropic provider

Per-request overrides (from LangGraph config["configurable"], injected by Cambium):
  provider     — one of: google_genai, openai, anthropic
  provider_key — the user's decrypted API key for that provider
  model        — optional model name override
"""

import os

from dotenv import load_dotenv

load_dotenv()

_DEFAULT_PROVIDER = "google_genai"

_SUPPORTED_PROVIDERS = frozenset({"google_genai", "openai", "anthropic"})

# Sensible defaults per provider when RHIZOME_MODEL is not set
_DEFAULT_MODELS = {
    "google_genai": "gemini-2.5-flash",
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-6",
}

# Environment variable names for each provider's API key
_API_KEY_ENV = {
    "google_genai": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

# Keyword argument names accepted by each provider's LangChain class
_API_KEY_KWARGS = {
    "google_genai": "google_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
}

# Cached instances for the env-var path (no per-request config)
_model = None
_triage_model = None


def _resolve(config, *, triage: bool = False):
    """Return (provider, model_name, api_key) from config and env vars."""
    configurable = (config or {}).get("configurable") or {}
    provider = configurable.get("provider") or os.getenv("RHIZOME_MODEL_PROVIDER", _DEFAULT_PROVIDER)

    if provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider {provider!r}. "
            f"Supported: {sorted(_SUPPORTED_PROVIDERS)}"
        )

    if triage:
        model_name = (
            configurable.get("model")
            or os.getenv("RHIZOME_TRIAGE_MODEL")
            or os.getenv("RHIZOME_MODEL")
            or _DEFAULT_MODELS[provider]
        )
    else:
        model_name = (
            configurable.get("model")
            or os.getenv("RHIZOME_MODEL")
            or _DEFAULT_MODELS[provider]
        )

    api_key = configurable.get("provider_key") or os.getenv(_API_KEY_ENV[provider])
    if not api_key:
        raise ValueError(
            f"No API key for provider {provider!r}. "
            f"Set {_API_KEY_ENV[provider]} or pass provider_key in config."
        )

    return provider, model_name, api_key


def _build(provider, model_name, api_key):
    from langchain.chat_models import init_chat_model
    return init_chat_model(
        model_name,
        model_provider=provider,
        temperature=0,
        **{_API_KEY_KWARGS[provider]: api_key},
    )


def _is_per_request(config):
    """True when the config carries a per-request provider or key override."""
    configurable = (config or {}).get("configurable") or {}
    return bool(configurable.get("provider") or configurable.get("provider_key"))


def get_model(config=None):
    """Return the primary model instance.

    Per-request config (provider/provider_key in configurable) bypasses the
    singleton cache and returns a fresh instance. Env-var-only calls are cached.
    """
    global _model
    if _is_per_request(config):
        provider, model_name, api_key = _resolve(config)
        return _build(provider, model_name, api_key)
    if _model is None:
        provider, model_name, api_key = _resolve(None)
        _model = _build(provider, model_name, api_key)
    return _model


def get_triage_model(config=None):
    """Return the triage model instance.

    Prefers RHIZOME_TRIAGE_MODEL over RHIZOME_MODEL; falls back to the
    provider's default. Per-request config bypasses the singleton cache.
    """
    global _triage_model
    if _is_per_request(config):
        provider, model_name, api_key = _resolve(config, triage=True)
        return _build(provider, model_name, api_key)
    if _triage_model is None:
        provider, model_name, api_key = _resolve(None, triage=True)
        _triage_model = _build(provider, model_name, api_key)
    return _triage_model
