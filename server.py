"""
Entry point for the Rhizome internal API server.

Usage:
    python server.py                  # dev (auto-reload)
    uvicorn agent.api.app:app         # production

Environment:
    DATABASE_URL  — Postgres connection string (required in staging/prod)
    PORT          — listen port (default: 8001)
"""

import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    reload = os.environ.get("ENV", "dev") == "dev"
    uvicorn.run("agent.api.app:app", host="0.0.0.0", port=port, reload=reload)
