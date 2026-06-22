# Planning Context

Planning context is the structured snapshot Rhizome uses to draft or revise a
project proposal. It collects relevant garden state and highlights conflicts
before the agent commits to a plan.

## Current Behavior

Gathers candidate locations, unavailable/conflicting resources, candidate plant
material, and resource usage before proposal generation.

## Inputs

- The project brief and current project status.
- Garden profile constraints and preferences.
- Beds, containers, plants, batches, and existing project assignments.
- Active tasks, recent activity, weather context, and incidents when relevant.

## Contract Notes

- Context assembly should prefer structured records over names mentioned in
  prior chat.
- Unavailable or conflicting resources should be visible to the proposal layer
  rather than silently filtered away.
- Candidate plant material should include enough identifiers for later task and
  project linking.
- The planning context route is a read surface; it should not create proposals
  or tasks.

## Related Docs

- [Garden Model](../garden/README.md)
- [Schedule Preview](schedule-preview.md)
- [Task Generation](../tasks/task-generation.md)
