"""
Tests for agent/domain/notifications.py (#130):
  - per-user queue lifecycle (create / reuse / remove)
  - push_event best-effort delivery (no-op when no active queue)
  - active_jobs registry tracking via job_started/job_step/job_complete/job_failed
  - make_event_sink binding
"""

import pytest

from agent.domain import notifications


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test gets a clean module-level registry — state is process-global."""
    notifications._user_queues.clear()
    notifications._active_jobs.clear()
    yield
    notifications._user_queues.clear()
    notifications._active_jobs.clear()


# ---------------------------------------------------------------------------
# Queue lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_or_create_user_queue_creates_once():
    q1 = notifications.get_or_create_user_queue("u1")
    q2 = notifications.get_or_create_user_queue("u1")
    assert q1 is q2


@pytest.mark.unit
def test_get_or_create_user_queue_distinct_per_user():
    q1 = notifications.get_or_create_user_queue("u1")
    q2 = notifications.get_or_create_user_queue("u2")
    assert q1 is not q2


@pytest.mark.unit
def test_has_active_queue_reflects_state():
    assert notifications.has_active_queue("u1") is False
    notifications.get_or_create_user_queue("u1")
    assert notifications.has_active_queue("u1") is True
    notifications.remove_user_queue("u1")
    assert notifications.has_active_queue("u1") is False


@pytest.mark.unit
def test_remove_user_queue_is_idempotent():
    notifications.remove_user_queue("never-existed")  # should not raise


# ---------------------------------------------------------------------------
# push_event — best-effort delivery
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_push_event_noop_when_no_active_queue():
    # Should not raise even though no queue exists for this user
    notifications.push_event("ghost-user", {"type": "heartbeat"})


@pytest.mark.unit
def test_push_event_delivers_to_active_queue():
    queue = notifications.get_or_create_user_queue("u1")
    notifications.push_event("u1", {"type": "alert", "payload": {"id": "a1"}})
    event = queue.get_nowait()
    assert event == {"type": "alert", "payload": {"id": "a1"}}


@pytest.mark.unit
def test_push_event_does_not_cross_deliver_between_users():
    q1 = notifications.get_or_create_user_queue("u1")
    notifications.get_or_create_user_queue("u2")
    notifications.push_event("u1", {"type": "heartbeat"})
    assert q1.qsize() == 1
    q2 = notifications.get_or_create_user_queue("u2")
    assert q2.qsize() == 0


# ---------------------------------------------------------------------------
# active_jobs registry
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_job_started_registers_job():
    notifications.push_event("u1", {"type": "job_started", "job_id": "job-1", "title": "Daily triage"})
    jobs = notifications.get_active_jobs("u1")
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "job-1"
    assert jobs[0]["title"] == "Daily triage"
    assert jobs[0]["steps"] == []


@pytest.mark.unit
def test_job_step_appends_to_job_steps():
    notifications.push_event("u1", {"type": "job_started", "job_id": "job-1", "title": "Daily triage"})
    notifications.push_event("u1", {"type": "job_step", "job_id": "job-1", "step": "Scoring tasks", "status": "running"})
    notifications.push_event("u1", {"type": "job_step", "job_id": "job-1", "step": "Scoring tasks", "status": "done"})
    jobs = notifications.get_active_jobs("u1")
    assert jobs[0]["steps"] == [
        {"step": "Scoring tasks", "status": "running"},
        {"step": "Scoring tasks", "status": "done"},
    ]


@pytest.mark.unit
def test_job_step_for_unknown_job_is_ignored():
    # No job_started first — should not raise or create a phantom entry
    notifications.push_event("u1", {"type": "job_step", "job_id": "ghost-job", "step": "x", "status": "running"})
    assert notifications.get_active_jobs("u1") == []


@pytest.mark.unit
def test_job_complete_removes_job_from_registry():
    notifications.push_event("u1", {"type": "job_started", "job_id": "job-1", "title": "Daily triage"})
    notifications.push_event("u1", {"type": "job_complete", "job_id": "job-1", "title": "Daily triage", "summary": "done"})
    assert notifications.get_active_jobs("u1") == []


@pytest.mark.unit
def test_job_failed_removes_job_from_registry():
    notifications.push_event("u1", {"type": "job_started", "job_id": "job-1", "title": "Daily triage"})
    notifications.push_event("u1", {"type": "job_failed", "job_id": "job-1", "title": "Daily triage", "error": "boom"})
    assert notifications.get_active_jobs("u1") == []


@pytest.mark.unit
def test_active_jobs_isolated_per_user():
    notifications.push_event("u1", {"type": "job_started", "job_id": "job-1", "title": "Job A"})
    notifications.push_event("u2", {"type": "job_started", "job_id": "job-2", "title": "Job B"})
    assert len(notifications.get_active_jobs("u1")) == 1
    assert len(notifications.get_active_jobs("u2")) == 1
    assert notifications.get_active_jobs("u1")[0]["job_id"] == "job-1"


@pytest.mark.unit
def test_get_active_jobs_empty_for_unknown_user():
    assert notifications.get_active_jobs("never-seen") == []


@pytest.mark.unit
def test_active_jobs_tracking_works_without_active_queue():
    # push_event should update the registry even when no SSE connection exists
    notifications.push_event("u1", {"type": "job_started", "job_id": "job-1", "title": "Daily triage"})
    assert notifications.has_active_queue("u1") is False
    assert len(notifications.get_active_jobs("u1")) == 1


# ---------------------------------------------------------------------------
# make_event_sink
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_make_event_sink_binds_user_id():
    queue = notifications.get_or_create_user_queue("u1")
    sink = notifications.make_event_sink("u1")
    sink({"type": "heartbeat"})
    assert queue.get_nowait() == {"type": "heartbeat"}
