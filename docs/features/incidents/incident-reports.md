# Incident Reports

Incident reports describe a problem or observation that may need treatment,
monitoring, or follow-up work.

## Current Behavior

Tracks pest, disease, weed, and other garden incidents with severity, status,
summary, notes, project links, subjects, reporter, and detected time.

## User Workflows

- Report a new incident from chat, API, or eventually a vision result.
- Link the incident to plants, batches, beds, containers, projects, or the
  whole garden.
- Filter incidents by status, severity, type, project, or subject.
- Update notes, severity, status, and subject links.
- Resolve an incident when the problem is handled or no longer relevant.

## Contract Notes

- Incident reads and writes are scoped through the owning user and linked
  garden records.
- Duplicate avoidance should prefer updating or linking to an existing open
  incident when the same subject and problem are already tracked.
- Resolved incidents remain historical records for activity and future
  diagnosis.
- Deletion should respect approved treatment plans and generated work.

## Related Docs

- [Treatment Plans](treatment-plans.md)
- [Sightings](../vision/sightings.md)
- [Per-Entity History](../activity/per-entity-history.md)
