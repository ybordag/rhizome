# Sun and Shadow Audit

## User Workflow

The user uploads one or more photos of a bed, container, or garden area at known
or approximate times of day. Rhizome estimates light and shadow conditions.

Examples:

- "How much sun does this bed get?"
- "This is the west side at 2pm. Is it full sun?"
- "Can you compare these morning and afternoon photos?"
- "Should I move these containers somewhere brighter?"

## Structured Output

The result should include:

- location target: bed, container, project area, or garden-wide area
- time-of-day metadata: morning, midday, afternoon, evening, unknown
- light class: full sun, partial sun, dappled shade, deep shade, unknown
- estimated sunlit versus shaded regions when masks are available
- visible shadow sources such as trees, fences, walls, buildings, neighboring
  plants, or shade cloth
- multi-image synthesis across the day when multiple photos are linked
- confidence and missing information

## Rhizome Actions

Possible actions after user confirmation:

- update `Bed.sunlight`
- update container location notes
- attach media to a bed, container, or project
- add a planning constraint for future proposals
- create a follow-up task to take another photo at a missing time of day
- suggest moving containers or changing plant selection

## Confirmation Boundary

Single-photo sun estimates should not overwrite profile data without
confirmation. Multi-photo audits are stronger, but final bed/container sunlight
updates still require user review.

## Pipeline Evaluation

**LocateAnything strengths:** locating beds, containers, shadow sources, bright
regions, and shaded regions if text prompts are reliable.

**SAM 3 strengths:** segmenting sunlit and shaded areas, tracking changes across
photos or video, and estimating region ratios.

**Combined pipeline:** LocateAnything grounds relevant scene objects; SAM 3
segments sun/shadow regions; the reasoning layer combines time, location, and
garden constraints.

## Open Questions

- Should Rhizome infer time from photo EXIF metadata when available?
- How many time points are required before calling something a full sun or
  partial sun location?
- Should weather conditions at capture time be used to discount cloudy-day
  photos?
