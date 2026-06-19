"""Rhizome telemetry helpers.

Provides two layers:
1. Standalone OpenTelemetry spans/events when opentelemetry is installed.
2. An optional observer interface for forwarding lifecycle events into
   external harnesses such as ControlFlux-style bridges.

All APIs degrade to no-ops when telemetry dependencies are unavailable.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.trace import StatusCode

    _HAS_OTEL_API = True
except ImportError:
    trace = None
    StatusCode = None
    _HAS_OTEL_API = False


class AgentObserver(Protocol):
    """Minimal event sink interface for external runtime observers."""

    def record_message(
        self,
        role: str,
        text: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        ...

    def record_tool_call_started(
        self,
        tool_name: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Any:
        ...

    def record_tool_call_completed(
        self,
        tool_name: str,
        *,
        success: bool,
        payload: Optional[Dict[str, Any]] = None,
        error: str = "",
    ) -> Any:
        ...

    def record_state_snapshot(
        self,
        snapshot_name: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        ...


class NoOpObserver:
    def record_message(self, role: str, text: str, *, payload=None, metadata=None) -> None:
        return None

    def record_tool_call_started(self, tool_name: str, *, payload=None) -> None:
        return None

    def record_tool_call_completed(self, tool_name: str, *, success: bool, payload=None, error: str = "") -> None:
        return None

    def record_state_snapshot(self, snapshot_name: str, *, payload=None, tags=None, metadata=None) -> None:
        return None


@dataclass
class _TelemetryState:
    observer: AgentObserver = NoOpObserver()
    configured_from_env: bool = False
    tracer_name: str = "rhizome"


_state = _TelemetryState()


def _parse_headers(raw: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            headers[key] = value
    return headers


def set_observer(observer: Optional[AgentObserver]) -> None:
    _state.observer = observer or NoOpObserver()


def get_observer() -> AgentObserver:
    return _state.observer


def configure_from_env() -> bool:
    """Best-effort standalone OTel setup for local Rhizome runs.

    Supported environment variables:
    - RHIZOME_OTEL_ENABLED=1
    - RHIZOME_OTEL_EXPORTER=console|otlp_http
    - RHIZOME_OTEL_ENDPOINT=http://host:4318/v1/traces
    - RHIZOME_OTEL_HEADERS=k=v,foo=bar
    - RHIZOME_OTEL_SERVICE_NAME=rhizome
    """
    if _state.configured_from_env:
        return _HAS_OTEL_API

    _state.configured_from_env = True
    _state.tracer_name = os.getenv("RHIZOME_OTEL_SERVICE_NAME", "rhizome")

    if os.getenv("RHIZOME_OTEL_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return _HAS_OTEL_API
    if not _HAS_OTEL_API:
        logger.warning("RHIZOME_OTEL_ENABLED is set but opentelemetry-api is not installed.")
        return False

    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        logger.warning("OpenTelemetry SDK is not installed; Rhizome will use the global no-op provider.")
        return False

    resource = Resource.create(
        {
            "service.name": _state.tracer_name,
            "service.version": "0.1.0",
        }
    )
    provider = TracerProvider(resource=resource)

    exporter_kind = os.getenv("RHIZOME_OTEL_EXPORTER", "console").lower()
    if exporter_kind == "otlp_http":
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:
            logger.warning("OTLP HTTP exporter requested but not installed; falling back to console exporter.")
            exporter = ConsoleSpanExporter()
        else:
            exporter = OTLPSpanExporter(
                endpoint=os.getenv("RHIZOME_OTEL_ENDPOINT"),
                headers=_parse_headers(os.getenv("RHIZOME_OTEL_HEADERS", "")),
            )
    else:
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(BatchSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
    logger.info("Rhizome OTel configured with exporter=%s", exporter_kind)
    return True


def _get_tracer():
    if not _HAS_OTEL_API:
        return None
    return trace.get_tracer(_state.tracer_name or "rhizome")


def _set_span_attributes(span: Any, attributes: Optional[Dict[str, Any]]) -> None:
    if span is None or not attributes:
        return
    for key, value in attributes.items():
        try:
            if value is not None:
                span.set_attribute(key, value)
        except Exception:
            continue


def _record_exception(span: Any, exc: BaseException) -> None:
    if span is None or not _HAS_OTEL_API:
        return
    try:
        span.record_exception(exc)
        span.set_status(StatusCode.ERROR, str(exc))
    except Exception:
        pass


@contextmanager
def start_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(name) as span:
        _set_span_attributes(span, attributes)
        try:
            yield span
        except Exception as exc:
            _record_exception(span, exc)
            raise


def add_event(name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
    if not _HAS_OTEL_API:
        return
    span = trace.get_current_span()
    if span is None:
        return
    try:
        span.add_event(name, attributes or {})
    except Exception:
        pass


def emit_message(role: str, text: str, *, payload: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
    observer = get_observer()
    observer.record_message(role, text, payload=payload, metadata=metadata)
    add_event(
        "rhizome.message",
        {
            "rhizome.message.role": role,
            "rhizome.message.length": len(text or ""),
            "rhizome.message.payload": json.dumps(payload or {}, default=str),
        },
    )


def emit_tool_started(tool_name: str, *, payload: Optional[Dict[str, Any]] = None) -> None:
    observer = get_observer()
    observer.record_tool_call_started(tool_name, payload=payload)
    add_event(
        "rhizome.tool.started",
        {
            "rhizome.tool.name": tool_name,
            "rhizome.tool.payload": json.dumps(payload or {}, default=str),
        },
    )


def emit_tool_completed(
    tool_name: str,
    *,
    success: bool,
    payload: Optional[Dict[str, Any]] = None,
    error: str = "",
) -> None:
    observer = get_observer()
    observer.record_tool_call_completed(
        tool_name,
        success=success,
        payload=payload,
        error=error,
    )
    add_event(
        "rhizome.tool.completed",
        {
            "rhizome.tool.name": tool_name,
            "rhizome.tool.success": success,
            "rhizome.tool.error": error,
            "rhizome.tool.payload": json.dumps(payload or {}, default=str),
        },
    )


def emit_state_snapshot(
    snapshot_name: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    observer = get_observer()
    observer.record_state_snapshot(
        snapshot_name,
        payload=payload,
        tags=tags,
        metadata=metadata,
    )
    add_event(
        "rhizome.state_snapshot",
        {
            "rhizome.snapshot.name": snapshot_name,
            "rhizome.snapshot.tags": ",".join(tags or []),
            "rhizome.snapshot.payload": json.dumps(payload or {}, default=str),
        },
    )
