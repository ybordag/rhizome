# Search and Navigation

Search and navigation help users and the agent find existing garden state
before creating duplicate records or planning against the wrong location. This
domain covers structured entity lookup, location browsing, and project-context
navigation.

## Feature Sets

- [Garden Search](garden-search.md)
- [Location Navigation](location-navigation.md)
- [Project Navigation](project-navigation.md)

## User Capabilities

- Search plants, batches, beds, containers, tasks, projects, and incidents by
  name or relevant structured fields.
- Browse a location and see the beds, containers, and plants associated with it.
- Navigate from a project to linked tasks, garden records, proposals, activity,
  and timeline events.
- Let the agent resolve existing entities before proposing mutations.
- Use structured search results in Cambium and Verdant without parsing agent
  prose.

## Owned Domain Concepts

- garden search result views
- unified search result grouping
- location result views
- project navigation context

## Invariants

- Search results are always scoped to `user_id`.
- Empty or too-short queries should return a controlled validation response
  rather than a broad accidental dump.
- Search should prefer active, relevant records while still allowing explicit
  access to historical records such as removed plants.
- Location navigation should verify ownership of the requested location before
  returning related entities.
- Current search is structured database search. Deeper full-text ranking,
  embeddings, and retrieval-augmented context are future improvements.

## Runtime Surfaces

- Agent tools use search to disambiguate user references and avoid duplicate
  garden records.
- Internal data routes expose garden search, unified search, location results,
  and project navigation data.
- Activity, project, task, and garden feature pages all depend on search and
  navigation for frontend workflows.

See [Garden Model](../garden/README.md), [Project Planning](../projects/README.md),
and [API Reference](../../architecture/api-reference.md) for the main route
consumers.
