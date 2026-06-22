from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from dotenv import load_dotenv
from sqlalchemy import or_

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from db import seed as base_seed
from db.database import SessionLocal, current_user_id, init_db
from db.models import (
    Base,
    Container,
    GardenProfile,
    GardeningProject,
    IncidentReport,
    Plant,
    PlantBatch,
    ProjectBrief,
    ProjectProposal,
    ProjectRevision,
    Thread,
    TreatmentPlan,
)


FIXTURE_MARKER = "[VERDANT_DEV_FIXTURE]"
FIXTURE_THREAD_ID = "verdant-fixture-thread"


def _fixture_note(existing: str | None) -> str:
    notes = existing or ""
    if FIXTURE_MARKER in notes:
        return notes
    return f"{notes.rstrip()}\n\n{FIXTURE_MARKER}".strip()


def _ensure_fixture_thread(user_id: str) -> None:
    session = SessionLocal()
    try:
        profile = (
            session.query(GardenProfile)
            .filter(GardenProfile.user_id == user_id)
            .first()
        )
        if not profile:
            raise RuntimeError(f"No garden profile found for user_id={user_id}")

        profile.notes = _fixture_note(profile.notes)

        project = (
            session.query(GardeningProject)
            .filter(GardeningProject.user_id == user_id)
            .order_by(GardeningProject.created_at.desc())
            .first()
        )
        plant = (
            session.query(Plant)
            .filter(Plant.user_id == user_id)
            .order_by(Plant.created_at.desc())
            .first()
        )
        container = (
            session.query(Container)
            .filter(Container.user_id == user_id)
            .order_by(Container.created_at.desc())
            .first()
        )
        incident = (
            session.query(IncidentReport)
            .filter(IncidentReport.user_id == user_id)
            .order_by(IncidentReport.created_at.desc())
            .first()
        )

        pinned_context = []
        if project:
            pinned_context.append(
                {
                    "subject_type": "project",
                    "subject_id": project.id,
                    "label": project.name,
                }
            )
        if plant:
            pinned_context.append(
                {
                    "subject_type": "plant",
                    "subject_id": plant.id,
                    "label": plant.name,
                }
            )
        if container:
            pinned_context.append(
                {
                    "subject_type": "container",
                    "subject_id": container.id,
                    "label": container.name,
                }
            )
        if incident:
            pinned_context.append(
                {
                    "subject_type": "incident",
                    "subject_id": incident.id,
                    "label": incident.summary,
                }
            )

        thread = session.get(Thread, FIXTURE_THREAD_ID)
        if thread and thread.user_id != user_id:
            raise RuntimeError(
                f"Fixture thread id already belongs to another user: {thread.user_id}"
            )
        if not thread:
            thread = Thread(id=FIXTURE_THREAD_ID, user_id=user_id)
            session.add(thread)

        thread.title = "Verdant fixture thread"
        thread.project_id = project.id if project else None
        thread.last_message_preview = "Fixture data for testing Rhizome workbench context."
        thread.last_active_at = datetime.now(timezone.utc).replace(tzinfo=None)
        thread.message_count = 0
        thread.pinned_context = pinned_context
        thread.session_context = {
            "available_minutes": 45,
            "energy_level": "medium",
            "focus": "Courtyard tomatoes",
            "focus_project_id": project.id if project else None,
            "source": "verdant_dev_fixture",
        }

        session.commit()
        print(
            "Verdant fixture ready.\n"
            f"User: {user_id}\n"
            f"Profile: {profile.id}\n"
            f"Thread: {thread.id}\n"
            f"Pinned context objects: {len(pinned_context)}"
        )
    finally:
        session.close()


def seed_for_user(user_id: str) -> None:
    init_db()
    base_seed.USER_ID = user_id
    token = current_user_id.set(user_id)
    try:
        base_seed.seed()
        _ensure_fixture_thread(user_id)
    finally:
        current_user_id.reset(token)


def cleanup_for_user(user_id: str, *, force: bool = False) -> None:
    init_db()
    session = SessionLocal()
    try:
        profiles = (
            session.query(GardenProfile)
            .filter(GardenProfile.user_id == user_id)
            .all()
        )
        has_fixture_marker = any(
            FIXTURE_MARKER in (profile.notes or "") for profile in profiles
        )
        fixture_thread = session.get(Thread, FIXTURE_THREAD_ID)
        has_fixture_thread = bool(fixture_thread and fixture_thread.user_id == user_id)
        if not force and not (has_fixture_marker or has_fixture_thread):
            raise RuntimeError(
                "No Verdant fixture marker found for this user. "
                "Pass --force only if you intentionally want to delete all "
                f"Rhizome data scoped to user_id={user_id}."
            )

        profile_ids = [profile.id for profile in profiles]
        project_ids = [
            row[0]
            for row in session.query(GardeningProject.id)
            .filter(GardeningProject.user_id == user_id)
            .all()
        ]
        incident_ids = [
            row[0]
            for row in session.query(IncidentReport.id)
            .filter(IncidentReport.user_id == user_id)
            .all()
        ]
        treatment_plan_ids = (
            [
                row[0]
                for row in session.query(TreatmentPlan.id)
                .filter(TreatmentPlan.incident_id.in_(incident_ids))
                .all()
            ]
            if incident_ids
            else []
        )
        batch_ids = [
            row[0]
            for row in session.query(PlantBatch.id)
            .filter(PlantBatch.user_id == user_id)
            .all()
        ]
        brief_ids = (
            [
                row[0]
                for row in session.query(ProjectBrief.id)
                .filter(ProjectBrief.project_id.in_(project_ids))
                .all()
            ]
            if project_ids
            else []
        )
        proposal_ids = (
            [
                row[0]
                for row in session.query(ProjectProposal.id)
                .filter(ProjectProposal.project_id.in_(project_ids))
                .all()
            ]
            if project_ids
            else []
        )
        revision_ids = (
            [
                row[0]
                for row in session.query(ProjectRevision.id)
                .filter(ProjectRevision.project_id.in_(project_ids))
                .all()
            ]
            if project_ids
            else []
        )

        total_deleted = 0
        for table in reversed(Base.metadata.sorted_tables):
            conditions = []
            columns = table.c
            if "user_id" in columns:
                conditions.append(columns.user_id == user_id)
            if profile_ids and "garden_profile_id" in columns:
                conditions.append(columns.garden_profile_id.in_(profile_ids))
            if project_ids and "project_id" in columns:
                conditions.append(columns.project_id.in_(project_ids))
            if incident_ids and "incident_id" in columns:
                conditions.append(columns.incident_id.in_(incident_ids))
            if treatment_plan_ids and "treatment_plan_id" in columns:
                conditions.append(columns.treatment_plan_id.in_(treatment_plan_ids))
            if batch_ids and "batch_id" in columns:
                conditions.append(columns.batch_id.in_(batch_ids))
            if brief_ids and "brief_id" in columns:
                conditions.append(columns.brief_id.in_(brief_ids))
            if proposal_ids and "proposal_id" in columns:
                conditions.append(columns.proposal_id.in_(proposal_ids))
            if proposal_ids and "source_proposal_id" in columns:
                conditions.append(columns.source_proposal_id.in_(proposal_ids))
            if revision_ids and "revision_id" in columns:
                conditions.append(columns.revision_id.in_(revision_ids))
            if "thread_id" in columns:
                conditions.append(columns.thread_id == FIXTURE_THREAD_ID)
            if table.name == Thread.__tablename__:
                conditions.append(columns.id == FIXTURE_THREAD_ID)

            if not conditions:
                continue

            result = session.execute(table.delete().where(or_(*conditions)))
            total_deleted += result.rowcount or 0

        session.commit()
        print(
            f"Removed Verdant fixture data for user {user_id}. "
            f"Rows deleted: {total_deleted}"
        )
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Seed or remove Rhizome data for a Cambium-backed Verdant dev user. "
            "Use the user_id from Cambium /auth/session."
        )
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="Cambium user id to seed into Rhizome",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove fixture data for the user",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow cleanup even if the fixture marker is missing",
    )
    args = parser.parse_args()

    if args.cleanup:
        cleanup_for_user(args.user_id, force=args.force)
    else:
        seed_for_user(args.user_id)


if __name__ == "__main__":
    main()
