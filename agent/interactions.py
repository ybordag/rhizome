from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional
import json
import uuid

from db.models import (
    InteractionRecord,
    ProjectProposal,
    Task,
    TriageSnapshot,
    TreatmentPlan,
    WeatherTaskChangeSet,
)


INTERACTION_PENDING = "pending"
INTERACTION_RESOLVED = "resolved"
INTERACTION_DISMISSED = "dismissed"
INTERACTION_EXPIRED = "expired"
RESOLVED_ACTIONS = {"approve", "confirm", "continue", "focus_section", "show_task_details", "start_task"}
DISMISSED_ACTIONS = {"reject", "cancel", "dismiss", "dismiss_changes", "request_revision"}


@dataclass
class InteractionAction:
    id: str
    label: str
    kind: str
    style_hint: str = "neutral"
    input_schema: Optional[list[dict[str, Any]]] = None


@dataclass
class InteractionEnvelope:
    id: str
    interaction_type: str
    status: str
    title: str
    summary: str
    body: Optional[str]
    sections: list[dict[str, Any]] = field(default_factory=list)
    actions: list[InteractionAction] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    requires_response: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    expires_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = [asdict(action) for action in self.actions]
        return payload


@dataclass
class InteractionResolution:
    interaction_id: str
    action_id: str
    inputs: dict[str, Any] = field(default_factory=dict)
    resolved_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    actor: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def interaction_id() -> str:
    return str(uuid.uuid4())


def make_action(
    action_id: str,
    label: str,
    kind: str,
    *,
    style_hint: str = "neutral",
    input_schema: Optional[list[dict[str, Any]]] = None,
) -> InteractionAction:
    return InteractionAction(
        id=action_id,
        label=label,
        kind=kind,
        style_hint=style_hint,
        input_schema=input_schema,
    )


def make_envelope(
    *,
    interaction_type: str,
    title: str,
    summary: str,
    body: Optional[str],
    sections: Optional[list[dict[str, Any]]] = None,
    actions: Optional[list[InteractionAction]] = None,
    context: Optional[dict[str, Any]] = None,
    requires_response: bool = False,
    record_id: Optional[str] = None,
) -> dict[str, Any]:
    return InteractionEnvelope(
        id=record_id or interaction_id(),
        interaction_type=interaction_type,
        status=INTERACTION_PENDING,
        title=title,
        summary=summary,
        body=body,
        sections=sections or [],
        actions=actions or [],
        context=context or {},
        requires_response=requires_response,
    ).to_dict()


def record_interaction_summary(
    session,
    envelope: dict[str, Any],
    *,
    source_type: str,
    source_id: Optional[str] = None,
    project_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> InteractionRecord:
    record = InteractionRecord(
        id=envelope["id"],
        interaction_type=envelope["interaction_type"],
        status=envelope["status"],
        title=envelope["title"],
        summary=envelope["summary"],
        project_id=project_id,
        source_type=source_type,
        source_id=source_id,
        record_metadata={
            "body": envelope.get("body"),
            "sections": [
                {"title": section.get("title"), "items": section.get("items", [])[:10]}
                for section in envelope.get("sections", [])
            ],
            "actions": [
                {
                    "id": action.get("id"),
                    "label": action.get("label"),
                    "kind": action.get("kind"),
                    "style_hint": action.get("style_hint"),
                    "input_schema": action.get("input_schema"),
                }
                for action in envelope.get("actions", [])
            ],
            "context": envelope.get("context", {}),
            **(metadata or {}),
        },
    )
    session.add(record)
    session.flush()
    return record


def find_pending_interaction_record(
    session,
    *,
    source_type: str,
    source_id: Optional[str] = None,
    interaction_type: Optional[str] = None,
) -> Optional[InteractionRecord]:
    query = session.query(InteractionRecord).filter(
        InteractionRecord.source_type == source_type,
        InteractionRecord.status == INTERACTION_PENDING,
    )
    if source_id is not None:
        query = query.filter(InteractionRecord.source_id == source_id)
    if interaction_type is not None:
        query = query.filter(InteractionRecord.interaction_type == interaction_type)
    return query.order_by(InteractionRecord.created_at.desc()).first()


def rebuild_envelope_from_record(record: InteractionRecord) -> dict[str, Any]:
    metadata = record.record_metadata or {}
    return make_envelope(
        interaction_type=record.interaction_type,
        title=record.title,
        summary=record.summary,
        body=metadata.get("body"),
        sections=metadata.get("sections") or [],
        actions=[
            make_action(
                action["id"],
                action["label"],
                action["kind"],
                style_hint=action.get("style_hint", "neutral"),
                input_schema=action.get("input_schema"),
            )
            for action in (metadata.get("actions") or [])
        ],
        context=metadata.get("context") or {},
        requires_response=True,
        record_id=record.id,
    )


def resolve_interaction_record(
    session,
    record: InteractionRecord,
    *,
    action_id: str,
    resolution_summary: Optional[str] = None,
) -> InteractionRecord:
    record.resolved_at = datetime.utcnow()
    record.resolution_action = action_id
    record.resolution_summary = resolution_summary
    record.status = infer_resolution_status(action_id)
    session.flush()
    return record


def infer_resolution_status(action_id: str) -> str:
    normalized = action_id.lower()
    if normalized in DISMISSED_ACTIONS:
        return INTERACTION_DISMISSED
    return INTERACTION_RESOLVED


def normalize_resolution(resolution: Any) -> InteractionResolution:
    if isinstance(resolution, dict):
        return InteractionResolution(
            interaction_id=resolution.get("interaction_id", ""),
            action_id=resolution.get("action_id", ""),
            inputs=resolution.get("inputs") or {},
            resolved_at=resolution.get("resolved_at") or datetime.utcnow().isoformat(),
            actor=resolution.get("actor") or "user",
        )

    text = str(resolution).strip().lower()
    if text in {"yes", "y", "confirm"}:
        action_id = "confirm"
    elif text in {"no", "n", "cancel"}:
        action_id = "cancel"
    else:
        action_id = text or "cancel"
    return InteractionResolution(interaction_id="", action_id=action_id)


def build_confirmation_interaction(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    sections = [
        {
            "title": "Operations",
            "items": [f"{call['name']}({call['args']})" for call in tool_calls],
        }
    ]
    return make_envelope(
        interaction_type="confirmation_request",
        title="Confirm destructive operation",
        summary="Rhizome needs approval before applying destructive changes.",
        body="Review the operation details and choose whether to continue.",
        sections=sections,
        actions=[
            make_action("confirm", "Confirm", "approve", style_hint="danger"),
            make_action("cancel", "Cancel", "cancel", style_hint="secondary"),
        ],
        context={"tool_calls": tool_calls},
        requires_response=True,
    )


def build_proposal_review_interaction(session, project_id: str, proposal_id: str) -> dict[str, Any]:
    proposal = (
        session.query(ProjectProposal)
        .filter(ProjectProposal.id == proposal_id, ProjectProposal.project_id == project_id)
        .first()
    )
    if not proposal:
        raise ValueError(f"No proposal found with id {proposal_id} for project {project_id}.")

    cost_estimate = proposal.cost_estimate or {}
    timeline_estimate = proposal.timeline_estimate or {}
    effort_estimate = proposal.effort_estimate or {}
    sections = [
        {
            "title": "Plan",
            "items": [
                proposal.summary,
                f"Approach: {proposal.recommended_approach}",
            ],
        },
        {
            "title": "Estimates",
            "items": [
                f"Cost: ${cost_estimate.get('total_estimated_cost', 'not set')}",
                f"Completion: {timeline_estimate.get('expected_completion_date', 'not set')}",
                f"Total effort: {effort_estimate.get('total_hours', 'not set')} hours",
                f"Weekly effort: {effort_estimate.get('avg_hours_per_week', 'not set')} hours/week",
            ],
        },
    ]
    if proposal.assumptions:
        sections.append({"title": "Assumptions", "items": proposal.assumptions})
    if proposal.tradeoffs:
        sections.append({"title": "Tradeoffs", "items": proposal.tradeoffs})
    if proposal.risks:
        sections.append({"title": "Risks", "items": proposal.risks})

    return make_envelope(
        interaction_type="proposal_review",
        title=f"Review proposal: {proposal.title}",
        summary="Choose whether to accept this proposal, reject it, or request revisions.",
        body=proposal.to_summary(),
        sections=sections,
        actions=[
            make_action("accept_proposal", "Accept proposal", "approve", style_hint="primary"),
            make_action("reject_proposal", "Reject proposal", "reject", style_hint="secondary"),
            make_action(
                "request_revision",
                "Request revision",
                "select",
                style_hint="neutral",
                input_schema=[{"name": "note", "label": "Revision note", "required": False}],
            ),
        ],
        context={"project_id": project_id, "proposal_id": proposal_id},
        requires_response=True,
    )


def build_treatment_plan_review_interaction(session, treatment_plan_id: str) -> dict[str, Any]:
    plan = session.query(TreatmentPlan).filter(TreatmentPlan.id == treatment_plan_id).first()
    if not plan:
        raise ValueError(f"No treatment plan found with id {treatment_plan_id}.")

    sections = [
        {"title": "Recommended steps", "items": [step.get("title", str(step)) for step in (plan.recommended_steps or [])]},
        {"title": "Follow-up", "items": [step.get("title", str(step)) for step in (plan.follow_up_strategy or [])]},
    ]
    return make_envelope(
        interaction_type="treatment_plan_review",
        title=f"Review treatment plan {plan.id}",
        summary="Approve, reject, or request revisions to this treatment plan.",
        body=plan.approach_summary,
        sections=sections,
        actions=[
            make_action("approve_treatment_plan", "Approve treatment plan", "approve", style_hint="primary"),
            make_action("reject_treatment_plan", "Reject treatment plan", "reject", style_hint="secondary"),
            make_action(
                "revise_treatment_plan",
                "Request revision",
                "select",
                style_hint="neutral",
                input_schema=[{"name": "note", "label": "Revision note", "required": False}],
            ),
        ],
        context={"treatment_plan_id": treatment_plan_id},
        requires_response=True,
    )


def build_weather_change_review_interaction(session, change_set_id: str) -> dict[str, Any]:
    change_set = session.query(WeatherTaskChangeSet).filter(WeatherTaskChangeSet.id == change_set_id).first()
    if not change_set:
        raise ValueError(f"No weather task change set found with id {change_set_id}.")

    items = []
    for change in change_set.proposed_changes or []:
        items.append(f"{change.get('task_title', 'Task')}: {change.get('summary', 'No summary')}")
    sections = [{"title": "Proposed changes", "items": items or ["No task changes proposed."]}]
    return make_envelope(
        interaction_type="weather_change_review",
        title=f"Review weather task changes {change_set.id}",
        summary="Approve or dismiss weather-driven task updates.",
        body=change_set.summary,
        sections=sections,
        actions=[
            make_action("approve_changes", "Approve changes", "approve", style_hint="primary"),
            make_action("dismiss_changes", "Dismiss changes", "dismiss", style_hint="secondary"),
        ],
        context={"change_set_id": change_set_id, "project_id": change_set.project_id},
        requires_response=True,
    )


def build_triage_view_interaction(session, snapshot: TriageSnapshot) -> dict[str, Any]:
    tasks = {
        task.id: task
        for task in session.query(Task).filter(Task.id.in_(snapshot.recommended_task_ids or [""])).all()
    }

    def _task_items(ids: list[str]) -> list[str]:
        items = []
        for task_id in ids:
            task = tasks.get(task_id)
            if task:
                items.append(f"{task.id}: {task.title} ({task.status}, {task.estimated_minutes} min)")
        return items or ["none"]

    visible_sections = []
    for title, ids in (
        ("Urgent", snapshot.urgent_task_ids or []),
        ("Routine", snapshot.routine_task_ids or []),
        ("Project Work", snapshot.project_task_ids or []),
    ):
        if ids:
            visible_sections.append({"title": title, "items": _task_items(ids)})
    if not visible_sections:
        visible_sections.append({"title": "Routine", "items": ["none"]})

    section_options = [section["title"] for section in visible_sections]

    return make_envelope(
        interaction_type="triage_view",
        title="Daily triage",
        summary=snapshot.reasoning_summary,
        body=snapshot.user_focus_summary,
        sections=visible_sections,
        actions=[
            make_action("continue", "Continue", "continue", style_hint="secondary"),
            make_action(
                "focus_section",
                "Focus section",
                "select",
                style_hint="neutral",
                input_schema=[
                    {
                        "name": "section",
                        "label": "Section",
                        "required": True,
                        "options": section_options,
                    }
                ],
            ),
            make_action(
                "show_task_details",
                "Show task details",
                "view_details",
                style_hint="neutral",
                input_schema=[{"name": "task_id", "label": "Task ID", "required": True}],
            ),
            make_action(
                "start_task",
                "Start task",
                "approve",
                style_hint="primary",
                input_schema=[{"name": "task_id", "label": "Task ID", "required": True}],
            ),
        ],
        context={
            "triage_snapshot_id": snapshot.id,
            "urgent_task_ids": snapshot.urgent_task_ids or [],
            "routine_task_ids": snapshot.routine_task_ids or [],
            "project_task_ids": snapshot.project_task_ids or [],
            "recommended_task_ids": snapshot.recommended_task_ids or [],
        },
        requires_response=False,
    )


def get_pending_interaction_record(session) -> Optional[InteractionRecord]:
    return (
        session.query(InteractionRecord)
        .filter(InteractionRecord.status == INTERACTION_PENDING)
        .order_by(InteractionRecord.created_at.desc())
        .first()
    )


def list_recent_interaction_records(session, *, limit: int = 20, interaction_type: Optional[str] = None, project_id: Optional[str] = None):
    query = session.query(InteractionRecord)
    if interaction_type:
        query = query.filter(InteractionRecord.interaction_type == interaction_type)
    if project_id:
        query = query.filter(InteractionRecord.project_id == project_id)
    return query.order_by(InteractionRecord.created_at.desc()).limit(limit).all()


def format_interaction_record(record: InteractionRecord) -> str:
    lines = [
        f"[Interaction] {record.title} (id: {record.id})",
        f"  Type: {record.interaction_type} | Status: {record.status}",
        f"  Summary: {record.summary}",
    ]
    if record.resolution_action:
        lines.append(f"  Resolution: {record.resolution_action}")
    if record.resolution_summary:
        lines.append(f"  Notes: {record.resolution_summary}")
    actions = (record.record_metadata or {}).get("actions") or []
    if actions:
        labels = ", ".join(action["label"] for action in actions)
        lines.append(f"  Actions: {labels}")
    return "\n".join(lines)


def stable_confirmation_source_id(tool_calls: list[dict[str, Any]]) -> str:
    return json.dumps(
        [
            {"name": call.get("name"), "args": call.get("args") or {}}
            for call in tool_calls
        ],
        sort_keys=True,
    )
