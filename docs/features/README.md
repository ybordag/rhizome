# Feature Specifications

Durable product-level feature specifications for Rhizome.

These docs describe what Rhizome should be able to do from a user's point of
view, what structured outputs the agent should produce, and which persistent
domain objects each feature can read or write. They are not roadmap plans.
Roadmap docs explain build order and implementation status; feature docs define
the intended behavior once a capability exists.

## Vision Features

Structured vision is the first modality expansion beyond text. Each feature is
designed to run through an asynchronous `VisionJob` and to return the same
high-level result shape regardless of the underlying model pipeline.

- [Vision Feature Surface](vision/README.md)
- [Plant Identification and Health Assessment](vision/plant-identification-health.md)
- [Sightings: Pests, Diseases, Weeds, Beneficials, and Wildlife](vision/sightings.md)
- [Growth and Phenology Estimation](vision/growth-phenology.md)
- [Space, Crowding, Airflow, and Container Capacity](vision/space-crowding-capacity.md)
- [Sun and Shadow Audit](vision/sun-shadow-audit.md)
- [Project Progress and Visual Notes](vision/project-progress-visual-notes.md)
- [Inventory and Container Reconciliation](vision/inventory-container-reconciliation.md)
- [Image Processing Architecture and Implementation Plan](vision/image-processing-architecture.md)

## Current Feature Domains

These folders describe the product behavior that Rhizome already owns today.
Use them to understand the feature boundaries before changing domain logic,
agent tools, or structured API contracts. They intentionally sit above the API
reference: API docs list routes and response shapes, while feature docs explain
the user outcome, persistent objects, invariants, and cross-feature behavior.

- [Garden Model](garden/README.md)
- [Project Planning](projects/README.md)
- [Task Management](tasks/README.md)
- [Daily Triage](triage/README.md)
- [Weather](weather/README.md)
- [Incidents and Treatment](incidents/README.md)
- [Human-in-the-Loop Interactions](interactions/README.md)
- [Action History](activity/README.md)
- [Search and Navigation](search/README.md)
