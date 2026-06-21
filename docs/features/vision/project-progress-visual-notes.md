# Project Progress and Visual Notes

## User Workflow

The user uploads a photo to show the current state of a project, plant, bed, or
container. Rhizome summarizes what it sees and optionally records it.

Examples:

- "Here is how the cut flower bed looks now."
- "Can you add this as a progress note?"
- "Does this project look on track?"
- "Remember this layout for later."

## Structured Output

The result should include:

- scene summary
- likely linked subjects: project, bed, container, plant, incident, or task
- visible progress since known project state, if comparable
- visible blockers or concerns
- aesthetic or layout notes when relevant
- suggested follow-up only when it is useful and grounded
- whether the image should be recorded as a note

## Rhizome Actions

Possible actions after user confirmation:

- attach media to a subject
- create a visual note
- record a project or subject activity event
- create a follow-up task
- pin visual context to the active thread when the user wants ongoing reference

## Confirmation Boundary

This feature is mostly observational. Recording a note or attaching media to a
subject can be confirmed lightly. Creating tasks or changing project state needs
the normal review boundary.

## Pipeline Evaluation

**LocateAnything strengths:** finding named entities in the scene, such as
containers, plants, supports, labels, or visible project materials.

**SAM 3 strengths:** scene-level masks, layout comparison, canopy progression,
and visual tracking when the user supplies repeated progress photos.

**Combined pipeline:** Detection and segmentation enrich a concise visual note;
the reasoning layer decides whether anything should affect Rhizome state.

## Open Questions

- Should visual notes be a dedicated model or activity events with attached
  media?
- How should Rhizome decide which subject a progress photo belongs to when the
  user does not specify one?
- Should project progress images be included in future planning context by
  default?

