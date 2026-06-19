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

from db.database import SessionLocal
from db.models import MonitorRun


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


def weather_job(session, user_id: int) -> str:
    """Placeholder — Phase 2 wires in weather refresh and alert writing."""
    run = _start_run(session, "weather", user_id)
    try:
        # Phase 2: refresh_weather_snapshot + apply_weather_impacts
        summary = "weather_job: not yet implemented (Phase 2)"
        print(f"  [weather] {summary}")
        _finish_run(session, run, summary)
        return summary
    except Exception as exc:
        _fail_run(session, run, str(exc))
        raise


def triage_job(session, user_id: int) -> str:
    """Placeholder — Phase 4 wires in triage snapshot generation."""
    run = _start_run(session, "triage", user_id)
    try:
        # Phase 4: build_triage_snapshot + MonitorAlert for urgent tasks
        summary = "triage_job: not yet implemented (Phase 4)"
        print(f"  [triage] {summary}")
        _finish_run(session, run, summary)
        return summary
    except Exception as exc:
        _fail_run(session, run, str(exc))
        raise


def series_job(session, user_id: int) -> str:
    """Placeholder — Phase 4 wires in recurring task series materialization."""
    run = _start_run(session, "series_materialization", user_id)
    try:
        # Phase 4: list_materializable_series + materialize_task_series
        summary = "series_job: not yet implemented (Phase 4)"
        print(f"  [series] {summary}")
        _finish_run(session, run, summary)
        return summary
    except Exception as exc:
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
