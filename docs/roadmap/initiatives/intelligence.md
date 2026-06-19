# Intelligence Initiative

**Track:** Intelligence
**Status:** Pending — starts after FastAPI internal layer is in place
**Last updated:** 2026-06

---

## Summary

Three complementary capabilities that make the agent's reasoning better grounded:

- **Google Search** — live, current information at planning time
- **RAG** — deep, structured knowledge retrieved from a curated knowledge base
- **Full-text search** — fast lookup across the user's own domain data

These are separate features but share an implementation phase since they all touch the agent's context-building pipeline.

---

## Google Search grounding

### Why

The agent's training data has a knowledge cutoff. When proposing a project or evaluating treatment options, it may be unaware of new pest pressures, updated guidance, current seed availability, or climate shifts. A Google Search call at planning time grounds the proposal in current information.

### What it enables

- "Best tomato varieties for zone 9b heat stress in 2026" — surfaces current cultivar recommendations
- "Organic treatment for cucumber mosaic virus" — retrieves current community-validated approaches
- "Companion planting for pest suppression with brassicas" — grounds care plans in evidence
- News-aware triage: "unusual late frost events in California this spring" — context the weather API alone can't provide

### Design

A `web_search(query)` tool wrapping the Google Custom Search API (or SerpAPI as an alternative):

```python
# agent/tools/operations/search.py
def web_search(query: str, num_results: int = 5) -> str:
    """Search Google for current information to ground planning decisions."""
```

The tool is available to the agent during project planning and incident analysis. The agent decides when to call it — it is not called automatically. Results are injected into the conversation as tool output, subject to the same interaction/confirmation flow as other external data.

**Key invariant:** search results derived from external sources that would create or modify domain records must still go through `interaction_node` confirmation. The agent can surface search findings in its response without a confirmation; it cannot auto-write a new IncidentReport based on a search result without user approval.

### API options

| Option | Cost | Notes |
|---|---|---|
| Google Custom Search API | $5/1000 queries | 100 free/day; most reliable |
| SerpAPI | $50/mo for 5000 queries | Easier setup, more results types |
| Tavily | $0 for 1000/mo | Designed for AI agents; clean JSON output |

Tavily is the recommended starting point — purpose-built for LLM tool use, returns clean structured results, and has a generous free tier.

### Environment variable

```
TAVILY_API_KEY  (or GOOGLE_CSE_KEY + GOOGLE_CSE_ID)
```

---

## RAG / knowledge base

### Why

Some knowledge is better served from a curated, structured source than from live web search: detailed plant care profiles, historical pest/disease reference data, seed-saving guides, companion planting matrices. RAG retrieves the most relevant chunks at query time and injects them into the agent's context.

### What it enables

- Accurate care recommendations grounded in species-specific requirements (not general gardening advice)
- Pest/disease identification with reference to documented symptoms and treatment protocols
- Propagation guidance with timing windows for the user's specific climate zone

### Design

Uses `pgvector` (already in `requirements.txt`, not yet enabled) for vector similarity search.

**Pipeline:**

```
Source documents (plant guides, pest references, etc.)
    ↓
Chunking + embedding (langchain text splitter + embedding model)
    ↓
pgvector store (new table: knowledge_chunk)
    ↓
At query time: embed the query → cosine similarity search → top-k chunks → inject into context
```

**New DB model:**

```python
class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"
    id          = Column(String, PK)
    source      = Column(String)   # e.g. "plant_care_guide", "pest_reference"
    title       = Column(String)
    content     = Column(Text)
    embedding   = Column(Vector(1536))  # pgvector
    created_at  = Column(DateTime)
```

**New tool:**

```python
def search_knowledge_base(query: str, source: str = None, limit: int = 5) -> str:
    """Retrieve relevant knowledge chunks for a planning or care query."""
```

**Knowledge sources to build out:**
- Plant care profiles (watering, fertilizing, pruning schedules by species)
- Common pest/disease identification guide (symptoms → likely cause)
- Companion planting matrix
- Seed-saving and propagation timing guide

### Prerequisite

`pgvector` extension must be enabled in Postgres: `CREATE EXTENSION IF NOT EXISTS vector;`

---

## Full-text search

### Why

Users need to find things in their own data: "show me all tasks mentioning drip irrigation", "find any plants I've noted as struggling", "search my activity for anything about the south bed".

### Design

Postgres `tsvector` full-text search across the main domain tables. No new infrastructure — Postgres handles it natively.

**Scope:** plants (name, variety, notes), tasks (title, description, notes), projects (name, goal, notes), activity_event (summary, notes), incident_report (summary, notes).

**New DB columns:**

```sql
ALTER TABLE plant ADD COLUMN search_vector tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(name,'') || ' ' || coalesce(variety,'') || ' ' || coalesce(notes,''))
    ) STORED;

-- GIN index for fast search
CREATE INDEX ix_plant_search ON plant USING GIN(search_vector);
-- (repeat for task, gardening_project, activity_event, incident_report)
```

**New tool:**

```python
def search_domain(query: str, types: list[str] = None, limit: int = 20) -> str:
    """Full-text search across plants, tasks, projects, and activity."""
```

**Cambium endpoint:**

```
GET /api/v1/search?q=drip+irrigation&types=tasks,plants
```

### Implementation notes

- `to_tsvector` generated columns are maintained automatically on insert/update — no application code needed
- Start with `english` dictionary; add multilingual support if needed later
- Ranking via `ts_rank` on the result set

---

## iNaturalist

### Why

iNaturalist is a crowdsourced species observation platform with a public API
covering millions of plant, insect, and wildlife observations worldwide. For a
gardening agent, it provides two things no other source does: hyperlocal pest
observation data and real-world species identification grounded in actual
sightings near the user's garden.

### What it enables

- "Have there been spotted lanternfly sightings near me this season?" — proactive
  risk awareness before a pest appears in the user's garden
- Cross-referencing a pest identified from a photo against local iNaturalist
  observations — strengthens an incident recommendation with real evidence
- Cataloging beneficial organisms: "what pollinators are common in my area right
  now?" — grounds companion planting and habitat recommendations
- Feeding into the reactive monitoring pipeline as a second signal source
  alongside weather — when local pest pressure is high, urgency on vulnerable
  plants can be escalated automatically

### Design

A `search_inaturalist(query, radius_km, days_back)` tool calls the
iNaturalist Observations API. No API key is required for read access — the
endpoint is public.

```python
# agent/tools/operations/search.py
def search_inaturalist(
    taxon_query: str,
    radius_km: float = 25.0,
    days_back: int = 30,
    limit: int = 10,
) -> str:
    """
    Search recent iNaturalist observations near the user's garden location.
    taxon_query: common or scientific name (e.g. 'aphid', 'Aphis gossypii').
    Returns recent local observations with dates, locations, and photo links.
    """
```

The tool reads `lat`/`lng` from the user's `GardenProfile`. If location is not
set, the tool returns an error instructing the user to update their profile.

**API endpoint:**
```
GET https://api.inaturalist.org/v1/observations
    ?lat=LAT&lng=LNG&radius=RADIUS_KM
    &q=TAXON_QUERY
    &d1=START_DATE
    &per_page=10
    &order=desc&order_by=observed_on
```

**No API key required** for read-only access. Rate limit: 100 requests/minute.

### Relationship to visual garden understanding

iNaturalist is most powerful when paired with the visual sighting catalog. When
a user photographs a pest and the agent identifies it, iNaturalist can immediately
confirm whether that pest has been observed locally — turning an isolated
identification into a grounded risk assessment. Building this after visual garden
understanding is recommended but not required; the tool works independently for
text-based queries too.

### Integration with reactive monitoring

Once iNaturalist is in place, the monitoring system (`scripts/monitor.py`) can
run a `pest_job()` alongside the existing weather job: query iNaturalist for
known pest taxa near the garden, cross-reference against active projects and
current plant inventory, and generate `MonitorAlert` records when pressure is
high. This closes the loop between community observation data and proactive
task urgency.

---

## Phases

### Phase 1 — Google Search
- Add Tavily (or Google CSE) API key to `.env`
- `agent/tools/operations/search.py`: `web_search()` tool
- Register in `agent/tools/__init__.py`
- Tests: tool returns structured results; agent calls it during planning

### Phase 2 — Full-text search
- Add `search_vector` generated columns + GIN indexes to relevant tables
- `agent/tools/operations/search.py`: `search_domain()` tool
- Cambium `GET /api/v1/search` endpoint (data proxy)
- Tests: keyword search returns relevant results; empty query returns error

### Phase 3 — iNaturalist

- `search_inaturalist()` tool in `agent/tools/operations/search.py`
- Register in `agent/tools/__init__.py`
- Tests: tool returns observations near a known lat/lon; handles missing location gracefully
- Optional: `pest_job()` in `scripts/monitor.py` for background iNaturalist monitoring

### Phase 4 — RAG
- Enable `pgvector` extension
- `KnowledgeChunk` model + embedding pipeline (`scripts/embed_knowledge.py`)
- `agent/tools/operations/search.py`: `search_knowledge_base()` tool
- Seed initial knowledge base (plant care profiles, pest reference)
- Tests: retrieval returns relevant chunks for known queries
