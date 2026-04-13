# agent/tools/profile.py
"""
Agent tools for updating the garden profile.
Tools must return strings — the LLM reads tool output as text.
"""

from langchain.tools import tool
from db.database import SessionLocal
from db.models import GardenProfile
from typing import Optional, List


@tool
def get_garden_profile(detailed: bool = False) -> str:
    """
    Show the current garden profile including hard constraints and soft
    preferences. Use this when the user asks about their garden setup,
    wants to review their constraints, or wants to confirm what the agent
    knows about their garden.
    """
    session = SessionLocal()
    try:
        profile = session.query(GardenProfile).filter(
            GardenProfile.user_id == 1
        ).first()
        if not profile:
            return "No garden profile found."

        return profile.to_detailed() if detailed else profile.to_summary()
    
    except Exception as e:
        print(f"[DEBUG] Failed to get garden profile: {e}")
        return f"Failed to get garden profile: {str(e)}"
    finally:
        session.close()

@tool
def update_garden_profile(
    climate_zone: Optional[str] = None,
    frost_date_last_spring: Optional[str] = None,
    frost_date_first_fall: Optional[str] = None,
    soil_type: Optional[str] = None,
    tray_capacity: Optional[int] = None,
    tray_indoor_capacity: Optional[int] = None,
    location_label: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    hard_constraints: Optional[dict] = None,
    soft_preferences: Optional[dict] = None,
    remove_hard_constraints: Optional[List[str]] = None,
    remove_soft_preferences: Optional[List[str]] = None, 
    notes: Optional[str] = None
) -> str:
    """
    Update the garden profile. Use this when the user reports a change to
    their garden setup — for example 'I got two more grow light trays so
    I now have 10 indoor trays', 'I need to add a constraint because we
    got a new puppy', or 'remove the no-thorns constraint, I made a mistake'.
    
    To add or update constraints, pass them in hard_constraints or
    soft_preferences as a dict — existing keys are preserved.
    To remove a specific constraint, pass its key in
    remove_hard_constraints or remove_soft_preferences as a list of
    key names — for example remove_hard_constraints=['no_thorns'].
    Only fields explicitly provided are changed.
    """
    session = SessionLocal()
    try:
        profile = session.query(GardenProfile).filter(
            GardenProfile.user_id == 1
        ).first()
        if not profile:
            return "Error: no garden profile found."

        if climate_zone is not None:
            profile.climate_zone = climate_zone
        if frost_date_last_spring is not None:
            profile.frost_date_last_spring = frost_date_last_spring
        if frost_date_first_fall is not None:
            profile.frost_date_first_fall = frost_date_first_fall
        if soil_type is not None:
            profile.soil_type = soil_type
        if tray_capacity is not None:
            profile.tray_capacity = tray_capacity
        if tray_indoor_capacity is not None:
            profile.tray_indoor_capacity = tray_indoor_capacity
        if location_label is not None:
            profile.location_label = location_label
        if latitude is not None:
            profile.latitude = latitude
        if longitude is not None:
            profile.longitude = longitude
        if notes is not None:
            profile.notes = notes

        # merge new constraints in
        if hard_constraints is not None:
            existing = dict(profile.hard_constraints or {})
            existing.update(hard_constraints)
            profile.hard_constraints = existing

        if soft_preferences is not None:
            existing = dict(profile.soft_preferences or {})
            existing.update(soft_preferences)
            profile.soft_preferences = existing

        # remove specified keys
        if remove_hard_constraints:
            existing = dict(profile.hard_constraints or {})
            for key in remove_hard_constraints:
                existing.pop(key, None)   # pop with None default — no error if key missing
            profile.hard_constraints = existing

        if remove_soft_preferences:
            existing = dict(profile.soft_preferences or {})
            for key in remove_soft_preferences:
                existing.pop(key, None)
            profile.soft_preferences = existing

        session.commit()

        # return a summary of what changed so the LLM can confirm back to the user
        changes = []
        if climate_zone is not None:
            changes.append(f"climate zone → {climate_zone}")
        if tray_capacity is not None:
            changes.append(f"tray capacity → {tray_capacity}")
        if tray_indoor_capacity is not None:
            changes.append(f"indoor trays → {tray_indoor_capacity}")
        if location_label is not None:
            changes.append(f"weather location label → {location_label}")
        if latitude is not None or longitude is not None:
            changes.append(f"weather coordinates → ({profile.latitude}, {profile.longitude})")
        if hard_constraints is not None:
            changes.append(f"added/updated constraints: {list(hard_constraints.keys())}")
        if remove_hard_constraints:
            changes.append(f"removed constraints: {remove_hard_constraints}")
        if soft_preferences is not None:
            changes.append(f"added/updated preferences: {list(soft_preferences.keys())}")
        if remove_soft_preferences:
            changes.append(f"removed preferences: {remove_soft_preferences}")

        summary = ", ".join(changes) if changes else "no changes made"
        return f"Garden profile updated: {summary}."

    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to update garden profile: {e}")
        return f"Failed to update garden profile: {str(e)}"
    finally:
        session.close()
