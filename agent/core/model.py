"""
Model factory for Rhizome.

All model access must go through get_model() or get_triage_model().
Never call init_chat_model() outside this module.

Configuration (environment variables):
  RHIZOME_MODEL          — primary model name (default: gemini-2.0-flash)
  RHIZOME_MODEL_PROVIDER — LangChain provider key (default: google_genai)
  RHIZOME_TRIAGE_MODEL   — model for session-start triage summaries;
                           falls back to RHIZOME_MODEL if not set
"""

import os

from dotenv import load_dotenv

load_dotenv()

_DEFAULT_MODEL = "gemini-2.0-flash"
_DEFAULT_PROVIDER = "google_genai"

_model = None
_triage_model = None


def get_model():
    """Return the primary model instance, creating it on first call."""
    global _model
    if _model is None:
        from langchain.chat_models import init_chat_model
        _model = init_chat_model(
            os.getenv("RHIZOME_MODEL", _DEFAULT_MODEL),
            model_provider=os.getenv("RHIZOME_MODEL_PROVIDER", _DEFAULT_PROVIDER),
            temperature=0,
        )
    return _model


def get_triage_model():
    """Return the triage model instance, creating it on first call.

    Checks RHIZOME_TRIAGE_MODEL first, falls back to RHIZOME_MODEL,
    then to the default. Point this at a faster/cheaper model than
    the primary when you want to reduce session-start latency.
    """
    global _triage_model
    if _triage_model is None:
        from langchain.chat_models import init_chat_model
        name = (
            os.getenv("RHIZOME_TRIAGE_MODEL")
            or os.getenv("RHIZOME_MODEL")
            or _DEFAULT_MODEL
        )
        _triage_model = init_chat_model(
            name,
            model_provider=os.getenv("RHIZOME_MODEL_PROVIDER", _DEFAULT_PROVIDER),
            temperature=0,
        )
    return _triage_model
