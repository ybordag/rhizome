# Project Planning

Project planning turns an open-ended gardening goal into a scoped, reviewable,
versioned plan that can generate executable work. It is the bridge between chat
planning and the durable task graph.

Projects should preserve user intent, make assumptions explicit, support
revision, and avoid creating irreversible or high-effort work without a review
step.

## Feature Sets

- [Project Briefs](project-briefs.md)
- [Planning Context](planning-context.md)
- [Proposals and Revisions](proposals-revisions.md)
- [Schedule Preview](schedule-preview.md)

## User Capabilities

- Create and update gardening projects from chat or structured API calls.
- Capture a project brief with goals, constraints, unknowns, locations,
  materials, timing, budget, and risk notes.
- Build planning context from the garden profile, current locations, plants,
  weather, tasks, and relevant history.
- Draft and revise project proposals before acceptance.
- Preview a schedule without committing generated tasks.
- Accept a proposal to create a project revision, execution spec, task
  generation run, and task set.
- Assign beds, containers, plants, expenses, and shopping items to a project.
- View progress, timeline, activity, and related tasks.

## Owned Domain Objects

- `GardeningProject`
- `ProjectBrief`
- `ProjectProposal`
- `ProjectRevision`
- `ProjectExecutionSpec`
- `TaskGenerationRun`
- project location, plant, shopping, and expense link models

## Invariants

- Proposal acceptance is a structured approval flow. A proposal should not
  become executable work merely because the agent mentioned it in prose.
- Accepted revisions are historical records. New planning work should create a
  new revision instead of rewriting what was accepted.
- The active execution spec is the source of truth for generated project tasks.
- Regeneration must preserve user-modified work and supersede only replaceable
  generated tasks.
- Deleting a project is blocked when active, non-superseded tasks still depend
  on it.
- Project routes and tools must enforce `user_id` ownership across projects,
  linked garden records, generated tasks, and activity history.

## Runtime Surfaces

- Agent tools support conversational project planning, proposal drafting,
  revision, acceptance, schedule preview, and status checks.
- Structured interaction records carry proposal-review envelopes into Cambium
  and Verdant.
- Internal data routes expose project lists, details, planning context,
  proposals, previews, generated tasks, timeline, activity, expenses, and
  shopping data.

See [Task Management](../tasks/README.md), [Human-in-the-Loop Interactions](../interactions/README.md),
and [API Reference](../../architecture/api-reference.md) for the connected
execution and review flows.
