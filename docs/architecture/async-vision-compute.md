# Async Vision Compute

Rhizome's structured vision features use asynchronous compute, but these jobs
are bounded model-inference tasks rather than durable multi-day business
workflows. The architecture keeps compute scheduling, domain state, and
container orchestration separate.

## Ownership Boundaries

| Layer | Owns | Does not own |
|---|---|---|
| Rhizome | Garden domain state, `VisionJob` records, media ownership, result interpretation, user confirmations | GPU scheduling, worker placement, generic queue policy |
| Fairlead | Compute job scheduling, worker registration, priority queues, resource-aware placement, retries, callbacks | Garden semantics, business writes, user-facing domain records |
| k3s | Container placement, restarts, service discovery, node scheduling | VRAM-aware request admission, job semantics, domain lifecycle |
| Temporal | Deferred; future durable product workflows if needed | Bounded image inference jobs in the first vision implementation |

The immediate design is:

```text
Rhizome VisionJob
  pending -> submitted_to_fairlead -> processing -> partial -> complete/failed

Fairlead Job
  queued -> leased -> running -> complete/failed/cancelled/expired
```

Rhizome owns the first state machine. Fairlead owns the second.

## Why Fairlead, Not Temporal, For Initial Vision Jobs

The first vision jobs are short-lived compute tasks:

- plant health assessment
- sighting analysis
- inventory and container reconciliation
- space assessment

These jobs should complete within seconds to a few minutes. If a job exceeds its
timeout, that is treated as a failed worker attempt, not a normal long-running
workflow.

Fairlead should handle the operational lifecycle:

- priority queues: `realtime`, `batch`, `background`
- worker registration and heartbeat
- resource-aware placement
- lease acquisition and lease renewal
- per-attempt timeout
- bounded retries
- cancellation
- status polling
- callback delivery
- eventually SQLite/Postgres-backed job state

Rhizome should handle the domain lifecycle:

- create and persist `VisionJob`
- link `MediaAsset` records
- choose `analysis_type`
- store feature-specific result payloads
- synthesize model output into garden findings
- create `InteractionRecord` for proposed writes
- create or update domain objects only after user confirmation

Temporal is useful later if Rhizome grows product workflows with long waits,
fanout/fanin, compensation, partial retries across many product steps, or crash
recovery across multi-step user journeys. It is not required for bounded vision
inference jobs.

## End-to-End Flow

```text
User uploads image
  -> Cambium stores or forwards media
  -> Rhizome creates MediaAsset

User asks for vision analysis
  -> Agent calls submit_vision_job(...)
  -> Rhizome creates VisionJob(status=pending)
  -> Rhizome submits a Fairlead job
  -> Rhizome marks VisionJob(status=submitted_to_fairlead)
  -> Agent responds immediately and continues the conversation

Fairlead schedules compute
  -> job enters batch priority queue
  -> scheduler chooses a registered vision worker
  -> worker lease starts
  -> worker runs LocateAnything, SAM 3, or a hybrid pipeline

Worker reports result
  -> callback updates Rhizome VisionJob partial/final payload
  -> Rhizome creates an InteractionRecord if user review is needed
  -> SSE notification is pushed when possible
  -> missed callbacks or notifications are recovered by polling/reconciliation
```

SSE is a fast delivery path, not the source of truth. The durable source of
truth is Rhizome's `VisionJob` and related domain records.

## Agent Behavior While Vision Runs

The agent should not block on model inference. After submitting a job, it should
continue useful text/tool work:

- load plant, bed, container, project, and incident context
- check recent care history
- detect duplicate active incidents before creating a new one
- precompute expected inventory for reconciliation
- ask clarifying questions about location, timing, or reference objects
- explain what will happen when the result is ready

When the vision result arrives, Rhizome surfaces it as an interaction card with
actions such as:

- confirm finding
- create sighting
- draft incident
- update plant notes
- update bed or container notes
- create follow-up task
- dismiss

## Fairlead Job Contract

Rhizome should submit jobs with enough metadata for routing and observability,
but without garden-domain coupling:

```json
{
  "workload_type": "vision_analysis",
  "priority": "batch",
  "idempotency_key": "vision-job-id",
  "callback_url": "http://rhizome/internal/vision/jobs/{id}/callback",
  "payload": {
    "vision_job_id": "vision-job-id",
    "analysis_type": "plant_health",
    "pipeline": "locate_anything_v1",
    "media": [
      {
        "media_id": "media-id",
        "content_url": "http://cambium/internal/media/media-id/content"
      }
    ],
    "context": {
      "target_type": "plant",
      "target_id": "plant-id"
    }
  }
}
```

Fairlead can inspect `workload_type`, `priority`, `pipeline`, and resource
requirements. It should treat the rest of `payload` as opaque application data.

## Reconciliation

Callbacks can fail. Rhizome should not depend exclusively on a callback or SSE
event.

Rhizome needs a reconciliation path:

- `check_vision_job(job_id)` polls Fairlead when the local job is not terminal
- a background reconciler retries stale `submitted_to_fairlead` or `processing`
  records
- completed Fairlead jobs can be pulled into Rhizome if the callback was missed
- expired or permanently failed Fairlead jobs mark the corresponding Rhizome
  `VisionJob` failed with an actionable error

This keeps the product behavior reliable without requiring Temporal for v1.
