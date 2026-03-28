# db/seed.py
from datetime import datetime
from db.database import SessionLocal, init_db
from db.models import (
    GardenProfile, Bed, Container, Plant, PlantBatch,
    GardeningProject, ProjectContainer, ProjectPlant
)

def seed():
    init_db()
    session = SessionLocal()

    # --- 1. Garden Profile ---
    existing = session.query(GardenProfile).first()
    if existing:
        profile = existing
        print("Updating existing garden profile...")
    else:
        profile = GardenProfile(user_id=1)
        session.add(profile)
        print("Creating new garden profile...")

    profile.climate_zone = "9b"
    profile.frost_date_last_spring = "January 15"
    profile.frost_date_first_fall = "November 30"
    profile.soil_type = "hard clay in ground beds"
    profile.tray_capacity = 12
    profile.tray_indoor_capacity = 8
    profile.hard_constraints = {
        "non_toxic_required": True,
        "reason": "dogs and children"
    }
    profile.soft_preferences = {
        "aesthetic": "cottage garden",
        "organic_preferred": True,
        "growing_goals": ["flowers", "vegetables"],
        "cost_conscious": True
    }
    profile.notes = """
        7000 sqft lot, ~1000 sqft active garden.
        Front: small beds, partial sun, small lawn strip.
        Courtyard: very small beds + one medium bed, mixed sun.
        Backyard: slope mostly shaded by 3 large trees.
        Two-step transplant: seed tray -> red cup water reservoir -> final location.
        Dogs have access to most of the garden.
    """
    session.commit()
    print("Garden profile seeded.")

    # --- 2. Beds ---
    existing_beds = session.query(Bed).filter(
        Bed.garden_profile_id == profile.id
    ).first()

    if not existing_beds:
        beds = [
            Bed(
                user_id=1,
                garden_profile_id=profile.id,
                name="front_bed_left",
                location="front",
                sunlight="partial sun",
                soil_type="hard clay, some amendment",
                dimensions_sqft=12.0,
                notes="Along the front of the house, left side"
            ),
            Bed(
                user_id=1,
                garden_profile_id=profile.id,
                name="front_bed_right",
                location="front",
                sunlight="partial sun",
                soil_type="hard clay, some amendment",
                dimensions_sqft=12.0,
                notes="Along the front of the house, right side"
            ),
            Bed(
                user_id=1,
                garden_profile_id=profile.id,
                name="courtyard_small_bed_1",
                location="courtyard",
                sunlight="partial sun",
                soil_type="hard clay",
                dimensions_sqft=4.0,
                notes="Very small bed in courtyard"
            ),
            Bed(
                user_id=1,
                garden_profile_id=profile.id,
                name="courtyard_small_bed_2",
                location="courtyard",
                sunlight="partial sun",
                soil_type="hard clay",
                dimensions_sqft=4.0,
                notes="Very small bed in courtyard"
            ),
            Bed(
                user_id=1,
                garden_profile_id=profile.id,
                name="courtyard_medium_bed",
                location="courtyard",
                sunlight="partial to full sun",
                soil_type="hard clay, amended",
                dimensions_sqft=25.0,
                notes="The main usable bed in the courtyard"
            ),
            Bed(
                user_id=1,
                garden_profile_id=profile.id,
                name="slope_bed_upper",
                location="backyard_slope",
                sunlight="full shade",
                soil_type="hard clay, slope",
                dimensions_sqft=30.0,
                notes="Upper slope, heavily shaded by 3 large trees"
            ),
            Bed(
                user_id=1,
                garden_profile_id=profile.id,
                name="slope_bed_lower",
                location="backyard_slope",
                sunlight="partial shade",
                soil_type="hard clay, slope",
                dimensions_sqft=30.0,
                notes="Lower slope, slightly more light than upper"
            ),
        ]
        session.add_all(beds)
        session.commit()
        print(f"Seeded {len(beds)} beds.")
    else:
        print("Beds already exist, skipping.")

    # --- 3. Containers ---
    existing_containers = session.query(Container).filter(
        Container.garden_profile_id == profile.id
    ).first()

    if not existing_containers:
        containers = [
            Container(
                user_id=1,
                garden_profile_id=profile.id,
                name="growbag_1",
                container_type="growbag",
                size_gallons=15.0,
                location="courtyard",
                is_mobile=True,
                notes="Large growbag, good for tomatoes or peppers"
            ),
            Container(
                user_id=1,
                garden_profile_id=profile.id,
                name="growbag_2",
                container_type="growbag",
                size_gallons=15.0,
                location="courtyard",
                is_mobile=True,
                notes="Large growbag, good for tomatoes or peppers"
            ),
            Container(
                user_id=1,
                garden_profile_id=profile.id,
                name="growbag_3",
                container_type="growbag",
                size_gallons=15.0,
                location="courtyard",
                is_mobile=True,
                notes="Large growbag, good for tomatoes or peppers"
            ),
            Container(
                user_id=1,
                garden_profile_id=profile.id,
                name="growbag_4",
                container_type="growbag",
                size_gallons=15.0,
                location="courtyard",
                is_mobile=True,
                notes="Large growbag, good for tomatoes or peppers"
            ),
            Container(
                user_id=1,
                garden_profile_id=profile.id,
                name="growbag_5",
                container_type="growbag",
                size_gallons=10.0,
                location="courtyard",
                is_mobile=True,
                notes="Medium growbag, good for herbs or smaller plants"
            ),
            Container(
                user_id=1,
                garden_profile_id=profile.id,
                name="growbag_6",
                container_type="growbag",
                size_gallons=10.0,
                location="courtyard",
                is_mobile=True,
                notes="Medium growbag, good for herbs or smaller plants"
            ),
            Container(
                user_id=1,
                garden_profile_id=profile.id,
                name="growbag_7",
                container_type="growbag",
                size_gallons=10.0,
                location="courtyard",
                is_mobile=True,
                notes="Medium growbag, good for herbs or smaller plants"
            ),
            Container(
                user_id=1,
                garden_profile_id=profile.id,
                name="pot_large_1",
                container_type="pot",
                size_gallons=10.0,
                location="front",
                is_mobile=True,
                notes="Large ceramic pot, front entrance"
            ),
            Container(
                user_id=1,
                garden_profile_id=profile.id,
                name="pot_large_2",
                container_type="pot",
                size_gallons=10.0,
                location="front",
                is_mobile=True,
                notes="Large ceramic pot, front entrance"
            ),
        ]
        session.add_all(containers)
        session.commit()   # commit before querying by name below
        print(f"Seeded {len(containers)} containers.")
    else:
        print("Containers already exist, skipping.")

    # --- 4. Project ---
    # this section is independent of containers — runs every time
    existing_project = session.query(GardeningProject).filter(
        GardeningProject.name == "Courtyard Tomatoes"
    ).first()

    if not existing_project:
        project = GardeningProject(
            user_id=1,
            garden_profile_id=profile.id,
            name="Courtyard Tomatoes",
            goal="Grow tomatoes from cuttings in the courtyard growbags for summer harvest",
            status="active",
            tray_slots=0,        # cuttings don't need tray slots
            budget_ceiling=50.0,
            approved_plan={
                "notes": "Cuttings from friend's heirloom plant, transplanted to growbags"
            },
            negotiation_history=[],
            iterations=[],
            notes="Tomatoes propagated from cuttings. Currently established and being staked."
        )
        session.add(project)
        session.commit()    # commit project before linking containers or plants
        print("Example project created.")

        # --- 5. Project container links ---
        growbag_1 = session.query(Container).filter(
            Container.name == "growbag_1"
        ).first()
        growbag_2 = session.query(Container).filter(
            Container.name == "growbag_2"
        ).first()

        if growbag_1:
            session.add(ProjectContainer(
                project_id=project.id,
                container_id=growbag_1.id
            ))
        if growbag_2:
            session.add(ProjectContainer(
                project_id=project.id,
                container_id=growbag_2.id
            ))
        session.commit()
        print("Project containers linked.")

        # --- 6. Plants ---
        # --- 6a. Plant batch ---
        batch = PlantBatch(
            user_id=1,
            garden_profile_id=profile.id,
            project_id=project.id,
            name="Courtyard Tomatoes March 2026",
            plant_name="Cherry Tomato",
            variety="Sungold",
            quantity_sown=2,
            source="cutting",
            sow_date=datetime(2026, 3, 1),         # cuttings don't have a sow date
            supplier="Friend's garden",
            supplier_reference="Heirloom cutting",
            grow_light=None,                        # cuttings, not seedlings
            tray=None,
            notes="Cuttings taken from friend's established heirloom plant."
        )
        session.add(batch)
        session.flush()   # get batch.id before creating plants
        print("Plant batch created.")

        # --- 6b. Plants (updated to include batch_id) ---
        plants = [
            Plant(
                user_id=1,
                garden_profile_id=profile.id,
                batch_id=batch.id,               # ← new
                name="Cherry Tomato",
                variety="Sungold",
                quantity=1,
                container_id=growbag_1.id if growbag_1 else None,
                source="cutting",
                transplant_date=datetime(2026, 3, 1),
                propagated_from="Friend's heirloom plant",
                status="established",
                is_flowering=True,
                is_fruiting=True,
                fertilizing_schedule="every 2 weeks with liquid tomato feed",
                last_fertilized_at=datetime(2026, 3, 10),
                special_instructions="Pinch out suckers weekly. Stake as it grows.",
                notes="Doing well, starting to fruit"
            ),
            Plant(
                user_id=1,
                garden_profile_id=profile.id,
                batch_id=batch.id,               # ← new
                name="Cherry Tomato",
                variety="Sungold",
                quantity=1,
                container_id=growbag_2.id if growbag_2 else None,
                source="cutting",
                transplant_date=datetime(2026, 3, 1),
                propagated_from="Friend's heirloom plant",
                status="established",
                is_flowering=True,
                is_fruiting=True,
                fertilizing_schedule="every 2 weeks with liquid tomato feed",
                last_fertilized_at=datetime(2026, 3, 10),
                special_instructions="Pinch out suckers weekly. Stake as it grows.",
                notes="Doing well, starting to fruit"
            ),
        ]
        session.add_all(plants)
        session.flush()

        # --- 6c. Project Plants ---
        session.add(ProjectPlant(project_id=project.id, plant_id=plants[0].id))
        session.add(ProjectPlant(project_id=project.id, plant_id=plants[1].id))

        session.commit()
        print(f"Seeded {len(plants)} plants.")
    else:
        print("Example project already exists, skipping.")

    session.close()
    print("Seed complete.")

if __name__ == "__main__":
    seed()