# Growth and Phenology Estimation

## User Workflow

The user uploads a current photo, or a sequence of photos over time, and asks
Rhizome to assess growth, readiness, or biological stage.

Examples:

- "Are these ready to transplant?"
- "How many seedlings came up?"
- "Has this plant improved since last week?"
- "Are the tomatoes flowering yet?"
- "Can I harvest these soon?"

## Structured Output

The result should include:

- growth stage: germinating, seedling, vegetative, budding, flowering,
  fruiting, harvest-ready, senescing, dormant, unknown
- estimated plant count or visible survival count
- germination or survival estimate when compared to expected quantity
- canopy coverage or size estimate when masks are available
- flowering, fruiting, pest damage, or stress evidence
- change since previous comparable media, if available
- transplant, pot-up, thinning, pruning, staking, or harvest readiness
- confidence and image-quality limitations

## Rhizome Actions

Possible actions after user confirmation:

- update `Plant.is_flowering` or `Plant.is_fruiting`
- update plant notes or care state
- record an inspection activity event
- create tasks such as thin seedlings, pot up, harden off, transplant, stake,
  prune, harvest, or recheck
- mark a task event anchor as satisfied when a biological trigger is visually
  confirmed

## Confirmation Boundary

Growth estimates can inform recommendations immediately, but inventory counts,
plant state changes, and event-anchor resolutions require confirmation.

## Pipeline Evaluation

**LocateAnything strengths:** counting seedlings, flowers, fruits, pots, labels,
or individual plants by open-vocabulary prompt.

**SAM 3 strengths:** canopy masks, repeated-instance segmentation, growth over
time, and tracking in video or multi-photo sequences.

**Combined pipeline:** LocateAnything counts and labels visible entities; SAM 3
measures area and tracks masks across time; the reasoning layer maps this to
gardening stages and task readiness.

## Open Questions

- What metadata is required to compare two photos reliably: same plant, same
  angle, same distance, same container, or explicit user confirmation?
- Should Rhizome store derived measurements separately from free-form notes?
- How should low-confidence counts affect inventory reconciliation?

