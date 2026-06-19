# Setup Guide

## Prerequisites

- Python 3.12+
- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) (the project uses a dedicated conda environment)
- A Google API key with Gemini access ([get one here](https://aistudio.google.com/app/apikey))

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

**2. Add your API key**

Open `.env` and set:

```
GOOGLE_API_KEY=your_key_here
```

The `.env` file is loaded by `python-dotenv` at startup. Never commit it.

**Optional: set a Gemini model override**

The model factory in `agent/core/model.py` defaults to `gemini-1.5-flash` for the primary model and a faster variant for triage. Override with:

```
RHIZOME_MODEL=gemini-1.5-pro
RHIZOME_TRIAGE_MODEL=gemini-1.5-flash
```

**Note on duplicate API keys:** If you also have `GEMINI_API_KEY` set in `~/.zprofile` or `~/.bashrc`, you'll see a warning about duplicate keys on startup. This is harmless as long as both keys are the same value. The model factory uses `GOOGLE_API_KEY` and falls back to `GEMINI_API_KEY`.

---

## Database

Rhizome uses SQLite for development. The DB file is created automatically on first run at `rhizome.db` (application state) and `rhizome_checkpoints.db` (LangGraph conversation checkpoints).

To start fresh:

```bash
rm -f rhizome.db rhizome_checkpoints.db
```

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

The CLI starts an interactive conversation. On first run (empty DB), the agent will introduce itself and ask about your garden. On subsequent runs, it loads the previous session state and starts with a triage snapshot.

Type `quit` or `exit` to end the session. Conversation history is preserved across sessions via LangGraph checkpoints.

---

## Running tests

```bash
# Full suite (310 tests)
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest

# By marker
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m unit          # fast, no DB
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m integration   # database-backed
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m graph         # graph + orchestration

# Specific file
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest tests/tools/projects/test_task_tracker_tools.py
```

Tests do **not** require `GOOGLE_API_KEY` — the model is mocked for all test runs. Each integration test gets a fresh in-memory SQLite database via pytest fixtures.

---

## Project layout reference

```
rhizome/
├── agent/
│   ├── core/       LangGraph runtime (graph, nodes, state, model, telemetry, temporal)
│   ├── domain/     Domain logic (triage, planner, tracker, care, weather, incidents,
│   │               interactions, activity_log)
│   └── tools/      93 tools in garden/, projects/, operations/ subdirectories
├── db/
│   ├── models.py   All SQLAlchemy models
│   ├── database.py Session factory, current_user_id ContextVar
│   └── seed.py     Dev seed data
├── tests/          310 tests; see docs/development/testing.md
├── docs/           This documentation
├── main.py         CLI entrypoint
├── CLAUDE.md       Claude Code session memory
└── README.md
```

See [Code Organization](../development/code-organization.md) for a full module-by-module guide.
