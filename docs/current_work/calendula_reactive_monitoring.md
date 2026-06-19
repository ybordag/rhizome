# Calendula: Reactive Monitoring and Alerting

**Branch:** `calendula`  
**Epic:** [Epic 6: Reactive Monitoring and Alerting](../roadmap/epics/epic_06_reactive_monitoring_and_alerting.md)  
**Status:** In progress — Phases 1–2 complete, Phase 3 next  
**Last updated:** 2026-06-18

---

## Summary

Rhizome already has a complete weather data layer — fetch, impact derivation,
task change approval, triage — but all of it requires a user to initiate it.
Calendula adds a background monitoring layer that:

- runs on a schedule without a user session
- auto-applies critical weather changes (storm, severe frost, high heat advisory)
- queues moderate impacts for user review (as today)
- surfaces safe/unsafe outdoor working windows as advisory context
- writes `MonitorAlert` records that the future FastAPI layer will serve to
  Verdant (front-page banner and chat-top alert)
- surfaces pending alerts at session start via the existing interaction context

---

## What already exists (do not rewrite)

| File | Relevant functions |
|------|-------------------|
| `agent/domain/weather.py` | `refresh_weather_snapshot`, `evaluate_weather_task_impacts`, `draft_weather_task_changes`, `approve_weather_task_changes` |
| `agent/domain/triage.py` | `build_triage_snapshot`, `format_triage_snapshot` |
| `agent/domain/tracker.py` | `materialize_task_series`, `list_materializable_series`, `compute_task_urgency` |
| `agent/tools/operations/weather.py` | tool wrappers (user-invoked only today) |
| `db/models.py` | `WeatherSnapshot`, `WeatherTaskChangeSet`, `TriageSnapshot`, `Task` |

---

## New models

### `MonitorAlert`

Single persistence point for all monitor-generated alerts. Queryable without a
session — the future `GET /api/v1/alerts` endpoint will serve this directly.
Also read at session start to inject critical context into the chat.

```
id            str PK
created_at    datetime (indexed)
expires_at    datetime        — 24h for advisories, 48h for critical
user_id       int FK          — indexed
alert_type    str             — 'weather_critical' | 'weather_advisory'
                                | 'working_window' | 'triage' | 'pest'
severity      str             — 'critical' | 'high' | 'medium' | 'low'
title         str
body          str
status        str             — 'pending' | 'dismissed' (default: 'pending')
dismissed_at  datetime nullable
source_type   str nullable    — 'weather_snapshot' | 'triage_snapshot' | 'monitor_run'
source_id     str nullable
metadata      JSON nullable
```

### `MonitorRun`

Audit trail for cron executions, so cron health is debuggable.

```
id            str PK
created_at    datetime (indexed)
completed_at  datetime nullable
run_type      str   — 'weather' | 'triage' | 'series_materialization'
status        str   — 'started' | 'completed' | 'failed'
summary       str nullable
error         str nullable
user_id       int nullable
```

---

## New weather impact types

Extend `derive_weather_impacts()` in `agent/domain/weather.py` with two new
types:

- **`unsafe_outdoor_window`** — triggered by afternoon heat > 95°F, severe
  rain, or storm. Payload includes `hours` and `reason`. Does not defer tasks.
- **`safe_outdoor_window`** — unusually good window in an otherwise difficult
  forecast. Payload includes `hours` and `reason`.

Both types generate a `MonitorAlert(alert_type='working_window')` and appear
in the triage `reasoning_summary`. They do **not** create or modify tasks.

---

## Auto-apply policy

Add `apply_weather_impacts(session, snapshot, user_id)` to
`agent/domain/weather.py`. The monitor calls this instead of the user-facing
draft → approve flow.

| Condition | Action |
|-----------|--------|
| `severity == 'critical'` (storm, severe frost ≥ high, heat ≥ high) | Call `approve_weather_task_changes()` directly. Write `MonitorAlert(alert_type='weather_critical', severity='critical')`. |
| `unsafe_outdoor_window` or `safe_outdoor_window` | No task changes. Write `MonitorAlert(alert_type='working_window')`. |
| Everything else | Call `draft_weather_task_changes()` as today. Write `MonitorAlert(alert_type='weather_advisory', severity='medium')`. |

---

## Monitor script (`scripts/monitor.py`)

Standalone script invoked by system cron. Imports domain functions directly.
Three jobs run in sequence:

**`weather_job(session, user_id)`**
1. `refresh_weather_snapshot()` if stale (> 6h — tightened from the 12h tool default)
2. `apply_weather_impacts()` → writes `MonitorAlert` records
3. Records `MonitorRun(run_type='weather')`

**`triage_job(session, user_id)`**
1. `build_triage_snapshot(session, opener='', timezone=DEFAULT_TIMEZONE)`
2. If `urgent_task_ids`: write `MonitorAlert(alert_type='triage', severity='high')`
3. Records `MonitorRun(run_type='triage')`

**`series_job(session, user_id)`**
1. `list_materializable_series()` → `materialize_task_series()` for each due series
2. Records `MonitorRun(run_type='series_materialization')`

```
# Usage
python scripts/monitor.py [--user-id 1] [--job weather|triage|series|all]

# Example crontab entries
0 6  * * * python /path/to/scripts/monitor.py --job all
0 0  * * * python /path/to/scripts/monitor.py --job series
```

---

## Session-start delivery

In `session_context_intake` (`agent/core/nodes.py`), after setting `user_id`,
query pending `MonitorAlert` records and return them as `monitor_alerts` in
state. `llm_call` injects them into the system prompt as a "⚠ Active alerts"
section above the triage context.

`GardenState` gets `monitor_alerts: Optional[list[dict]]`.

Only `severity in ('critical', 'high')` and non-expired alerts are injected.

---

## Phases

### Phase 1 — Models + runner skeleton ✅
- `MonitorAlert` and `MonitorRun` added to `db/models.py`
- `scripts/monitor.py` with `--job` flag, `MonitorRun` lifecycle tracking, per-job error isolation
- 13 integration tests in `tests/db/test_monitor_models.py`

### Phase 2 — Automated weather pipeline ✅
- `unsafe_outdoor_window` and `safe_outdoor_window` impact types in `derive_weather_impacts()`
- `_create_changeset()` private helper; `_is_critical_task_impact()`
- `apply_weather_impacts(session, *, snapshot, user_id)` — auto-applies critical (storm/frost/heat), queues moderate as draft, writes working window `MonitorAlert` records only
- `weather_job()` wired into `scripts/monitor.py` with fresh-snapshot guard and rollback on failure
- 20 tests in `tests/agent/domain/test_weather_monitor.py`

### Phase 3 — Session delivery
- `session_context_intake` reads pending alerts → `monitor_alerts` in state
- `llm_call` injects into system prompt
- Tests: alerts present in state when pending; absent when dismissed or expired

### Phase 4 — Triage + series jobs
- `triage_job()` and `series_job()` in `scripts/monitor.py`
- Tests: series materialization runs for due series; triage job writes alert when urgent tasks exist

### Phase 5 — iNaturalist pest monitoring
- `agent/domain/pests.py` — iNaturalist Observations API, observation → `IncidentReport` mapping
- `pest_job()` in `scripts/monitor.py`
- Wire into existing incident + treatment plan workflow
- Tests: mocked iNaturalist response creates `IncidentReport` + `MonitorAlert`

---

## Files to create or modify

| File | Change |
|------|--------|
| `db/models.py` | Add `MonitorAlert`, `MonitorRun` |
| `agent/domain/weather.py` | Add `unsafe_outdoor_window`/`safe_outdoor_window` impact types, `apply_weather_impacts()` |
| `agent/core/nodes.py` | `session_context_intake` reads pending alerts; `llm_call` injects into prompt |
| `agent/core/state.py` | Add `monitor_alerts: Optional[list[dict]]` |
| `scripts/monitor.py` | New — standalone cron runner |
| `agent/domain/pests.py` | New (Phase 5) — iNaturalist integration |
| `tests/db/test_monitor_models.py` | New — `MonitorAlert`/`MonitorRun` model tests |
| `tests/agent/domain/test_weather_monitor.py` | New — auto-apply policy tests |
| `tests/agent/core/test_nodes.py` | Extend — alert injection into session context |

---

## Verification

```bash
# Full test suite
python -m pytest -m "unit or integration" -v

# Smoke-test the monitor script
python scripts/monitor.py --job weather --user-id 1
python scripts/monitor.py --job triage --user-id 1
python scripts/monitor.py --job series --user-id 1

# Confirm alerts written to DB
python -c "
from db.database import SessionLocal
from db.models import MonitorAlert
s = SessionLocal()
print(s.query(MonitorAlert).all())
"

# CLI smoke test — alerts should surface in first response
python main.py
```

---

## Open questions resolved

| Question | Decision |
|----------|----------|
| Alert persistence model? | New `MonitorAlert` model; queryable by API without a session |
| Weather and pest alerts: shared or separate? | Shared `MonitorAlert` model, different `alert_type` values |
| Alert creates new task vs escalates urgency? | Critical severity: auto-apply (defer + create blockers). Moderate: queue for approval. Working window: advisory only, no task changes. |
| When does an alert trigger a plan amendment? | Not in this epic — plan amendments remain user-initiated |
