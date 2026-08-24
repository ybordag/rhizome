# Weather Snapshots

Weather snapshots store the forecast Rhizome used when it reasoned about
garden work. They provide a stable record for triage, monitor alerts, and
weather-driven task changes.

## Current Behavior

Fetches a 7-day forecast, stores summary conditions, alert summaries, derived
impacts, recommendations, and raw payload.

## Snapshot Content

- Garden profile location and fetch timestamp.
- Summary forecast conditions and raw upstream payload.
- Alert summaries and derived garden impacts.
- Recommendations that can be shown in chat or dashboards.
- Links to task impact or change-set records derived from the snapshot.

## Contract Notes

- Snapshot fetch depends on a usable garden profile location.
- Stale data should be identified clearly rather than silently treated as fresh.
- The upstream forecast source should be isolated behind domain helpers so API
  routes and tools return consistent structured data.
- Forecast failures should not break unrelated chat or task workflows.

## Related Docs

- [Weather Task Impacts](weather-task-impacts.md)
- [Daily Triage](../triage/README.md)
