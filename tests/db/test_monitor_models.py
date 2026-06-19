"""Tests for MonitorRun and MonitorAlert models (Phase 1 — calendula)."""

from datetime import datetime, timedelta, timezone

import pytest

from db.models import MonitorAlert, MonitorRun


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _expires(hours=24):
    return _now() + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# MonitorRun
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_monitor_run_starts_with_started_status(db_session):
    run = MonitorRun(run_type="weather", user_id=1)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    assert run.id is not None
    assert run.status == "started"
    assert run.created_at is not None
    assert run.completed_at is None
    assert run.error is None


@pytest.mark.integration
def test_monitor_run_can_be_marked_completed(db_session):
    run = MonitorRun(run_type="triage", user_id=1)
    db_session.add(run)
    db_session.commit()

    run.status = "completed"
    run.completed_at = _now()
    run.summary = "Built triage snapshot, 3 urgent tasks."
    db_session.commit()
    db_session.refresh(run)

    assert run.status == "completed"
    assert run.completed_at is not None
    assert "urgent" in run.summary


@pytest.mark.integration
def test_monitor_run_can_be_marked_failed(db_session):
    run = MonitorRun(run_type="series_materialization", user_id=1)
    db_session.add(run)
    db_session.commit()

    run.status = "failed"
    run.completed_at = _now()
    run.error = "Open-Meteo connection timeout"
    db_session.commit()
    db_session.refresh(run)

    assert run.status == "failed"
    assert "timeout" in run.error


@pytest.mark.integration
def test_monitor_run_all_run_types_are_storable(db_session):
    for run_type in ("weather", "triage", "series_materialization"):
        run = MonitorRun(run_type=run_type, user_id=1)
        db_session.add(run)
    db_session.commit()

    rows = db_session.query(MonitorRun).all()
    stored_types = {r.run_type for r in rows}
    assert stored_types == {"weather", "triage", "series_materialization"}


@pytest.mark.integration
def test_monitor_run_user_id_is_nullable(db_session):
    run = MonitorRun(run_type="weather", user_id=None)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    assert run.user_id is None


# ---------------------------------------------------------------------------
# MonitorAlert
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_monitor_alert_defaults_to_pending(db_session):
    alert = MonitorAlert(
        expires_at=_expires(24),
        user_id=1,
        alert_type="weather_critical",
        severity="critical",
        title="Frost warning tonight",
        body="Sub-zero temperatures expected. Outdoor tasks deferred.",
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)

    assert alert.id is not None
    assert alert.status == "pending"
    assert alert.created_at is not None
    assert alert.dismissed_at is None


@pytest.mark.integration
def test_monitor_alert_can_be_dismissed(db_session):
    alert = MonitorAlert(
        expires_at=_expires(24),
        user_id=1,
        alert_type="weather_advisory",
        severity="medium",
        title="Rain expected this afternoon",
        body="Consider rescheduling outdoor work.",
    )
    db_session.add(alert)
    db_session.commit()

    alert.status = "dismissed"
    alert.dismissed_at = _now()
    db_session.commit()
    db_session.refresh(alert)

    assert alert.status == "dismissed"
    assert alert.dismissed_at is not None


@pytest.mark.integration
def test_monitor_alert_all_alert_types_are_storable(db_session):
    for alert_type in ("weather_critical", "weather_advisory", "working_window", "triage", "pest"):
        db_session.add(MonitorAlert(
            expires_at=_expires(24),
            user_id=1,
            alert_type=alert_type,
            severity="medium",
            title=f"Test {alert_type}",
            body="Test body.",
        ))
    db_session.commit()

    rows = db_session.query(MonitorAlert).all()
    stored_types = {r.alert_type for r in rows}
    assert stored_types == {"weather_critical", "weather_advisory", "working_window", "triage", "pest"}


@pytest.mark.integration
def test_monitor_alert_all_severity_levels_are_storable(db_session):
    for severity in ("critical", "high", "medium", "low"):
        db_session.add(MonitorAlert(
            expires_at=_expires(24),
            user_id=1,
            alert_type="triage",
            severity=severity,
            title=f"{severity} alert",
            body="Body.",
        ))
    db_session.commit()

    rows = db_session.query(MonitorAlert).all()
    stored_severities = {r.severity for r in rows}
    assert stored_severities == {"critical", "high", "medium", "low"}


@pytest.mark.integration
def test_monitor_alert_source_fields_are_optional(db_session):
    alert = MonitorAlert(
        expires_at=_expires(48),
        user_id=1,
        alert_type="weather_critical",
        severity="critical",
        title="Storm incoming",
        body="All outdoor tasks deferred automatically.",
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)

    assert alert.source_type is None
    assert alert.source_id is None
    assert alert.alert_metadata is None


@pytest.mark.integration
def test_monitor_alert_stores_source_and_metadata(db_session):
    alert = MonitorAlert(
        expires_at=_expires(48),
        user_id=1,
        alert_type="weather_critical",
        severity="critical",
        title="Frost warning",
        body="Tasks deferred.",
        source_type="weather_snapshot",
        source_id="snap-abc123",
        alert_metadata={"impact_types": ["frost"], "tasks_affected": 3},
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)

    assert alert.source_type == "weather_snapshot"
    assert alert.source_id == "snap-abc123"
    assert alert.alert_metadata["tasks_affected"] == 3


@pytest.mark.integration
def test_monitor_alert_pending_query_filters_by_user_and_status(db_session):
    now = _now()
    future = now + timedelta(hours=24)
    past = now - timedelta(hours=1)

    # user 1 — pending, not expired → should appear
    db_session.add(MonitorAlert(
        expires_at=future, user_id=1, alert_type="triage",
        severity="high", title="Active alert", body=".",
    ))
    # user 1 — dismissed → should not appear
    alert_dismissed = MonitorAlert(
        expires_at=future, user_id=1, alert_type="triage",
        severity="high", title="Dismissed alert", body=".",
        status="dismissed", dismissed_at=now,
    )
    db_session.add(alert_dismissed)
    # user 1 — expired → should not appear
    db_session.add(MonitorAlert(
        expires_at=past, user_id=1, alert_type="triage",
        severity="high", title="Expired alert", body=".",
    ))
    # user 2 — pending → should not appear for user 1 query
    db_session.add(MonitorAlert(
        expires_at=future, user_id=2, alert_type="triage",
        severity="high", title="Other user alert", body=".",
    ))
    db_session.commit()

    active = (
        db_session.query(MonitorAlert)
        .filter(
            MonitorAlert.user_id == 1,
            MonitorAlert.status == "pending",
            MonitorAlert.expires_at > now,
        )
        .all()
    )

    assert len(active) == 1
    assert active[0].title == "Active alert"


@pytest.mark.integration
def test_monitor_alert_critical_ttl_is_longer_than_advisory(db_session):
    now = _now()
    critical = MonitorAlert(
        expires_at=now + timedelta(hours=48),
        user_id=1, alert_type="weather_critical", severity="critical",
        title="Storm", body=".",
    )
    advisory = MonitorAlert(
        expires_at=now + timedelta(hours=24),
        user_id=1, alert_type="weather_advisory", severity="medium",
        title="Light rain", body=".",
    )
    db_session.add_all([critical, advisory])
    db_session.commit()

    rows = db_session.query(MonitorAlert).order_by(MonitorAlert.expires_at.desc()).all()
    assert rows[0].alert_type == "weather_critical"
    assert rows[1].alert_type == "weather_advisory"
