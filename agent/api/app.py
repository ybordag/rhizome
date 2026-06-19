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
from db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Rhizome Internal API", lifespan=lifespan)

app.include_router(agent_router, prefix="/internal")
app.include_router(data_router, prefix="/internal/data")


@app.get("/health")
def health():
    return {"status": "ok"}
