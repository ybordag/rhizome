# Setup Guide

## Prerequisites

- Python 3.12+
- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) (the project uses a dedicated conda environment)
- An LLM provider API key. Google Gemini is the default provider; OpenAI and Anthropic are also supported.
- Optional: Postgres, if you want to run the same shared-database shape used by staging/production.

---

## Installation

**1. Activate the project conda environment**

```bash
conda activate RHIZOME_ENV
```

If `RHIZOME_ENV` does not exist yet, create it:

```bash
conda create -n RHIZOME_ENV python=3.12
conda activate RHIZOME_ENV
```

**2. Install dependencies**

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` — runtime dependencies (LangGraph, SQLAlchemy, langchain-google-genai, Open-Meteo client, etc.)  
`requirements-dev.txt` — test dependencies (pytest, pytest-cov, etc.)

---

## Configuration

**1. Copy the environment template**

```bash
cp .env.example .env
```

**2. Add at least one API key**

Open `.env` and set:

```
GOOGLE_API_KEY=your_key_here
```

For other providers, set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` and set
`RHIZOME_MODEL_PROVIDER` accordingly.

The `.env` file is loaded by `python-dotenv` at startup. Never commit it.

**Optional: set a provider/model override**

The model factory in `agent/core/model.py` defaults to `google_genai` and uses provider defaults when no model is specified. For Google, the default is `gemini-2.5-flash`. Override with:

```
RHIZOME_MODEL_PROVIDER=google_genai
RHIZOME_MODEL=gemini-2.5-flash
RHIZOME_TRIAGE_MODEL=gemini-2.5-flash
```

**Note on provider keys:** The model factory reads `GOOGLE_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` based on `RHIZOME_MODEL_PROVIDER`. For the default Google provider, set `GOOGLE_API_KEY`.

---

## Database Modes

Rhizome supports two local modes:

**Quick local / CLI mode: SQLite**

If `DATABASE_URL` is unset, Rhizome uses `sqlite:///rhizome.db` for application state. The LangGraph checkpointer uses `rhizome_checkpoints.db` unless `RHIZOME_CHECKPOINT_SQLITE_PATH` is set. Both files are created automatically on first run.

To reset SQLite state:

```bash
rm -f rhizome.db rhizome_checkpoints.db
```

**Shared dev / staging-like mode: Postgres**

Set `DATABASE_URL` to a Postgres DSN, then run migrations:

```bash
DATABASE_URL=postgresql+psycopg2://postgres:dev@localhost:5432/postgres alembic upgrade head
```

All Rhizome tables live in the `rhizome` schema. The SQLAlchemy engine and LangGraph checkpointer set `search_path=rhizome` automatically for Postgres connections.

To seed the DB with sample data:

```bash
python db/seed.py
```

The seed script creates a sample garden profile, a few beds and containers, and some plants.

---

## Running the CLI

```bash
python main.py
```

The CLI starts an interactive conversation. On first run (empty DB), the agent will introduce itself and ask about your garden. On subsequent runs, it loads the previous session state and current garden context.

Type `quit` or `exit` to end the session. Conversation history is preserved across sessions via LangGraph checkpoints.

---

## Running the API Server

```bash
python server.py
```

The internal API listens on port `8001` by default. Swagger UI is available at:

```
http://localhost:8001/docs
```

Cambium calls these `/internal/...` routes and exposes the authenticated `/api/v1` surface to Verdant.

---

## Running tests

```bash
# Local suite (excludes live provider calls)
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m "not live"

# Full suite, including live provider smoke tests
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest

# By marker
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m unit          # fast, no DB
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m integration   # database-backed
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m graph         # graph + orchestration

# Specific file
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest tests/tools/projects/test_task_tracker_tools.py
```

Non-live tests do **not** require `GOOGLE_API_KEY` — the model is mocked outside `@pytest.mark.live` tests. Each integration test gets a fresh SQLite database via pytest fixtures. Tests do not run Alembic; migrations are for Postgres-backed environments.

---

## Makefile shortcuts

Rhizome includes a `Makefile` for common local workflows. Run:

```bash
make help
```

The Makefile wraps the documented setup, runtime, migration, test, OpenAPI, and background monitor commands. It defaults to `/opt/miniconda3/envs/RHIZOME_ENV/bin/python`; override with `PYTHON=/path/to/python` when using a different environment.

Useful examples:

```bash
make setup
make rhizome
make api
make test
make check
make check-full
make test-file FILE=tests/agent/api/test_internal_api.py
make swagger
make clean-openapi
```

`make rhizome` starts the CLI. If the CLI adds or needs command-line arguments, pass them with `ARGS="..."`, for example `make rhizome ARGS="--help"`. `make check` runs a broad non-live local check over API, tool, and DB tests; `make check-full` adds domain, core, and CLI tests. `make swagger` exports the generated FastAPI OpenAPI schema to `openapi.json` using temporary SQLite database and checkpoint files under `/tmp`; use `make openapi-check` when you only want to validate schema generation without updating that file, and `make clean-openapi` to remove generated OpenAPI artifacts. For the interactive Swagger UI, start the API server with `make api`, then run `make swagger-ui` or open `http://localhost:8001/docs`.

---

## Project layout reference

```
rhizome/
├── agent/
│   ├── core/       LangGraph runtime (graph, nodes, state, model, telemetry, temporal)
│   ├── domain/     Domain logic (triage, planner, tracker, care, weather, incidents,
│   │               interactions, activity_log)
│   └── tools/      94 tools in garden/, projects/, operations/ subdirectories
├── db/
│   ├── models.py   All SQLAlchemy models
│   ├── database.py Session factory, current_user_id ContextVar
│   └── seed.py     Dev seed data
├── tests/          900+ non-live tests; see docs/development/testing.md
├── docs/           This documentation
├── main.py         CLI entrypoint
├── CLAUDE.md       Claude Code session memory
└── README.md
```

For a task-oriented local runbook covering SQLite vs Postgres, the API server, Cambium/Verdant handoff, and troubleshooting, see [Local Development](local-development.md). For module-level orientation, see [Code Organization](../development/code-organization.md).
