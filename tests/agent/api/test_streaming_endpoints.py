"""
Regression tests for #141: the SSE streaming endpoints
(`POST /internal/agent/stream`, `POST /internal/agent/resume/stream`) raised
`NotImplementedError` from the sync-only checkpointer's `aget_tuple()` before
yielding any bytes — `agent.astream_events()` requires the checkpointer's
async interface, and `SqliteSaver`/`PostgresSaver` don't implement it.

These exercise the real graph (not a mocked router) through the actual HTTP
path, with a genuinely async-capable checkpointer (`AsyncSqliteSaver`) built
the same way `agent/api/app.py`'s lifespan builds the production one — the
exact code path that was broken. The model is faked (as in every other graph
test in this suite); the checkpointer and graph wiring are real.

Note: `agent.core.graph` reads `DATABASE_URL` into `_use_postgres` at import
time, but importing it transitively imports `agent.core.nodes` ->
`agent.core.model`, which calls `load_dotenv()` unconditionally. That
silently repopulates `DATABASE_URL` from `.env` even though
`tests/conftest.py` pops it first — and `.env` points at the real shared dev
Postgres. Every test below that wants SQLite explicitly monkeypatches
`graph_module._use_postgres = False` rather than trusting the env var; the
one test that *wants* Postgres (`test_async_checkpointer_postgres_branch`)
forces `True` instead, for the same reason — neither relies on what the
import side effect happened to leave behind.
"""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager

import httpx
import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from httpx import ASGITransport
from langchain.messages import HumanMessage
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent.api.app import app
from agent.api.routers import get_streaming_agent, _is_user_visible_llm_stream_event
from agent.core import graph as graph_module
from agent.core import nodes
from agent.domain import triage as triage_module
from db.models import GardeningProject
from tests.support.fakes import make_ai_message, make_tool_call_message


def _parse_sse_events(body: bytes) -> list[dict]:
    """Parse `data: {...}\\n\\n` frames into a list of decoded event dicts,
    instead of substring-matching the raw bytes — substring checks can't
    tell "done" appearing as the final event from it appearing inside some
    unrelated token's content."""
    events = []
    for frame in body.decode().split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        assert frame.startswith("data: "), f"unexpected SSE frame shape: {frame!r}"
        events.append(json.loads(frame[len("data: "):]))
    return events


def test_user_visible_llm_stream_filter_only_allows_llm_call_tokens():
    """The SSE router must not forward internal model streams.

    Keep this predicate-level contract explicit: graph integration tests prove
    the real triage leak is fixed, while this fast test guards future changes
    to the shared filter used by both stream endpoints.
    """
    assert _is_user_visible_llm_stream_event({
        "event": "on_chat_model_stream",
        "metadata": {"langgraph_node": "llm_call"},
    })
    assert not _is_user_visible_llm_stream_event({
        "event": "on_chat_model_stream",
        "metadata": {"langgraph_node": "triage_reasoner"},
    })
    assert not _is_user_visible_llm_stream_event({
        "event": "on_chat_model_stream",
        "metadata": {"langgraph_node": "tool_node"},
    })
    assert not _is_user_visible_llm_stream_event({
        "event": "on_chat_model_stream",
        "metadata": {},
    })
    assert not _is_user_visible_llm_stream_event({
        "event": "on_chat_model_end",
        "metadata": {"langgraph_node": "llm_call"},
    })


@asynccontextmanager
async def _streaming_agent_override(test_graph):
    """Install `test_graph` as the streaming agent dependency for the
    duration of the block, restoring whatever (if anything) was there
    before. `app.dependency_overrides` is global mutable state on the
    shared `app` object — fine under pytest's default sequential execution,
    but this guards against silent double-override if that ever changes
    (e.g. a future move to pytest-xdist) instead of one test clobbering
    another's override.
    """
    previous = app.dependency_overrides.get(get_streaming_agent)
    assert previous is None, "streaming agent override already set — unexpected test overlap"
    app.dependency_overrides[get_streaming_agent] = lambda: test_graph
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_streaming_agent, None)
        else:
            app.dependency_overrides[get_streaming_agent] = previous


async def _build_sqlite_streaming_graph(monkeypatch, tmp_path, model_with_tools):
    monkeypatch.setattr(nodes, "model_with_tools", model_with_tools)
    monkeypatch.setenv("RHIZOME_CHECKPOINT_SQLITE_PATH", str(tmp_path / "stream_checkpoints.db"))
    monkeypatch.setattr(graph_module, "_use_postgres", False)
    checkpointer, aclose = await graph_module.build_async_checkpointer()
    test_graph = graph_module.build_agent(checkpointer)
    return test_graph, aclose


async def _post_sse(path: str, payload: dict) -> bytes:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("POST", path, json=payload) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
    return body


@pytest.mark.graph
def test_stream_agent_emits_token_and_done_events(
    monkeypatch, tmp_path, seed_garden_profile, patched_sessionlocal,
):
    """Uses a genuinely streaming-capable fake model (GenericFakeChatModel,
    a real langchain_core Runnable) instead of the plain FakeBoundModel used
    elsewhere — FakeBoundModel.invoke() is a bare Python call, not a traced
    Runnable invocation, so astream_events() never emits on_chat_model_stream
    for it. That's fine for the other tests here (they're about the pipe
    completing at all, not about token forwarding specifically), but it means
    none of them could ever catch a regression in the
    `if event["event"] == "on_chat_model_stream"` branch in
    agent/api/routers.py — this test exists to cover exactly that branch."""
    streaming_model = GenericFakeChatModel(messages=iter([AIMessage(content="Hello from the stream.")]))

    async def run():
        test_graph, aclose = await _build_sqlite_streaming_graph(monkeypatch, tmp_path, streaming_model)
        async with _streaming_agent_override(test_graph):
            try:
                return await _post_sse("/internal/agent/stream", {
                    "user_id": "1", "thread_id": "stream-thread-token-test", "message": "hi",
                })
            finally:
                await aclose()

    body = asyncio.run(run())
    events = _parse_sse_events(body)

    assert events, "stream body was empty — the async checkpointer bug (#141) reproduces as a silently empty stream"
    token_events = [e for e in events if e["type"] == "token"]
    assert token_events, "expected at least one token event from the streaming-capable fake model"
    assert "".join(e["content"] for e in token_events) == "Hello from the stream."
    assert events[-1] == {"type": "done"}


@pytest.mark.graph
def test_stream_agent_filters_internal_triage_model_tokens(
    monkeypatch, tmp_path, seed_garden_profile, patched_sessionlocal,
):
    """Regression for #142.

    A graph turn can include chat-model calls before the final assistant
    response. Triage summary generation is one of those internal calls. The
    SSE endpoint must only forward tokens from the user-facing `llm_call`
    node; otherwise clients see internal context text as a duplicate or
    confusing extra assistant reply.
    """
    triage_model = GenericFakeChatModel(messages=iter([AIMessage(content="TRIAGE SHOULD NOT STREAM")]))
    final_model = GenericFakeChatModel(messages=iter([AIMessage(content="FINAL USER RESPONSE")]))
    monkeypatch.setattr(triage_module, "triage_summary_model", triage_model)

    async def run():
        test_graph, aclose = await _build_sqlite_streaming_graph(monkeypatch, tmp_path, final_model)
        async with _streaming_agent_override(test_graph):
            try:
                return await _post_sse("/internal/agent/stream", {
                    "user_id": "1", "thread_id": "stream-thread-internal-filter", "message": "hi",
                })
            finally:
                await aclose()

    body = asyncio.run(run())
    events = _parse_sse_events(body)
    token_text = "".join(e["content"] for e in events if e["type"] == "token")

    assert token_text == "FINAL USER RESPONSE"
    assert "TRIAGE SHOULD NOT STREAM" not in token_text
    assert events[-1] == {"type": "done"}


@pytest.mark.graph
def test_stream_agent_emits_done_event(
    monkeypatch, tmp_path, fake_bound_model, seed_garden_profile, patched_sessionlocal,
):
    fake_bound_model.queue(make_ai_message("Hello from the stream."))

    async def run():
        test_graph, aclose = await _build_sqlite_streaming_graph(monkeypatch, tmp_path, fake_bound_model)
        async with _streaming_agent_override(test_graph):
            try:
                return await _post_sse("/internal/agent/stream", {
                    "user_id": "1", "thread_id": "stream-thread-1", "message": "hi",
                })
            finally:
                await aclose()

    body = asyncio.run(run())
    events = _parse_sse_events(body)

    # Before the fix, this body was empty — astream_events() raised
    # NotImplementedError on the checkpointer's aget_tuple() before a single
    # byte was yielded, and StreamingResponse swallowed it into a 200 with a
    # zero-length body (exactly the live repro in #141).
    assert events, "stream body was empty — the async checkpointer bug (#141) reproduces as a silently empty stream"
    assert events[-1] == {"type": "done"}


@pytest.mark.graph
def test_resume_agent_stream_emits_done_event(
    monkeypatch, tmp_path, fake_bound_model, seed_garden_profile, db_session, patched_sessionlocal,
):
    """Same bug, on the resume path — agent.get_state() also has to become
    the async aget_state() once the checkpointer is async-only."""
    project = GardeningProject(
        user_id="1",
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
    project_id = project.id

    # Only one model call happens: on a negative resume, interaction_node
    # short-circuits with a hardcoded cancellation message and never calls
    # the model again (same as test_graph.py's sync equivalent of this case).
    fake_bound_model.queue(
        make_tool_call_message(
            "Deleting project", name="delete_project",
            args={"project_id": project_id}, call_id="call-1",
        ),
    )

    async def run():
        test_graph, aclose = await _build_sqlite_streaming_graph(monkeypatch, tmp_path, fake_bound_model)
        async with _streaming_agent_override(test_graph):
            try:
                config = {"configurable": {"thread_id": "stream-thread-resume", "user_id": "1"}}
                # Pause the graph on the destructive-tool-call interrupt
                # directly via the same async checkpointer the HTTP resume
                # call will use.
                await test_graph.ainvoke({"messages": [HumanMessage(content="delete it")]}, config=config)
                state = await test_graph.aget_state(config)
                assert "interaction_node" in state.next

                body = await _post_sse("/internal/agent/resume/stream", {
                    "user_id": "1", "thread_id": "stream-thread-resume", "resolution": "no",
                })

                # Confirm the resume actually completed the run (no leftover
                # interrupt) via the same async accessor the route itself
                # uses — the SSE body alone doesn't prove the graph reached
                # a clean end state, just that *some* bytes came back.
                final_state = await test_graph.aget_state(config)
                return body, final_state
            finally:
                await aclose()

    body, final_state = asyncio.run(run())
    events = _parse_sse_events(body)

    assert events, "resume stream body was empty — same async checkpointer bug as #141, on the resume path"
    assert events[-1] == {"type": "done"}
    assert not any(e["type"] == "interaction" for e in events), \
        "resolution='no' should not leave a new pending interrupt"
    assert not final_state.next, "graph should have run to completion after resume, not stayed paused"
    assert final_state.values["messages"][-1].content == "Operation cancelled. No changes were made."

    db_session.expire_all()
    assert db_session.query(GardeningProject).filter(GardeningProject.id == project_id).first() is not None


def _postgres_checkpoint_url() -> str:
    """The real dev Postgres URL, read directly from `.env` rather than from
    `graph_module._database_url` — that module attribute is now reliably the
    SQLite URL `conftest.py` forces for the whole suite (the #141 postmortem
    fix), so it can no longer be (ab)used to find the dev Postgres URL the way
    it could when DATABASE_URL leaked through `load_dotenv()` by accident."""
    database_url = dotenv_values(".env").get("DATABASE_URL", "")
    return database_url.replace("postgresql+psycopg2://", "postgresql://")


def _delete_postgres_checkpoint_rows(thread_id: str) -> None:
    import psycopg
    with psycopg.connect(_postgres_checkpoint_url(), options="-csearch_path=rhizome", autocommit=True) as conn:
        with conn.cursor() as cur:
            for table in ("checkpoint_blobs", "checkpoint_writes", "checkpoints"):
                cur.execute(f"DELETE FROM rhizome.{table} WHERE thread_id = %s", (thread_id,))


@pytest.mark.graph
def test_async_checkpointer_postgres_branch(monkeypatch, fake_bound_model, seed_garden_profile, patched_sessionlocal):
    """The Postgres branch of build_async_checkpointer() (AsyncPostgresSaver)
    has no other automated coverage — every other test in this file forces
    the SQLite branch. A typo in the AsyncConnection/row_factory wiring there
    would only ever surface live, against staging/prod. Runs against the
    local dev Postgres instance from .env; skips cleanly if it's unreachable
    (e.g. CI without a local Postgres). Uses a random thread_id and deletes
    its own checkpoint rows on the way out — the SQLite tests don't need
    this since they each get a throwaway tmp_path file instead."""
    import psycopg

    try:
        with psycopg.connect(_postgres_checkpoint_url(), connect_timeout=2):
            pass
    except Exception as exc:
        pytest.skip(f"local dev Postgres unreachable, skipping: {exc}")

    fake_bound_model.queue(make_ai_message("Hello from Postgres."))
    monkeypatch.setattr(nodes, "model_with_tools", fake_bound_model)
    monkeypatch.setattr(graph_module, "_use_postgres", True)
    # build_async_checkpointer() reads the module-level _database_url, which
    # conftest.py now reliably forces to the SQLite URL for the whole suite —
    # point it at the real dev Postgres URL for just this test.
    monkeypatch.setattr(graph_module, "_database_url", dotenv_values(".env").get("DATABASE_URL", ""))
    thread_id = f"test-postgres-checkpointer-{uuid.uuid4()}"

    async def run():
        checkpointer, aclose = await graph_module.build_async_checkpointer()
        try:
            test_graph = graph_module.build_agent(checkpointer)
            config = {"configurable": {"thread_id": thread_id, "user_id": "1"}}
            result = await test_graph.ainvoke({"messages": [HumanMessage(content="hi")]}, config=config)
            state = await test_graph.aget_state(config)
            return result, state
        finally:
            await aclose()

    try:
        result, state = asyncio.run(run())
        assert result["messages"][-1].content == "Hello from Postgres."
        assert not state.next
    finally:
        _delete_postgres_checkpoint_rows(thread_id)


@pytest.mark.graph
def test_app_lifespan_builds_usable_streaming_agent(
    monkeypatch, tmp_path, fake_bound_model, seed_garden_profile, patched_sessionlocal,
):
    """Every other test above overrides get_streaming_agent via
    app.dependency_overrides, which never touches agent/api/app.py's
    lifespan at all — it's pure substitution. Nothing else in this suite
    verifies the real lifespan itself actually builds a usable
    app.state.streaming_agent: plain `TestClient(app)` (the pattern every
    other test file in tests/agent/api/ uses) silently never runs the
    lifespan unless entered as a context manager, so a break in the
    lifespan wiring (a typo in `app.state.streaming_agent = ...`,
    build_async_checkpointer() raising and getting swallowed, etc.) would
    only ever surface live. This test goes through the unmocked
    get_streaming_agent dependency end-to-end instead of overriding it."""
    monkeypatch.setattr(nodes, "model_with_tools", fake_bound_model)
    monkeypatch.setenv("RHIZOME_CHECKPOINT_SQLITE_PATH", str(tmp_path / "lifespan_checkpoints.db"))
    monkeypatch.setattr(graph_module, "_use_postgres", False)
    fake_bound_model.queue(make_ai_message("Hello from the real lifespan."))

    assert get_streaming_agent not in app.dependency_overrides, \
        "a previous test left a streaming agent override in place — this test needs the real one"

    try:
        with TestClient(app) as client:
            assert hasattr(app.state, "streaming_agent"), "lifespan did not set app.state.streaming_agent"
            from langgraph.graph.state import CompiledStateGraph
            assert isinstance(app.state.streaming_agent, CompiledStateGraph)

            response = client.post("/internal/agent/stream", json={
                "user_id": "1", "thread_id": "lifespan-thread", "message": "hi",
            })
    finally:
        # FastAPI's lifespan shutdown closes the checkpointer connection but
        # does not clear app.state — left alone, app.state.streaming_agent
        # would persist on this module-level `app` singleton for the rest of
        # the pytest session, pointing at a now-closed connection. Harmless
        # today (every other test either overrides the dependency or never
        # touches the streaming endpoints), but stale closed-resource state
        # on a shared object is worth not leaving behind regardless.
        if hasattr(app.state, "streaming_agent"):
            del app.state.streaming_agent

    assert response.status_code == 200
    events = _parse_sse_events(response.content)
    assert events, "real-lifespan stream body was empty"
    assert events[-1] == {"type": "done"}
