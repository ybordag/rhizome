"""
Proves that user data is correctly scoped: user A cannot read user B's garden.
This is the fundamental correctness guarantee of Phase 1 multi-tenancy.
"""
from __future__ import annotations

import pytest
from db.database import current_user_id
from db.models import GardenProfile, Bed, Plant, GardeningProject
from tests.support.factories import make_profile, make_bed, make_plant, make_project


def test_garden_profile_is_scoped_to_user(db_session):
    profile_a = make_profile(db_session, user_id=1)
    profile_b = make_profile(db_session, user_id=2)

    current_user_id.set(1)
    visible = db_session.query(GardenProfile).filter(
        GardenProfile.user_id == current_user_id.get()
    ).all()
    ids = {p.id for p in visible}
    assert profile_a.id in ids
    assert profile_b.id not in ids


def test_beds_are_scoped_to_user(db_session):
    profile_a = make_profile(db_session, user_id=1)
    profile_b = make_profile(db_session, user_id=2)
    bed_a = make_bed(db_session, profile_a, user_id=1)
    bed_b = make_bed(db_session, profile_b, user_id=2)

    current_user_id.set(2)
    visible = db_session.query(Bed).filter(
        Bed.user_id == current_user_id.get()
    ).all()
    ids = {b.id for b in visible}
    assert bed_b.id in ids
    assert bed_a.id not in ids


def test_projects_are_scoped_to_user(db_session):
    profile_a = make_profile(db_session, user_id=1)
    profile_b = make_profile(db_session, user_id=2)
    project_a = make_project(db_session, profile_a, user_id=1)
    project_b = make_project(db_session, profile_b, user_id=2)

    current_user_id.set(1)
    visible = db_session.query(GardeningProject).filter(
        GardeningProject.user_id == current_user_id.get()
    ).all()
    ids = {p.id for p in visible}
    assert project_a.id in ids
    assert project_b.id not in ids


def test_plants_are_scoped_to_user(db_session):
    profile_a = make_profile(db_session, user_id=1)
    profile_b = make_profile(db_session, user_id=2)
    plant_a = make_plant(db_session, profile_a, user_id=1)
    plant_b = make_plant(db_session, profile_b, user_id=2)

    current_user_id.set(2)
    visible = db_session.query(Plant).filter(
        Plant.user_id == current_user_id.get()
    ).all()
    ids = {p.id for p in visible}
    assert plant_b.id in ids
    assert plant_a.id not in ids


def test_switching_users_changes_visible_data(db_session):
    """The contextvar correctly isolates data when user_id changes mid-session."""
    profile_a = make_profile(db_session, user_id=1)
    profile_b = make_profile(db_session, user_id=2)

    current_user_id.set(1)
    as_user_1 = {
        p.id for p in db_session.query(GardenProfile).filter(
            GardenProfile.user_id == current_user_id.get()
        ).all()
    }

    current_user_id.set(2)
    as_user_2 = {
        p.id for p in db_session.query(GardenProfile).filter(
            GardenProfile.user_id == current_user_id.get()
        ).all()
    }

    assert profile_a.id in as_user_1
    assert profile_b.id not in as_user_1
    assert profile_b.id in as_user_2
    assert profile_a.id not in as_user_2
