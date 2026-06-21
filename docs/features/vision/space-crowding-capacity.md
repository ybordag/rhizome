# Space, Crowding, Airflow, and Container Capacity

## User Workflow

The user uploads a photo of a bed, container grouping, growbag area, or open
garden space and asks Rhizome whether the space is usable or overfilled.

Examples:

- "Can I fit anything else here?"
- "Is this too crowded?"
- "How many containers can I add?"
- "Does this bed have enough airflow?"
- "Can this area support the next planting project?"

## Structured Output

The result should include:

- detected beds, containers, plants, open soil, paths, walls, fences, slopes,
  supports, obstructions, and access constraints
- crowding level: open, moderately planted, crowded, severely crowded, unknown
- airflow risk: low, medium, high, unknown
- visible empty or usable zones
- container capacity notes: available space, likely mobility/access issues,
  visible pot/growbag sizes when inferable
- confidence in spatial estimates
- whether a reference object or known dimensions are needed

## Rhizome Actions

Possible actions after user confirmation:

- attach media to a `Bed`, `Container`, or project
- update bed or container notes
- propose dimension, capacity, or sunlight-related profile updates
- add planning constraints to a project brief or proposal context
- create tasks such as thin plants, prune for airflow, move containers, clear
  path, measure bed, or take reference photo

## Confirmation Boundary

Spatial estimates should be treated as planning evidence, not authoritative
measurement. Dimension or capacity updates require user confirmation, especially
when there is no reference object.

## Pipeline Evaluation

**LocateAnything strengths:** finding beds, containers, plant clusters, paths,
walls, support structures, and visible empty regions by prompt.

**SAM 3 strengths:** segmenting open soil, canopy coverage, container footprints,
paths, and crowded regions. Better for area ratios and mask-level measurement.

**Combined pipeline:** LocateAnything locates concepts; SAM 3 produces masks;
the reasoning layer turns ratios and scene context into crowding and planning
constraints.

## Open Questions

- Should Rhizome require known bed dimensions before estimating usable area?
- How should container size be inferred when pot labels or reference objects are
  not visible?
- Where should long-lived visual planning constraints be stored?

