from __future__ import annotations

from agent.planner import (
    build_execution_spec_payload,
    build_plan_input,
    check_plan_feasibility,
    estimate_plan_cost,
    estimate_plan_effort,
    estimate_plan_timeline,
    generate_schedule_preview,
)
from tests.support.factories import (
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
)


def test_planner_estimate_helpers_return_stable_shapes(db_session):
    profile = make_profile(db_session, tray_indoor_capacity=4)
    project = make_project(db_session, profile, tray_slots=3, budget_ceiling=150.0)
    brief = make_project_brief(
        db_session,
        project,
        target_start=None,
        target_completion=None,
    )

    plan_input = build_plan_input(
        project=project,
        brief=brief,
        profile=profile,
        selected_locations=[
            {
                "location_type": "container",
                "location_id": "container-1",
                "name": "Growbag 1",
                "estimated_setup_cost": 20,
            }
        ],
        selected_plants=[
            {"name": "Tomato", "quantity": 2, "propagation_method": "seed"},
            {"name": "Basil", "quantity": 3, "propagation_method": "seed"},
        ],
    )

    feasibility = check_plan_feasibility(plan_input)
    cost = estimate_plan_cost(plan_input)
    timeline = estimate_plan_timeline(plan_input)
    effort = estimate_plan_effort(plan_input)

    assert feasibility["is_feasible"] is True
    assert cost["total_estimated_cost"] >= cost["plant_material_cost"]
    assert timeline["expected_completion_date"] >= timeline["planning_start"]
    assert effort["total_hours"] > 0
    assert effort["avg_hours_per_week"] > 0
    assert effort["peak_hours_per_week"] >= effort["avg_hours_per_week"]
    assert effort["maintenance_hours_per_week"] > 0


def test_planner_feasibility_catches_budget_and_timing_conflicts(db_session):
    profile = make_profile(db_session, tray_indoor_capacity=1)
    project = make_project(db_session, profile, tray_slots=3, budget_ceiling=5.0)
    brief = make_project_brief(
        db_session,
        project,
        target_start="2026-04-01" if False else None,
    )

    plan_input = build_plan_input(
        project=project,
        brief=brief,
        profile=profile,
        selected_locations=[
            {
                "location_type": "container",
                "location_id": "container-1",
                "name": "Growbag 1",
                "estimated_setup_cost": 20,
            }
        ],
        selected_plants=[
            {"name": "Pepper", "quantity": 2, "propagation_method": "seed"},
        ],
    )
    plan_input["target_start"] = "2026-04-15"
    plan_input["target_completion"] = "2026-05-01"

    feasibility = check_plan_feasibility(plan_input)

    assert feasibility["is_feasible"] is False
    assert any("budget" in violation.lower() for violation in feasibility["hard_constraint_violations"])
    assert any("completion date" in violation.lower() for violation in feasibility["hard_constraint_violations"])
    assert any("tray slots" in violation.lower() for violation in feasibility["hard_constraint_violations"])


def test_execution_spec_payload_and_schedule_preview_support_calendar_and_event_modes(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(
        db_session,
        project,
        brief,
        selected_plants=[
            {
                "name": "Tomato",
                "quantity": 2,
                "propagation_method": "seed",
                "event_triggers": [{"event_type": "plant_germinated", "offset_days": 14}],
            }
        ],
        timing_anchors={
            "modes": ["calendar", "event"],
            "calendar": [{"name": "spring_window", "date": "2026-04-01"}],
            "event": [{"event_type": "plant_germinated", "offset_days": 14}],
        },
        timeline_estimate={
            "planning_start": "2026-04-01",
            "expected_first_action_date": "2026-04-01",
            "expected_establishment_date": "2026-05-20",
            "expected_completion_date": "2026-07-01",
            "maintenance_mode_date": "2026-06-01",
            "timeline_confidence": "high",
        },
    )

    execution_spec = build_execution_spec_payload(proposal, brief)
    preview = generate_schedule_preview(execution_spec)

    assert execution_spec["timing_anchors"]["modes"] == ["calendar", "event"]
    assert any(task["title"].startswith("Sow Tomato") for task in preview["milestone_tasks"])
    assert any(rule["title"] == "Water Tomato" for rule in preview["recurring_rules"])
    assert preview["dependency_links"]
    assert "Propagation" in preview["tree"]
