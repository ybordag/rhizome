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
from tests.support.factories import make_bed, make_plant, make_project

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
