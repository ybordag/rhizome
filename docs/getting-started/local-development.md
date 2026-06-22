# Local Development

This guide is the practical path for getting Rhizome running on a development machine. Use it after the basic installation steps in [Setup](setup.md).

Rhizome can run by itself for agent/domain work, or as part of the broader Verdant -> Cambium -> Rhizome stack.

---

## Choose A Mode

| Mode | Use When | Database | Interface |
|---|---|---|---|
| Rhizome-only quickstart | You are working on tools, graph behavior, domain logic, or tests | SQLite files | CLI or Rhizome Swagger |
| Rhizome API development | You are working on internal routes or Cambium proxy behavior | SQLite or Postgres | Rhizome Swagger |
| Full stack development | You are validating Verdant/Cambium/Rhizome together | Postgres recommended | Cambium `/api/v1` |

There is no Rhizome-local Docker Compose file. The repo has a Dockerfile and k8s manifests for deployment, but local development is usually direct Python plus an optional Postgres instance.

---

## Rhizome-Only Quickstart

Use this for most backend work.

```bash
conda activate RHIZOME_ENV
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Set at least one provider key in `.env`. For the default provider:

```bash
GOOGLE_API_KEY=your_key_here
```

Leave `DATABASE_URL` unset for SQLite. Rhizome will create:

- `rhizome.db` for SQLAlchemy application state
- `rhizome_checkpoints.db` for LangGraph checkpoints

Run the CLI:

```bash
python main.py
```

Run the internal API:

```bash
python server.py
```

Verify:

```bash
curl http://localhost:8001/health
```

Open Swagger UI:

```text
http://localhost:8001/docs
```

---

## Postgres-Backed Rhizome

Use this when you need the same database shape as shared dev/staging/prod, or when testing behavior that SQLite cannot represent well.

Set `DATABASE_URL`:

```bash
export DATABASE_URL=postgresql+psycopg2://postgres:dev@localhost:5432/postgres
```

Apply migrations:

```bash
alembic upgrade head
```

Run the server:

```bash
python server.py
```

Rhizome stores all domain tables in the `rhizome` schema. The SQLAlchemy engine and LangGraph checkpointer set `search_path=rhizome` automatically.

If you switch back to SQLite, unset `DATABASE_URL`:

```bash
unset DATABASE_URL
```

---

## Cambium And Verdant Integration

Cambium is the public API gateway for local frontend work. Rhizome should be running first:

```bash
cd rhizome
python server.py
```

Then start Cambium in the sibling repo. Cambium defaults to:

```bash
RHIZOME_INTERNAL_URL=http://localhost:8001
PORT=8080
```

Cambium exposes:

```text
http://localhost:8080/docs/index.html
```

Verdant should call Cambium's `/api/v1` surface, not Rhizome's `/internal/...` routes directly.

For authenticated chat/agent requests, Cambium injects:

- `user_id` from the verified JWT
- decrypted provider key
- provider/model overrides when present
- `thread_id` for conversation continuity

Rhizome receives those values through internal request bodies/query params and graph config.

---

## Test Workflow

Run non-live tests:

```bash
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m "not live"
```

Run focused tests while iterating:

```bash
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest tests/agent/api/test_threads.py -q
```

The test suite uses isolated SQLite databases and does not run Alembic. When adding a model field, update both `db/models.py` and an Alembic migration, then test the model/API behavior with normal pytest fixtures.

---

## Reset And Seed

Reset SQLite state:

```bash
rm -f rhizome.db rhizome_checkpoints.db
```

Seed sample data:

```bash
python db/seed.py
```

For Postgres, prefer migrations plus targeted seed/setup commands. Do not use `Base.metadata.create_all()` as a substitute for Alembic in shared environments.

---

## Common Problems

**`psycopg.OperationalError` on startup**

`DATABASE_URL` points to Postgres, but Postgres is not reachable. Start Postgres, fix the DSN, or unset `DATABASE_URL` to use SQLite.

**`ValueError: No API key for provider ...`**

Set the provider key expected by `RHIZOME_MODEL_PROVIDER`: `GOOGLE_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`.

**`no such table` with Postgres**

Run `alembic upgrade head` using the same `DATABASE_URL` that the server uses.

**Cambium returns 502 for Rhizome routes**

Confirm Rhizome is running on `http://localhost:8001`, then check Cambium's `RHIZOME_INTERNAL_URL`.

**Swagger shows Rhizome routes but Verdant cannot call them**

That is expected if you are looking at Rhizome's `http://localhost:8001/docs`. Verdant uses Cambium's `http://localhost:8080/docs/index.html` and authenticated `/api/v1` routes.
