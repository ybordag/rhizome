# Rhizome Documentation

## Overview
- [Vision and Design](overview/vision-and-design.md) — why it exists, design philosophy, interaction surface
- [Features](overview/features.md) — complete capability inventory

## Feature Specifications
- [Feature Specs](features/README.md) — durable product-level behavior specs
- [Garden Model](features/garden/README.md)
- [Project Planning](features/projects/README.md)
- [Task Management](features/tasks/README.md)
- [Daily Triage](features/triage/README.md)
- [Weather](features/weather/README.md)
- [Incidents and Treatment](features/incidents/README.md)
- [Human-in-the-Loop Interactions](features/interactions/README.md)
- [Action History](features/activity/README.md)
- [Search and Navigation](features/search/README.md)
- [Vision Feature Surface](features/vision/README.md) — structured vision capability surface and shared contracts
- [Plant Identification and Health Assessment](features/vision/plant-identification-health.md)
- [Sightings: Pests, Diseases, Weeds, Beneficials, and Wildlife](features/vision/sightings.md)
- [Growth and Phenology Estimation](features/vision/growth-phenology.md)
- [Space, Crowding, Airflow, and Container Capacity](features/vision/space-crowding-capacity.md)
- [Sun and Shadow Audit](features/vision/sun-shadow-audit.md)
- [Project Progress and Visual Notes](features/vision/project-progress-visual-notes.md)
- [Inventory and Container Reconciliation](features/vision/inventory-container-reconciliation.md)
- [Image Processing Architecture and Implementation Plan](features/vision/image-processing-architecture.md)

## Getting Started
- [Setup](getting-started/setup.md) — installation, configuration, first run
- [Using the CLI](getting-started/using-the-cli.md) — how to have a session

## Architecture
- [System Overview](architecture/system-overview.md) — repos, runtime topology, Cambium/Rhizome/Verdant/Fairlead
- [Agent Loop](architecture/agent-loop.md) — end-to-end session walkthrough
- [Async Vision Compute](architecture/async-vision-compute.md) — Rhizome/Fairlead/k3s ownership for bounded vision jobs
- [Data Model](architecture/data-model.md) — all models, lifecycle, relationships
- [Deployment](architecture/deployment.md) — instance topology, stateless scaling, Postgres checkpointer, Temporal future
- [API Reference](architecture/api-reference.md) — complete `/api/v1` endpoint reference
- [Tools Reference](architecture/tools-reference.md) — all 95 tools by domain

## Development
- [Code Organization](development/code-organization.md) — directory guide, module responsibilities, how to add tools
- [Testing Guide](development/testing.md) — test structure, patterns, writing new tests

## Current Work
- [Calendula: Reactive Monitoring and Alerting](current_work/calendula_reactive_monitoring.md) — cron runner, MonitorAlert model, auto-apply weather policy, triage + series jobs

## Roadmap
- [Roadmap Overview](roadmap/overview.md) — tracks, current status, dependency map
- [Intelligence: Google Search, RAG, full-text search](roadmap/initiatives/intelligence.md)
- [Visual Garden Understanding](roadmap/initiatives/visual_garden_understanding.md)
- [App Frontend Experience (Verdant)](roadmap/initiatives/app_frontend_experience.md)

## Design Reference
- [Original Design Document](design/garden_agent_design.md) — original problem statement and design vision (2026, partially stale)

## Archive
- [Archive Index](archive/README.md) — completed phase plans and superseded docs, now for historical reference only
