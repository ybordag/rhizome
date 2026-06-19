# Onboarding and Data Import

**Track:** Platform
**Status:** Pending — starts after visual garden understanding (Phase 1) is in place
**Last updated:** 2026-06

---

## Shared infrastructure with visual garden understanding

Chat import uses the **same async job pattern** as vision analysis: submit a
job, process incrementally, push partial results as cards via SSE, deliver a
final confirmation card when complete.

For chat import, "incremental" means the parser extracts garden context section
by section — profile data, then plants, then projects — pushing each batch as a
partial card as it finishes rather than making the user wait for the full parse.
The user can review and confirm early findings while later extractions are still
running.

The `VisionJob` model (and the async delivery pipeline in Phase 1 of the visual
garden understanding initiative) should be generalized before chat import is
built — either by making `VisionJob` a generic `BackgroundJob` with a `job_type`
field, or by sharing the SSE push and `InteractionRecord` creation logic while
keeping separate job tables. This is a design decision to make at implementation
time, once the vision infrastructure is proven.

---

## Summary

Two capabilities that help users bring existing knowledge into Rhizome rather
than starting from scratch:

- **Google Drive integration** — connect a Drive account for image import and
  ongoing photo storage, so photos taken on a phone can flow directly into the
  agent without manual upload
- **Chat import** — parse existing AI chat histories (Claude, ChatGPT, Gemini)
  to bootstrap a garden profile and project context for new users or users who
  have been planning verbally with an AI assistant but haven't structured that
  knowledge yet

Both features handle external, potentially inconsistent data. All extracted
content must go through `interaction_node` confirmation before persisting to any
domain record — this is a hard invariant, not optional.

---

## Google Drive integration

### Why

Users document their garden constantly: photos of pests, progress shots, plans
sketched out in chat. That material often lives in Google Drive or on a phone
that backs up to Drive. Connecting Drive means:

- users can import images from Drive directly into Rhizome without uploading
  through Verdant
- photos taken on a phone can be added to a sighting, incident, or project note
  by selecting them from Drive
- existing plant photos become available for visual analysis without re-uploading

### What it enables

- "Use the photos I took of my tomatoes this week" — user selects Drive photos;
  agent runs visual analysis on them
- "I documented the aphid problem in a Drive folder last summer" — user imports
  images; agent links them to the existing incident history
- Ongoing: new photos saved to a designated Drive folder can appear in Rhizome
  automatically (push notification or periodic sync)

### Design

Google Drive access is handled through an MCP (Model Context Protocol) server.
The MCP server runs as a sidecar and exposes Drive read operations as tools
the agent can call. The agent never writes to Drive — it only reads.

**New tools (via Drive MCP):**

```python
def list_drive_images(folder_path: str = None, days_back: int = 30) -> str:
    """List images in the user's Drive, optionally filtered by folder or recency."""

def import_drive_image(drive_file_id: str, attachment_kind: str,
                        subject_type: str = None, subject_id: str = None) -> str:
    """
    Import an image from Drive into Rhizome's MediaAsset store.
    Downloads the file, creates a MediaAsset record, and optionally links it
    to a subject. Returns the new media_id for use with visual analysis tools.
    """
```

**Key invariant:** Drive files are external, untrusted content. An image pulled
from Drive creates a `MediaAsset` record and can be passed to visual analysis
tools, but any AI-derived findings still go through `interaction_node`
confirmation before persisting to domain records.

### Dependencies

- `MediaAsset` model must exist (Visual Garden Understanding, Phase 1)
- Google Drive OAuth credentials configured for the user
- Drive MCP server running as a sidecar process

---

## Chat import

### Why

Many users have months of gardening conversations with Claude, ChatGPT, or
Gemini. These conversations contain:

- plant inventory ("I have 3 tomato plants in growbags on the patio")
- project plans ("I want to do a cottage garden in the front bed this spring")
- care history ("I moved the lavender after it struggled with poor drainage")
- preferences ("I never use chemical pesticides")
- constraints ("my dog eats everything at ground level")

Parsing this history and turning it into a structured Rhizome profile and project
context is the highest-value onboarding path — it turns a new user into an
informed user without a lengthy intake interview.

### What it enables

- New user onboarding: paste or import a chat history → agent extracts garden
  profile draft, existing plants, any projects discussed → user confirms before
  anything is saved
- Catch-up for existing users: import a conversation that happened outside
  Rhizome to get it into the record
- "We talked about the herb spiral last month in Claude" — user imports that
  chat; agent extracts the discussed plan and creates a project draft

### Design

**Two input paths:**

1. **Paste**: user pastes raw chat text into the Rhizome conversation. Agent
   detects it's a chat log and runs the extraction flow.
2. **Drive import**: user imports a chat export file (JSON or text) from Drive
   using the Drive MCP tools above. Agent parses and runs the extraction flow.

**Extraction flow:**

```
Incoming chat text (raw, untrusted)
    ↓
submit_chat_import_job(text, thread_id) → job_id returned immediately
Agent responds: "I'm parsing your chat history — I'll send you what I
  find as I go. Feel free to keep working."

[Background parser processes the chat in sections]

Section 1 — profile data extracted:
  → partial result pushed as SSE card: "Found: zone 9b, clay soil, 
    preference for organic methods — confirm?"

Section 2 — plants extracted:
  → partial result: "Found 4 plants: 3 tomatoes, 1 lavender — confirm?"

Section 3 — projects extracted:
  → partial result: "Found a planned cottage garden project — confirm?"

All sections done:
  → final InteractionRecord created (type: chat_import_complete)
  → SSE card: "Import complete — 3 of 4 sections confirmed, 
    1 needs your review"
```

**Key invariant:** every extracted item must be user-confirmed before writing.
Each partial card is a review interaction — the user can confirm, edit, or
dismiss each batch independently as they arrive. This is the highest-risk
path for hallucinated or misinterpreted data in the entire system; the
incremental review pattern makes it safer because smaller batches are easier
to verify than one large wall of extracted data.

**New tool:**

```python
def extract_from_chat_history(raw_text: str) -> str:
    """
    Parse a pasted or imported AI chat log and extract structured garden
    context: profile data, plants, projects, care notes. Returns an extraction
    draft for user review. Nothing is written until the user confirms.
    """
```

**Common chat export formats to handle:**
- Claude.ai: JSON export with conversation turns
- ChatGPT: JSON export (`conversations.json`)
- Google Gemini: direct text paste (no structured export yet)
- Generic: any text that looks like a conversation (alternating user/assistant turns)

### Accuracy considerations

Chat history extraction is inherently imprecise. The agent will find:
- Hypothetical plans that were discussed but never acted on
- Contradictory information from different points in the conversation
- Vague descriptions ("a few tomatoes") that need disambiguation

The extraction prompt should explicitly distinguish **confirmed facts** (things
the user stated as true now) from **discussed plans** (things that might happen)
and **questions** (things the user wasn't sure about). Uncertain items should
surface as questions in the review interaction rather than proposed writes.

---

## Phases

### Phase 1 — Drive MCP setup

- Configure Google Drive MCP server
- `list_drive_images` and `import_drive_image` tools
- `MediaAsset` creation from Drive files
- Tests: import a Drive image → MediaAsset record created; linked subject optional

### Phase 2 — Chat import (paste path)

- `extract_from_chat_history` tool and extraction prompt
- `interaction_node` review flow for extracted garden context
- Handle Claude.ai and ChatGPT export formats
- Tests: known chat fixture extracts correct plants and profile; hallucinated items
  are flagged as uncertain; nothing writes without confirmation

### Phase 3 — Chat import (Drive path)

- Import chat export files from Drive using the Drive MCP tools
- Parse JSON export formats for Claude.ai and ChatGPT
- Tests: Drive JSON import produces same extraction quality as paste path

---

## Completion criteria

- users can import Drive images and run visual analysis on them
- users can paste or import a chat history and get a structured review of what
  Rhizome extracted
- no extracted data persists without explicit user confirmation
- extraction correctly distinguishes confirmed facts from discussed plans

---

## Dependencies

**Required:**
- `MediaAsset` model (Visual Garden Understanding, Phase 1)
- Drive MCP server configured and available as a sidecar

**Benefits from:**
- Visual garden understanding tools (imported Drive images can immediately be
  analyzed for plant ID, health, or sightings)
