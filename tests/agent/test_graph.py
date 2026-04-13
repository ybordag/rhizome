import pytest
from langchain.messages import HumanMessage
from langgraph.types import Command

from agent.tools.planning import save_project_proposal, update_project_brief
from db.models import GardeningProject, ProjectProposal
from tests.support.fakes import make_ai_message, make_tool_call_message


@pytest.mark.graph
def test_conversational_turn_ends_without_interrupt(fresh_test_graph, fake_bound_model, seed_garden_profile):
    fake_bound_model.queue(make_ai_message("Hello from Rhizome."))
    config = {"configurable": {"thread_id": "thread-plain"}}

    result = fresh_test_graph.invoke({"messages": [HumanMessage(content="hi")]}, config=config)
    state = fresh_test_graph.get_state(config)

    assert result["messages"][-1].content == "Hello from Rhizome."
    assert not state.next


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
    assert resumed["messages"][-1].content == "Cancellation acknowledged."
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
    assert resumed["messages"][-1].content == "Proposal accepted."
