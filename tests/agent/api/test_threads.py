"""Tests for thread management endpoints."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain.messages import AIMessage, HumanMessage

from agent.api.app import app
from agent.core import graph as graph_module
from db.models import Task, Thread
from tests.support.factories import make_plant, make_profile, make_project

client = TestClient(app)


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


THREAD_VIEW_FIELDS = (
    "thread_id",
    "title",
    "project_id",
    "last_message_preview",
    "last_active_at",
    "message_count",
    "pinned_context",
    "session_context",
    "created_at",
)
THREAD_VIEW_KEYS = set(THREAD_VIEW_FIELDS)


def _compact_json(value):
    return json.dumps(value, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Thread.to_view — #139 serializer contract
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_thread_to_view_preserves_existing_inline_serializer_contract():
    now = _now()
    thread = Thread(
        id="serializer-thread",
        user_id=1,
        title="Serializer check",
        project_id="project-1",
        last_message_preview="Last message",
        last_active_at=now,
        message_count=4,
        pinned_context=None,
        session_context=None,
        created_at=now,
    )

    view = thread.to_view()

    assert list(view) == list(THREAD_VIEW_FIELDS)
    assert "id" not in view
    assert view == {
        "thread_id": "serializer-thread",
        "title": "Serializer check",
        "project_id": "project-1",
        "last_message_preview": "Last message",
        "last_active_at": now,
        "message_count": 4,
        "pinned_context": [],
        "session_context": None,
        "created_at": now,
    }


# ---------------------------------------------------------------------------
# POST /internal/data/threads — create
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_create_thread(patched_sessionlocal):
    resp = client.post("/internal/data/threads?user_id=1", json={
        "thread_id": "silver-fern-cascade",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["thread_id"] == "silver-fern-cascade"
    assert data["created"] is True


@pytest.mark.integration
def test_create_thread_with_title(patched_sessionlocal):
    resp = client.post("/internal/data/threads?user_id=1", json={
        "thread_id": "amber-lotus-dawn",
        "title": "Spring planting plan",
    })
    assert resp.status_code == 200
    assert resp.json()["created"] is True


@pytest.mark.integration
def test_create_thread_idempotent(patched_sessionlocal):
    client.post("/internal/data/threads?user_id=1", json={"thread_id": "mossy-oak-mist"})
    resp = client.post("/internal/data/threads?user_id=1", json={"thread_id": "mossy-oak-mist"})
    assert resp.status_code == 200
    assert resp.json()["created"] is False


# ---------------------------------------------------------------------------
# GET /internal/data/threads — list
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_threads_empty(patched_sessionlocal):
    resp = client.get("/internal/data/threads?user_id=1")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_threads_returns_users_threads(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(id="fern-a", user_id=1, created_at=now, last_active_at=now))
    db_session.add(Thread(id="fern-b", user_id=1, created_at=now, last_active_at=now))
    db_session.add(Thread(id="fern-c", user_id=2, created_at=now, last_active_at=now))
    db_session.commit()

    resp = client.get("/internal/data/threads?user_id=1")
    assert resp.status_code == 200
    ids = [t["thread_id"] for t in resp.json()]
    assert "fern-a" in ids
    assert "fern-b" in ids
    assert "fern-c" not in ids


@pytest.mark.integration
def test_list_threads_preserves_thread_view_shape(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(
        id="shape-thread",
        user_id=1,
        title="Shape check",
        project_id="project-1",
        last_message_preview="Last message",
        last_active_at=now,
        message_count=7,
        pinned_context=[{"subject_type": "project", "subject_id": "project-1"}],
        session_context={"focus_text": "Water tomatoes", "source": "inferred"},
        created_at=now,
    ))
    db_session.commit()

    resp = client.get("/internal/data/threads?user_id=1")

    assert resp.status_code == 200
    body = resp.json()[0]
    expected = {
        "thread_id": "shape-thread",
        "title": "Shape check",
        "project_id": "project-1",
        "last_message_preview": "Last message",
        "last_active_at": now.isoformat(),
        "message_count": 7,
        "pinned_context": [{"subject_type": "project", "subject_id": "project-1"}],
        "session_context": {"focus_text": "Water tomatoes", "source": "inferred"},
        "created_at": now.isoformat(),
    }
    assert list(body) == list(THREAD_VIEW_FIELDS)
    assert set(body) == THREAD_VIEW_KEYS
    assert body == expected
    assert resp.text == _compact_json([expected])


@pytest.mark.integration
def test_list_threads_sorted_by_last_active(patched_sessionlocal, db_session):
    from datetime import timedelta
    now = _now()
    db_session.add(Thread(id="old-thread", user_id=1, created_at=now,
                          last_active_at=now - timedelta(hours=2)))
    db_session.add(Thread(id="new-thread", user_id=1, created_at=now,
                          last_active_at=now))
    db_session.commit()

    resp = client.get("/internal/data/threads?user_id=1")
    ids = [t["thread_id"] for t in resp.json()]
    assert ids[0] == "new-thread"
    assert ids[1] == "old-thread"


# ---------------------------------------------------------------------------
# GET /internal/data/threads/{id} — get one
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_thread(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(
        id="velvet-pine-frost",
        user_id=1,
        title="My garden plan",
        created_at=now,
        last_active_at=now,
        message_count=3,
    ))
    db_session.commit()

    resp = client.get("/internal/data/threads/velvet-pine-frost?user_id=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["thread_id"] == "velvet-pine-frost"
    assert data["title"] == "My garden plan"
    assert data["message_count"] == 3


@pytest.mark.integration
def test_get_thread_preserves_thread_view_shape_and_defaults(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(
        id="default-thread",
        user_id=1,
        created_at=now,
        last_active_at=None,
    ))
    db_session.commit()

    resp = client.get("/internal/data/threads/default-thread?user_id=1")

    assert resp.status_code == 200
    body = resp.json()
    expected = {
        "thread_id": "default-thread",
        "title": None,
        "project_id": None,
        "last_message_preview": None,
        "last_active_at": None,
        "message_count": 0,
        "pinned_context": [],
        "session_context": None,
        "created_at": now.isoformat(),
    }
    assert list(body) == list(THREAD_VIEW_FIELDS)
    assert set(body) == THREAD_VIEW_KEYS
    assert body == expected
    assert resp.text == _compact_json(expected)


@pytest.mark.integration
def test_get_thread_not_found(patched_sessionlocal):
    resp = client.get("/internal/data/threads/nonexistent?user_id=1")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_thread_wrong_user(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(id="other-user-thread", user_id=2, created_at=now))
    db_session.commit()

    resp = client.get("/internal/data/threads/other-user-thread?user_id=1")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET/PATCH /internal/data/threads/{id}/session-context — #148
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_thread_session_context_unset(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(id="unset-context-thread", user_id=1, created_at=now))
    db_session.commit()

    resp = client.get("/internal/data/threads/unset-context-thread/session-context?user_id=1")

    assert resp.status_code == 200
    assert resp.json() == {
        "time_text": None,
        "energy_text": None,
        "focus_text": None,
        "focus_context": [],
        "source": "unset",
        "updated_at": None,
    }


@pytest.mark.integration
def test_get_thread_session_context_resolves_focus_context_labels(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    now = _now()
    plant = make_plant(db_session, seed_garden_profile, name="Cherry Tomato", variety="Sungold")
    db_session.add(Thread(
        id="stored-context-thread",
        user_id=1,
        created_at=now,
        session_context={
            "time_text": "45 minutes, all afternoon",
            "energy_text": "low, focused",
            "focus_text": "How do I fertilize the cherry tomatoes?",
            "focus_context": [{"subject_type": "plant", "subject_id": plant.id}],
            "source": "inferred",
            "updated_at": now.isoformat(),
        },
    ))
    db_session.commit()

    resp = client.get("/internal/data/threads/stored-context-thread/session-context?user_id=1")

    assert resp.status_code == 200
    assert resp.json() == {
        "time_text": "45 minutes, all afternoon",
        "energy_text": "low, focused",
        "focus_text": "How do I fertilize the cherry tomatoes?",
        "focus_context": [
            {"subject_type": "plant", "subject_id": plant.id, "label": "Cherry Tomato (Sungold)"}
        ],
        "source": "inferred",
        "updated_at": now.isoformat(),
    }


@pytest.mark.integration
def test_patch_thread_session_context_updates_user_values(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    now = _now()
    db_session.add(Thread(id="editable-context-thread", user_id=1, created_at=now))
    db_session.commit()

    resp = client.patch("/internal/data/threads/editable-context-thread/session-context?user_id=1", json={
        "time_text": "45 minutes, all afternoon",
        "energy_text": "low, focused, tired but can water",
        "focus_text": "How do I fertilize the cherry tomatoes?",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["time_text"] == "45 minutes, all afternoon"
    assert body["energy_text"] == "low, focused, tired but can water"
    assert body["focus_text"] == "How do I fertilize the cherry tomatoes?"
    assert body["focus_context"] == []
    assert body["source"] == "user"
    assert body["updated_at"]

    db_session.expire_all()
    stored = db_session.get(Thread, "editable-context-thread").session_context
    assert stored["source"] == "user"
    assert stored["time_text"] == "45 minutes, all afternoon"
    assert stored["energy_text"] == "low, focused, tired but can water"
    assert stored["focus_text"] == "How do I fertilize the cherry tomatoes?"


@pytest.mark.integration
def test_patch_thread_session_context_accepts_multiple_focus_context_entries(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    now = _now()
    project = make_project(db_session, seed_garden_profile, name="Tomato Sprint")
    plant = make_plant(db_session, seed_garden_profile, name="Cherry Tomato", variety="Sungold")
    task = Task(
        id="fertilize-task",
        project_id=project.id,
        source_type="generated",
        generator_key="test.task",
        title="Fertilize tomato after transplant",
        type="maintenance",
        status="pending",
        estimated_minutes=20,
    )
    db_session.add_all([task, Thread(id="focus-context-thread", user_id=1, created_at=now)])
    db_session.commit()

    resp = client.patch("/internal/data/threads/focus-context-thread/session-context?user_id=1", json={
        "focus_context": [
            {"subject_type": "plant", "subject_id": plant.id},
            {"subject_type": "task", "subject_id": task.id},
        ],
    })

    assert resp.status_code == 200
    assert resp.json()["focus_context"] == [
        {"subject_type": "plant", "subject_id": plant.id, "label": "Cherry Tomato (Sungold)"},
        {"subject_type": "task", "subject_id": task.id, "label": "Fertilize tomato after transplant"},
    ]

    db_session.expire_all()
    assert db_session.get(Thread, "focus-context-thread").session_context["focus_context"] == [
        {"subject_type": "plant", "subject_id": plant.id},
        {"subject_type": "task", "subject_id": task.id},
    ]


@pytest.mark.integration
def test_patch_thread_session_context_allows_explicit_clear(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(
        id="clear-context-thread",
        user_id=1,
        created_at=now,
        session_context={
            "time_text": "all afternoon",
            "energy_text": "high",
            "focus_text": "fertilize tomatoes",
            "focus_context": [{"subject_type": "plant", "subject_id": "plant-1"}],
            "source": "user",
            "updated_at": now.isoformat(),
        },
    ))
    db_session.commit()

    resp = client.patch("/internal/data/threads/clear-context-thread/session-context?user_id=1", json={
        "time_text": None,
        "focus_context": None,
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["time_text"] is None
    assert body["energy_text"] == "high"
    assert body["focus_text"] == "fertilize tomatoes"
    assert body["focus_context"] == []
    assert body["source"] == "user"


@pytest.mark.integration
def test_patch_thread_session_context_rejects_empty_patch(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(id="empty-context-patch-thread", user_id=1, created_at=now))
    db_session.commit()

    resp = client.patch("/internal/data/threads/empty-context-patch-thread/session-context?user_id=1", json={})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "No session context fields provided"


@pytest.mark.integration
def test_patch_thread_session_context_rejects_unknown_fields(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(id="unknown-context-patch-thread", user_id=1, created_at=now))
    db_session.commit()

    resp = client.patch("/internal/data/threads/unknown-context-patch-thread/session-context?user_id=1", json={
        "focus_text": "tomatoes",
        "mood": "determined",
    })

    assert resp.status_code == 422


@pytest.mark.integration
@pytest.mark.parametrize("payload", [
    {"focus_context": [{"subject_type": "plant", "subject_id": str(i)} for i in range(11)]},
    {"focus_context": [{"subject_type": "trellis", "subject_id": "t1"}]},
])
def test_patch_thread_session_context_validates_fields(patched_sessionlocal, db_session, payload):
    now = _now()
    db_session.add(Thread(id=f"invalid-context-{next(iter(payload))}", user_id=1, created_at=now))
    db_session.commit()

    resp = client.patch(f"/internal/data/threads/invalid-context-{next(iter(payload))}/session-context?user_id=1", json=payload)

    assert resp.status_code in {400, 422}


@pytest.mark.integration
def test_thread_session_context_wrong_user_404(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(id="protected-context-thread", user_id=2, created_at=now))
    db_session.commit()

    get_resp = client.get("/internal/data/threads/protected-context-thread/session-context?user_id=1")
    patch_resp = client.patch("/internal/data/threads/protected-context-thread/session-context?user_id=1", json={
        "focus_text": "tomatoes",
    })

    assert get_resp.status_code == 404
    assert patch_resp.status_code == 404


@pytest.mark.integration
def test_patch_thread_session_context_rejects_other_users_focus_object(
    patched_sessionlocal,
    db_session,
):
    now = _now()
    other_profile = make_profile(db_session, user_id="2", location_label="Oakland, CA")
    other_plant = make_plant(db_session, other_profile, user_id="2", name="Other Tomato")
    db_session.add(Thread(id="other-focus-context-thread", user_id=1, created_at=now))
    db_session.commit()

    resp = client.patch("/internal/data/threads/other-focus-context-thread/session-context?user_id=1", json={
        "focus_context": [{"subject_type": "plant", "subject_id": other_plant.id}],
    })

    assert resp.status_code == 400


@pytest.mark.integration
def test_session_context_intake_persists_inferred_context(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    from langchain.messages import HumanMessage
    from agent.core.nodes import session_context_intake

    config = {"configurable": {"thread_id": "inferred-context-thread", "user_id": "1"}}
    state = {"messages": [HumanMessage(content="I have 30 minutes and low energy for a quick container task.")]}

    result = session_context_intake(state, config)

    assert result["session_context"]["focus_text"] == "I have 30 minutes and low energy for a quick container task."
    assert result["session_context"]["focus_context"] == []
    assert "available_minutes" not in result["session_context"]
    assert "energy_level" not in result["session_context"]

    db_session.expire_all()
    thread = db_session.get(Thread, "inferred-context-thread")
    assert thread.session_context["source"] == "inferred"
    assert thread.session_context["focus_text"] == "I have 30 minutes and low energy for a quick container task."
    assert thread.session_context["updated_at"]


@pytest.mark.integration
def test_session_context_intake_uses_user_updated_context(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    from langchain.messages import HumanMessage
    from agent.core.nodes import session_context_intake

    now = _now()
    db_session.add(Thread(
        id="manual-context-thread",
        user_id=1,
        created_at=now,
        session_context={
            "time_text": "5 minutes",
            "energy_text": "high",
            "focus_text": "water containers",
            "source": "user",
            "updated_at": now.isoformat(),
        },
    ))
    db_session.commit()

    result = session_context_intake(
        {"messages": [HumanMessage(content="I have 2 hours and low energy outside.")]},
        {"configurable": {"thread_id": "manual-context-thread", "user_id": "1"}},
    )

    assert result["session_context"]["time_text"] == "5 minutes"
    assert result["session_context"]["energy_text"] == "high"
    assert result["session_context"]["focus_text"] == "water containers"

    db_session.expire_all()
    thread = db_session.get(Thread, "manual-context-thread")
    assert thread.session_context["time_text"] == "5 minutes"
    assert thread.session_context["energy_text"] == "high"
    assert thread.session_context["source"] == "user"


@pytest.mark.integration
def test_session_context_intake_refreshes_existing_inferred_context(
    patched_sessionlocal,
    db_session,
):
    from langchain.messages import HumanMessage
    from agent.core.nodes import session_context_intake

    now = _now()
    db_session.add(Thread(
        id="refresh-inferred-context-thread",
        user_id=1,
        created_at=now,
        session_context={
            "focus_text": "old inferred focus",
            "source": "inferred",
            "updated_at": now.isoformat(),
        },
    ))
    db_session.commit()

    result = session_context_intake(
        {"messages": [HumanMessage(content="I have 60 minutes and low energy for a quick bed task.")]},
        {"configurable": {"thread_id": "refresh-inferred-context-thread", "user_id": "1"}},
    )

    assert result["session_context"]["focus_text"] == "I have 60 minutes and low energy for a quick bed task."

    db_session.expire_all()
    stored = db_session.get(Thread, "refresh-inferred-context-thread").session_context
    assert stored["focus_text"] == "I have 60 minutes and low energy for a quick bed task."
    assert stored["source"] == "inferred"


@pytest.mark.integration
def test_session_context_intake_does_not_use_other_users_thread_context(
    patched_sessionlocal,
    db_session,
):
    from langchain.messages import HumanMessage
    from agent.core.nodes import session_context_intake

    now = _now()
    db_session.add(Thread(
        id="shared-external-thread-id",
        user_id="2",
        title="Other user thread",
        created_at=now,
        last_active_at=now,
        message_count=9,
        pinned_context=[{"subject_type": "project", "subject_id": "secret-project"}],
        session_context={
            "time_text": "5 minutes",
            "energy_text": "high",
            "source": "user",
            "updated_at": now.isoformat(),
        },
    ))
    db_session.commit()

    result = session_context_intake(
        {"messages": [HumanMessage(content="I have 45 minutes and low energy.")]},
        {"configurable": {"thread_id": "shared-external-thread-id", "user_id": "1"}},
    )

    assert result["session_context"]["focus_text"] == "I have 45 minutes and low energy."
    assert result.get("pinned_context_text") is None

    db_session.expire_all()
    other_thread = db_session.get(Thread, "shared-external-thread-id")
    assert other_thread.user_id == "2"
    assert other_thread.message_count == 9
    assert other_thread.session_context["time_text"] == "5 minutes"
    assert other_thread.session_context["energy_text"] == "high"


@pytest.mark.integration
def test_session_context_intake_injects_text_first_summary_separate_from_pinned_context(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    from langchain.messages import HumanMessage
    from agent.core.nodes import session_context_intake

    now = _now()
    plant = make_plant(db_session, seed_garden_profile, name="Cherry Tomato", variety="Sungold")
    db_session.add(Thread(
        id="summary-context-thread",
        user_id=1,
        created_at=now,
        pinned_context=[{"subject_type": "plant", "subject_id": plant.id}],
        session_context={
            "time_text": "45 minutes",
            "energy_text": "low but focused",
            "focus_text": "How do I fertilize the cherry tomatoes?",
            "focus_context": [{"subject_type": "plant", "subject_id": plant.id}],
            "source": "user",
            "updated_at": now.isoformat(),
        },
    ))
    db_session.commit()

    result = session_context_intake(
        {"messages": [HumanMessage(content="What should I do?")]},
        {"configurable": {"thread_id": "summary-context-thread", "user_id": "1"}},
    )

    assert result["session_context_text"] == "\n".join([
        "Time available: 45 minutes",
        "Energy: low but focused",
        "Thread focus: How do I fertilize the cherry tomatoes?",
        "Focus objects:",
        f"- plant: Cherry Tomato (Sungold) ({plant.id})",
    ])
    assert result["pinned_context_text"]
    assert result["session_context_text"] != result["pinned_context_text"]


# ---------------------------------------------------------------------------
# GET /internal/data/threads/{id}/messages — message history
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_thread_messages_empty_thread(patched_sessionlocal, db_session):
    """New thread with no chat history returns empty messages list."""
    now = _now()
    db_session.add(Thread(id="silent-moss-vale", user_id=1, created_at=now))
    db_session.commit()

    resp = client.get("/internal/data/threads/silent-moss-vale/messages?user_id=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["thread_id"] == "silent-moss-vale"
    assert data["messages"] == []


@pytest.mark.integration
def test_get_thread_messages_normalizes_provider_content_blocks(monkeypatch):
    """Refresh history should render assistant text, not provider metadata reprs."""

    class FakeAgent:
        def get_state(self, config):
            return SimpleNamespace(values={
                "messages": [
                    HumanMessage(content="hello world"),
                    SimpleNamespace(type="ai", content=[]),
                    SimpleNamespace(type="tool", content="Error: no garden profile found."),
                    AIMessage(content=[
                        {"type": "text", "text": "I can", "extras": {"signature": "opaque"}},
                        "'t show provider metadata.",
                    ]),
                ],
            })

    monkeypatch.setattr(graph_module, "agent", FakeAgent())

    resp = client.get("/internal/data/threads/content-block-history/messages?user_id=1")

    assert resp.status_code == 200
    assert resp.json()["messages"] == [
        {"role": "user", "content": "hello world", "type": "human"},
        {"role": "assistant", "content": "I can't show provider metadata.", "type": "ai"},
    ]


# ---------------------------------------------------------------------------
# DELETE /internal/data/threads/{id} — delete
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_delete_thread(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(id="ancient-willow-rain", user_id=1, created_at=now))
    db_session.commit()

    resp = client.delete("/internal/data/threads/ancient-willow-rain?user_id=1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    resp2 = client.get("/internal/data/threads/ancient-willow-rain?user_id=1")
    assert resp2.status_code == 404


@pytest.mark.integration
def test_delete_thread_not_found(patched_sessionlocal):
    resp = client.delete("/internal/data/threads/ghost-thread?user_id=1")
    assert resp.status_code == 404


@pytest.mark.integration
def test_delete_thread_wrong_user(patched_sessionlocal, db_session):
    now = _now()
    db_session.add(Thread(id="protected-fern", user_id=2, created_at=now))
    db_session.commit()

    resp = client.delete("/internal/data/threads/protected-fern?user_id=1")
    assert resp.status_code == 404
