# Image Processing Architecture and Implementation Plan

This document describes the first implementation architecture for Rhizome's
structured vision features. It focuses on the plumbing, contracts, storage,
state machines, and rollout sequence. Detailed pipeline specs for SAM 3,
LocateAnything, and hybrid execution will be written separately.

## Goals

- Add image media as a first-class Rhizome input.
- Keep image processing asynchronous and non-blocking for the agent.
- Store media through a backend-neutral storage abstraction, using localstore
  first.
- Support comparable pipelines behind stable feature contracts.
- Let Fairlead schedule bounded compute jobs without learning garden semantics.
- Require user confirmation before AI-derived findings mutate domain records.

## First Feature Set

The first implemented vision features are:

1. `plant_health`
2. `sighting`
3. `inventory_reconciliation`
4. `space_assessment`

These are selected because they exercise different parts of the model stack:
localization, segmentation, counting, matching, and domain synthesis.

## Service Topology

Initial Thor/Loki deployment target:

| Process | Initial node | Role |
|---|---|---|
| Verdant | Thor | User-facing app |
| Cambium | Thor | Auth, API gateway, SSE proxy |
| Rhizome API/agent #1 | Thor | Agent and domain API |
| Rhizome API/agent #2 | Loki | Second stateless worker |
| Postgres | Loki | Domain state, checkpoints, vision metadata |
| Rhizome media localstore | Loki volume or configured shared path | Image bytes and derivatives |
| Fairlead | Thor or Loki | Compute router and job scheduler |
| Vision worker: LocateAnything | GPU node, likely Loki first | Open-vocabulary localization |
| Vision worker: SAM 3 | GPU node, likely Loki first | Segmentation and masks |
| Vision worker: hybrid | GPU node, likely Loki first | LocateAnything plus SAM 3 |

The node placement can change as the cluster matures. The architecture should
not assume media files are available through a hardcoded path on every process.

## Media Storage

Rhizome uses a storage abstraction from the start:

```python
class MediaStorage:
    def write(self, data: bytes, *, mime_type: str, user_id: str) -> StoredMedia: ...
    def open_read(self, storage_key: str): ...
    def get_read_ref(self, storage_key: str, *, ttl_seconds: int) -> MediaReadRef: ...
    def delete(self, storage_key: str) -> None: ...
```

The first backend is localstore. Later backends can be MinIO, Garage, SeaweedFS,
NFS, JuiceFS, Ceph, or another distributed store.

`storage_key` is opaque. Code outside `agent/media/storage.py` must not parse
it or assume filesystem layout.

### Localstore Layout

The default localstore root should be configurable:

```text
RHIZOME_MEDIA_ROOT=/var/lib/rhizome/media
```

Suggested layout:

```text
/var/lib/rhizome/media/
  users/
    {user_id}/
      originals/
        {media_id}.{ext}
      derivatives/
        {media_id}/
          thumbnail.webp
          normalized.jpg
          crops/
          masks/
```

The exact path is an implementation detail of the localstore backend.

### Media Read References

Vision workers should receive a storage-neutral read reference:

```json
{
  "kind": "content_endpoint",
  "url": "http://rhizome/internal/media/{media_id}/content",
  "headers": {
    "Authorization": "Bearer service-token"
  },
  "expires_at": "2026-06-21T12:00:00"
}
```

Later backends may produce:

```json
{ "kind": "https_url", "url": "https://...", "expires_at": "..." }
```

or:

```json
{ "kind": "mount_path", "path": "/mnt/rhizome-media/..." }
```

Workers should consume `read_ref`, not `storage_key`.

## Database Models

Add the vision/media models in one migration.

### `MediaAsset`

Stores metadata for uploaded media.

Important fields:

- `id`
- `user_id`
- `storage_backend`
- `storage_key`
- `mime_type`
- `size_bytes`
- `sha256`
- `width`
- `height`
- `original_filename`
- `attachment_kind`
- `linked_subject_type`
- `linked_subject_id`
- `created_at`

Image bytes are not stored in Postgres.

### `VisionJob`

Tracks Rhizome's domain-level image analysis lifecycle.

Important fields:

- `id`
- `user_id`
- `thread_id`
- `analysis_type`
- `pipeline`
- `status`
- `submitted_at`
- `started_at`
- `completed_at`
- `fairlead_job_id`
- `target_type`
- `target_id`
- `context_payload`
- `partial_results`
- `result_payload`
- `proposed_actions`
- `error_message`
- `attempt_count`

Initial statuses:

```text
pending
submitted_to_fairlead
processing
partial
complete
failed
cancelled
```

### `VisionJobMedia`

Join table for single-image and multi-image jobs.

Important fields:

- `id`
- `vision_job_id`
- `media_asset_id`
- `role`: primary, comparison, context, reference
- `sort_order`

### `GardenSighting`

Durable observation model for organisms, symptoms, weeds, beneficials,
pollinators, and wildlife. It is not the same as `IncidentReport`.

Important fields:

- `id`
- `user_id`
- `project_id`
- `sighting_type`
- `name`
- `confidence`
- `location_type`
- `location_id`
- `media_asset_id`
- `notes`
- `observed_at`
- `created_at`
- `linked_incident_id`

## Rhizome Modules

Add these modules:

```text
agent/media/
  __init__.py
  storage.py
  localstore.py
  types.py

agent/domain/
  vision.py
  media.py
  sightings.py

agent/tools/operations/
  vision.py

agent/api/
  media routes
  vision callback/status routes
```

Responsibilities:

- `agent/media/*`: storage backends and read references.
- `agent/domain/media.py`: create/read/link media metadata.
- `agent/domain/vision.py`: create jobs, submit jobs, handle callbacks, reconcile.
- `agent/domain/sightings.py`: create/query `GardenSighting`.
- `agent/tools/operations/vision.py`: LangChain tool wrappers.
- API routes: upload media, fetch media, callback, status, list jobs.

## Agent Tools

Initial safe tools:

```python
submit_vision_job(
    media_ids: list[str],
    analysis_type: str,
    pipeline: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    context: dict | None = None,
) -> str
```

```python
check_vision_job(job_id: str) -> str
```

```python
list_vision_jobs(status: str | None = None, limit: int = 10) -> str
```

```python
attach_media_to_subject(media_id: str, subject_type: str, subject_id: str) -> str
```

```python
list_media_for_subject(subject_type: str, subject_id: str) -> str
```

```python
record_visual_note(media_id: str, subject_type: str, subject_id: str, notes: str) -> str
```

Feature wrappers can call `submit_vision_job` with a fixed `analysis_type`:

- `analyze_plant_health_from_image`
- `analyze_sighting_from_image`
- `reconcile_inventory_from_image`
- `assess_space_from_image`

## API Surface

Rhizome internal endpoints:

```text
POST /internal/media
GET  /internal/media/{media_id}
GET  /internal/media/{media_id}/content
POST /internal/media/{media_id}/attach

GET  /internal/vision/jobs
GET  /internal/vision/jobs/{job_id}
POST /internal/vision/jobs/{job_id}/callback
POST /internal/vision/jobs/{job_id}/cancel
```

Cambium exposes the stable `/api/v1` equivalents and injects `user_id`.

## Vision Job Submission Flow

```text
User asks for image analysis
  -> Rhizome agent calls submit_vision_job
  -> Rhizome validates media ownership
  -> Rhizome creates VisionJob(status=pending)
  -> Rhizome creates VisionJobMedia rows
  -> Rhizome creates read_ref values for each media asset
  -> Rhizome submits Fairlead job
  -> Rhizome stores fairlead_job_id
  -> Rhizome marks VisionJob(status=submitted_to_fairlead)
  -> Tool returns immediately to the agent
```

The agent should then continue useful text/tool work rather than wait for
inference.

## Fairlead Job Payload

Fairlead sees a bounded compute job:

```json
{
  "workload_type": "vision_analysis",
  "priority": "batch",
  "idempotency_key": "vision-job-id",
  "callback_url": "http://rhizome/internal/vision/jobs/vision-job-id/callback",
  "payload": {
    "vision_job_id": "vision-job-id",
    "analysis_type": "plant_health",
    "pipeline": "locate_anything_v1",
    "media": [
      {
        "media_id": "media-id",
        "read_ref": {
          "kind": "content_endpoint",
          "url": "http://rhizome/internal/media/media-id/content",
          "expires_at": "2026-06-21T12:00:00"
        }
      }
    ],
    "context": {
      "target_type": "plant",
      "target_id": "plant-id"
    }
  }
}
```

Fairlead can route on `workload_type`, `priority`, `pipeline`, worker
capabilities, node, and resource requirements. The nested payload is application
data.

## Worker Callback Contract

Workers callback to Rhizome with partial or final updates:

```json
{
  "fairlead_job_id": "fairlead-job-id",
  "vision_job_id": "vision-job-id",
  "status": "complete",
  "pipeline": "locate_anything_v1",
  "model_versions": {
    "locate_anything": "..."
  },
  "latency_ms": 18342,
  "partial_index": null,
  "result": {
    "analysis_type": "plant_health",
    "media_results": [],
    "findings": [],
    "confidence": {
      "overall": "medium",
      "reasons": []
    },
    "recommended_actions": [],
    "proposed_actions": []
  },
  "error": null
}
```

Rhizome writes the callback payload to `VisionJob`, then creates an
`InteractionRecord` if the result proposes user-confirmed writes.

## Result Envelope

All pipelines normalize into this shape before Rhizome interprets them:

```json
{
  "analysis_type": "space_assessment",
  "pipeline": "sam3_v1",
  "media_results": [
    {
      "media_id": "media-id",
      "observations": [],
      "regions": [
        {
          "region_id": "r1",
          "label": "open_soil",
          "geometry_type": "mask",
          "bbox": [0.12, 0.20, 0.68, 0.79],
          "mask_ref": null,
          "confidence": 0.78
        }
      ],
      "quality": {
        "usable": true,
        "limitations": []
      }
    }
  ],
  "findings": [],
  "confidence": {
    "overall": "medium",
    "reasons": []
  },
  "recommended_actions": [],
  "proposed_actions": [],
  "requires_confirmation": true
}
```

Coordinates should be normalized image coordinates unless a pipeline-specific
artifact explicitly states otherwise.

## Interaction Boundary

Vision results can propose changes, but they do not directly apply them.

Examples of proposed actions:

- create `GardenSighting`
- draft `IncidentReport`
- update plant health notes
- update bed/container notes
- create follow-up task
- mark inventory mismatch as resolved

Each proposed action should become either:

- an `InteractionRecord` with explicit user actions, or
- a tool call only after the user explicitly asks for it.

## Reconciliation

Callbacks and SSE events are not guaranteed delivery.

Rhizome needs:

- `check_vision_job(job_id)` to poll local DB and Fairlead status.
- stale-job reconciliation for `submitted_to_fairlead` and `processing` jobs.
- idempotent callback handling keyed by `vision_job_id`, `fairlead_job_id`, and
  `partial_index`.
- failure mapping from Fairlead terminal states into Rhizome `VisionJob`.

## Step-by-Step Implementation Plan

### Phase 1: Media Foundation

1. Add media storage settings.
2. Add `agent/media/types.py`.
3. Add `agent/media/storage.py` with backend-neutral interface.
4. Add `agent/media/localstore.py`.
5. Add `MediaAsset` model and migration.
6. Add domain functions to write, read, and attach media.
7. Add internal media API endpoints.
8. Add tests for localstore writes, reads, ownership, and metadata.

### Phase 2: Vision Job Foundation

1. Add `VisionJob` and `VisionJobMedia` models and migration.
2. Add `agent/domain/vision.py` with create/get/list/update helpers.
3. Add `submit_vision_job`, `check_vision_job`, and `list_vision_jobs` tools.
4. Add callback endpoint that updates job state idempotently.
5. Add a fake Fairlead client that returns a deterministic `fairlead_job_id`.
6. Add a fake worker callback fixture for complete and failed jobs.
7. Add tests for state transitions and callback idempotency.

### Phase 3: Sightings Foundation

1. Add `GardenSighting` model and migration.
2. Add `agent/domain/sightings.py`.
3. Add `log_garden_sighting` and `list_garden_sightings` tools.
4. Add activity events for sighting creation.
5. Add incident-linking support.
6. Add tests for user scoping, subject linking, and incident escalation.

### Phase 4: Result Contracts and Interactions

1. Define Python types or Pydantic models for normalized vision results.
2. Define proposed-action types.
3. Add interaction builder for `vision_result_review`.
4. Add action handlers for confirm/dismiss/create_sighting/draft_incident/update_note.
5. Add tests proving AI-derived results do not write domain objects without
   confirmation.

### Phase 5: Agent Behavior

1. Update system prompt guidelines for async vision jobs.
2. Add active/completed vision job context to `session_context_intake`.
3. Teach the agent to continue useful context gathering after submission.
4. Add tests for prompt injection of active/completed jobs.
5. Add CLI/API behavior for pending vision interactions.

### Phase 6: Fairlead Integration

1. Add Fairlead client module for job submission/status/cancellation.
2. Submit real Fairlead job payloads from `submit_vision_job`.
3. Store `fairlead_job_id`.
4. Add cancellation flow.
5. Add reconciliation logic for stale jobs.
6. Add tests with mocked Fairlead responses.

### Phase 7: Vision Worker Harness

1. Define worker input and callback schemas.
2. Build a standalone vision worker process with a fake pipeline.
3. Support local image fetch via `read_ref`.
4. Emit normalized result envelopes.
5. Add health endpoint and worker metadata.
6. Prepare for Fairlead worker registration.

### Phase 8: First Real Pipelines

1. Implement LocateAnything-backed pipeline.
2. Implement SAM 3-backed pipeline.
3. Implement hybrid LocateAnything plus SAM 3 pipeline.
4. Emit model version and latency metadata.
5. Add feature-specific prompt/context builders.
6. Add small fixture image set for repeatable evaluation.

### Phase 9: Feature Rollout

1. Implement `plant_health`.
2. Implement `sighting`.
3. Implement `inventory_reconciliation`.
4. Implement `space_assessment`.
5. Add feature-specific interaction cards.
6. Add evaluation metrics by feature and pipeline.

### Phase 10: Deployment Hardening

1. Add localstore volume configuration for k3s.
2. Add service tokens for worker media reads and callbacks.
3. Add metrics for job status, latency, callback failures, and result errors.
4. Add cleanup policy for derivatives and failed jobs.
5. Add backup guidance for media localstore and Postgres metadata.

## Next Pipeline Specs

The next design checkpoint should define:

- LocateAnything-backed pipeline: inputs, prompts, outputs, strengths,
  limitations, feature mapping, and evaluation criteria.
- SAM 3-backed pipeline: prompt strategy, mask representation, derivative
  storage, strengths, limitations, feature mapping, and evaluation criteria.
- Hybrid pipeline: how LocateAnything boxes/points seed SAM 3 masks, and when
  the added cost is justified.
