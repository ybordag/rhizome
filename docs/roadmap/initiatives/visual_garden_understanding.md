# Visual Garden Understanding

**Track:** Sensing
**Status:** Pending — starts after MediaAsset, GardenSighting, and VisionJob models are merged
**Last updated:** 2026-06

---

## Summary

Let Rhizome use photos to reason about the physical garden: identify plants,
evaluate plant health, assess space and light, and catalog what's living in the
garden. This is one of the most differentiating capabilities in the design
vision — it turns Rhizome from a text-only assistant into an agent that can
see what the gardener sees.

---

## Async delivery model

All visual analysis is **asynchronous**. The agent submits a job and responds
immediately; the vision service processes in the background; results are
delivered as an inline card in the active chat via SSE push.

This matters because local vision models on the Spark nodes can take several
seconds per image — blocking the conversation on inference would make the
feature feel broken. More importantly, multi-image jobs (sun audits, batch
health checks) produce **incremental results**: each image is analyzed
independently and the partial result is pushed to the frontend as it completes,
before the full synthesis is done. The user sees results arriving in real time
rather than waiting for the slowest image.

### Full flow

```
User uploads photo → Cambium stores it → media_id returned
User: "Analyze this photo of my tomato bed"
  → Agent calls submit_vision_job(media_id, analysis_type, thread_id)
  → VisionJob created (status: pending)
  → Agent responds immediately: "Analyzing — I'll send you the results
    shortly. What would you like to work on in the meantime?"

[Vision service picks up job, starts processing]

For each image processed:
  → Vision service writes partial result to VisionJob.partial_results
  → Rhizome background watcher detects new partial result
  → Pushes SSE event to Cambium: { type: "vision_partial", job_id, result }
  → Cambium pushes to frontend SSE stream for this thread
  → Frontend renders incremental card update in the chat

When all analysis is complete:
  → Vision service writes final synthesis to VisionJob.result_payload,
    sets status=complete
  → Rhizome creates InteractionRecord (type: vision_result_ready)
  → SSE push: final card with full results and action buttons
  → User sees the complete card appear inline in the chat without
    sending another message
```

### SSE event types

```
event: vision_partial
data: { job_id, analysis_type, partial_index, result: {...} }

event: vision_complete
data: { job_id, interaction_id, card: { title, body, actions } }
```

The `vision_complete` event carries the full interaction envelope. Verdant
renders it as a chat card with action buttons (confirm identification,
create incident, update profile field, dismiss).

### Incremental result pattern

The same pattern is used by the chat import feature (see
`onboarding_and_data_import.md`) — a long-running parse that extracts
garden data section by section, pushing cards as extractions complete.
Any long-running job that produces useful intermediate results should
share this infrastructure.

### Image storage

Images are stored on the local filesystem for now. `storage_path` in
`MediaAsset` is the only place this is referenced — the rest of the
codebase reads and writes images through a small storage interface
(`read_media(media_id)`, `write_media(data) → media_id`) that abstracts
the underlying path. When the time comes to migrate to object storage
(MinIO running on the Sparks is the target), only this interface changes.

The vision service fetches images using the same interface. If the vision
service runs on a different node (loki GPU, Rhizome on thor), the
`storage_path` must be accessible from both — either a shared mount or
a Cambium media-serve endpoint (`GET /api/v1/media/{id}/content` with a
service token).

---

## Prerequisite models

Three new DB models are required before any visual analysis features can land.
They should be added as a single migration before work begins on the features
below.

### `MediaAsset`

Stores references to uploaded images and their relationships to domain objects.
Image processing results are linked back here.

```python
class MediaAsset(Base):
    id                  = Column(UUID, PK)
    user_id             = Column(Integer, FK users)
    filename            = Column(String)
    mime_type           = Column(String)       # image/jpeg, image/png, image/webp
    size_bytes          = Column(Integer)
    storage_path        = Column(String)       # local path — see storage note above
    original_filename   = Column(String)
    attachment_kind     = Column(String)       # garden_sighting | incident | treatment |
                                               # project | bed | container | plant | chat
    linked_subject_type = Column(String)       # nullable — the entity this image shows
    linked_subject_id   = Column(String)       # nullable
    created_at          = Column(DateTime)
```

Tools need an `attach_media_to_subject(media_id, subject_type, subject_id)` tool
for linking after the fact.

### `VisionJob`

Tracks async vision analysis jobs through their lifecycle. Supports
incremental results for multi-image jobs.

```python
class VisionJob(Base):
    id              = Column(UUID, PK)
    user_id         = Column(Integer, FK)
    media_asset_id  = Column(UUID, FK MediaAsset)  # primary image; multi-image
                                                    # jobs link additional assets
                                                    # via VisionJobMedia
    thread_id       = Column(String)                # conversation that submitted it
    analysis_type   = Column(String)                # plant_id | pest_sighting |
                                                    # space_assessment | sun_audit
    status          = Column(String)                # pending | processing |
                                                    # partial | complete | failed
    submitted_at    = Column(DateTime)
    completed_at    = Column(DateTime, nullable=True)
    partial_results = Column(JSON)                  # list of incremental results,
                                                    # one per image analyzed so far
    result_payload  = Column(JSON, nullable=True)   # final synthesized result
    error_message   = Column(String, nullable=True)
```

The `partial_results` list grows as each image is processed. `result_payload`
is written once on final completion and contains the synthesis across all
partial results. `status=partial` means at least one image has been processed
but the job is not yet complete.

### `GardenSighting`

Records observations of things in the garden: pollinators, beneficial insects,
pests, weeds, birds, and anything else worth tracking. This is distinct from
`IncidentReport`, which models a problem requiring treatment. A sighting may
eventually escalate to an incident, but many sightings are neutral or positive
and should not become incidents.

```python
class GardenSighting(Base):
    id                  = Column(UUID, PK)
    user_id             = Column(Integer, FK users)
    project_id          = Column(UUID, FK, nullable)
    sighting_type       = Column(String)       # pollinator | pest | weed | bird |
                                               # beneficial | other
    name                = Column(String)       # user-confirmed or AI-suggested
    confidence          = Column(Float)        # nullable — AI confidence if identified
    location_type       = Column(String)       # bed | container | garden_wide
    location_id         = Column(String)       # nullable
    media_asset_id      = Column(UUID, FK MediaAsset, nullable)
    notes               = Column(Text)
    observed_at         = Column(DateTime)
    created_at          = Column(DateTime)
    linked_incident_id  = Column(UUID, FK IncidentReport, nullable)
```

---

## Features

### 1. Plant identification and health evaluation

**What it does:**
A user photographs a plant — whether to identify an unknown one, assess a
struggling one, or confirm a new arrival. The agent analyzes the image and
returns:

- likely species candidates with confidence levels
- current health status (healthy, stressed, diseased, pest damage)
- visible issues flagged with specifics (yellowing leaves, spots, wilting, etc.)
- follow-up questions when the image is ambiguous or quality is low

**What it connects to:**

Identification candidates feed into plant inventory updates, but only after
user confirmation — the agent cannot write a new `Plant` record from an image
alone without going through `interaction_node`. If issues are found during
health evaluation, the agent can draft an `IncidentReport` from the same flow.

**New tool:**

```python
def analyze_plants_from_image(media_id: str, plant_id: str = None) -> str:
    """
    Identify likely plant species and evaluate visible health from an image.
    Returns structured candidates with confidence. All writes require user confirmation.
    If plant_id is provided, focuses the analysis on that plant's known context.
    """
```

---

### 2. Pest, disease, and wildlife recognition

**What it does:**
A user photographs something suspicious on a plant, a bed, or the soil. The
agent identifies likely pest candidates, disease symptoms, or beneficial organisms
and creates a structured `GardenSighting` record. Pest/disease findings are
presented as candidates — not confirmed diagnoses — and always go through user
confirmation before creating an `IncidentReport` or treatment plan.

This is also the primary tool for cataloging beneficial sightings: pollinators,
predatory insects, birds, and other wildlife that are worth noting but do not
require any intervention.

**What it connects to:**

- Confirmed pest/disease findings can create or update an `IncidentReport` (links to existing incident system)
- All sightings create a `GardenSighting` record
- Over time, sighting history surfaces patterns (e.g., "aphids appear in this bed every May")

**New tools:**

```python
def analyze_sighting_from_image(media_id: str, location_type: str = None,
                                 location_id: str = None) -> str:
    """
    Identify likely organism(s) from an image — pest, disease, beneficial insect,
    pollinator, weed, or other. Returns candidates with confidence and recommended
    next steps. Creates a GardenSighting draft; user confirms before persisting.
    """

def log_garden_sighting(sighting_type: str, name: str, location_type: str,
                         location_id: str = None, media_id: str = None,
                         notes: str = None, observed_at: str = None) -> str:
    """
    Manually log a garden sighting without image analysis. For when the user
    reports seeing something and wants it recorded.
    """

def list_garden_sightings(location_id: str = None, sighting_type: str = None,
                           days_back: int = 30) -> str:
    """List recent sightings, optionally filtered by location or type."""
```

---

### 3. Space estimation and spatial grounding

**What it does:**
A user photographs a bed, container grouping, or open garden area. The agent
estimates usable growing area, identifies crowding or airflow issues, and notes
physical constraints visible in the image. This grounded assessment can inform
project planning — rather than relying entirely on self-reported dimensions, the
agent can see how much room is actually available.

**What it connects to:**

- Estimated dimensions can update `Bed.dimensions_sqft` or `Container` capacity after user confirmation
- Crowding notes can surface as planning constraints when a new project is proposed for the same space
- Links into Epic 3 (Project Planning) where spatial constraints gate what's feasible

**New tool:**

```python
def assess_space_from_image(media_id: str, target_type: str,
                             target_id: str = None) -> str:
    """
    Estimate usable growing area, crowding, and physical constraints from an
    image. target_type: 'bed' | 'container' | 'area'. Returns structured
    assessment; dimension updates require user confirmation.
    """
```

---

### 4. Sun audit

**What it does:**
A user photographs a bed or area at different times of day. The agent estimates
light intensity (full sun, partial sun, dappled, deep shade) and notes shadow
patterns from structures, trees, or neighboring plants. Multiple photos taken
across the day build a more complete picture than a single assessment.

Sun data is critical for plant placement — many planning failures come from
incorrect sunlight assumptions. This feature closes the loop between what the
user says about sun conditions and what the garden actually receives.

**What it connects to:**

- Sunlight assessments can update `Bed.sunlight` or `Container.location` notes after user confirmation
- Assessment results surface during project planning when checking whether a plant's sun requirements match the proposed location

**New tool:**

```python
def assess_sunlight_from_image(media_id: str, location_type: str,
                                location_id: str = None,
                                time_of_day: str = None) -> str:
    """
    Estimate sunlight intensity and quality from an image.
    time_of_day: 'morning' | 'midday' | 'afternoon' | 'evening'.
    Returns intensity estimate and notes. Updates require user confirmation.
    """
```

---

### 5. Aesthetic and project progress context

**What it does:**
A user shares a photo of how a bed looks now, how a project is progressing, or
what aesthetic they're going for. The agent uses this visual context to ground
its responses — commenting on what it sees, comparing progress to the project
plan, or offering suggestions informed by the actual current state of the garden.

This is the most conversational of the visual features. Most of the time it does
not produce a structured write — the value is in the agent's grounded response.
The user can explicitly ask the agent to record an observation if they want it
persisted.

**No dedicated tool is needed for pure conversational use** — the image is part
of the message, and the multimodal LLM reasons over it naturally. What is needed
is:

- the intake contract (Phase 1 below) so images can flow through Cambium into messages
- a `record_visual_note(media_id, subject_type, subject_id, notes)` tool for when the user explicitly wants to attach the image and a note to a project, bed, or plant

---

## Implementation phases

### Phase 1 — Async infrastructure and media foundation

All three prerequisite models, the async delivery pipeline, and the SSE
push mechanism. Nothing in Phases 2–4 can land without this.

**DB models and migrations:**
- `MediaAsset`, `GardenSighting`, `VisionJob` — single migration
- `VisionJobMedia` join table for multi-image jobs (optional in first pass)

**Storage interface:**
- `agent/media/storage.py`: `read_media(media_id) → bytes`,
  `write_media(data, mime_type) → media_id`
- All file I/O goes through this module — no raw path access elsewhere

**Rhizome tools:**
- `submit_vision_job(media_id, analysis_type)` → returns job_id immediately
- `check_vision_jobs()` → returns any completed/partial jobs for this user
- `attach_media_to_subject(media_id, subject_type, subject_id)`
- `list_media_for_subject(subject_type, subject_id)`
- `record_visual_note(media_id, subject_type, subject_id, notes)`

**Async delivery pipeline:**
- Background watcher in Rhizome detects VisionJob status changes
- On `partial`: pushes `vision_partial` SSE event through Cambium
- On `complete`: creates `InteractionRecord` (type: `vision_result_ready`),
  pushes `vision_complete` SSE event
- Cambium SSE handler: new event types forwarded to the active thread stream

**Vision service stub:**
- Minimal HTTP service that accepts jobs, processes them (cloud vision API
  initially), and writes results back to the VisionJob table
- Confirm the full pipeline end-to-end before building the real model

### Phase 2 — Plant identification and health evaluation

- `analyze_plants_from_image` tool
- `interaction_node` confirmation flow for writing to plant inventory
- Incident draft path from health issues found in image
- Tests: tool returns structured candidates; cannot write without confirmation

### Phase 3 — Sighting catalog

- `analyze_sighting_from_image`, `log_garden_sighting`, `list_garden_sightings` tools
- `GardenSighting` create/update/query domain functions
- Incident escalation path from confirmed pest/disease sightings
- Tests: sightings are created; confirmed pests link to incidents; beneficial sightings do not

### Phase 4 — Space and sun assessment

- `assess_space_from_image` and `assess_sunlight_from_image` tools
- Confirmation flow for writing dimension/sunlight updates to bed/container records
- Surface assessments as planning constraints during project proposal generation
- Tests: assessment returns structured output; writes require confirmation

---

## Completion criteria

- users can attach images to messages through Verdant and the agent responds to them
- all five feature areas produce structured outputs
- AI-derived findings go through `interaction_node` before persisting to any domain record
- `GardenSighting` history is queryable and surfaces in incident context
- sighting catalog links correctly to existing incident/treatment system

---

## Dependencies

**Required before starting Phase 1:**
- Cambium media upload endpoint working end-to-end (Phase 4 — complete)
- Decision on image storage location (local filesystem on Sparks vs. object storage)

**Benefits significantly from:**
- iNaturalist integration (cross-reference sighting ID with local observation data)
- RAG knowledge base (pest/disease reference data enriches identification)
- Verdant image upload UX (though CLI testing is possible with media IDs)

**Strongly enables:**
- iNaturalist pest monitoring (visual confirmation + local data = stronger incident recommendations)
- Epic 3 project planning (spatial grounding from images improves feasibility assessments)

---

## Open questions

- Image storage location: local filesystem on Thor/Loki, or object storage (MinIO)?
  Local is simpler for now; object storage is better for Verdant serving and multi-node access.
- Still photos only for v1, or support short video clips from the start?
- How should multi-image sessions work? (User sends 4 photos of the same bed across the day for a sun audit — are these linked as a set, or analyzed independently?)
- Confidence threshold below which the agent should always ask a follow-up question rather than present candidates?
