# Inventory and Container Reconciliation

## User Workflow

The user uploads a photo of an area and asks Rhizome to compare what is visible
with what the garden inventory says should be there.

Examples:

- "Does this match what Rhizome thinks is in this bed?"
- "Which containers are visible here?"
- "Did I forget to log any plants?"
- "Can you check whether these growbags are already in the inventory?"
- "I moved some pots. Help me update Rhizome."

## Structured Output

The result should include:

- expected plants from Rhizome inventory for the target location
- expected containers from Rhizome inventory for the target location
- detected plants
- detected containers
- matched expected items
- expected items not visible
- unexpected visible items
- ambiguous matches
- suggested corrections with confidence
- unresolved questions for the user

## Rhizome Actions

Possible actions after user confirmation:

- attach media to the reconciled area
- update plant location, status, notes, or removed state
- update container location, notes, or removed state
- create new plant or container draft records
- create an inspection task for unresolved mismatches
- record an inventory reconciliation activity event

## Confirmation Boundary

Inventory reconciliation is consequential. The model can propose corrections,
but every plant or container creation, move, removal, or status update requires
explicit user confirmation.

## Pipeline Evaluation

**LocateAnything strengths:** open-vocabulary detection and counting of plant
types, pots, growbags, trays, labels, trellises, and other inventory-relevant
objects. This is likely the primary benchmark for LocateAnything.

**SAM 3 strengths:** segmenting repeated containers, plant canopies, trays, and
grouped objects. Useful when object boundaries or overlaps make box-only
matching unreliable.

**Combined pipeline:** LocateAnything proposes visible objects; SAM 3 separates
instances and overlapping regions; the reasoning layer matches detections to
Rhizome records.

## Open Questions

- What minimum evidence is needed to mark an expected plant or container as
  missing rather than merely out of frame?
- Should barcode/label/OCR matching be part of this feature or a later
  enhancement?
- How should Rhizome represent "suspected duplicate" records before user
  cleanup?
