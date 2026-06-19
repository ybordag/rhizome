"""
Rhizome background monitor — standalone cron runner.

Invoked by system cron (or manually) to run weather refresh, triage
snapshot generation, and recurring task series materialization without
requiring an active user session.

Usage:
    python scripts/monitor.py [--user-id ID] [--job JOB]

Arguments:
    --user-id   integer user ID to run jobs for (default: 1)
    --job       one of: weather | triage | series | all  (default: all)

Example crontab:
    0 6 * * * cd /path/to/rhizome && python scripts/monitor.py --job all
    0 0 * * * cd /path/to/rhizome && python scripts/monitor.py --job series
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path when invoked directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from datetime import timedelta

from db.database import SessionLocal
from db.models import MonitorAlert, MonitorRun


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _start_run(session, run_type: str, user_id: int) -> MonitorRun:
    run = MonitorRun(run_type=run_type, status="started", user_id=user_id)
    session.add(run)
    session.commit()
    return run


def _finish_run(session, run: MonitorRun, summary: str) -> None:
    run.status = "completed"
    run.completed_at = _now()
    run.summary = summary
    session.commit()


def _fail_run(session, run: MonitorRun, error: str) -> None:
    run.status = "failed"
    run.completed_at = _now()
    run.error = error
    session.commit()


def _write_alert(
    session,
    *,
    user_id: int,
    alert_type: str,
    severity: str,
    title: str,
    body: str,
    source_type: str = None,
    source_id: str = None,
    ttl_hours: int = 24,
) -> MonitorAlert:
    alert = MonitorAlert(
        expires_at=_now() + timedelta(hours=ttl_hours),
        user_id=user_id,
        alert_type=alert_type,
        severity=severity,
        title=title,
        body=body,
        source_type=source_type,
        source_id=source_id,
    )
    session.add(alert)
    return alert


def weather_job(session, user_id: int) -> str:
    """
    Refresh the weather snapshot if stale, then auto-apply critical impacts
    and queue advisory ones. Writes MonitorAlert records for all categories.
    Only processes impacts when a fresh snapshot was created this run.
    """
    from agent.domain.weather import (
        MONITOR_FRESHNESS_HOURS,
        apply_weather_impacts,
        get_latest_weather_snapshot,
        load_or_refresh_weather_snapshot,
    )
    from db.database import current_user_id
    current_user_id.set(user_id)

    run = _start_run(session, "weather", user_id)
    try:
        existing = get_latest_weather_snapshot(session)
        snapshot = load_or_refresh_weather_snapshot(
            session, freshness_hours=MONITOR_FRESHNESS_HOURS
        )
        if snapshot is None:
            summary = "No weather snapshot available (garden profile may be missing location)."
            print(f"  [weather] {summary}")
            _finish_run(session, run, summary)
            return summary

        is_new = existing is None or snapshot.id != existing.id
        if not is_new:
            summary = f"Snapshot {snapshot.id} is still fresh; skipping impact evaluation."
            print(f"  [weather] {summary}")
            _finish_run(session, run, summary)
            return summary

        result = apply_weather_impacts(session, snapshot=snapshot, user_id=user_id)
        session.commit()
        summary = (
            f"Snapshot refreshed. "
            f"Critical auto-applied: {result['critical_applied']}, "
            f"advisory queued: {result['advisory_queued']}, "
            f"window alerts: {result['window_alerts']}."
        )
        print(f"  [weather] {summary}")
        _finish_run(session, run, summary)
        return summary
    except Exception as exc:
        session.rollback()
        _fail_run(session, run, str(exc))
        raise


def triage_job(session, user_id: int) -> str:
    """
    Build a triage snapshot and write a MonitorAlert when urgent tasks exist.
    The alert surfaces at the next session start via session_context_intake.
    """
    from agent.core.temporal import DEFAULT_TIMEZONE
    from agent.domain.triage import build_triage_snapshot, format_triage_snapshot
    from db.database import current_user_id
    current_user_id.set(user_id)

    run = _start_run(session, "triage", user_id)
    try:
        snapshot = build_triage_snapshot(session, opener="", timezone=DEFAULT_TIMEZONE)
        session.commit()

        urgent_count = len(snapshot.urgent_task_ids or [])
        if urgent_count > 0:
            _write_alert(
                session,
                user_id=user_id,
                alert_type="triage",
                severity="high",
                title=f"{urgent_count} urgent task(s) need attention today",
                body=format_triage_snapshot(session, snapshot),
                source_type="triage_snapshot",
                source_id=snapshot.id,
                ttl_hours=20,
            )
            session.commit()

        summary = (
            f"Triage snapshot built. "
            f"Urgent: {urgent_count}, "
            f"routine: {len(snapshot.routine_task_ids or [])}, "
            f"project: {len(snapshot.project_task_ids or [])}."
        )
        print(f"  [triage] {summary}")
        _finish_run(session, run, summary)
        return summary
    except Exception as exc:
        session.rollback()
        _fail_run(session, run, str(exc))
        raise


def series_job(session, user_id: int) -> str:
    """
    Materialize any recurring task series whose next_generation_date has
    entered the rolling 14-day horizon. Idempotent: existing task dates are
    skipped by materialize_task_series().
    """
    from agent.domain.tracker import materialize_task_series
    from db.database import current_user_id
    current_user_id.set(user_id)

    run = _start_run(session, "series_materialization", user_id)
    try:
        created = materialize_task_series(session)
        session.commit()
        summary = f"Materialized {len(created)} recurring task(s) from active series."
        print(f"  [series] {summary}")
        _finish_run(session, run, summary)
        return summary
    except Exception as exc:
        session.rollback()
        _fail_run(session, run, str(exc))
        raise


_JOBS = {
    "weather": weather_job,
    "triage": triage_job,
    "series": series_job,
}


def run(user_id: int, job: str) -> None:
    jobs = list(_JOBS.items()) if job == "all" else [(job, _JOBS[job])]
    session = SessionLocal()
    try:
        for name, fn in jobs:
            print(f"[monitor] running {name} for user_id={user_id}")
            try:
                fn(session, user_id)
            except Exception as exc:
                print(f"[monitor] {name} failed: {exc}", file=sys.stderr)
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rhizome background monitor")
    parser.add_argument("--user-id", type=int, default=1, dest="user_id")
    parser.add_argument(
        "--job",
        choices=["weather", "triage", "series", "all"],
        default="all",
    )
    args = parser.parse_args()
    run(user_id=args.user_id, job=args.job)


if __name__ == "__main__":
    main()
