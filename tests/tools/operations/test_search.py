"""Tests for agent/domain/search.py — search_entities() and GET /search."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from agent.domain.search import search_entities

client = TestClient(app)
USER = "1"
from tests.support.factories import (
    make_bed,
    make_container,
    make_incident_report,
    make_incident_subject,
    make_plant,
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _subject_ids(result: dict, type_: str) -> list[str]:
    return [r["subject_id"] for r in result["results"] if r["subject_type"] == type_]


def _task_chain(session, profile, user_id="1"):
    """Return (project, revision, generation_run) — minimal task prerequisites."""
    project = make_project(session, profile, user_id=user_id)
    brief = make_project_brief(session, project)
    proposal = make_project_proposal(session, project, brief)
    revision = make_project_revision(session, project, proposal)
    generation_run = make_task_generation_run(session, project=project, revision=revision)
    return project, revision, generation_run


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_empty_query_raises(db_session):
    profile = make_profile(db_session)
    with pytest.raises(ValueError, match="empty"):
        search_entities(db_session, "1", "  ")


@pytest.mark.integration
def test_unknown_type_raises(db_session):
    profile = make_profile(db_session)
    with pytest.raises(ValueError, match="unknown entity type"):
        search_entities(db_session, "1", "tomato", types=["plant", "widget"])


# ---------------------------------------------------------------------------
# Plant
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_plant_ilike_match_on_name(db_session):
    profile = make_profile(db_session)
    container = make_container(db_session, profile)
    p = make_plant(db_session, profile, container=container, name="Cherry Tomato", variety="Sungold")

    result = search_entities(db_session, "1", "cherry", types=["plant"])
    assert p.id in _subject_ids(result, "plant")
    hit = next(r for r in result["results"] if r["subject_id"] == p.id)
    assert "Cherry Tomato" in hit["label"]
    assert "Sungold" in hit["label"]
    assert result["by_type"]["plant"] == 1


@pytest.mark.integration
def test_plant_ilike_match_on_variety(db_session):
    profile = make_profile(db_session)
    p = make_plant(db_session, profile, name="Pepper", variety="Padron")

    result = search_entities(db_session, "1", "padr", types=["plant"])
    assert p.id in _subject_ids(result, "plant")


@pytest.mark.integration
def test_plant_secondary_label_includes_location_and_status(db_session):
    profile = make_profile(db_session)
    container = make_container(db_session, profile, name="Growbag A")
    p = make_plant(db_session, profile, container=container, name="Basil", status="established")

    result = search_entities(db_session, "1", "basil", types=["plant"])
    hit = next(r for r in result["results"] if r["subject_id"] == p.id)
    assert "Growbag A" in hit["secondary_label"]
    assert "established" in hit["secondary_label"]


@pytest.mark.integration
def test_plant_summary_includes_last_care(db_session):
    from datetime import datetime
    profile = make_profile(db_session)
    p = make_plant(
        db_session, profile,
        name="Kale",
        last_watered_at=datetime(2026, 6, 1),
        last_inspected_at=datetime(2026, 6, 10),
    )

    result = search_entities(db_session, "1", "kale", types=["plant"])
    hit = next(r for r in result["results"] if r["subject_id"] == p.id)
    assert "2026-06-10" in hit["summary"]


@pytest.mark.integration
def test_plant_excludes_removed_status(db_session):
    profile = make_profile(db_session)
    p = make_plant(db_session, profile, name="OldTomato", status="removed")

    result = search_entities(db_session, "1", "OldTomato", types=["plant"])
    assert p.id not in _subject_ids(result, "plant")


@pytest.mark.integration
def test_plant_user_isolation(db_session):
    profile_a = make_profile(db_session, user_id="A")
    make_plant(db_session, profile_a, name="SpyTomato", user_id="A")

    result = search_entities(db_session, "B", "SpyTomato", types=["plant"])
    assert result["results"] == []


@pytest.mark.integration
def test_plant_uuid_exact_match(db_session):
    profile = make_profile(db_session)
    p = make_plant(db_session, profile, name="UniqueByID")

    result = search_entities(db_session, "1", p.id, types=["plant"])
    assert p.id in _subject_ids(result, "plant")


# ---------------------------------------------------------------------------
# Bed
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_bed_ilike_match_on_name(db_session):
    profile = make_profile(db_session)
    b = make_bed(db_session, profile, name="South Slope Bed")

    result = search_entities(db_session, "1", "slope", types=["bed"])
    assert b.id in _subject_ids(result, "bed")


@pytest.mark.integration
def test_bed_ilike_match_on_location(db_session):
    profile = make_profile(db_session)
    b = make_bed(db_session, profile, name="Front Bed", location="front_garden")

    result = search_entities(db_session, "1", "front_garden", types=["bed"])
    assert b.id in _subject_ids(result, "bed")


@pytest.mark.integration
def test_bed_summary_includes_active_plant_count(db_session):
    profile = make_profile(db_session)
    bed = make_bed(db_session, profile, name="Herb Bed")
    make_plant(db_session, profile, bed=bed, name="Thyme", status="established")
    make_plant(db_session, profile, bed=bed, name="Rosemary", status="established")
    make_plant(db_session, profile, bed=bed, name="OldMint", status="removed")

    result = search_entities(db_session, "1", "Herb", types=["bed"])
    hit = next(r for r in result["results"] if r["subject_id"] == bed.id)
    assert "2 active" in hit["summary"]


@pytest.mark.integration
def test_bed_user_isolation(db_session):
    profile_x = make_profile(db_session, user_id="X")
    make_bed(db_session, profile_x, name="SecretBed", user_id="X")

    result = search_entities(db_session, "Y", "SecretBed", types=["bed"])
    assert result["results"] == []


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_container_ilike_match_on_name(db_session):
    profile = make_profile(db_session)
    c = make_container(db_session, profile, name="Terracotta Pot")

    result = search_entities(db_session, "1", "terracotta", types=["container"])
    assert c.id in _subject_ids(result, "container")


@pytest.mark.integration
def test_container_secondary_label_includes_type_and_location(db_session):
    profile = make_profile(db_session)
    c = make_container(
        db_session, profile,
        name="Bucket",
        container_type="bucket",
        location="patio",
    )

    result = search_entities(db_session, "1", "bucket", types=["container"])
    hit = next(r for r in result["results"] if r["subject_id"] == c.id)
    assert "bucket" in hit["secondary_label"]
    assert "patio" in hit["secondary_label"]


@pytest.mark.integration
def test_container_user_isolation(db_session):
    profile_a = make_profile(db_session, user_id="A")
    make_container(db_session, profile_a, name="HiddenBag", user_id="A")

    result = search_entities(db_session, "B", "HiddenBag", types=["container"])
    assert result["results"] == []


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_task_ilike_match_on_title(db_session):
    profile = make_profile(db_session)
    project, revision, gen_run = _task_chain(db_session, profile)
    t = make_task(db_session, project, revision, gen_run, title="Inspect tomatoes for aphids")

    result = search_entities(db_session, "1", "aphids", types=["task"])
    assert t.id in _subject_ids(result, "task")


@pytest.mark.integration
def test_task_secondary_label_includes_project_name(db_session):
    profile = make_profile(db_session)
    project, revision, gen_run = _task_chain(db_session, profile)
    make_project(db_session, profile, name="Tomato Project")
    t = make_task(db_session, project, revision, gen_run, title="Stake plants")

    result = search_entities(db_session, "1", "stake", types=["task"])
    hit = next(r for r in result["results"] if r["subject_id"] == t.id)
    assert project.name in hit["secondary_label"]


@pytest.mark.integration
def test_task_excludes_done_and_superseded(db_session):
    profile = make_profile(db_session)
    project, revision, gen_run = _task_chain(db_session, profile)
    done = make_task(db_session, project, revision, gen_run, title="OldTask done", status="done")
    sup = make_task(db_session, project, revision, gen_run, title="OldTask superseded", status="superseded")

    result = search_entities(db_session, "1", "OldTask", types=["task"])
    ids = _subject_ids(result, "task")
    assert done.id not in ids
    assert sup.id not in ids


@pytest.mark.integration
def test_task_summary_shows_scheduled_date(db_session):
    from datetime import datetime
    profile = make_profile(db_session)
    project, revision, gen_run = _task_chain(db_session, profile)
    t = make_task(
        db_session, project, revision, gen_run,
        title="Prune roses",
        scheduled_date=datetime(2026, 7, 4),
        deadline=None,
    )

    result = search_entities(db_session, "1", "prune", types=["task"])
    hit = next(r for r in result["results"] if r["subject_id"] == t.id)
    assert "2026-07-04" in hit["summary"]


@pytest.mark.integration
def test_task_user_isolation(db_session):
    profile_a = make_profile(db_session, user_id="A")
    project_a = make_project(db_session, profile_a, user_id="A")
    brief = make_project_brief(db_session, project_a)
    proposal = make_project_proposal(db_session, project_a, brief)
    revision = make_project_revision(db_session, project_a, proposal)
    gen_run = make_task_generation_run(db_session, project=project_a, revision=revision)
    make_task(db_session, project_a, revision, gen_run, title="SecretTask")

    result = search_entities(db_session, "B", "SecretTask", types=["task"])
    assert result["results"] == []


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_project_ilike_match_on_name(db_session):
    profile = make_profile(db_session)
    p = make_project(db_session, profile, name="Autumn Squash")

    result = search_entities(db_session, "1", "squash", types=["project"])
    assert p.id in _subject_ids(result, "project")


@pytest.mark.integration
def test_project_summary_includes_open_task_count(db_session):
    profile = make_profile(db_session)
    project, revision, gen_run = _task_chain(db_session, profile)
    make_task(db_session, project, revision, gen_run, title="Task A", status="pending")
    make_task(db_session, project, revision, gen_run, title="Task B", status="in_progress")
    make_task(db_session, project, revision, gen_run, title="Task C", status="done")

    result = search_entities(db_session, "1", project.name, types=["project"])
    hit = next(r for r in result["results"] if r["subject_id"] == project.id)
    assert "2 open" in hit["summary"]


@pytest.mark.integration
def test_project_excludes_complete(db_session):
    profile = make_profile(db_session)
    p = make_project(db_session, profile, name="DoneProject", status="complete")

    result = search_entities(db_session, "1", "DoneProject", types=["project"])
    assert p.id not in _subject_ids(result, "project")


@pytest.mark.integration
def test_project_user_isolation(db_session):
    profile_a = make_profile(db_session, user_id="A")
    make_project(db_session, profile_a, name="SecretProject", user_id="A")

    result = search_entities(db_session, "B", "SecretProject", types=["project"])
    assert result["results"] == []


# ---------------------------------------------------------------------------
# Incident
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_incident_ilike_match_on_type(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    inc = make_incident_report(db_session, project_id=project.id, incident_type="blight")

    result = search_entities(db_session, "1", "blight", types=["incident"])
    assert inc.id in _subject_ids(result, "incident")


@pytest.mark.integration
def test_incident_ilike_match_on_summary(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    inc = make_incident_report(
        db_session,
        project_id=project.id,
        summary="Powdery mildew spreading on cucumbers",
    )

    result = search_entities(db_session, "1", "powdery", types=["incident"])
    assert inc.id in _subject_ids(result, "incident")


@pytest.mark.integration
def test_incident_subject_appears_in_summary(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    container = make_container(db_session, profile)
    inc = make_incident_report(db_session, project_id=project.id, incident_type="pest")
    make_incident_subject(
        db_session, inc,
        subject_type="container",
        subject_id=container.id,
    )

    result = search_entities(db_session, "1", "pest", types=["incident"])
    hit = next(r for r in result["results"] if r["subject_id"] == inc.id)
    assert "container" in hit["summary"]


@pytest.mark.integration
def test_incident_excludes_resolved(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    inc = make_incident_report(
        db_session, project_id=project.id,
        incident_type="weed", status="resolved",
    )

    result = search_entities(db_session, "1", "weed", types=["incident"])
    assert inc.id not in _subject_ids(result, "incident")


@pytest.mark.integration
def test_incident_project_user_isolation(db_session):
    profile_a = make_profile(db_session, user_id="A")
    project_a = make_project(db_session, profile_a, user_id="A")
    make_incident_report(db_session, project_id=project_a.id, incident_type="pest")

    result = search_entities(db_session, "B", "pest", types=["incident"])
    assert result["results"] == []


@pytest.mark.integration
def test_incident_projectless_not_returned_to_any_user(db_session):
    # Incidents with no project_id cannot be scoped to an owner and must
    # never appear in search results, regardless of who is searching.
    make_profile(db_session)
    orphan = make_incident_report(db_session, project_id=None, incident_type="blight")

    result_user1 = search_entities(db_session, "1", "blight", types=["incident"])
    result_user2 = search_entities(db_session, "other-user", "blight", types=["incident"])
    assert orphan.id not in _subject_ids(result_user1, "incident")
    assert orphan.id not in _subject_ids(result_user2, "incident")


# ---------------------------------------------------------------------------
# Multi-type and filtering
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_types_filter_limits_to_requested_types(db_session):
    profile = make_profile(db_session)
    make_plant(db_session, profile, name="Aphid Target")
    make_bed(db_session, profile, name="Aphid Target")

    result = search_entities(db_session, "1", "aphid", types=["plant"])
    types_returned = {r["subject_type"] for r in result["results"]}
    assert types_returned == {"plant"}


@pytest.mark.integration
def test_combined_search_returns_multiple_types(db_session):
    profile = make_profile(db_session)
    make_plant(db_session, profile, name="SearchMe Plant")
    make_bed(db_session, profile, name="SearchMe Bed")
    make_container(db_session, profile, name="SearchMe Container")

    result = search_entities(db_session, "1", "SearchMe", types=["plant", "bed", "container"])
    types_returned = {r["subject_type"] for r in result["results"]}
    assert types_returned == {"plant", "bed", "container"}


@pytest.mark.integration
def test_by_type_counts_are_accurate(db_session):
    profile = make_profile(db_session)
    make_plant(db_session, profile, name="CountMe 1")
    make_plant(db_session, profile, name="CountMe 2")

    result = search_entities(db_session, "1", "CountMe", types=["plant", "bed"])
    assert result["by_type"]["plant"] == 2
    assert result["by_type"]["bed"] == 0


@pytest.mark.integration
def test_limit_per_type_is_respected(db_session):
    profile = make_profile(db_session)
    for i in range(8):
        make_plant(db_session, profile, name=f"LimitPlant {i}")

    result = search_entities(db_session, "1", "LimitPlant", types=["plant"], limit_per_type=3)
    assert len([r for r in result["results"] if r["subject_type"] == "plant"]) == 3


@pytest.mark.integration
def test_limit_capped_at_20(db_session):
    profile = make_profile(db_session)
    result = search_entities(db_session, "1", "anything", limit_per_type=999)
    # No assertion on count (empty DB), just confirm no error raised
    assert "results" in result


@pytest.mark.integration
def test_no_results_returns_empty(db_session):
    make_profile(db_session)
    result = search_entities(db_session, "1", "zzznomatch")
    assert result["results"] == []
    assert all(v == 0 for v in result["by_type"].values())


# ---------------------------------------------------------------------------
# GET /internal/data/search — API endpoint (Part 4/5)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_api_search_returns_structured_results(patched_sessionlocal, db_session):
    profile = make_profile(db_session)
    make_plant(db_session, profile, name="Sungold Tomato")

    resp = client.get(f"/internal/data/search?user_id={USER}&q=sungold")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "by_type" in data
    assert any(r["subject_type"] == "plant" for r in data["results"])
    hit = next(r for r in data["results"] if r["subject_type"] == "plant")
    assert "subject_id" in hit
    assert "label" in hit


@pytest.mark.integration
def test_api_search_types_filter(patched_sessionlocal, db_session):
    profile = make_profile(db_session)
    make_plant(db_session, profile, name="Filterme Plant")
    make_bed(db_session, profile, name="Filterme Bed")

    resp = client.get(f"/internal/data/search?user_id={USER}&q=filterme&types=plant")
    assert resp.status_code == 200
    data = resp.json()
    types = {r["subject_type"] for r in data["results"]}
    assert types == {"plant"}


@pytest.mark.integration
def test_api_search_empty_q_returns_400(patched_sessionlocal, db_session):
    make_profile(db_session)
    resp = client.get(f"/internal/data/search?user_id={USER}&q=")
    assert resp.status_code == 400


@pytest.mark.integration
def test_api_search_limit_out_of_range_returns_400(patched_sessionlocal, db_session):
    make_profile(db_session)
    resp = client.get(f"/internal/data/search?user_id={USER}&q=tomato&limit=50")
    assert resp.status_code == 400


@pytest.mark.integration
def test_api_search_unknown_type_returns_400(patched_sessionlocal, db_session):
    make_profile(db_session)
    resp = client.get(f"/internal/data/search?user_id={USER}&q=tomato&types=widget")
    assert resp.status_code == 400


@pytest.mark.integration
def test_api_search_by_type_counts_present_for_all_types(patched_sessionlocal, db_session):
    make_profile(db_session)
    resp = client.get(f"/internal/data/search?user_id={USER}&q=anything")
    assert resp.status_code == 200
    by_type = resp.json()["by_type"]
    assert set(by_type.keys()) == {"plant", "bed", "container", "task", "project", "incident"}


@pytest.mark.integration
def test_api_search_user_isolation(patched_sessionlocal, db_session):
    # Plant belonging to user A must not appear in user B's API response.
    profile_a = make_profile(db_session, user_id="user-a")
    make_plant(db_session, profile_a, name="PrivatePlant", user_id="user-a")

    resp = client.get("/internal/data/search?user_id=user-b&q=PrivatePlant")
    assert resp.status_code == 200
    assert resp.json()["results"] == []
