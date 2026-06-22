# Project Briefs

Project briefs capture the user's intent before Rhizome drafts a plan. They
separate the goal and constraints from the later proposal and generated work.

## Current Behavior

Captures project requirements including goal, desired outcome, target dates,
budget, effort preference, propagation preference, priorities, and notes.

## User Workflows

- Create a brief from chat or structured project setup.
- Update goals, constraints, unknowns, timing, budget, and effort preferences as
  the user clarifies intent.
- Ask the agent what information is still missing before proposal drafting.
- Use the brief as the stable input for planning context and proposal
  generation.

## Contract Notes

- A brief can be incomplete; the agent should expose unknowns rather than
  inventing constraints.
- Updating a brief should not mutate accepted proposals or historical
  revisions.
- Brief data is user-scoped through the owning project.
- Readiness for proposal is a domain judgment based on required context,
  explicit unknowns, and the risk of acting on assumptions.

## Related Docs

- [Planning Context](planning-context.md)
- [Proposals and Revisions](proposals-revisions.md)
