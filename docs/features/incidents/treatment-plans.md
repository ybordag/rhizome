# Treatment Plans

Treatment plans convert an incident into specific recommended action while
keeping the final decision with the user.

## Current Behavior

Drafts treatment approaches with recommended steps and follow-up strategy.
Approval creates treatment tasks linked to the incident's project.

## Plan Content

- Diagnosis or working hypothesis.
- Recommended steps and timing.
- Safety notes and escalation criteria.
- Follow-up strategy and expected outcome.
- Task generation payload for approved work.

## Contract Notes

- Drafting a treatment plan should not create treatment tasks.
- Approval is a structured interaction or structured API operation.
- Approved plans create linked tasks and activity events.
- Existing draft or approved plans should prevent accidental duplicate drafts
  for the same incident.
- Manual treatment plans should use the same structured view shape as
  agent-drafted plans.

## Related Docs

- [Structured Approvals](../interactions/structured-approvals.md)
- [Task Generation](../tasks/task-generation.md)
