"""
Unit tests for critical domain-logic functions that have no coverage elsewhere:
  - compute_task_blocked_state
  - estimate_plan_cost / estimate_plan_timeline / estimate_plan_effort
  - infer_care_action
  - _resolve_subjects (subject resolution with duplicate plant names)
  - circular dependency handling
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from agent.domain.care import CARE_ACTIONS, _resolve_subjects, infer_care_action
from agent.domain.planner import estimate_plan_cost, estimate_plan_effort, estimate_plan_timeline
from agent.domain.tracker import compute_task_blocked_state
from db.models import Plant, Task
from tests.support.factories import (
    link_plant_to_project,
    make_bed,
    make_container,
    make_plant,
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_dependency,
    make_task_generation_run,
)


# ─── compute_task_blocked_state ───────────────────────────────────────────────

@pytest.mark.integration
def test_blocked_state_no_deps_is_false(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.solo")

    assert compute_task_blocked_state(db_session, task) is False


@pytest.mark.integration
def test_blocked_state_pending_blocker_blocks(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    blocker = make_task(db_session, project=project, revision=revision, generation_run=run,
                        generator_key="test.blocker", status="pending")
    blocked = make_task(db_session, project=project, revision=revision, generation_run=run,
                        generator_key="test.blocked")
    make_task_dependency(db_session, blocker, blocked)

    assert compute_task_blocked_state(db_session, blocked) is True


@pytest.mark.integration
def test_blocked_state_done_blocker_unblocks(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    blocker = make_task(db_session, project=project, revision=revision, generation_run=run,
                        generator_key="test.done_blocker", status="done")
    blocked = make_task(db_session, project=project, revision=revision, generation_run=run,
                        generator_key="test.will_unblock")
    make_task_dependency(db_session, blocker, blocked)

    assert compute_task_blocked_state(db_session, blocked) is False


@pytest.mark.integration
def test_blocked_state_skipped_blocker_unblocks(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    blocker = make_task(db_session, project=project, revision=revision, generation_run=run,
                        generator_key="test.skipped_blocker", status="skipped")
    blocked = make_task(db_session, project=project, revision=revision, generation_run=run,
                        generator_key="test.skipped_dep")
    make_task_dependency(db_session, blocker, blocked)

    assert compute_task_blocked_state(db_session, blocked) is False


@pytest.mark.integration
def test_blocked_state_event_anchor_without_date_is_blocked(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.event_anchor",
                     event_anchor_type="plant_germinated",
                     scheduled_date=None)

    assert compute_task_blocked_state(db_session, task) is True


@pytest.mark.integration
def test_blocked_state_event_anchor_with_date_is_not_blocked(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.event_resolved",
                     event_anchor_type="plant_germinated",
                     scheduled_date=datetime(2026, 5, 1))

    assert compute_task_blocked_state(db_session, task) is False


@pytest.mark.integration
def test_blocked_state_chain_a_blocks_b_blocks_c(db_session, patched_sessionlocal):
    """A→B→C: B is blocked by A, C is blocked by B. C should be blocked."""
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    task_a = make_task(db_session, project=project, revision=revision, generation_run=run,
                       generator_key="test.a", status="pending")
    task_b = make_task(db_session, project=project, revision=revision, generation_run=run,
                       generator_key="test.b")
    task_c = make_task(db_session, project=project, revision=revision, generation_run=run,
                       generator_key="test.c")
    make_task_dependency(db_session, task_a, task_b)
    make_task_dependency(db_session, task_b, task_c)

    # compute_task_blocked_state is one level deep — C sees B as pending → blocked
    assert compute_task_blocked_state(db_session, task_b) is True
    assert compute_task_blocked_state(db_session, task_c) is True


@pytest.mark.integration
def test_blocked_state_circular_dependency_does_not_crash(db_session, patched_sessionlocal):
    """A→B and B→A: both are blocked by each other. No infinite loop."""
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    task_a = make_task(db_session, project=project, revision=revision, generation_run=run,
                       generator_key="test.circ_a", status="pending")
    task_b = make_task(db_session, project=project, revision=revision, generation_run=run,
                       generator_key="test.circ_b", status="pending")
    make_task_dependency(db_session, task_a, task_b)
    make_task_dependency(db_session, task_b, task_a)

    # Should return True for both (mutually blocked), not raise or hang
    result_a = compute_task_blocked_state(db_session, task_a)
    result_b = compute_task_blocked_state(db_session, task_b)
    assert result_a is True
    assert result_b is True


@pytest.mark.integration
def test_blocked_state_accepts_task_id_string(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.id_str")

    assert compute_task_blocked_state(db_session, task.id) is False


# ─── estimate_plan_cost ───────────────────────────────────────────────────────

def _tomato_plan_input(**overrides):
    data = {
        "selected_plants": [
            {"name": "Tomato", "quantity": 2, "propagation_method": "seed", "estimated_setup_cost": 0}
        ],
        "selected_locations": [
            {"location_type": "container", "location_id": "c1", "name": "Growbag",
             "estimated_setup_cost": 20.0, "amendment_cost": 0.0, "material_cost": 0.0,
             "available": True}
        ],
        "budget_cap": 200.0,
    }
    data.update(overrides)
    return data


@pytest.mark.unit
def test_estimate_plan_cost_arithmetic():
    plan = _tomato_plan_input()
    result = estimate_plan_cost(plan)

    # Tomato seed: unit_cost=0.50 × qty=2 = 1.00 plant_material_cost
    # Support cost: support_cost=8.00 × max(qty=2,1) = 16.00 materials_cost
    # container_cost: estimated_setup_cost=20.00 (container location type)
    # amendment_cost: 0.00, material_cost: 0.00
    # subtotal: 1.00 + 16.00 + 0.00 + 20.00 = 37.00
    # contingency: 37.00 × 0.10 = 3.70
    # total: 40.70
    assert result["plant_material_cost"] == pytest.approx(1.00)
    assert result["container_cost"] == pytest.approx(20.00)
    assert result["contingency_cost"] == pytest.approx(3.70, rel=0.01)
    assert result["total_estimated_cost"] == pytest.approx(40.70, rel=0.01)


@pytest.mark.unit
def test_estimate_plan_cost_zero_plants_returns_zero_cost():
    plan = {"selected_plants": [], "selected_locations": []}
    result = estimate_plan_cost(plan)
    assert result["total_estimated_cost"] == 0.0


@pytest.mark.unit
def test_estimate_plan_cost_confidence_medium_when_no_unit_cost():
    # A plant with no known rule gets default unit_cost from normalization
    plan = {
        "selected_plants": [{"name": "UnknownPlant", "quantity": 1, "propagation_method": "seed",
                              "unit_cost": 0}],
        "selected_locations": [],
    }
    result = estimate_plan_cost(plan)
    assert result["cost_confidence"] == "medium"


@pytest.mark.unit
def test_estimate_plan_cost_contingency_is_ten_percent():
    plan = _tomato_plan_input()
    result = estimate_plan_cost(plan)
    subtotal = (result["total_estimated_cost"] - result["contingency_cost"])
    assert result["contingency_cost"] == pytest.approx(subtotal * 0.1, rel=0.01)


# ─── estimate_plan_timeline ───────────────────────────────────────────────────

@pytest.mark.unit
def test_estimate_plan_timeline_tomato_establishment_is_11_weeks():
    plan = {
        "selected_plants": [{"name": "Tomato", "quantity": 1, "propagation_method": "seed"}],
        "target_start": "2026-04-01",
    }
    result = estimate_plan_timeline(plan)

    start = datetime(2026, 4, 1)
    expected_establishment = start + timedelta(weeks=11)
    assert result["expected_establishment_date"] == expected_establishment.date().isoformat()


@pytest.mark.unit
def test_estimate_plan_timeline_uses_preferred_completion_when_given():
    plan = {
        "selected_plants": [{"name": "Tomato", "quantity": 1, "propagation_method": "seed"}],
        "target_start": "2026-04-01",
        "target_completion": "2026-08-01",
    }
    result = estimate_plan_timeline(plan)

    assert result["expected_completion_date"] == "2026-08-01"
    assert result["timeline_confidence"] == "high"


@pytest.mark.unit
def test_estimate_plan_timeline_confidence_medium_without_completion():
    plan = {
        "selected_plants": [{"name": "Basil", "quantity": 1, "propagation_method": "seed"}],
        "target_start": "2026-04-01",
    }
    result = estimate_plan_timeline(plan)
    assert result["timeline_confidence"] == "medium"


@pytest.mark.unit
def test_estimate_plan_timeline_multiple_plants_uses_longest_establishment():
    # Pepper: 13 weeks, Basil: 6 weeks → establishment should use 13 weeks
    plan = {
        "selected_plants": [
            {"name": "Pepper", "quantity": 1, "propagation_method": "seed"},
            {"name": "Basil", "quantity": 1, "propagation_method": "seed"},
        ],
        "target_start": "2026-04-01",
    }
    result = estimate_plan_timeline(plan)

    start = datetime(2026, 4, 1)
    expected = start + timedelta(weeks=13)
    assert result["expected_establishment_date"] == expected.date().isoformat()


# ─── estimate_plan_effort ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_estimate_plan_effort_structure():
    plan = {
        "selected_plants": [{"name": "Tomato", "quantity": 2, "propagation_method": "seed"}],
        "selected_locations": [{"location_type": "container", "location_id": "c1",
                                 "name": "Growbag", "available": True}],
        "target_start": "2026-04-01",
        "target_completion": "2026-07-01",
    }
    result = estimate_plan_effort(plan)

    assert "total_hours" in result
    assert "avg_hours_per_week" in result
    assert "peak_hours_per_week" in result
    assert "maintenance_hours_per_week" in result
    assert "major_work_buckets" in result
    assert result["total_hours"] > 0
    assert result["peak_hours_per_week"] >= result["avg_hours_per_week"]


@pytest.mark.unit
def test_estimate_plan_effort_seed_propagation_costs_more_than_starts():
    base = {
        "selected_locations": [{"location_type": "container", "location_id": "c1",
                                  "name": "Growbag", "available": True}],
        "target_start": "2026-04-01",
        "target_completion": "2026-07-01",
    }
    seed_plan = {**base, "selected_plants": [
        {"name": "Tomato", "quantity": 1, "propagation_method": "seed"}
    ]}
    start_plan = {**base, "selected_plants": [
        {"name": "Tomato", "quantity": 1, "propagation_method": "starts"}
    ]}
    assert estimate_plan_effort(seed_plan)["total_hours"] > estimate_plan_effort(start_plan)["total_hours"]


@pytest.mark.unit
def test_estimate_plan_effort_work_buckets_sum_to_roughly_total():
    plan = {
        "selected_plants": [{"name": "Tomato", "quantity": 1, "propagation_method": "seed"}],
        "selected_locations": [{"location_type": "container", "location_id": "c1",
                                  "name": "Growbag", "available": True}],
        "target_start": "2026-04-01",
        "target_completion": "2026-07-01",
    }
    result = estimate_plan_effort(plan)
    bucket_sum = sum(b["hours"] for b in result["major_work_buckets"])
    # buckets cover setup + propagation + care; total also includes quantity overhead
    assert bucket_sum <= result["total_hours"] + 1.0  # allow small delta for quantity


# ─── infer_care_action ────────────────────────────────────────────────────────

def _task_with_title(title: str, key: str = "test.key", description: str = "") -> SimpleNamespace:
    """Lightweight stand-in for Task — infer_care_action only reads generator_key, title, description."""
    return SimpleNamespace(generator_key=key, title=title, description=description)


@pytest.mark.unit
def test_infer_care_action_water():
    assert infer_care_action(_task_with_title("Water tomatoes")) == "water"


@pytest.mark.unit
def test_infer_care_action_fertilize():
    assert infer_care_action(_task_with_title("Fertilize peppers")) == "fertilize"


@pytest.mark.unit
def test_infer_care_action_feed_maps_to_fertilize():
    assert infer_care_action(_task_with_title("Feed basil with diluted solution")) == "fertilize"


@pytest.mark.unit
def test_infer_care_action_amend():
    assert infer_care_action(_task_with_title("Amend soil in raised bed")) == "amend"


@pytest.mark.unit
def test_infer_care_action_compost_maps_to_amend():
    assert infer_care_action(_task_with_title("Add compost to beds")) == "amend"


@pytest.mark.unit
def test_infer_care_action_mulch_maps_to_amend():
    assert infer_care_action(_task_with_title("Apply mulch around pepper plants")) == "amend"


@pytest.mark.unit
def test_infer_care_action_inspect():
    assert infer_care_action(_task_with_title("Inspect tomatoes for pests")) == "inspect"


@pytest.mark.unit
def test_infer_care_action_prune():
    assert infer_care_action(_task_with_title("Prune side shoots from tomato")) == "prune"


@pytest.mark.unit
def test_infer_care_action_sucker_maps_to_prune():
    assert infer_care_action(_task_with_title("Remove suckers from tomato plant")) == "prune"


@pytest.mark.unit
def test_infer_care_action_treat():
    assert infer_care_action(_task_with_title("Treat aphid infestation")) == "treat"


@pytest.mark.unit
def test_infer_care_action_spray_maps_to_treat():
    assert infer_care_action(_task_with_title("Spray neem oil on leaves")) == "treat"


@pytest.mark.unit
def test_infer_care_action_aphid_maps_to_treat():
    assert infer_care_action(_task_with_title("Remove aphids from stems")) == "treat"


@pytest.mark.unit
def test_infer_care_action_unrelated_returns_none():
    assert infer_care_action(_task_with_title("Check first harvest window for tomato")) is None


@pytest.mark.unit
def test_infer_care_action_checks_generator_key():
    t = _task_with_title("Milestone task", key="tomato.watering")
    assert infer_care_action(t) == "water"


@pytest.mark.unit
def test_infer_care_action_checks_description():
    t = _task_with_title("Garden task", description="fertilize and water before end of week")
    # "water" comes first in haystack search → water
    assert infer_care_action(t) == "water"


# ─── _resolve_subjects — duplicate plant names ───────────────────────────────

@pytest.mark.integration
def test_resolve_subjects_explicit_linked_subject_takes_priority(db_session, patched_sessionlocal):
    """Explicit linked_subjects should be used without falling back to name matching."""
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    plant = make_plant(db_session, profile, name="Tomato")
    decoy = make_plant(db_session, profile, name="Tomato")
    link_plant_to_project(db_session, project, plant)
    link_plant_to_project(db_session, project, decoy)

    task = make_task(
        db_session, project=project, revision=revision, generation_run=run,
        generator_key="test.explicit",
        title="Water Tomato",
        linked_subjects=[{"subject_type": "plant", "subject_id": plant.id, "role": "primary"}],
    )

    resolved = _resolve_subjects(db_session, task)
    resolved_ids = {obj.id for _, obj in resolved}

    assert plant.id in resolved_ids
    assert decoy.id not in resolved_ids


@pytest.mark.integration
def test_resolve_subjects_name_fallback_matches_all_plants_with_same_name(db_session, patched_sessionlocal):
    """When no explicit subjects, name matching should pick up ALL plants matching the title."""
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    tomato_1 = make_plant(db_session, profile, name="Tomato")
    tomato_2 = make_plant(db_session, profile, name="Tomato")
    other = make_plant(db_session, profile, name="Basil")
    link_plant_to_project(db_session, project, tomato_1)
    link_plant_to_project(db_session, project, tomato_2)
    link_plant_to_project(db_session, project, other)

    task = make_task(
        db_session, project=project, revision=revision, generation_run=run,
        generator_key="test.name_fallback",
        title="Water Tomato",
        linked_subjects=[],
    )

    resolved = _resolve_subjects(db_session, task)
    resolved_ids = {obj.id for _, obj in resolved if _ == "plant"}

    assert tomato_1.id in resolved_ids
    assert tomato_2.id in resolved_ids
    assert other.id not in resolved_ids


@pytest.mark.integration
def test_resolve_subjects_name_fallback_includes_plant_container(db_session, patched_sessionlocal):
    """Name-matched plant's container should also be included in resolved subjects."""
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    container = make_container(db_session, profile, name="Growbag")
    plant = make_plant(db_session, profile, name="Tomato", container=container)
    link_plant_to_project(db_session, project, plant)

    task = make_task(
        db_session, project=project, revision=revision, generation_run=run,
        generator_key="test.container_follow",
        title="Water Tomato",
        linked_subjects=[],
    )

    resolved = _resolve_subjects(db_session, task)
    resolved_types = {t for t, _ in resolved}

    assert "plant" in resolved_types
    assert "container" in resolved_types


@pytest.mark.integration
def test_resolve_subjects_no_match_returns_empty(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)

    task = make_task(
        db_session, project=project, revision=revision, generation_run=run,
        generator_key="test.no_match",
        title="Check first harvest window",
        linked_subjects=[],
    )

    resolved = _resolve_subjects(db_session, task)
    assert resolved == []
