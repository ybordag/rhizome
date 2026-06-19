"""Tests for thread management endpoints."""

import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from db.models import Thread

client = TestClient(app)


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
