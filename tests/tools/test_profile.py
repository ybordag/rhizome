import pytest

from agent.tools.profile import get_garden_profile, update_garden_profile
from db.models import GardenProfile


@pytest.mark.integration
def test_get_garden_profile_returns_empty_state_when_missing(patched_sessionlocal):
    result = get_garden_profile.invoke({"detailed": False})

    assert result == "No garden profile found."


@pytest.mark.integration
def test_update_garden_profile_updates_existing_profile(db_session, patched_sessionlocal, seed_garden_profile):
    result = update_garden_profile.invoke(
        {
            "climate_zone": "10a",
            "tray_capacity": 12,
            "hard_constraints": {"no_thorns": True},
            "soft_preferences": {"cut_flowers": True},
        }
    )

    db_session.expire_all()
    updated = db_session.query(GardenProfile).filter(GardenProfile.user_id == 1).one()

    assert "Garden profile updated:" in result
    assert updated.climate_zone == "10a"
    assert updated.tray_capacity == 12
    assert updated.hard_constraints["no_thorns"] is True
    assert updated.soft_preferences["cut_flowers"] is True


@pytest.mark.integration
def test_repeated_profile_updates_modify_singleton_record(db_session, patched_sessionlocal, seed_garden_profile):
    update_garden_profile.invoke({"soil_type": "loam"})
    update_garden_profile.invoke({"notes": "Updated once."})

    db_session.expire_all()
    profiles = db_session.query(GardenProfile).filter(GardenProfile.user_id == 1).all()

    assert len(profiles) == 1
    assert profiles[0].soil_type == "loam"
    assert profiles[0].notes == "Updated once."
