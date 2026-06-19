"""
Integration tests for scripts/monitor.py triage_job() and series_job().

Phase 4 of the calendula reactive monitoring workstream.
"""

from datetime import datetime, timedelta, timezone

import pytest

from db.models import MonitorAlert, MonitorRun, Task
from scripts.monitor import series_job, triage_job
from tests.support.factories import (
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
    make_task_series,
)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _setup_project(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project, revision)
    return project, revision, run


# ---------------------------------------------------------------------------
# triage_job
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_triage_job_records_monitor_run(db_session, patched_sessionlocal, monkeypatch):
    from agent.domain import triage as triage_runtime
    monkeypatch.setattr(triage_runtime, "triage_summary_model", None)

    triage_job(db_session, user_id=1)

    runs = db_session.query(MonitorRun).filter(MonitorRun.run_type == "triage").all()
    assert len(runs) == 1
    assert runs[0].status == "completed"
    assert runs[0].completed_at is not None


@pytest.mark.integration
def test_triage_job_writes_alert_when_urgent_tasks_exist(db_session, patched_sessionlocal, monkeypatch):
    from agent.domain import triage as triage_runtime
    monkeypatch.setattr(triage_runtime, "triage_summary_model", None)

    project, revision, run = _setup_project(db_session)
    now = _now()
    # type='emergency' + generator_key starting with 'weather.' → _triage_section_for_task returns 'Urgent'
    make_task(
        db_session, project, revision, run,
        title="Protect seedlings from frost",
        type="emergency",
        generator_key="weather.frost.protect",
        deadline=now + timedelta(hours=20),
        window_end=now + timedelta(hours=20),
    )

    triage_job(db_session, user_id=1)

    alerts = db_session.query(MonitorAlert).filter(MonitorAlert.alert_type == "triage").all()
    assert len(alerts) == 1
    assert alerts[0].severity == "high"
    assert alerts[0].user_id == 1
    assert "urgent" in alerts[0].title.lower()
    assert alerts[0].source_type == "triage_snapshot"


@pytest.mark.integration
def test_triage_job_writes_no_alert_when_no_urgent_tasks(db_session, patched_sessionlocal, monkeypatch):
    from agent.domain import triage as triage_runtime
    monkeypatch.setattr(triage_runtime, "triage_summary_model", None)

    # No tasks in DB → no urgent tasks → no alert
    triage_job(db_session, user_id=1)

    alerts = db_session.query(MonitorAlert).filter(MonitorAlert.alert_type == "triage").all()
    assert len(alerts) == 0


@pytest.mark.integration
def test_triage_job_summary_includes_counts(db_session, patched_sessionlocal, monkeypatch):
    from agent.domain import triage as triage_runtime
    monkeypatch.setattr(triage_runtime, "triage_summary_model", None)

    summary = triage_job(db_session, user_id=1)

    assert "Urgent:" in summary
    assert "routine:" in summary
    assert "project:" in summary


# ---------------------------------------------------------------------------
# series_job
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_series_job_records_monitor_run(db_session, patched_sessionlocal):
    series_job(db_session, user_id=1)

    runs = db_session.query(MonitorRun).filter(MonitorRun.run_type == "series_materialization").all()
    assert len(runs) == 1
    assert runs[0].status == "completed"
    assert runs[0].completed_at is not None


@pytest.mark.integration
def test_series_job_materializes_due_series(db_session, patched_sessionlocal):
    project, revision, run = _setup_project(db_session)
    now = _now()

    # Series whose next_generation_date is today → within 14-day horizon
    make_task_series(
        db_session, project, revision, run,
        next_generation_date=now,
        cadence_days=2,
        active=True,
    )

    series_job(db_session, user_id=1)

    tasks = db_session.query(Task).filter(Task.series_id.isnot(None)).all()
    assert len(tasks) > 0


@pytest.mark.integration
def test_series_job_does_not_materialize_future_series(db_session, patched_sessionlocal):
    project, revision, run = _setup_project(db_session)
    now = _now()

    # Series whose next_generation_date is 30 days away → outside 14-day horizon
    make_task_series(
        db_session, project, revision, run,
        next_generation_date=now + timedelta(days=30),
        cadence_days=7,
        active=True,
    )

    series_job(db_session, user_id=1)

    tasks = db_session.query(Task).filter(Task.series_id.isnot(None)).all()
    assert len(tasks) == 0


@pytest.mark.integration
def test_series_job_skips_inactive_series(db_session, patched_sessionlocal):
    project, revision, run = _setup_project(db_session)
    now = _now()

    make_task_series(
        db_session, project, revision, run,
        next_generation_date=now,
        active=False,  # inactive — should not materialize
    )

    series_job(db_session, user_id=1)

    tasks = db_session.query(Task).filter(Task.series_id.isnot(None)).all()
    assert len(tasks) == 0


@pytest.mark.integration
def test_series_job_summary_reports_task_count(db_session, patched_sessionlocal):
    project, revision, run = _setup_project(db_session)
    now = _now()

    make_task_series(db_session, project, revision, run, next_generation_date=now)

    summary = series_job(db_session, user_id=1)

    assert "Materialized" in summary
    assert "recurring task" in summary
