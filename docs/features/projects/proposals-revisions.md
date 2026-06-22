# Proposals and Revisions

Proposals are reviewable plans. Revisions are accepted historical versions.
This split lets the user compare, edit, and approve a plan before Rhizome
creates executable work.

## Current Behavior

Stores project proposals with selected locations/plants, feasibility notes,
cost/timeline/effort estimates, assumptions, risks, and tradeoffs. Accepting a
proposal creates a `ProjectRevision` and `ProjectExecutionSpec`.

## User Workflows

- Draft a proposal from a project brief and planning context.
- Review locations, plant material, assumptions, risks, tradeoffs, timeline, and
  estimated cost.
- Ask for revisions before accepting.
- Accept a proposal through a structured approval interaction.
- Inspect accepted revisions and the active execution spec later.

## Contract Notes

- Proposal acceptance is the boundary between planning and task generation.
- Accepted proposal data should be copied into immutable revision records.
- A new accepted revision should supersede prior active execution where the
  domain rules allow it.
- Interaction cards should carry enough source IDs for approval to resume
  without reparsing chat text.
- Revision history should remain available for timeline and audit views.

## Related Docs

- [Structured Approvals](../interactions/structured-approvals.md)
- [Task Generation](../tasks/task-generation.md)
- [Project Timeline](../activity/project-timeline.md)
