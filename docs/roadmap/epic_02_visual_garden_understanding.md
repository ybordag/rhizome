# Epic 2 Plan: Visual Garden Understanding

**Epic status:** Ready to start  
**Last updated:** April 29th, 2026

---

## Purpose

Let Rhizome use photos or video to identify plants, reason about plant health,
assess physical space, and support visual updates to the garden model.

This is one of the most differentiated product capabilities in the original
design vision.

---

## Why this epic matters now

The current system already has strong backend foundations that visual analysis
can feed into:

- garden profile and plant/container/bed persistence
- incidents and treatment plans
- task tracker and triage
- structured interactions
- activity log

What is missing is the visual input and analysis layer.

---

## What should exist by the end of this epic

- the user can provide photos or video of:
  - a plant
  - a bed/container area
  - a broader garden space
- Rhizome can:
  - identify likely plants from images
  - identify likely pest or disease candidates from images
  - assess broad plant condition from images
  - assess layout/space conditions from images where appropriate
  - turn the results into:
    - candidate diagnoses
    - profile updates
    - incident drafts
    - planning constraints
    - follow-up questions when uncertain
- all diagnosis or treatment recommendations remain user-confirmed rather than
  fully autonomous

---

## Proposed implementation slices

### Slice 1: Visual intake contract

Define how Rhizome receives and references image/video inputs:

- what data the app passes
- how backend tools reference media
- what analysis result schema should look like

This should align with Epic 9.

### Slice 2: Plant identification

Implement the first narrow visual capability:

- image -> likely plant identity candidates
- confidence / uncertainty handling
- option to write identified plants into inventory/profile workflows

### Slice 3: Pest / disease candidate analysis

Add visual incident-assist workflows:

- image -> likely pest or disease candidates
- confidence / uncertainty handling
- clear user confirmation before:
  - incident creation
  - treatment-plan drafting
  - task creation

This should support the existing incident/treatment stack rather than bypass it.

### Slice 4: Space / layout assessment

Add visual support for physical garden understanding:

- identify whether an image shows a bed, container grouping, or general space
- estimate rough usable area where possible
- capture visible crowding / airflow issues
- support sunlight/layout notes when the visual evidence is strong enough

### Slice 5: Visual update workflows

Turn analysis into structured workflows:

- “use this image to update my profile”
- “record this as a possible pest issue”
- “help me decide whether this bed has space for another plant”
- “estimate whether this location has enough light”

---

## Completion criteria

This epic should be considered complete when:

- users can submit plant or garden images through the product flow
- Rhizome can produce structured visual analysis outputs for plant ID and
  incident candidates
- visual analysis can feed profile, incident, and planning workflows
- Rhizome asks for confirmation when uncertainty is material
- visual diagnosis does not bypass the current treatment and task systems

---

## Important dependencies

### Strongly depends on

- Epic 9: App-Facing Interaction and Frontend Experience

This epic is not strictly impossible without Epic 9, but image-first UX is far
better in the app than in the CLI.

### Also benefits from

- Epic 1: Garden Profiling and Spatial Garden Modeling
- Epic 8: Knowledge and External Retrieval

### Strongly enables

- Epic 3: Project Planning and Negotiation
- Epic 6: Reactive Monitoring and Alerting
- Epic 7: Iteration and Amendments

---

## Open questions to resolve inside this epic

- what visual tasks are in scope for v1?
- should video be included in the first slice, or should we start with still
  images only?
- how do we represent confidence and uncertainty in a way that is usable in the
  app?
- what visual outputs should become structured updates versus plain advisory
  text?
