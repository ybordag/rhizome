"""
Unified entity search tool — searches across all six entity types.
"""
from typing import Optional

from langchain.tools import tool

from agent.domain.search import ALL_TYPES, search_entities
from db.database import SessionLocal, current_user_id


def _format_results(data: dict) -> str:
    results = data["results"]
    by_type = data["by_type"]

    if not results:
        return "No matching entities found."

    total = len(results)
    type_summary = ", ".join(
        f"{count} {t}" for t, count in by_type.items() if count > 0
    )
    lines = [f"Found {total} result(s) — {type_summary}:\n"]

    current_type = None
    for r in results:
        if r["subject_type"] != current_type:
            current_type = r["subject_type"]
            lines.append(f"[{current_type.upper()}]")
        parts = [f"  • {r['label']} (id: {r['subject_id']})"]
        if r.get("secondary_label"):
            parts.append(f"    {r['secondary_label']}")
        if r.get("summary"):
            parts.append(f"    {r['summary']}")
        lines.append("\n".join(parts))

    return "\n".join(lines)


@tool
def search_domain(
    query: str,
    types: Optional[str] = None,
    limit: Optional[int] = 5,
) -> str:
    """
    Search across all garden entities by keyword or UUID. Use this when the
    user asks to find something by name or description and you're not sure
    which entity type it belongs to — for example 'find anything about
    aphids', 'search for drip irrigation', 'what do I have called Sungold?'.
    Also use for UUID lookups when you have an ID but don't know the type.

    Prefer the more specific tools (list_plants, list_project_tasks, etc.)
    when you already know the entity type and just need to filter or list.

    types: comma-separated entity types to search — plant, bed, container,
    task, project, incident. Omit to search all types.
    limit: max results per type (default 5, max 20).
    """
    session = SessionLocal()
    try:
        type_list = [t.strip() for t in types.split(",")] if types else None
        data = search_entities(
            session,
            user_id=current_user_id.get(),
            query=query,
            types=type_list,
            limit_per_type=limit or 5,
        )
        return _format_results(data)
    except ValueError as e:
        return f"Search error: {e}"
    except Exception as e:
        print(f"[DEBUG] search_domain failed: {e}")
        return f"Search failed: {e}"
    finally:
        session.close()
