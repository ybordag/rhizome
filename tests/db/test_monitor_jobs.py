"""
Integration tests for scripts/monitor.py triage_job() and series_job().

Phase 4 of the calendula reactive monitoring workstream.
"""

from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest

from db.models import MonitorAlert, MonitorRun, Task
from scripts.monitor import series_job, triage_job, weather_job
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
    assert alerts[0].user_id == "1"
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
# triage_job — event_sink instrumentation (#130)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_triage_job_works_unchanged_without_event_sink(db_session, patched_sessionlocal, monkeypatch):
    """Jobs must behave identically when no sink is provided — the default."""
    from agent.domain import triage as triage_runtime
    monkeypatch.setattr(triage_runtime, "triage_summary_model", None)

    summary = triage_job(db_session, user_id=1)  # event_sink defaults to None

    assert "Urgent:" in summary
    runs = db_session.query(MonitorRun).filter(MonitorRun.run_type == "triage").all()
    assert runs[0].status == "completed"


@pytest.mark.integration
def test_triage_job_emits_job_started_and_complete(db_session, patched_sessionlocal, monkeypatch):
    from agent.domain import triage as triage_runtime
    monkeypatch.setattr(triage_runtime, "triage_summary_model", None)

    events = []
    triage_job(db_session, user_id=1, event_sink=events.append)

    types = [e["type"] for e in events]
    assert types[0] == "job_started"
    assert types[-1] == "job_complete"
    assert all(e["job_id"] == events[0]["job_id"] for e in events)
    assert events[0]["title"] == "Daily triage"


@pytest.mark.integration
def test_triage_job_emits_all_four_steps(db_session, patched_sessionlocal, monkeypatch):
    from agent.domain import triage as triage_runtime
    monkeypatch.setattr(triage_runtime, "triage_summary_model", None)

    events = []
    triage_job(db_session, user_id=1, event_sink=events.append)

    steps = [e["step"] for e in events if e["type"] == "job_step" and e["status"] == "running"]
    assert steps == [
        "Loading garden state",
        "Checking weather impacts",
        "Scoring tasks",
        "Generating recommendations",
    ]
    done_steps = [e["step"] for e in events if e["type"] == "job_step" and e["status"] == "done"]
    assert done_steps == steps  # every running step has a matching done


@pytest.mark.integration
def test_triage_job_emits_job_failed_on_error(db_session, patched_sessionlocal, monkeypatch):
    from agent.domain import triage as triage_runtime
    monkeypatch.setattr(triage_runtime, "build_triage_snapshot", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    events = []
    with pytest.raises(RuntimeError):
        triage_job(db_session, user_id=1, event_sink=events.append)

    types = [e["type"] for e in events]
    assert types[-1] == "job_failed"
    assert events[-1]["error"] == "boom"


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


@pytest.mark.integration
def test_series_job_writes_alert_when_tasks_materialized(db_session, patched_sessionlocal):
    project, revision, run = _setup_project(db_session)
    now = _now()

    make_task_series(db_session, project, revision, run, next_generation_date=now)

    series_job(db_session, user_id=1)

    alerts = db_session.query(MonitorAlert).filter(MonitorAlert.alert_type == "series").all()
    assert len(alerts) == 1
    assert alerts[0].severity == "low"
    assert alerts[0].user_id == "1"
    assert "materialized" in alerts[0].title.lower()
    assert alerts[0].source_type == "monitor_run"


@pytest.mark.integration
def test_series_job_writes_no_alert_when_nothing_materialized(db_session, patched_sessionlocal):
    # No task series in DB → nothing materialized → no alert
    series_job(db_session, user_id=1)

    alerts = db_session.query(MonitorAlert).filter(MonitorAlert.alert_type == "series").all()
    assert len(alerts) == 0


# ---------------------------------------------------------------------------
# series_job — event_sink instrumentation (#130)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_series_job_works_unchanged_without_event_sink(db_session, patched_sessionlocal):
    summary = series_job(db_session, user_id=1)  # event_sink defaults to None
    assert "Materialized" in summary


@pytest.mark.integration
def test_series_job_emits_started_step_and_complete(db_session, patched_sessionlocal):
    events = []
    series_job(db_session, user_id=1, event_sink=events.append)

    types = [e["type"] for e in events]
    assert types == ["job_started", "job_step", "job_step", "job_complete"]
    assert events[0]["title"] == "Recurring task materialization"
    assert events[1] == {
        "type": "job_step", "job_id": events[0]["job_id"],
        "step": "Materialising recurring tasks", "status": "running",
    }
    assert events[2]["status"] == "done"
    assert all(e["job_id"] == events[0]["job_id"] for e in events)


@pytest.mark.integration
def test_series_job_emits_job_failed_on_error(db_session, patched_sessionlocal, monkeypatch):
    monkeypatch.setattr(
        "agent.domain.tracker.materialize_task_series",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    events = []
    with pytest.raises(RuntimeError):
        series_job(db_session, user_id=1, event_sink=events.append)

    assert events[-1]["type"] == "job_failed"
    assert events[-1]["error"] == "boom"


# ---------------------------------------------------------------------------
# weather_job — event_sink instrumentation (#130)
# ---------------------------------------------------------------------------

class _FakeMeteoResponse:
    """Stands in for the urlopen() context manager — avoids a real network call."""

    def __init__(self, payload: dict):
        import json
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


@pytest.fixture
def fake_open_meteo(monkeypatch):
    payload = {
        "daily": {
            "time": ["2026-06-20", "2026-06-21"],
            "temperature_2m_max": [75.0, 76.0],
            "temperature_2m_min": [55.0, 56.0],
            "precipitation_sum": [0.0, 0.0],
            "wind_speed_10m_max": [5.0, 6.0],
        }
    }
    monkeypatch.setattr("agent.domain.weather.urlopen", lambda url, timeout=10: _FakeMeteoResponse(payload))
    return payload


@pytest.mark.integration
def test_weather_job_works_unchanged_without_event_sink(db_session, patched_sessionlocal, fake_open_meteo):
    make_profile(db_session)
    summary = weather_job(db_session, user_id=1)  # event_sink defaults to None
    assert "Snapshot refreshed" in summary


@pytest.mark.integration
def test_weather_job_emits_job_started_and_complete(db_session, patched_sessionlocal, fake_open_meteo):
    make_profile(db_session)
    events = []
    weather_job(db_session, user_id=1, event_sink=events.append)

    types = [e["type"] for e in events]
    assert types[0] == "job_started"
    assert types[-1] == "job_complete"
    assert events[0]["title"] == "Weather refresh"
    assert all(e["job_id"] == events[0]["job_id"] for e in events)


@pytest.mark.integration
def test_weather_job_emits_all_three_steps(db_session, patched_sessionlocal, fake_open_meteo):
    make_profile(db_session)
    events = []
    weather_job(db_session, user_id=1, event_sink=events.append)

    running_steps = [e["step"] for e in events if e["type"] == "job_step" and e["status"] == "running"]
    assert running_steps == ["Fetching forecast", "Deriving impacts", "Identifying affected tasks"]
    done_steps = [e["step"] for e in events if e["type"] == "job_step" and e["status"] == "done"]
    assert done_steps == running_steps


@pytest.mark.integration
def test_weather_job_no_profile_completes_without_steps(db_session, patched_sessionlocal, fake_open_meteo):
    # No GardenProfile -> load_or_refresh_weather_snapshot returns None before
    # any fetch/derive step runs; job_complete still fires with that summary.
    events = []
    summary = weather_job(db_session, user_id=1, event_sink=events.append)

    assert "No weather snapshot available" in summary
    assert events[0]["type"] == "job_started"
    assert events[-1]["type"] == "job_complete"
    assert not any(e["type"] == "job_step" for e in events)


@pytest.mark.integration
def test_weather_job_emits_job_failed_on_error(db_session, patched_sessionlocal, monkeypatch, fake_open_meteo):
    make_profile(db_session)
    monkeypatch.setattr(
        "agent.domain.weather.apply_weather_impacts",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    events = []
    with pytest.raises(RuntimeError):
        weather_job(db_session, user_id=1, event_sink=events.append)

    assert events[-1]["type"] == "job_failed"
    assert events[-1]["error"] == "boom"


# ---------------------------------------------------------------------------
# Cron-layer multi-user isolation (different users have different garden
# locations, so weather/triage data must not collide between them)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_weather_job_isolates_snapshots_between_users(db_session, patched_sessionlocal, fake_open_meteo):
    from db.models import WeatherSnapshot

    profile_a = make_profile(db_session, user_id="owner-a", location_label="Phoenix, AZ")
    profile_b = make_profile(db_session, user_id="owner-b", location_label="Duluth, MN")

    weather_job(db_session, user_id="owner-a")
    weather_job(db_session, user_id="owner-b")

    snapshot_a = db_session.query(WeatherSnapshot).filter(WeatherSnapshot.garden_profile_id == profile_a.id).one()
    snapshot_b = db_session.query(WeatherSnapshot).filter(WeatherSnapshot.garden_profile_id == profile_b.id).one()

    assert snapshot_a.id != snapshot_b.id
    assert snapshot_a.location_label == "Phoenix, AZ"
    assert snapshot_b.location_label == "Duluth, MN"


@pytest.mark.integration
def test_triage_job_isolates_snapshots_between_users(db_session, patched_sessionlocal, monkeypatch):
    from agent.domain import triage as triage_runtime
    from db.models import TriageSnapshot
    monkeypatch.setattr(triage_runtime, "triage_summary_model", None)

    profile_a = make_profile(db_session, user_id="owner-a")
    profile_b = make_profile(db_session, user_id="owner-b")

    triage_job(db_session, user_id="owner-a")
    triage_job(db_session, user_id="owner-b")

    snapshot_a = db_session.query(TriageSnapshot).filter(TriageSnapshot.garden_profile_id == profile_a.id).one()
    snapshot_b = db_session.query(TriageSnapshot).filter(TriageSnapshot.garden_profile_id == profile_b.id).one()
    assert snapshot_a.id != snapshot_b.id
