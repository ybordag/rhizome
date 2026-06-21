"""
Rhizome internal FastAPI service.

Two routers:
  /internal/agent  — LangGraph graph execution (AI operations)
  /internal/data   — direct SQLAlchemy queries (CRUD, no agent overhead)

Called by Cambium only. Not exposed to the public internet.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent.api.routers import agent_router, data_router
from agent.core.graph import build_agent, build_async_checkpointer
from db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # The SSE streaming endpoints (/internal/agent/stream, /internal/agent/
    # resume/stream) call agent.astream_events()/aget_state(), which require
    # an async-capable checkpointer — the module-level `agent` in
    # agent.core.graph uses a sync-only one (SqliteSaver/PostgresSaver) and
    # raises NotImplementedError on those calls (#141). Build a second agent
    # backed by the async saver classes, scoped to this app's lifespan so it
    # shares the running event loop with the requests that will use it.
    streaming_checkpointer, close_streaming_checkpointer = await build_async_checkpointer()
    app.state.streaming_agent = build_agent(streaming_checkpointer)

    yield

    await close_streaming_checkpointer()


app = FastAPI(title="Rhizome Internal API", lifespan=lifespan)

app.include_router(agent_router, prefix="/internal")
app.include_router(data_router, prefix="/internal/data")


@app.get("/health")
def health():
    return {"status": "ok"}
