# Plant Identification and Health Assessment

## User Workflow

The user uploads one or more photos of a plant and asks Rhizome to identify it,
confirm an existing plant, or assess visible health.

Examples:

- "What plant is this?"
- "Is this tomato healthy?"
- "Does this look like blight?"
- "Can you check the basil in this container?"

## Structured Output

The result should include:

- likely plant candidates with confidence and uncertainty reasons
- whether the image appears to show the requested plant
- visible symptoms such as yellowing, spotting, wilting, scorching, holes,
  curling, chlorosis, mildew, broken stems, or pest damage
- likely stress categories: water, heat, nutrient, pest, disease, transplant
  shock, crowding, unknown
- affected plant regions when available: leaves, stem, flowers, fruit, roots,
  soil surface
- image quality limitations and requested follow-up photos
- recommended next steps

## Rhizome Actions

Possible actions after user confirmation:

- attach the media asset to an existing `Plant`
- propose a new `Plant` record or update an existing one
- update plant state such as flowering, fruiting, stressed, inspected, or notes
- record a care or inspection activity event
- draft an `IncidentReport` for confirmed pest, disease, or severe stress
- create a follow-up task such as inspect underside of leaves, prune damaged
  foliage, isolate plant, water deeply, or photograph again in several days

## Confirmation Boundary

The model may suggest plant identity and health findings, but it must not
directly create or modify plant records. It should create a reviewable
interaction when it wants to write inventory, care state, incident, or task data.

## Pipeline Evaluation

**LocateAnything strengths:** locating plant instances, leaves, flowers, fruit,
and visible damage regions by text query. Useful for cropping candidate regions
before classification or reasoning.

**SAM 3 strengths:** segmenting the plant canopy or damaged areas and measuring
coverage. Useful for severity estimates and before/after comparison.

**Combined pipeline:** LocateAnything finds the plant or damaged region; SAM 3
produces masks; the reasoning layer interprets symptoms in garden context.

## Open Questions

- What confidence threshold requires a follow-up photo rather than a candidate?
- Should species candidates be validated against a local plant database,
  PlantNet, iNaturalist, or a user-specific plant inventory first?
- How should Rhizome represent "suspected disease" before incident confirmation?
