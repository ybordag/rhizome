PYTHON ?= /opt/miniconda3/envs/RHIZOME_ENV/bin/python
PYTEST ?= $(PYTHON) -m pytest
PORT ?= 8001
POSTGRES_DSN ?= postgresql+psycopg2://postgres:dev@localhost:5432/postgres
OPENAPI_OUT ?= openapi.json
OPENAPI_DATABASE_URL ?= sqlite:////tmp/rhizome-openapi.db
OPENAPI_CHECKPOINT_PATH ?= /tmp/rhizome-openapi-checkpoints.db
USER_ID ?= 1
MESSAGE ?= migration

.PHONY: help
help:
	@printf '%s\n' 'Rhizome targets:'
	@printf '%s\n' ''
	@printf '%s\n' 'Setup:'
	@printf '%s\n' '  make conda-env          Create the RHIZOME_ENV conda environment'
	@printf '%s\n' '  make env-file           Create .env from .env.example if missing'
	@printf '%s\n' '  make install            Install runtime and dev dependencies'
	@printf '%s\n' '  make setup              Create .env if needed and install dependencies'
	@printf '%s\n' '  make seed               Seed local development data'
	@printf '%s\n' '  make reset-sqlite       Remove local SQLite app/checkpoint databases'
	@printf '%s\n' ''
	@printf '%s\n' 'Run:'
	@printf '%s\n' '  make cli                Start the Rhizome CLI'
	@printf '%s\n' '  make api                Start the internal FastAPI server'
	@printf '%s\n' '  make api-prod           Start the internal API without reload'
	@printf '%s\n' '  make health             Check the internal API health endpoint'
	@printf '%s\n' '  make swagger-ui         Open the generated FastAPI Swagger UI'
	@printf '%s\n' ''
	@printf '%s\n' 'Database:'
	@printf '%s\n' '  make migrate            Apply Alembic migrations using current DATABASE_URL'
	@printf '%s\n' '  make migrate-postgres   Apply migrations using POSTGRES_DSN'
	@printf '%s\n' '  make migration MESSAGE="..."'
	@printf '%s\n' '  make db-current         Show the current Alembic revision'
	@printf '%s\n' '  make db-history         Show Alembic migration history'
	@printf '%s\n' '  make db-heads           Show Alembic migration heads'
	@printf '%s\n' ''
	@printf '%s\n' 'Tests:'
	@printf '%s\n' '  make check              Run broad non-live local checks'
	@printf '%s\n' '  make check-full         Run broader non-live local checks'
	@printf '%s\n' '  make test               Run non-live regression tests'
	@printf '%s\n' '  make test-all           Run the full pytest suite, including live tests'
	@printf '%s\n' '  make test-unit          Run unit tests'
	@printf '%s\n' '  make test-integration   Run integration tests'
	@printf '%s\n' '  make test-graph         Run graph/orchestration tests'
	@printf '%s\n' '  make test-e2e           Run e2e tests; requires Rhizome and Cambium running'
	@printf '%s\n' '  make test-api           Run internal API tests'
	@printf '%s\n' '  make test-core          Run LangGraph/core tests'
	@printf '%s\n' '  make test-db            Run database tests'
	@printf '%s\n' '  make test-domain        Run domain tests'
	@printf '%s\n' '  make test-cli           Run CLI tests'
	@printf '%s\n' '  make test-live          Run live provider tests'
	@printf '%s\n' '  make test-telemetry     Run telemetry tests'
	@printf '%s\n' '  make smoke-api          Run focused API smoke tests'
	@printf '%s\n' '  make test-tools         Run tool tests'
	@printf '%s\n' '  make test-file FILE=... Run a focused pytest target'
	@printf '%s\n' '  make test-cov           Run non-live tests with coverage'
	@printf '%s\n' ''
	@printf '%s\n' 'OpenAPI and monitor jobs:'
	@printf '%s\n' '  make openapi            Export FastAPI OpenAPI schema to OPENAPI_OUT'
	@printf '%s\n' '  make openapi-check      Validate OpenAPI generation without changing OPENAPI_OUT'
	@printf '%s\n' '  make clean-openapi      Remove generated OpenAPI temp/output files'
	@printf '%s\n' '  make swagger            Alias for openapi'
	@printf '%s\n' '  make monitor            Run all background monitor jobs'
	@printf '%s\n' '  make monitor-weather    Run weather monitor job'
	@printf '%s\n' '  make monitor-triage     Run triage monitor job'
	@printf '%s\n' '  make monitor-series     Run recurring task series monitor job'

.PHONY: conda-env
conda-env:
	conda create -n RHIZOME_ENV python=3.12

.PHONY: env-file
env-file:
	@test -f .env || cp .env.example .env

.PHONY: install
install:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

.PHONY: setup
setup: env-file install

.PHONY: seed
seed:
	$(PYTHON) db/seed.py

.PHONY: reset-sqlite
reset-sqlite:
	rm -f rhizome.db rhizome_checkpoints.db

.PHONY: cli
cli:
	$(PYTHON) main.py

.PHONY: api
api:
	PORT=$(PORT) ENV=dev $(PYTHON) server.py

.PHONY: api-prod
api-prod:
	PORT=$(PORT) ENV=prod $(PYTHON) server.py

.PHONY: health
health:
	curl http://localhost:$(PORT)/health

.PHONY: swagger-ui
swagger-ui:
	$(PYTHON) -m webbrowser -t http://localhost:$(PORT)/docs

.PHONY: migrate
migrate:
	alembic upgrade head

.PHONY: migrate-postgres
migrate-postgres:
	DATABASE_URL=$(POSTGRES_DSN) alembic upgrade head

.PHONY: migration
migration:
	alembic revision --autogenerate -m "$(MESSAGE)"

.PHONY: db-current
db-current:
	alembic current

.PHONY: db-history
db-history:
	alembic history

.PHONY: db-heads
db-heads:
	alembic heads

.PHONY: check
check:
	$(PYTEST) -m "not live" tests/agent/api tests/tools tests/db

.PHONY: check-full
check-full:
	$(PYTEST) -m "not live" tests/agent/api tests/tools tests/db tests/agent/domain tests/agent/core tests/test_main_cli.py

.PHONY: test
test:
	$(PYTEST) -m "not live"

.PHONY: test-all
test-all:
	$(PYTEST)

.PHONY: test-unit
test-unit:
	$(PYTEST) -m unit

.PHONY: test-integration
test-integration:
	$(PYTEST) -m integration

.PHONY: test-graph
test-graph:
	$(PYTEST) -m graph

.PHONY: test-e2e
test-e2e:
	$(PYTEST) -m e2e

.PHONY: test-api
test-api:
	$(PYTEST) tests/agent/api

.PHONY: test-core
test-core:
	$(PYTEST) tests/agent/core

.PHONY: test-db
test-db:
	$(PYTEST) tests/db

.PHONY: test-domain
test-domain:
	$(PYTEST) tests/agent/domain

.PHONY: test-cli
test-cli:
	$(PYTEST) tests/test_main_cli.py

.PHONY: test-live
test-live:
	$(PYTEST) -m live

.PHONY: test-telemetry
test-telemetry:
	$(PYTEST) -m telemetry

.PHONY: smoke-api
smoke-api:
	$(PYTEST) tests/agent/api/test_internal_api.py tests/agent/api/test_streaming_endpoints.py

.PHONY: test-tools
test-tools:
	$(PYTEST) tests/tools

.PHONY: test-file
test-file:
	@test -n "$(FILE)" || (printf '%s\n' 'Usage: make test-file FILE=tests/path/to/test_file.py' && exit 1)
	$(PYTEST) $(FILE)

.PHONY: test-cov
test-cov:
	$(PYTEST) -m "not live" --cov=agent --cov=db

.PHONY: openapi
openapi:
	DATABASE_URL=$(OPENAPI_DATABASE_URL) RHIZOME_CHECKPOINT_SQLITE_PATH=$(OPENAPI_CHECKPOINT_PATH) $(PYTHON) -c "import json; from agent.api.app import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))" > $(OPENAPI_OUT)

.PHONY: openapi-check
openapi-check:
	DATABASE_URL=$(OPENAPI_DATABASE_URL) RHIZOME_CHECKPOINT_SQLITE_PATH=$(OPENAPI_CHECKPOINT_PATH) $(PYTHON) -c "import json; from agent.api.app import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))" > /tmp/rhizome-openapi.json

.PHONY: clean-openapi
clean-openapi:
	rm -f $(OPENAPI_OUT) /tmp/rhizome-openapi.json /tmp/rhizome-openapi.db /tmp/rhizome-openapi-checkpoints.db

.PHONY: swagger
swagger: openapi

.PHONY: monitor
monitor:
	$(PYTHON) scripts/monitor.py --user-id $(USER_ID) --job all

.PHONY: monitor-weather
monitor-weather:
	$(PYTHON) scripts/monitor.py --user-id $(USER_ID) --job weather

.PHONY: monitor-triage
monitor-triage:
	$(PYTHON) scripts/monitor.py --user-id $(USER_ID) --job triage

.PHONY: monitor-series
monitor-series:
	$(PYTHON) scripts/monitor.py --user-id $(USER_ID) --job series
