# state.py
from langgraph.graph import MessagesState
from typing import Any, Optional

class GardenState(MessagesState):
    temporal_context: Optional[dict[str, Any]]
    session_context: Optional[dict[str, Any]]
    startup_opener: Optional[str]
    weather_context: Optional[dict[str, Any]]
    triage_snapshot: Optional[dict[str, Any]]
    pending_interaction: Optional[dict[str, Any]]
    interaction_history: Optional[list[dict[str, Any]]]
    skip_tool_node: Optional[bool]
    user_id: Optional[int]
