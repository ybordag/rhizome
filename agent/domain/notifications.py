"""
Per-process notification event bus (#130).

A per-user asyncio.Queue acts as the event bus for the SSE stream
(GET /internal/data/notifications/stream). Background jobs and write paths
push events into a user's queue via push_event() — a no-op if the user has
no active SSE connection in this process (e.g. cron-triggered jobs running
in a separate process, or no client currently connected).

push_event() also maintains an in-memory active_jobs registry so the sync
endpoint (GET /internal/data/notifications) can report in-flight job
progress to a client that reconnects or polls instead of streaming.

All state here is process-local. A cron-triggered job running in a separate
OS process (scripts/monitor.py) cannot reach into a live web server's queue —
its alerts and interactions still land in the DB and are picked up by the
next sync poll or session_context_intake; only the SSE push is best-effort.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

_user_queues: dict[str, "asyncio.Queue[dict]"] = {}
_active_jobs: dict[str, dict[str, dict]] = {}

EventSink = Optional[Callable[[dict[str, Any]], None]]


def get_or_create_user_queue(user_id: str) -> "asyncio.Queue[dict]":
    queue = _user_queues.get(user_id)
    if queue is None:
        queue = asyncio.Queue()
        _user_queues[user_id] = queue
    return queue


def remove_user_queue(user_id: str) -> None:
    _user_queues.pop(user_id, None)


def has_active_queue(user_id: str) -> bool:
    return user_id in _user_queues


def push_event(user_id: str, event: dict[str, Any]) -> None:
    """Best-effort push: no-op if the user has no active queue in this process."""
    etype = event.get("type")
    if etype == "job_started":
        jobs = _active_jobs.setdefault(user_id, {})
        jobs[event["job_id"]] = {"job_id": event["job_id"], "title": event.get("title"), "steps": []}
    elif etype == "job_step":
        job = _active_jobs.get(user_id, {}).get(event["job_id"])
        if job is not None:
            job["steps"].append({"step": event["step"], "status": event["status"]})
    elif etype in ("job_complete", "job_failed"):
        _active_jobs.get(user_id, {}).pop(event["job_id"], None)

    queue = _user_queues.get(user_id)
    if queue is not None:
        queue.put_nowait(event)


def get_active_jobs(user_id: str) -> list[dict]:
    return list(_active_jobs.get(user_id, {}).values())


def make_event_sink(user_id: str) -> Callable[[dict[str, Any]], None]:
    """Returns a callable bound to user_id for passing as a job's event_sink."""
    return lambda event: push_event(user_id, event)
