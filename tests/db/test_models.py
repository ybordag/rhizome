from datetime import datetime

import pytest

from db.models import Bed, Container, GardenProfile, GardeningProject, Plant, PlantBatch


@pytest.mark.unit
def test_garden_profile_rendering_is_multiline_and_readable():
    profile = GardenProfile(
        user_id=1,
        climate_zone="9b",
        frost_date_last_spring="January 15",
        frost_date_first_fall="November 30",
        soil_type="hard clay",
        tray_capacity=10,
        tray_indoor_capacity=6,
        notes="Spring amendments added.",
        created_at=datetime(2026, 1, 5),
        updated_at=datetime(2026, 1, 7),
    )

    summary = profile.to_summary()
    detailed = profile.to_detailed()

    assert summary.startswith("[Garden] Zone 9b")
    assert "\n  Soil: hard clay" in summary
    assert "\n  Trays: 6 indoor, 10 total" in summary
    assert "\n  Created at: January 05, 2026" in summary
    assert "\n  Updated at: January 07, 2026" in detailed
    assert "\n  Log:\nSpring amendments added." in detailed


@pytest.mark.unit
def test_project_rendering_separates_goal_timestamps_and_notes():
    project = GardeningProject(
        user_id=1,
        garden_profile_id="profile-1",
        name="Tomato Sprint",
        goal="Grow sauce tomatoes.",
        status="active",
        tray_slots=8,
        budget_ceiling=120.0,
        approved_plan={"notes": "Plant after last frost."},
        notes="Monitor aphids.",
        created_at=datetime(2026, 2, 1),
        updated_at=datetime(2026, 2, 10),
    )

    summary = project.to_summary(plant_count=4, bed_count=1, container_count=2, batch_count=1)
    detailed = project.to_detailed(plant_count=4, bed_count=1, container_count=2, batch_count=1)

    assert "\n  Goal: Grow sauce tomatoes." in summary
    assert "\n  Created at: February 01, 2026" in summary
    assert "\n  Budget: $120.0 | Tray slots: 8" in detailed
    assert "\n  Plan: Plant after last frost." in detailed
    assert "\n  Updated at: February 10, 2026" in detailed
    assert "\n  Notes: Monitor aphids." in detailed


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "expected_bits"),
    [
        (
            Bed(
                user_id=1,
                garden_profile_id="profile-1",
                name="Slope Bed",
                location="backyard_slope",
                sunlight="part sun",
                soil_type="loam",
                dimensions_sqft=12.0,
                notes="Needs edging.",
                created_at=datetime(2026, 2, 2),
                updated_at=datetime(2026, 2, 4),
            ),
            [
                "[Bed] Slope Bed",
                "\n  Location: backyard_slope | Sunlight: part sun",
                "\n  Size: 12.0 sqft | Soil: loam",
                "\n  Updated at: February 04, 2026",
                "\n  Notes: Needs edging.",
            ],
        ),
        (
            Container(
                user_id=1,
                garden_profile_id="profile-1",
                name="Blue Pot",
                container_type="pot",
                size_gallons=7.0,
                location="front",
                is_mobile=False,
                notes="Ceramic.",
                created_at=datetime(2026, 2, 3),
                updated_at=datetime(2026, 2, 5),
            ),
            [
                "[Container] Blue Pot",
                "\n  Type: pot | Size: 7.0 gal | Location: front",
                "\n  Mobile: False",
                "\n  Updated at: February 05, 2026",
                "\n  Notes: Ceramic.",
            ],
        ),
    ],
)
def test_bed_and_container_rendering_are_stable(model, expected_bits):
    detailed = model.to_detailed()

    for bit in expected_bits:
        assert bit in detailed


@pytest.mark.unit
def test_plant_rendering_includes_location_dates_and_notes():
    plant = Plant(
        user_id=1,
        garden_profile_id="profile-1",
        batch_id="batch-1",
        name="Tomato",
        variety="Sungold",
        quantity=1,
        source="seed",
        status="producing",
        sow_date=datetime(2026, 1, 10),
        red_cup_date=datetime(2026, 1, 24),
        transplant_date=datetime(2026, 2, 20),
        is_flowering=True,
        is_fruiting=True,
        fertilizing_schedule="weekly",
        last_fertilized_at=datetime(2026, 3, 1),
        special_instructions="Prune lower leaves.",
        notes="Doing well.",
        created_at=datetime(2026, 1, 10),
        updated_at=datetime(2026, 3, 2),
    )

    summary = plant.to_summary(location_name="Front Growbag")
    detailed = plant.to_detailed(location_name="Front Growbag")

    assert "Status: producing | flowering, fruiting" in summary
    assert "Location: Front Growbag | Source: seed" in summary
    assert "\n  Batch: batch-1" in detailed
    assert "Sow: January 10, 2026 | Red cup: January 24, 2026 | Transplant: February 20, 2026" in detailed
    assert "\n  Instructions: Prune lower leaves." in detailed
    assert "\n  Notes: Doing well." in detailed
    assert "\n  Updated: March 02, 2026" in detailed


@pytest.mark.unit
def test_batch_rendering_uses_readable_defaults():
    batch = PlantBatch(
        user_id=1,
        garden_profile_id="profile-1",
        name="Cosmos Spring 2026",
        plant_name="Cosmos",
        variety=None,
        quantity_sown=8,
        source="seed",
        sow_date=None,
        supplier=None,
        supplier_reference=None,
        grow_light=None,
        tray=None,
        notes=None,
        created_at=datetime(2026, 2, 1),
        updated_at=datetime(2026, 2, 6),
    )

    detailed = batch.to_detailed()

    assert "Quantity sown: 8 on unknown" in detailed
    assert "Supplier: not recorded | Ref: none" in detailed
    assert "Light: not recorded | Tray: not recorded" in detailed
    assert "\n  Updated at: February 06, 2026" in detailed
    assert "\n  Log:\n  none" in detailed
