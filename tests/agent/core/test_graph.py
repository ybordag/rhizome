import pytest
from langchain.messages import HumanMessage
from langgraph.types import Command

from agent.tools.operations.incidents import approve_treatment_plan, draft_treatment_plan, report_incident
from agent.tools.projects.planning import save_project_proposal, update_project_brief
from db.models import GardeningProject, ProjectProposal, Task, Thread, TreatmentPlan, TriageSnapshot
from tests.support.fakes import make_ai_message, make_tool_call_message
from tests.support.factories import (
    make_batch,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
)


@pytest.mark.graph
def test_conversational_turn_ends_without_interrupt(fresh_test_graph, fake_bound_model, seed_garden_profile):
    fake_bound_model.queue(make_ai_message("Hello from Rhizome."))
    config = {"configurable": {"thread_id": "thread-plain"}}

    result = fresh_test_graph.invoke({"messages": [HumanMessage(content="hi")]}, config=config)
    state = fresh_test_graph.get_state(config)

    assert result["messages"][-1].content == "Hello from Rhizome."
    assert not state.next


@pytest.mark.graph
def test_session_bootstrap_creates_triage_without_calling_model(
    fresh_test_graph, fake_bound_model, seed_garden_profile
):
    config = {"configurable": {"thread_id": "thread-bootstrap"}}

    result = fresh_test_graph.invoke({"messages": []}, config=config)
    state = fresh_test_graph.get_state(config)
    triage_interaction = state.values.get("pending_interaction")

    assert result["messages"] == []
    assert not state.next
    assert triage_interaction["interaction_type"] == "triage_view"
    assert fake_bound_model.invocations == []


@pytest.mark.graph
def test_first_user_turn_reuses_startup_triage_snapshot_without_regenerating(
    fresh_test_graph, fake_bound_model, seed_garden_profile
):
    config = {"configurable": {"thread_id": "thread-startup-reuse"}}

    fresh_test_graph.invoke({"messages": []}, config=config)
    startup_state = fresh_test_graph.get_state(config)
    startup_interaction_id = startup_state.values["pending_interaction"]["id"]
    startup_snapshot_id = startup_state.values["triage_snapshot"]["id"]

    fake_bound_model.queue(make_ai_message("Hello after triage."))
    result = fresh_test_graph.invoke({"messages": [HumanMessage(content="hi")]}, config=config)
    resumed_state = fresh_test_graph.get_state(config)

    assert result["messages"][-1].content == "Hello after triage."
    assert resumed_state.values["pending_interaction"]["id"] == startup_interaction_id
    assert resumed_state.values["triage_snapshot"]["id"] == startup_snapshot_id
    assert len(fake_bound_model.invocations) == 1


@pytest.mark.graph
def test_first_user_turn_preserves_patched_session_context_in_triage(
    fresh_test_graph,
    fake_bound_model,
    seed_garden_profile,
    db_session,
):
    project = make_project(db_session, seed_garden_profile, name="Courtyard Tomatoes")
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project, revision)
    task = make_task(
        db_session,
        project=project,
        revision=revision,
        generation_run=run,
        title="Prepare growbag_1",
    )
    stored_context = {
        "time_text": "35 minutes",
        "energy_text": "low but focused",
        "focus_text": "Courtyard Tomatoes March 2026",
        "focus_context": [{"subject_type": "project", "subject_id": project.id}],
        "source": "user",
    }
    db_session.add(
        Thread(
            id="thread-session-context-graph",
            user_id="1",
            session_context=stored_context,
        )
    )
    db_session.commit()
    fake_bound_model.queue(make_ai_message("Use the tomato task first."))
    config = {"configurable": {"thread_id": "thread-session-context-graph", "user_id": "1"}}

    result = fresh_test_graph.invoke({"messages": [HumanMessage(content="What should I do first?")]}, config=config)
    state = fresh_test_graph.get_state(config)
    snapshot_id = state.values["triage_snapshot"]["id"]
    snapshot = db_session.get(TriageSnapshot, snapshot_id)

    assert result["messages"][-1].content == "Use the tomato task first."
    assert snapshot.session_context == stored_context
    assert task.id in snapshot.recommended_task_ids
    assert state.values["session_context"] == stored_context


@pytest.mark.graph
def test_first_user_turn_injects_batch_focus_related_tasks_into_prompt(
    fresh_test_graph,
    fake_bound_model,
    seed_garden_profile,
    db_session,
):
    project = make_project(db_session, seed_garden_profile, name="Courtyard Tomatoes")
    batch = make_batch(
        db_session,
        seed_garden_profile,
        project=project,
        name="Courtyard Tomatoes March 2026",
        plant_name="Cherry Tomato",
        variety="Sungold",
    )
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project, revision)
    task = make_task(
        db_session,
        project=project,
        revision=revision,
        generation_run=run,
        title="Prepare growbag_1",
        priority="high",
        estimated_minutes=45,
        linked_subjects=[{"subject_type": "batch", "subject_id": batch.id, "role": "affected"}],
    )
    stored_context = {
        "time_text": "35 minutes",
        "energy_text": "low but focused",
        "focus_text": "What should I do first for the tomatoes?",
        "focus_context": [{"subject_type": "batch", "subject_id": batch.id}],
        "source": "user",
    }
    db_session.add(
        Thread(
            id="thread-batch-session-context-graph",
            user_id="1",
            session_context=stored_context,
        )
    )
    db_session.commit()
    fake_bound_model.queue(make_ai_message("Start with the growbag task."))
    config = {"configurable": {"thread_id": "thread-batch-session-context-graph", "user_id": "1"}}

    result = fresh_test_graph.invoke({"messages": [HumanMessage(content="What should I do first?")]}, config=config)
    state = fresh_test_graph.get_state(config)
    snapshot = db_session.get(TriageSnapshot, state.values["triage_snapshot"]["id"])
    system_prompt = fake_bound_model.invocations[0][0].content

    assert result["messages"][-1].content == "Start with the growbag task."
    assert snapshot.session_context == stored_context
    assert task.id in snapshot.recommended_task_ids
    assert state.values["session_context"] == stored_context
    assert "Session context for this thread:" in system_prompt
    assert "Thread focus: What should I do first for the tomatoes?" in system_prompt
    assert "[Batch]" in system_prompt
    assert "Courtyard Tomatoes March 2026" in system_prompt
    assert f"id: {batch.id}" in system_prompt
    assert "Related open tasks:" in system_prompt
    assert "Prepare growbag_1" in system_prompt
    assert f"id: {task.id}" in system_prompt


@pytest.mark.graph
def test_non_destructive_tool_call_executes_and_loops_back(fresh_test_graph, fake_bound_model, seed_garden_profile):
    fake_bound_model.queue(
        make_tool_call_message("Need projects", name="list_projects", args={}, call_id="call-1"),
        make_ai_message("Here are your projects."),
    )
    config = {"configurable": {"thread_id": "thread-tool"}}

    result = fresh_test_graph.invoke({"messages": [HumanMessage(content="show projects")]}, config=config)

    assert result["messages"][-1].content == "Here are your projects."
    assert len(fake_bound_model.invocations) == 2
    assert not fresh_test_graph.get_state(config).next


@pytest.mark.graph
def test_destructive_tool_call_interrupts_and_cancels_on_negative_resume(
    fresh_test_graph, fake_bound_model, seed_garden_profile, db_session, patched_sessionlocal
):
    project = GardeningProject(
        user_id=1,
        garden_profile_id=seed_garden_profile.id,
        name="Delete Me",
        goal="Temporary project",
        status="planning",
        tray_slots=1,
        budget_ceiling=5.0,
        negotiation_history=[],
        iterations=[],
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    fake_bound_model.queue(
        make_tool_call_message(
            "Deleting project",
            name="delete_project",
            args={"project_id": project.id},
            call_id="call-1",
        ),
        make_ai_message("Cancellation acknowledged."),
    )
    config = {"configurable": {"thread_id": "thread-cancel"}}
    project_id = project.id

    first = fresh_test_graph.invoke({"messages": [HumanMessage(content="delete it")]}, config=config)
    state = fresh_test_graph.get_state(config)
    resumed = fresh_test_graph.invoke(Command(resume="no"), config=config)

    db_session.expire_all()
    assert first["messages"][-1].tool_calls[0]["name"] == "delete_project"
    assert "interaction_node" in state.next
    assert resumed["messages"][-1].content == "Operation cancelled. No changes were made."
    assert db_session.query(GardeningProject).filter(GardeningProject.id == project_id).first() is not None


@pytest.mark.graph
def test_destructive_tool_call_executes_on_affirmative_resume(
    fresh_test_graph, fake_bound_model, seed_garden_profile, db_session, patched_sessionlocal
):
    project = GardeningProject(
        user_id=1,
        garden_profile_id=seed_garden_profile.id,
        name="Delete Me Too",
        goal="Temporary project",
        status="planning",
        tray_slots=1,
        budget_ceiling=5.0,
        negotiation_history=[],
        iterations=[],
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    fake_bound_model.queue(
        make_tool_call_message(
            "Deleting project",
            name="delete_project",
            args={"project_id": project.id},
            call_id="call-1",
        ),
        make_ai_message("Project deleted."),
    )
    config = {"configurable": {"thread_id": "thread-confirm"}}
    project_id = project.id

    fresh_test_graph.invoke({"messages": [HumanMessage(content="delete it")]}, config=config)
    resumed = fresh_test_graph.invoke(Command(resume="yes"), config=config)

    db_session.expire_all()
    assert resumed["messages"][-1].content == "Project deleted."
    assert db_session.query(GardeningProject).filter(GardeningProject.id == project_id).first() is None


@pytest.mark.graph
def test_checkpoint_state_is_isolated_by_thread_id(fresh_test_graph, fake_bound_model, seed_garden_profile):
    fake_bound_model.queue(
        make_tool_call_message("delete first", name="delete_project", args={"project_id": "proj-1"}, call_id="call-1"),
        make_ai_message("Second thread response."),
    )

    first_config = {"configurable": {"thread_id": "thread-one"}}
    second_config = {"configurable": {"thread_id": "thread-two"}}

    fresh_test_graph.invoke({"messages": [HumanMessage(content="delete thread one")]}, config=first_config)
    fresh_test_graph.invoke({"messages": [HumanMessage(content="hello thread two")]}, config=second_config)

    first_state = fresh_test_graph.get_state(first_config)
    second_state = fresh_test_graph.get_state(second_config)

    assert "interaction_node" in first_state.next
    assert not second_state.next


@pytest.mark.graph
def test_proposal_acceptance_interrupts_with_structured_review_and_accepts(
    fresh_test_graph, fake_bound_model, seed_garden_profile, db_session, patched_sessionlocal
):
    project = GardeningProject(
        user_id=1,
        garden_profile_id=seed_garden_profile.id,
        name="Tomato Review",
        goal="Summer tomatoes",
        status="planning",
        tray_slots=2,
        budget_ceiling=100.0,
        negotiation_history=[],
        iterations=[],
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "Tomatoes by midsummer.",
            "target_start": "2026-04-20",
            "target_completion": "2026-07-15",
            "budget_cap": 100.0,
        }
    )
    save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Balanced plan",
            "summary": "Use two growbags for tomatoes.",
            "recommended_approach": "Seed-start tomatoes and stage them into growbags.",
            "selected_locations": [{"location_type": "container", "location_id": "c-1", "name": "Growbag 1"}],
            "selected_plants": [{"name": "Tomato", "quantity": 2, "propagation_method": "seed"}],
        }
    )
    proposal_id = (
        db_session.query(ProjectProposal.id)
        .filter(ProjectProposal.project_id == project.id)
        .scalar()
    )

    fake_bound_model.queue(
        make_tool_call_message(
            "Accept proposal",
            name="accept_project_proposal",
            args={"project_id": project.id, "proposal_id": proposal_id},
            call_id="call-1",
        ),
        make_ai_message("Proposal accepted."),
    )
    config = {"configurable": {"thread_id": "thread-proposal-review"}}

    fresh_test_graph.invoke({"messages": [HumanMessage(content="accept the plan")]}, config=config)
    state = fresh_test_graph.get_state(config)
    interrupt_payload = state.tasks[0].interrupts[0].value
    resumed = fresh_test_graph.invoke(
        Command(
            resume={
                "interaction_id": interrupt_payload["id"],
                "action_id": "accept_proposal",
                "inputs": {},
            }
        ),
        config=config,
    )

    assert interrupt_payload["interaction_type"] == "proposal_review"
    assert "Accepted proposal 'Balanced plan'" in resumed["messages"][-1].content


@pytest.mark.graph
def test_treatment_plan_approval_interrupt_executes_and_creates_tasks(
    fresh_test_graph, fake_bound_model, seed_garden_profile, db_session, patched_sessionlocal
):
    project = GardeningProject(
        user_id=1,
        garden_profile_id=seed_garden_profile.id,
        name="Disease Review",
        goal="Treat mildew on tomatoes",
        status="planning",
        tray_slots=2,
        budget_ceiling=40.0,
        negotiation_history=[],
        iterations=[],
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "Get tomatoes through the mildew outbreak.",
            "target_start": "2026-04-20",
            "target_completion": "2026-07-15",
            "budget_cap": 40.0,
        }
    )
    save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Tomato treatment base plan",
            "summary": "Use existing growbags and treat mildew quickly.",
            "recommended_approach": "Keep airflow up and use organic treatment steps.",
            "selected_locations": [{"location_type": "container", "location_id": "c-1", "name": "Growbag 1"}],
            "selected_plants": [{"name": "Tomato", "quantity": 2, "propagation_method": "start"}],
        }
    )
    proposal_id = (
        db_session.query(ProjectProposal.id)
        .filter(ProjectProposal.project_id == project.id)
        .scalar()
    )
    from agent.tools.projects.planning import accept_project_proposal
    from agent.tools.projects.tracker import generate_project_tasks

    accept_project_proposal.invoke({"project_id": project.id, "proposal_id": proposal_id})
    generate_project_tasks.invoke({"project_id": project.id})

    report_incident.invoke(
        {
            "incident_type": "blight",
            "summary": "Powdery mildew on tomatoes",
            "project_id": project.id,
            "severity": "medium",
            "subjects": [],
        }
    )
    from db.models import IncidentReport

    incident = db_session.query(IncidentReport).order_by(IncidentReport.created_at.desc()).first()
    draft_treatment_plan.invoke({"incident_id": incident.id})
    plan = db_session.query(TreatmentPlan).order_by(TreatmentPlan.created_at.desc()).first()

    fake_bound_model.queue(
        make_tool_call_message(
            "Approve treatment",
            name="approve_treatment_plan",
            args={"treatment_plan_id": plan.id},
            call_id="call-1",
        ),
        make_ai_message("Treatment plan approved and tasks created."),
    )
    config = {"configurable": {"thread_id": "thread-treatment-review"}}

    fresh_test_graph.invoke({"messages": [HumanMessage(content="approve the treatment plan")]}, config=config)
    state = fresh_test_graph.get_state(config)
    interrupt_payload = state.tasks[0].interrupts[0].value
    resumed = fresh_test_graph.invoke(
        Command(
            resume={
                "interaction_id": interrupt_payload["id"],
                "action_id": "approve_treatment_plan",
                "inputs": {},
            }
        ),
        config=config,
    )

    db_session.expire_all()
    refreshed = db_session.query(TreatmentPlan).filter(TreatmentPlan.id == plan.id).one()
    incident_tasks = db_session.query(Task).filter(Task.project_id == project.id, Task.generator_key.like("incident.%")).all()

    assert interrupt_payload["interaction_type"] == "treatment_plan_review"
    assert "Approved treatment plan" in resumed["messages"][-1].content
    assert refreshed.status == "approved"
    assert incident_tasks
