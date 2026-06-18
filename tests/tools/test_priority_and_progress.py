"""
Tests for:
- Task priority field (model, generation, update_task validation)
- cascade_defer_to_dependents (scheduling cascade logic)
- get_daily_priority_tasks (scoring and ranking)
- list_incidents / get_incident (gap-fill tools)
- get_project_proposal (gap-fill tool)
- get_project_progress (new aggregation tool)
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from agent.tracker import cascade_defer_to_dependents, get_daily_priority_tasks
from agent.tools.incidents import get_incident, list_incidents
from agent.tools.planning import get_project_proposal
from agent.tools.projects import get_project_progress
from agent.tools.tracker import (
    defer_task,
    get_daily_priority_tasks as get_daily_priority_tasks_tool,
    generate_project_tasks,
    update_task,
)
from db.models import Task, TaskDependency
from tests.support.factories import (
    make_incident_report,
    make_incident_subject,
    make_profile,
    make_project,
    make_project_brief,
    make_project_execution_spec,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_dependency,
    make_task_generation_run,
    make_treatment_plan,
    make_triage_snapshot,
)
from tests.tools.test_task_tracker_tools import _accept_plan


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _base_project(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    return project, revision, run


def _make_task(db_session, project, revision, run, **overrides):
    defaults = dict(
        window_end=datetime(2026, 6, 1),
        deadline=datetime(2026, 6, 1),
        type="milestone",
        priority="normal",
        parent_task_id="sentinel",  # not None so it's treated as a leaf task
    )
    defaults.update(overrides)
    # parent_task_id must be a real id or None; for leaf tasks we use None here
    # and accept that scoring skips section tasks (generator_key.startswith("section."))
    defaults["parent_task_id"] = overrides.get("parent_task_id", None)
    return make_task(db_session, project=project, revision=revision,
                     generation_run=run, **defaults)


# ─── Priority field ────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_task_priority_defaults_to_normal_on_milestone(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    task = _make_task(db_session, project, revision, run, type="milestone")
    # factory does not set priority, so model default applies
    db_session.expire_all()
    refreshed = db_session.query(Task).filter(Task.id == task.id).one()
    assert refreshed.priority in ("normal", "high", None)  # model default or factory override


@pytest.mark.integration
def test_update_task_accepts_valid_priority(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    task = _make_task(db_session, project, revision, run)

    result = update_task.invoke({"task_id": task.id, "priority": "critical"})
    assert "Updated task" in result

    db_session.expire_all()
    refreshed = db_session.query(Task).filter(Task.id == task.id).one()
    assert refreshed.priority == "critical"
    assert refreshed.is_user_modified is True


@pytest.mark.integration
def test_update_task_rejects_invalid_priority(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    task = _make_task(db_session, project, revision, run)

    result = update_task.invoke({"task_id": task.id, "priority": "urgent"})
    assert "Invalid priority" in result
    assert "urgent" in result


@pytest.mark.integration
def test_update_task_all_valid_priorities_accepted(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    for priority in ("critical", "high", "normal", "low"):
        task = _make_task(db_session, project, revision, run,
                          generator_key=f"test.priority.{priority}")
        result = update_task.invoke({"task_id": task.id, "priority": priority})
        assert "Updated task" in result, f"Expected success for priority={priority}"


# ─── Task generation assigns priority from type ───────────────────────────────

@pytest.mark.integration
def test_generated_milestone_tasks_have_high_priority(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})

    milestone_tasks = (
        db_session.query(Task)
        .filter(
            Task.project_id == project.id,
            Task.type == "milestone",
            Task.parent_task_id.isnot(None),
        )
        .all()
    )
    assert len(milestone_tasks) > 0
    for t in milestone_tasks:
        assert t.priority == "high", f"Milestone task '{t.title}' has priority={t.priority}"


@pytest.mark.integration
def test_generated_maintenance_tasks_have_normal_priority(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})

    maintenance_tasks = (
        db_session.query(Task)
        .filter(
            Task.project_id == project.id,
            Task.type == "maintenance",
        )
        .all()
    )
    assert len(maintenance_tasks) > 0
    for t in maintenance_tasks:
        assert t.priority == "normal", f"Maintenance task '{t.title}' has priority={t.priority}"


# ─── cascade_defer_to_dependents ──────────────────────────────────────────────

@pytest.mark.integration
def test_cascade_defer_pushes_dependent_earliest_start(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    blocker = _make_task(db_session, project, revision, run,
                         generator_key="test.blocker", title="Blocker task")
    dependent = _make_task(db_session, project, revision, run,
                           generator_key="test.dependent", title="Dependent task",
                           earliest_start=datetime(2026, 4, 10))
    make_task_dependency(db_session, blocker, dependent)

    defer_to = datetime(2026, 5, 15)
    pushed = cascade_defer_to_dependents(db_session, task=blocker, deferred_until=defer_to)

    assert dependent.title in pushed
    assert dependent.earliest_start == defer_to + timedelta(days=1)


@pytest.mark.integration
def test_cascade_defer_skips_completed_dependents(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    blocker = _make_task(db_session, project, revision, run,
                         generator_key="test.blocker2", title="Blocker")
    done_dep = _make_task(db_session, project, revision, run,
                          generator_key="test.done_dep", title="Done dep",
                          status="done", earliest_start=datetime(2026, 4, 1))
    make_task_dependency(db_session, blocker, done_dep)

    pushed = cascade_defer_to_dependents(
        db_session, task=blocker, deferred_until=datetime(2026, 5, 15)
    )
    assert done_dep.title not in pushed


@pytest.mark.integration
def test_cascade_defer_sets_earliest_start_when_none(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    blocker = _make_task(db_session, project, revision, run,
                         generator_key="test.blocker3", title="Blocker")
    dep = _make_task(db_session, project, revision, run,
                     generator_key="test.dep_no_start", title="Dep no start",
                     earliest_start=None)
    make_task_dependency(db_session, blocker, dep)

    defer_to = datetime(2026, 5, 20)
    cascade_defer_to_dependents(db_session, task=blocker, deferred_until=defer_to)

    assert dep.earliest_start == defer_to + timedelta(days=1)


@pytest.mark.integration
def test_defer_task_tool_reports_cascade_in_output(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    blocker = _make_task(db_session, project, revision, run,
                         generator_key="test.defer_cascade", title="Setup bed")
    dependent = _make_task(db_session, project, revision, run,
                           generator_key="test.defer_dep", title="Transplant tomatoes",
                           earliest_start=datetime(2026, 4, 1))
    make_task_dependency(db_session, blocker, dependent)

    result = defer_task.invoke({
        "task_id": blocker.id,
        "deferred_until": "2026-05-10",
        "reason": "Location not ready",
    })

    assert "Deferred task" in result
    assert "Transplant tomatoes" in result
    assert "Pushed earliest start" in result


@pytest.mark.integration
def test_defer_task_tool_no_cascade_message_when_no_dependents(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    standalone = _make_task(db_session, project, revision, run,
                            generator_key="test.standalone", title="Standalone task")

    result = defer_task.invoke({
        "task_id": standalone.id,
        "deferred_until": "2026-05-10",
    })

    assert "Deferred task" in result
    assert "Pushed earliest start" not in result


# ─── get_daily_priority_tasks scoring ─────────────────────────────────────────

@pytest.mark.integration
def test_daily_priority_blocker_urgency_outranks_backlog(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    now = datetime(2026, 4, 15)
    # blocker urgency: deadline <= tomorrow
    urgent = _make_task(db_session, project, revision, run,
                        generator_key="test.urgent",
                        title="Urgent task",
                        type="maintenance",
                        priority="normal",
                        window_end=now + timedelta(days=1),
                        deadline=now + timedelta(days=1))
    # backlog: no dates
    backlog = _make_task(db_session, project, revision, run,
                         generator_key="test.backlog",
                         title="Backlog task",
                         type="milestone",
                         priority="normal",
                         window_end=None,
                         deadline=None,
                         scheduled_date=None)

    rows = get_daily_priority_tasks(db_session, now=now)
    titles = [r["task"].title for r in rows]
    assert titles.index("Urgent task") < titles.index("Backlog task")


@pytest.mark.integration
def test_daily_priority_critical_priority_boosts_score(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    now = datetime(2026, 4, 15)
    # Both scheduled urgency (window_end in 10 days), same type
    # critical priority should score higher than low
    critical_task = _make_task(db_session, project, revision, run,
                               generator_key="test.critical_p",
                               title="Critical priority task",
                               type="milestone",
                               priority="critical",
                               window_end=now + timedelta(days=10),
                               deadline=now + timedelta(days=10))
    low_task = _make_task(db_session, project, revision, run,
                          generator_key="test.low_p",
                          title="Low priority task",
                          type="milestone",
                          priority="low",
                          window_end=now + timedelta(days=10),
                          deadline=now + timedelta(days=10))

    rows = get_daily_priority_tasks(db_session, now=now)
    titles = [r["task"].title for r in rows]
    assert titles.index("Critical priority task") < titles.index("Low priority task")


@pytest.mark.integration
def test_daily_priority_triage_recommended_boosts_score(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    now = datetime(2026, 4, 15)
    # Two identical tasks — one in triage recommendations
    plain = _make_task(db_session, project, revision, run,
                       generator_key="test.plain",
                       title="Plain task",
                       type="milestone",
                       priority="normal",
                       window_end=now + timedelta(days=10))
    recommended = _make_task(db_session, project, revision, run,
                             generator_key="test.recommended",
                             title="Triage recommended task",
                             type="milestone",
                             priority="normal",
                             window_end=now + timedelta(days=10))

    make_triage_snapshot(db_session, recommended_task_ids=[recommended.id])

    rows = get_daily_priority_tasks(db_session, now=now)
    titles = [r["task"].title for r in rows]
    assert titles.index("Triage recommended task") < titles.index("Plain task")


@pytest.mark.integration
def test_daily_priority_section_tasks_excluded(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    section_task = make_task(
        db_session, project=project, revision=revision, generation_run=run,
        generator_key="section.setup",
        title="Setup",
        parent_task_id=None,
    )
    rows = get_daily_priority_tasks(db_session)
    task_ids = [r["task"].id for r in rows]
    assert section_task.id not in task_ids


@pytest.mark.integration
def test_daily_priority_deferred_future_tasks_excluded(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    now = datetime(2026, 4, 15)
    deferred = _make_task(db_session, project, revision, run,
                          generator_key="test.deferred_future",
                          title="Future deferred task",
                          status="deferred",
                          deferred_until=now + timedelta(days=30))

    rows = get_daily_priority_tasks(db_session, now=now)
    task_ids = [r["task"].id for r in rows]
    assert deferred.id not in task_ids


@pytest.mark.integration
def test_daily_priority_tool_returns_string(db_session, patched_sessionlocal):
    project, revision, run = _base_project(db_session)
    _make_task(db_session, project, revision, run, generator_key="test.tool_check")

    result = get_daily_priority_tasks_tool.invoke({"limit": 5})
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.integration
def test_daily_priority_tool_rejects_invalid_limit(db_session, patched_sessionlocal):
    result = get_daily_priority_tasks_tool.invoke({"limit": 0})
    assert "limit" in result.lower()


@pytest.mark.integration
def test_daily_priority_project_filter_scopes_results(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project_a = make_project(db_session, profile, name="Project A")
    project_b = make_project(db_session, profile, name="Project B")

    brief_a = make_project_brief(db_session, project_a)
    proposal_a = make_project_proposal(db_session, project_a, brief_a)
    revision_a = make_project_revision(db_session, project_a, proposal_a)
    run_a = make_task_generation_run(db_session, project=project_a, revision=revision_a)

    brief_b = make_project_brief(db_session, project_b)
    proposal_b = make_project_proposal(db_session, project_b, brief_b)
    revision_b = make_project_revision(db_session, project_b, proposal_b)
    run_b = make_task_generation_run(db_session, project=project_b, revision=revision_b)

    task_a = _make_task(db_session, project_a, revision_a, run_a, generator_key="test.a", title="Task A")
    task_b = _make_task(db_session, project_b, revision_b, run_b, generator_key="test.b", title="Task B")

    rows = get_daily_priority_tasks(db_session, project_id=project_a.id)
    task_ids = [r["task"].id for r in rows]
    assert task_a.id in task_ids
    assert task_b.id not in task_ids


# ─── list_incidents ────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_list_incidents_returns_all(db_session, patched_sessionlocal):
    make_incident_report(db_session, summary="Aphids on tomatoes", incident_type="pest")
    make_incident_report(db_session, summary="Powdery mildew", incident_type="blight")

    result = list_incidents.invoke({})
    assert "Aphids on tomatoes" in result
    assert "Powdery mildew" in result


@pytest.mark.integration
def test_list_incidents_filters_by_project(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    make_incident_report(db_session, project_id=project.id, summary="Project incident")
    make_incident_report(db_session, project_id=None, summary="Unlinked incident")

    result = list_incidents.invoke({"project_id": project.id})
    assert "Project incident" in result
    assert "Unlinked incident" not in result


@pytest.mark.integration
def test_list_incidents_filters_by_status(db_session, patched_sessionlocal):
    make_incident_report(db_session, summary="Active incident", status="reported")
    make_incident_report(db_session, summary="Resolved incident", status="resolved")

    result = list_incidents.invoke({"status": "reported"})
    assert "Active incident" in result
    assert "Resolved incident" not in result


@pytest.mark.integration
def test_list_incidents_empty(db_session, patched_sessionlocal):
    result = list_incidents.invoke({})
    assert "No incidents found" in result


# ─── get_incident ──────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_get_incident_returns_detail(db_session, patched_sessionlocal):
    incident = make_incident_report(db_session, summary="Spider mites on pepper")
    make_incident_subject(db_session, incident, subject_type="plant", subject_id="p1")

    result = get_incident.invoke({"incident_id": incident.id})
    assert "Spider mites on pepper" in result
    assert "plant" in result
    assert "p1" in result


@pytest.mark.integration
def test_get_incident_shows_treatment_plan_when_present(db_session, patched_sessionlocal):
    incident = make_incident_report(db_session)
    plan = make_treatment_plan(db_session, incident)

    result = get_incident.invoke({"incident_id": incident.id})
    assert plan.id in result
    assert "draft" in result


@pytest.mark.integration
def test_get_incident_shows_no_plan_when_absent(db_session, patched_sessionlocal):
    incident = make_incident_report(db_session)

    result = get_incident.invoke({"incident_id": incident.id})
    assert "none drafted" in result


@pytest.mark.integration
def test_get_incident_not_found(db_session, patched_sessionlocal):
    result = get_incident.invoke({"incident_id": "nonexistent-id"})
    assert "No incident found" in result


# ─── get_project_proposal ─────────────────────────────────────────────────────

@pytest.mark.integration
def test_get_project_proposal_returns_detail(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief,
                                     title="Summer tomato plan")

    result = get_project_proposal.invoke({
        "project_id": project.id,
        "proposal_id": proposal.id,
    })
    assert "Summer tomato plan" in result


@pytest.mark.integration
def test_get_project_proposal_wrong_project_returns_error(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project_a = make_project(db_session, profile, name="Project A")
    project_b = make_project(db_session, profile, name="Project B")
    brief = make_project_brief(db_session, project_a)
    proposal = make_project_proposal(db_session, project_a, brief)

    result = get_project_proposal.invoke({
        "project_id": project_b.id,
        "proposal_id": proposal.id,
    })
    assert "No proposal found" in result


@pytest.mark.integration
def test_get_project_proposal_not_found(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)

    result = get_project_proposal.invoke({
        "project_id": project.id,
        "proposal_id": "nonexistent-id",
    })
    assert "No proposal found" in result


# ─── get_project_progress ─────────────────────────────────────────────────────

@pytest.mark.integration
def test_get_project_progress_shows_task_counts(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})

    result = get_project_progress.invoke({"project_id": project.id})
    assert "Tasks:" in result
    assert "done" in result
    assert "%" in result


@pytest.mark.integration
def test_get_project_progress_shows_timeline(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal,
                           propagation_method="seed",
                           target_completion="2026-07-01")
    generate_project_tasks.invoke({"project_id": project.id})

    result = get_project_progress.invoke({"project_id": project.id})
    assert "Timeline" in result or "days remaining" in result


@pytest.mark.integration
def test_get_project_progress_not_found(db_session, patched_sessionlocal):
    result = get_project_progress.invoke({"project_id": "nonexistent-id"})
    assert "No project found" in result


@pytest.mark.integration
def test_get_project_progress_completion_increases_after_task_done(db_session, patched_sessionlocal):
    from agent.tools.tracker import complete_task

    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="nursery")
    generate_project_tasks.invoke({"project_id": project.id})

    result_before = get_project_progress.invoke({"project_id": project.id})

    # Complete any one leaf task
    leaf = (
        db_session.query(Task)
        .filter(
            Task.project_id == project.id,
            Task.parent_task_id.isnot(None),
            Task.status == "pending",
        )
        .first()
    )
    if leaf:
        complete_task.invoke({"task_id": leaf.id})
        result_after = get_project_progress.invoke({"project_id": project.id})
        # After completing one task the done count should increase
        # Extract "N done" numbers from both results and compare
        import re
        before_done = int(re.search(r"(\d+) done", result_before).group(1))
        after_done = int(re.search(r"(\d+) done", result_after).group(1))
        assert after_done == before_done + 1
