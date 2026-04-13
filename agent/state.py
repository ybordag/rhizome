# state.py
from langgraph.graph import MessagesState
from typing import Any, Optional

class GardenState(MessagesState):
    temporal_context: Optional[dict[str, Any]]
    session_context: Optional[dict[str, Any]]
    weather_context: Optional[dict[str, Any]]
    triage_snapshot: Optional[dict[str, Any]]
