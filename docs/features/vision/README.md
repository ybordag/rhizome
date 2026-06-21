# Vision Feature Surface

Rhizome's vision layer lets the agent reason over garden images while keeping
domain state, user confirmation, and async delivery explicit.

The feature surface is intentionally model-agnostic. LocateAnything, SAM 3, a
multimodal LLM, or a combined pipeline can all serve the same user workflows as
long as they return the same structured result contracts.

See [Async Vision Compute](../../architecture/async-vision-compute.md) for the
architecture boundary between Rhizome, Fairlead, k3s, and deferred Temporal.
See [Image Processing Architecture and Implementation Plan](image-processing-architecture.md)
for the first implementation design.

## Product Principles

**Async first.** Image analysis runs through `VisionJob`. The agent submits a
job, responds immediately, and receives partial or final results later.

**Structured before conversational.** Vision outputs should be machine-readable
enough to create interaction cards, proposed updates, tasks, sightings, and
incidents. Free-text summaries are derived from structured findings.

**Confirmation before writes.** AI-derived facts do not directly mutate garden
records. Any update to plants, beds, containers, incidents, tasks, or project
constraints goes through a user-visible confirmation or review path.

**Observations are not incidents.** Many visual findings are neutral or useful
context. `GardenSighting` records observations. `IncidentReport` records a
problem requiring tracking or treatment.

**Pipelines are comparable.** Each feature should support multiple pipeline
implementations behind the same result shape, so Fairlead or a future vision
router can compare quality, latency, cost, and hardware fit.

## Shared Vision Result Shape

Every vision feature should return a high-level envelope like this:

```json
{
  "job_id": "vision-job-id",
  "analysis_type": "plant_health",
  "pipeline": "locate_anything_v1",
  "media_results": [
    {
      "media_id": "media-id",
      "observations": [],
      "regions": [],
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
  "requires_confirmation": true
}
```

Fields can be specialized by feature, but the outer shape should remain stable.

## Pipeline Families

**LocateAnything pipeline.** Best for open-vocabulary localization, counting,
and bounding boxes. It should be evaluated for object discovery, inventory
checks, pest/weed localization, and container detection.

**SAM 3 pipeline.** Best for concept segmentation, masks, repeated instances,
and video/image tracking. It should be evaluated for canopy coverage, crowding,
growth comparison, weed coverage, shadow regions, and mask-level spatial
estimates.

**LocateAnything plus SAM 3 pipeline.** LocateAnything proposes boxes or points;
SAM 3 turns them into masks. This is likely strongest when Rhizome needs both
open-vocabulary detection and quantitative region measurement.

**Reasoning/synthesis layer.** A multimodal or text LLM still synthesizes model
outputs into gardening findings, uncertainty notes, and proposed Rhizome
actions. Local grounding models should not be expected to decide treatment,
toxicity, climate fit, or long-horizon planning effects alone.

## Feature Set

1. Plant identification and health assessment
2. Pest, disease, weed, beneficial, pollinator, and wildlife sightings
3. Growth and phenology estimation
4. Space, crowding, airflow, and container capacity
5. Sun and shadow audit
6. Project progress and visual notes
7. Inventory and container reconciliation

## Implementation Plan

- [Image Processing Architecture and Implementation Plan](image-processing-architecture.md)
