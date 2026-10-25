"""Versioned local-prototype API. Client claims never become trusted context.

Sessions and event deduplication live in one process only. The default adapter has
no observations, receipts or physical facts; real adapters belong to Phase 6.
"""

import asyncio
import os
from dataclasses import dataclass, field, replace
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from .schemas import Profile
from .tasking.models import ObservationSnapshot, TaskEvent, TaskModel, TaskPlan, TaskState, Text
from .tasking.planning import (
    NebiusPlanProvider,
    PlanningError,
    PlanningRequest,
    PlanProposal,
    PlanProvider,
    generate_reviewed_plan,
    start_planned_task,
)
from .tasking.prompting import Cue
from .tasking.semantics import SemanticReview
from .tasking.service import ServiceEvent, ServiceResult, handle_event
from .tasking.verification import VerificationContext, profile_to_capabilities


class TaskCreateRequest(TaskModel):
    goal: Text = Field(max_length=200)
    transcript: Text = Field(max_length=500)
    user_profile: Profile


class TaskEventRequest(TaskModel):
    event_id: Text = Field(max_length=100)
    expected_version: int = Field(strict=True, ge=1)
    event: TaskEvent


class TaskSessionResponse(TaskModel):
    task_id: str
    version: int
    plan: TaskPlan
    state: TaskState
    mode: Literal["MOCK_PROVIDER", "LIVE_NEBIUS", "TEMPLATE"]
    accepted: bool
    reason_code: str
    cue: Cue | None = None
    events: list[ServiceEvent] = Field(default_factory=list)


class TaskCreateResponse(TaskModel):
    decision: Literal["allow", "confirm", "assist", "stop"]
    reason_code: str
    session: TaskSessionResponse | None = None


@dataclass
class Session:
    proposal: PlanProposal
    request: TaskCreateRequest
    review: SemanticReview
    result: ServiceResult
    version: int = 1
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    event_ids: set[str] = field(default_factory=set)


class TaskSessions:
    """Backend dependency; replace context() only with an authenticated adapter.

    UUID task IDs are possession handles for this local synthetic prototype, not
    account authentication. Never accept VerificationContext from HTTP payloads.
    """

    def __init__(self, max_sessions: int = 100, max_events: int = 1000):
        self.sessions: dict[str, Session] = {}
        self.max_sessions = max_sessions
        self.max_events = max_events
        self.pending = 0

    def context(self, task_id: str, plan_id: str, request: TaskCreateRequest):
        return VerificationContext(
            task_id=task_id,
            plan_id=plan_id,
            snapshot=ObservationSnapshot(revision="unobserved"),
            capabilities=profile_to_capabilities(request.user_profile),
        )

    def current_context(self, session: Session):
        return replace(
            self.context(session.proposal.task_id, session.proposal.plan.plan_id, session.request),
            semantic_review=session.review,
        )

    def get(self, task_id: str):
        session = self.sessions.get(task_id)
        if session is None:
            raise HTTPException(404, detail="task_not_found")
        return session


def sessions(request: Request) -> TaskSessions:
    return request.app.state.task_sessions


def provider() -> PlanProvider:
    # Explicit live opt-in; no fixture/template or legacy demo fallback.
    if os.getenv("PLANNER_MODE", "demo").lower() != "live":
        raise PlanningError("live_mode_required")
    return NebiusPlanProvider.from_environment()


def response(session: Session, result: ServiceResult) -> TaskSessionResponse:
    return TaskSessionResponse(
        task_id=session.proposal.task_id,
        version=session.version,
        plan=session.proposal.plan,
        state=result.state,
        mode=session.proposal.mode,
        accepted=result.accepted,
        reason_code=result.reason_code,
        cue=result.cue,
        events=list(result.events),
    )


router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
Store = Annotated[TaskSessions, Depends(sessions)]


@router.post("", response_model=TaskCreateResponse)
async def create_task(body: TaskCreateRequest, store: Store):
    if len(store.sessions) + store.pending >= store.max_sessions:
        raise HTTPException(503, detail="session_capacity_reached")
    store.pending += 1
    live_provider = None
    try:
        task_id, plan_id = uuid4().hex, uuid4().hex
        context = store.context(task_id, plan_id, body)
        data = PlanningRequest(
            task_id=task_id, plan_id=plan_id, goal=body.goal, transcript=body.transcript,
            capabilities=context.capabilities, observations=context.snapshot,
        )
        # Lazy provider: independent veto must not require credentials or call a model.
        class LazyProvider:
            mode = "LIVE_NEBIUS"
            model_id = None

            async def complete(self, messages, schema):
                nonlocal live_provider
                live_provider = provider()
                self.mode, self.model_id = live_provider.mode, live_provider.model_id
                return await live_provider.complete(messages, schema)

        reviewed = await generate_reviewed_plan(data, LazyProvider())
        check = reviewed.verification
        if reviewed.proposal is None:
            return TaskCreateResponse(decision=check.decision, reason_code=check.reason_code)
        started = start_planned_task(
            reviewed.proposal,
            replace(store.context(task_id, plan_id, body), semantic_review=reviewed.review),
            body.user_profile.preferred_guidance,
        )
        if started.service is None:
            return TaskCreateResponse(
                decision=started.verification.decision,
                reason_code=started.verification.reason_code,
            )
        session = Session(reviewed.proposal, body, reviewed.review, started.service)
        store.sessions[task_id] = session
        return TaskCreateResponse(
            decision=started.verification.decision,
            reason_code=started.service.reason_code,
            session=response(session, started.service),
        )
    except PlanningError as error:
        raise HTTPException(502, detail=error.reason_code) from None
    finally:
        store.pending -= 1
        if isinstance(live_provider, NebiusPlanProvider):
            await live_provider.__aexit__(None, None, None)


@router.get("/{task_id}", response_model=TaskSessionResponse)
async def get_task(task_id: str, store: Store):
    session = store.get(task_id)
    async with session.lock:
        result = handle_event(
            session.proposal.plan, session.result.state, store.current_context(session),
            preferred_guidance=session.request.user_profile.preferred_guidance,
        )
        if result.state != session.result.state:
            session.version += 1
        session.result = result
        return response(session, result)


@router.post("/{task_id}/events", response_model=TaskSessionResponse)
async def task_event(task_id: str, body: TaskEventRequest, store: Store):
    session = store.get(task_id)
    async with session.lock:
        # Retries never re-emit cues or replay a stale success response.
        if body.event_id in session.event_ids:
            raise HTTPException(409, detail="duplicate_event_id")
        if body.expected_version != session.version:
            raise HTTPException(409, detail="state_version_conflict")
        if session.result.state.status in ("stopped", "completed"):
            raise HTTPException(409, detail="terminal_state")
        if len(session.event_ids) >= store.max_events and body.event.type not in (
            "stop", "refusal",
        ):
            raise HTTPException(409, detail="event_capacity_reached")
        result = handle_event(
            session.proposal.plan, session.result.state, store.current_context(session),
            body.event, session.request.user_profile.preferred_guidance,
        )
        # Every well-formed, ordered attempt consumes a version, including policy holds.
        session.event_ids.add(body.event_id)
        session.version += 1
        session.result = result
        return response(session, result)
