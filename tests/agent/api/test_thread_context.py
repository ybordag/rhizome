"""
Tests for thread pinned context feature (#127):
  POST /threads/{id}/context                        — add entity to pinned context
  DELETE /threads/{id}/context/{type}/{subject_id}  — remove from pinned context
  GET /threads / GET /threads/{id}                  — pinned_context field present
  POST /threads with initial_context                — seed context at creation
  session_context_intake                            — inject pinned context text into state
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from unittest.mock import patch

from agent.api.app import app
from db.models import GardeningProject, Thread
from tests.support.factories import (
    make_batch, make_bed, make_container, make_incident_report, make_plant, make_project,
    make_project_brief, make_project_proposal, make_project_revision,
    make_task, make_task_generation_run,
)

client = TestClient(app)
USER = "1"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_thread(db_session, thread_id="thread-1", pinned=None):
    t = Thread(
        id=thread_id,
        user_id=USER,
        pinned_context=pinned or [],
        created_at=_now(),
        last_active_at=_now(),
    )
    db_session.add(t)
    db_session.commit()
    return t


def _make_task_via_chain(db_session, profile, user_id=USER, **overrides):
    """Create a task through the full project→brief→proposal→revision→run chain."""
    project = make_project(db_session, profile, user_id=user_id)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    return make_task(db_session, project=project, revision=revision, generation_run=run, **overrides)


# ---------------------------------------------------------------------------
# GET /threads and GET /threads/{id} — pinned_context field present
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_threads_includes_pinned_context(patched_sessionlocal, db_session, seed_garden_profile):
    _make_thread(db_session)
    resp = client.get(f"/internal/data/threads?user_id={USER}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert "pinned_context" in data[0]
    assert data[0]["pinned_context"] == []


@pytest.mark.integration
def test_get_thread_includes_pinned_context(patched_sessionlocal, db_session, seed_garden_profile):
    _make_thread(db_session)
    resp = client.get(f"/internal/data/threads/thread-1?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json()["pinned_context"] == []


# ---------------------------------------------------------------------------
# POST /threads/{id}/context — add entity
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_add_plant_to_context(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, name="Basil")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "plant", "subject_id": plant.id},
    )
    assert resp.status_code == 200
    assert resp.json()["pinned_context"] == [{"subject_type": "plant", "subject_id": plant.id}]


@pytest.mark.integration
def test_add_bed_to_context(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "bed", "subject_id": bed.id},
    )
    assert resp.status_code == 200
    assert resp.json()["pinned_context"][0]["subject_type"] == "bed"


@pytest.mark.integration
def test_add_project_to_context(patched_sessionlocal, db_session, seed_garden_profile):
    proj = make_project(db_session, seed_garden_profile)
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "project", "subject_id": proj.id},
    )
    assert resp.status_code == 200
    assert len(resp.json()["pinned_context"]) == 1


@pytest.mark.integration
def test_add_invalid_subject_type_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "weather", "subject_id": "some-id"},
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_add_entity_owned_by_other_user_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    # Create a plant for user "other-user" (different from USER="1")
    other_plant = make_plant(db_session, seed_garden_profile, name="Stolen Basil", user_id="other-user")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "plant", "subject_id": other_plant.id},
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_add_duplicate_entity_returns_409(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile)
    _make_thread(db_session, pinned=[{"subject_type": "plant", "subject_id": plant.id}])
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "plant", "subject_id": plant.id},
    )
    assert resp.status_code == 409


@pytest.mark.integration
def test_add_context_at_limit_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    beds = [make_bed(db_session, seed_garden_profile, name=f"Bed {i}") for i in range(10)]
    pinned = [{"subject_type": "bed", "subject_id": b.id} for b in beds]
    _make_thread(db_session, pinned=pinned)
    extra = make_bed(db_session, seed_garden_profile, name="Extra Bed")
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "bed", "subject_id": extra.id},
    )
    assert resp.status_code == 400
    assert "limit" in resp.json()["detail"].lower()


@pytest.mark.integration
def test_add_context_to_nonexistent_thread_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(
        f"/internal/data/threads/ghost/context?user_id={USER}",
        json={"subject_type": "bed", "subject_id": "x"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /threads/{id}/context/{type}/{subject_id}
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_remove_context_entry(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile)
    _make_thread(db_session, pinned=[{"subject_type": "plant", "subject_id": plant.id}])
    resp = client.delete(
        f"/internal/data/threads/thread-1/context/plant/{plant.id}?user_id={USER}",
    )
    assert resp.status_code == 200
    assert resp.json()["pinned_context"] == []


@pytest.mark.integration
def test_remove_one_of_two_context_entries(patched_sessionlocal, db_session, seed_garden_profile):
    bed1 = make_bed(db_session, seed_garden_profile, name="Bed A")
    bed2 = make_bed(db_session, seed_garden_profile, name="Bed B")
    _make_thread(db_session, pinned=[
        {"subject_type": "bed", "subject_id": bed1.id},
        {"subject_type": "bed", "subject_id": bed2.id},
    ])
    resp = client.delete(
        f"/internal/data/threads/thread-1/context/bed/{bed1.id}?user_id={USER}",
    )
    assert resp.status_code == 200
    remaining = resp.json()["pinned_context"]
    assert len(remaining) == 1
    assert remaining[0]["subject_id"] == bed2.id


@pytest.mark.integration
def test_remove_context_not_found_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    _make_thread(db_session)
    resp = client.delete(
        f"/internal/data/threads/thread-1/context/plant/ghost-id?user_id={USER}",
    )
    assert resp.status_code == 404


@pytest.mark.integration
def test_remove_context_wrong_user_thread_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    other_thread = Thread(
        id="other-thread",
        user_id="other-user",
        pinned_context=[],
        created_at=_now(),
        last_active_at=_now(),
    )
    db_session.add(other_thread)
    db_session.commit()
    resp = client.delete(
        f"/internal/data/threads/other-thread/context/bed/x?user_id={USER}",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /threads with initial_context
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_create_thread_with_initial_context(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, name="Chili")
    resp = client.post(
        f"/internal/data/threads?user_id={USER}",
        json={
            "thread_id": "thread-seed",
            "initial_context": [{"subject_type": "plant", "subject_id": plant.id}],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["created"] is True
    get_resp = client.get(f"/internal/data/threads/thread-seed?user_id={USER}")
    assert get_resp.json()["pinned_context"] == [{"subject_type": "plant", "subject_id": plant.id}]


@pytest.mark.integration
def test_create_thread_initial_context_unowned_entity_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    other_plant = make_plant(db_session, seed_garden_profile, user_id="other-user")
    resp = client.post(
        f"/internal/data/threads?user_id={USER}",
        json={
            "thread_id": "thread-bad",
            "initial_context": [{"subject_type": "plant", "subject_id": other_plant.id}],
        },
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_create_thread_initial_context_over_limit_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(
        f"/internal/data/threads?user_id={USER}",
        json={
            "thread_id": "thread-over",
            "initial_context": [{"subject_type": "bed", "subject_id": f"id-{i}"} for i in range(11)],
        },
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_create_thread_no_initial_context_gives_empty_pinned(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(
        f"/internal/data/threads?user_id={USER}",
        json={"thread_id": "thread-empty"},
    )
    assert resp.status_code == 200
    get_resp = client.get(f"/internal/data/threads/thread-empty?user_id={USER}")
    assert get_resp.json()["pinned_context"] == []


# ---------------------------------------------------------------------------
# session_context_intake — pinned_context_text injected into state
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_session_context_intake_injects_pinned_text(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, name="Basil")
    _make_thread(db_session, thread_id="thread-ctx", pinned=[{"subject_type": "plant", "subject_id": plant.id}])

    from agent.core.nodes import session_context_intake
    from langchain.messages import HumanMessage

    state = {"messages": [HumanMessage(content="hello")]}
    config = {"configurable": {"user_id": USER, "thread_id": "thread-ctx"}}

    with patch("agent.core.nodes.build_temporal_context", return_value={}), \
         patch("agent.core.nodes.infer_session_context", return_value={}):
        result = session_context_intake(state, config)

    assert result.get("pinned_context_text")
    assert "plant" in result["pinned_context_text"]
    assert "Basil" in result["pinned_context_text"]


@pytest.mark.integration
def test_session_context_intake_no_thread_no_pinned_text(patched_sessionlocal, db_session, seed_garden_profile):
    from agent.core.nodes import session_context_intake
    from langchain.messages import HumanMessage

    state = {"messages": [HumanMessage(content="hello")]}
    config = {"configurable": {"user_id": USER}}

    with patch("agent.core.nodes.build_temporal_context", return_value={}), \
         patch("agent.core.nodes.infer_session_context", return_value={}):
        result = session_context_intake(state, config)

    assert not result.get("pinned_context_text")


@pytest.mark.integration
def test_session_context_intake_empty_pinned_no_text(patched_sessionlocal, db_session, seed_garden_profile):
    _make_thread(db_session, thread_id="thread-empty2")

    from agent.core.nodes import session_context_intake
    from langchain.messages import HumanMessage

    state = {"messages": [HumanMessage(content="hello")]}
    config = {"configurable": {"user_id": USER, "thread_id": "thread-empty2"}}

    with patch("agent.core.nodes.build_temporal_context", return_value={}), \
         patch("agent.core.nodes.infer_session_context", return_value={}):
        result = session_context_intake(state, config)

    assert not result.get("pinned_context_text")


# ---------------------------------------------------------------------------
# Entity type coverage: container, task, incident in _verify_entity_owner
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_add_container_to_context(patched_sessionlocal, db_session, seed_garden_profile):
    container = make_container(db_session, seed_garden_profile, name="Growbag A")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "container", "subject_id": container.id},
    )
    assert resp.status_code == 200
    assert resp.json()["pinned_context"][0]["subject_type"] == "container"


@pytest.mark.integration
def test_add_container_owned_by_other_user_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    other_container = make_container(db_session, seed_garden_profile, name="Other Pot", user_id="other-user")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "container", "subject_id": other_container.id},
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_add_batch_to_context(patched_sessionlocal, db_session, seed_garden_profile):
    batch = make_batch(db_session, seed_garden_profile, name="Cosmos Spring 2026")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "batch", "subject_id": batch.id},
    )
    assert resp.status_code == 200
    assert resp.json()["pinned_context"][0]["subject_type"] == "batch"


@pytest.mark.integration
def test_add_batch_owned_by_other_user_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    batch = make_batch(db_session, seed_garden_profile, name="Other Batch", user_id="other-user")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "batch", "subject_id": batch.id},
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_add_task_to_context(patched_sessionlocal, db_session, seed_garden_profile):
    task = _make_task_via_chain(db_session, seed_garden_profile, title="Prune roses")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "task", "subject_id": task.id},
    )
    assert resp.status_code == 200
    assert resp.json()["pinned_context"][0]["subject_type"] == "task"


@pytest.mark.integration
def test_add_task_owned_by_other_user_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    # Task's project belongs to other-user, so the join on GardeningProject.user_id won't match USER
    task = _make_task_via_chain(db_session, seed_garden_profile, user_id="other-user")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "task", "subject_id": task.id},
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_add_incident_to_context(patched_sessionlocal, db_session, seed_garden_profile):
    proj = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=proj.id, summary="Aphids on peppers")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "incident", "subject_id": incident.id},
    )
    assert resp.status_code == 200
    assert resp.json()["pinned_context"][0]["subject_type"] == "incident"


@pytest.mark.integration
def test_add_incident_owned_by_other_user_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    other_proj = make_project(db_session, seed_garden_profile, user_id="other-user")
    incident = make_incident_report(db_session, project_id=other_proj.id, user_id="other-user")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "incident", "subject_id": incident.id},
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_add_owned_projectless_incident_succeeds(patched_sessionlocal, db_session, seed_garden_profile):
    # IncidentReport.user_id (audit fix) scopes project-less incidents directly.
    incident = make_incident_report(db_session, project_id=None, user_id=USER)
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "incident", "subject_id": incident.id},
    )
    assert resp.status_code == 200


@pytest.mark.integration
def test_add_projectless_incident_owned_by_other_user_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    incident = make_incident_report(db_session, project_id=None, user_id="other-user")
    _make_thread(db_session)
    resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "incident", "subject_id": incident.id},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Wrong-user thread on POST /context
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_add_context_to_other_users_thread_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    other_thread = Thread(
        id="other-thread",
        user_id="other-user",
        pinned_context=[],
        created_at=_now(),
        last_active_at=_now(),
    )
    db_session.add(other_thread)
    db_session.commit()
    bed = make_bed(db_session, seed_garden_profile)
    resp = client.post(
        f"/internal/data/threads/other-thread/context?user_id={USER}",
        json={"subject_type": "bed", "subject_id": bed.id},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Append semantics: multiple sequential pins
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_add_two_items_sequentially_both_present(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, name="Tomato")
    bed = make_bed(db_session, seed_garden_profile, name="Main Bed")
    _make_thread(db_session)

    client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "plant", "subject_id": plant.id},
    )
    client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "bed", "subject_id": bed.id},
    )

    resp = client.get(f"/internal/data/threads/thread-1?user_id={USER}")
    pinned = resp.json()["pinned_context"]
    assert len(pinned) == 2
    types = {p["subject_type"] for p in pinned}
    assert types == {"plant", "bed"}


# ---------------------------------------------------------------------------
# Persistence: GET confirms DB change after POST /context
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_add_context_persisted_to_db(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, name="Pepper")
    _make_thread(db_session)

    post_resp = client.post(
        f"/internal/data/threads/thread-1/context?user_id={USER}",
        json={"subject_type": "plant", "subject_id": plant.id},
    )
    assert post_resp.status_code == 200

    get_resp = client.get(f"/internal/data/threads/thread-1?user_id={USER}")
    assert get_resp.json()["pinned_context"] == [{"subject_type": "plant", "subject_id": plant.id}]


@pytest.mark.integration
def test_remove_context_persisted_to_db(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile)
    _make_thread(db_session, pinned=[{"subject_type": "plant", "subject_id": plant.id}])

    client.delete(f"/internal/data/threads/thread-1/context/plant/{plant.id}?user_id={USER}")

    get_resp = client.get(f"/internal/data/threads/thread-1?user_id={USER}")
    assert get_resp.json()["pinned_context"] == []


# ---------------------------------------------------------------------------
# _pinned_context_text: all entity type branches in session_context_intake
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_session_context_intake_injects_bed_text(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile, name="Sunny Bed", location="back yard")
    _make_thread(db_session, thread_id="thread-bed", pinned=[{"subject_type": "bed", "subject_id": bed.id}])

    from agent.core.nodes import session_context_intake
    from langchain.messages import HumanMessage

    state = {"messages": [HumanMessage(content="hello")]}
    config = {"configurable": {"user_id": USER, "thread_id": "thread-bed"}}

    with patch("agent.core.nodes.build_temporal_context", return_value={}), \
         patch("agent.core.nodes.infer_session_context", return_value={}):
        result = session_context_intake(state, config)

    text = result.get("pinned_context_text") or ""
    assert "bed" in text
    assert "Sunny Bed" in text


@pytest.mark.integration
def test_session_context_intake_injects_container_text(patched_sessionlocal, db_session, seed_garden_profile):
    container = make_container(db_session, seed_garden_profile, name="Big Growbag", container_type="growbag")
    _make_thread(db_session, thread_id="thread-ct", pinned=[{"subject_type": "container", "subject_id": container.id}])

    from agent.core.nodes import session_context_intake
    from langchain.messages import HumanMessage

    state = {"messages": [HumanMessage(content="hello")]}
    config = {"configurable": {"user_id": USER, "thread_id": "thread-ct"}}

    with patch("agent.core.nodes.build_temporal_context", return_value={}), \
         patch("agent.core.nodes.infer_session_context", return_value={}):
        result = session_context_intake(state, config)

    text = result.get("pinned_context_text") or ""
    assert "container" in text
    assert "Big Growbag" in text


@pytest.mark.integration
def test_session_context_intake_injects_batch_text(patched_sessionlocal, db_session, seed_garden_profile):
    batch = make_batch(db_session, seed_garden_profile, name="Cosmos Spring 2026", plant_name="Cosmos")
    _make_thread(db_session, thread_id="thread-batch", pinned=[{"subject_type": "batch", "subject_id": batch.id}])

    from agent.core.nodes import session_context_intake
    from langchain.messages import HumanMessage

    state = {"messages": [HumanMessage(content="hello")]}
    config = {"configurable": {"user_id": USER, "thread_id": "thread-batch"}}

    with patch("agent.core.nodes.build_temporal_context", return_value={}), \
         patch("agent.core.nodes.infer_session_context", return_value={}):
        result = session_context_intake(state, config)

    text = result.get("pinned_context_text") or ""
    assert "batch" in text
    assert "Cosmos Spring 2026" in text


@pytest.mark.integration
def test_session_context_intake_injects_task_text(patched_sessionlocal, db_session, seed_garden_profile):
    task = _make_task_via_chain(db_session, seed_garden_profile, title="Stake tomatoes")
    _make_thread(db_session, thread_id="thread-task", pinned=[{"subject_type": "task", "subject_id": task.id}])

    from agent.core.nodes import session_context_intake
    from langchain.messages import HumanMessage

    state = {"messages": [HumanMessage(content="hello")]}
    config = {"configurable": {"user_id": USER, "thread_id": "thread-task"}}

    with patch("agent.core.nodes.build_temporal_context", return_value={}), \
         patch("agent.core.nodes.infer_session_context", return_value={}):
        result = session_context_intake(state, config)

    text = result.get("pinned_context_text") or ""
    assert "task" in text
    assert "Stake tomatoes" in text


@pytest.mark.integration
def test_session_context_intake_injects_project_text(patched_sessionlocal, db_session, seed_garden_profile):
    proj = make_project(db_session, seed_garden_profile, name="Summer Harvest")
    _make_thread(db_session, thread_id="thread-proj", pinned=[{"subject_type": "project", "subject_id": proj.id}])

    from agent.core.nodes import session_context_intake
    from langchain.messages import HumanMessage

    state = {"messages": [HumanMessage(content="hello")]}
    config = {"configurable": {"user_id": USER, "thread_id": "thread-proj"}}

    with patch("agent.core.nodes.build_temporal_context", return_value={}), \
         patch("agent.core.nodes.infer_session_context", return_value={}):
        result = session_context_intake(state, config)

    text = result.get("pinned_context_text") or ""
    assert "project" in text
    assert "Summer Harvest" in text


@pytest.mark.integration
def test_session_context_intake_injects_incident_text(patched_sessionlocal, db_session, seed_garden_profile):
    proj = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=proj.id, incident_type="fungal_disease", summary="Powdery mildew on squash")
    _make_thread(db_session, thread_id="thread-inc", pinned=[{"subject_type": "incident", "subject_id": incident.id}])

    from agent.core.nodes import session_context_intake
    from langchain.messages import HumanMessage

    state = {"messages": [HumanMessage(content="hello")]}
    config = {"configurable": {"user_id": USER, "thread_id": "thread-inc"}}

    with patch("agent.core.nodes.build_temporal_context", return_value={}), \
         patch("agent.core.nodes.infer_session_context", return_value={}):
        result = session_context_intake(state, config)

    text = result.get("pinned_context_text") or ""
    assert "incident" in text
    assert "fungal_disease" in text


# ---------------------------------------------------------------------------
# Stale pinned entity: deleted entity silently skipped
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_stale_pinned_entity_silently_skipped(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, name="Doomed Plant")
    plant_id = plant.id
    _make_thread(db_session, thread_id="thread-stale", pinned=[{"subject_type": "plant", "subject_id": plant_id}])

    # Delete the plant after pinning it
    db_session.delete(plant)
    db_session.commit()

    from agent.core.nodes import session_context_intake
    from langchain.messages import HumanMessage

    state = {"messages": [HumanMessage(content="hello")]}
    config = {"configurable": {"user_id": USER, "thread_id": "thread-stale"}}

    with patch("agent.core.nodes.build_temporal_context", return_value={}), \
         patch("agent.core.nodes.infer_session_context", return_value={}):
        result = session_context_intake(state, config)

    # No crash; stale entry produces no text
    assert not result.get("pinned_context_text")


# ---------------------------------------------------------------------------
# initial_context with invalid subject_type
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_create_thread_initial_context_invalid_type_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(
        f"/internal/data/threads?user_id={USER}",
        json={
            "thread_id": "thread-badtype",
            "initial_context": [{"subject_type": "weather", "subject_id": "some-id"}],
        },
    )
    assert resp.status_code == 400
