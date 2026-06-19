"""Pydantic request/response models for the internal API."""

from typing import Optional
from pydantic import BaseModel


class AgentRequest(BaseModel):
    user_id: str
    thread_id: str
    message: str
    provider: Optional[str] = None
    provider_key: Optional[str] = None
    model: Optional[str] = None


class AgentResponse(BaseModel):
    thread_id: str
    response: str
    # interaction contains the interrupt payload when the graph pauses for user input
    interaction: Optional[dict] = None


class ResumeRequest(BaseModel):
    user_id: str
    thread_id: str
    resolution: str


class DismissAlertRequest(BaseModel):
    pass


class TaskActionRequest(BaseModel):
    notes: Optional[str] = None


class DeferTaskRequest(BaseModel):
    defer_until: str  # ISO date string
    notes: Optional[str] = None
