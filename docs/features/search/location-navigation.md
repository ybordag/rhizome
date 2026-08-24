# Location Navigation

Location navigation returns the garden entities associated with a named area,
bed, or container so the frontend can show what is physically there.

## Current Behavior

Lists everything in a named garden area or location, including plants,
containers, and beds.

## Result Content

- Matching beds and containers.
- Plants located in or associated with the requested location.
- Convenience labels such as location name and plant summary fields.
- Links back to related projects, tasks, and activity where available.

## Contract Notes

- The requested location must resolve within the current user's garden.
- Unowned or nonexistent locations should return not found rather than an empty
  success response.
- Result grouping should stay stable enough for Verdant to render location
  pages without parsing prose.
- Location names are labels; duplicate or ambiguous names should be handled with
  explicit IDs where possible.

## Related Docs

- [Beds and Containers](../garden/beds-containers.md)
- [Garden Search](garden-search.md)
