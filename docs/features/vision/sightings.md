# Sightings: Pests, Diseases, Weeds, Beneficials, and Wildlife

## User Workflow

The user uploads a photo of an organism, symptom, weed, or garden visitor and
asks Rhizome what it is or whether it matters.

Examples:

- "What bug is this on my pepper?"
- "Is this a weed or something I planted?"
- "Are these aphids?"
- "Can you log this pollinator?"
- "What are these spots on the cucumber leaves?"

## Structured Output

The result should include:

- candidate names or symptom labels
- sighting type: `pest`, `disease`, `weed`, `beneficial`, `pollinator`,
  `wildlife`, or `unknown`
- confidence and uncertainty reasons
- visible evidence: location on plant, number of organisms, affected tissue,
  spread pattern, damage type
- affected subjects if identifiable: plant, bed, container, project, or
  garden-wide
- severity estimate: none, low, medium, high, urgent
- recommended immediate observation or organic-first response
- whether the finding should remain a sighting or escalate to an incident

## Rhizome Actions

Possible actions after user confirmation:

- create a `GardenSighting`
- attach media to the sighting and linked subject
- create or update an `IncidentReport`
- draft a treatment plan for confirmed incidents
- create monitoring or inspection tasks
- add the sighting to local pest/wildlife history for later seasonal pattern
  analysis

## Confirmation Boundary

Beneficial and neutral sightings can be logged after confirmation. Pest,
disease, and weed findings should not automatically create incidents or
treatment tasks without user review.

## Pipeline Evaluation

**LocateAnything strengths:** open-vocabulary localization of small visible
targets such as insects, eggs, weeds, spots, holes, webs, frass, or larvae.

**SAM 3 strengths:** segmenting affected leaf regions, weed coverage, clusters,
or repeated organism instances when the concept is visually consistent.

**Combined pipeline:** LocateAnything identifies candidate objects or symptoms;
SAM 3 segments the region; the reasoning layer determines whether it is a
record-only sighting or an incident candidate.

## Open Questions

- How should Rhizome handle uncertain pest/disease identity when the visual
  symptom is real but taxonomy is unclear?
- Should sightings be deduplicated by date, subject, and likely organism?
- Which external local-observation sources should enrich sighting confidence?
