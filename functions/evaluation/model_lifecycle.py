# -*- coding: utf-8 -*-
from dataclasses import asdict, dataclass

from config import VALIDATION_MAX_ATTEMPTS


@dataclass(frozen=True)
class ResearchIdea:
    idea_id: str
    status: str
    validation_attempt_count: int
    baseline_at_attempt_start: str | None = None


@dataclass(frozen=True)
class IdeaAttempt:
    idea_id: str
    attempt_id: str
    stage: str
    status: str


def register_research_idea(idea_id, baseline_at_attempt_start=None):
    return ResearchIdea(
        idea_id=idea_id,
        status="active",
        validation_attempt_count=0,
        baseline_at_attempt_start=baseline_at_attempt_start,
    )


def register_validation_attempt(idea_state, stage="validation"):
    attempt_number = idea_state.validation_attempt_count + 1
    attempt = IdeaAttempt(
        idea_id=idea_state.idea_id,
        attempt_id=f"{idea_state.idea_id}_attempt_{attempt_number:02d}",
        stage=stage,
        status="running",
    )
    next_status = "active"
    if attempt_number >= VALIDATION_MAX_ATTEMPTS:
        next_status = "attempt_limit_reached"
    next_idea = ResearchIdea(
        idea_id=idea_state.idea_id,
        status=next_status,
        validation_attempt_count=attempt_number,
        baseline_at_attempt_start=idea_state.baseline_at_attempt_start,
    )
    return next_idea, attempt


def freeze_candidate_for_test(idea_state):
    return ResearchIdea(
        idea_id=idea_state.idea_id,
        status="frozen_for_test",
        validation_attempt_count=idea_state.validation_attempt_count,
        baseline_at_attempt_start=idea_state.baseline_at_attempt_start,
    )


def terminate_idea(idea_state):
    return ResearchIdea(
        idea_id=idea_state.idea_id,
        status="terminated",
        validation_attempt_count=idea_state.validation_attempt_count,
        baseline_at_attempt_start=idea_state.baseline_at_attempt_start,
    )


def lifecycle_snapshot(idea_state, attempt=None):
    payload = {"idea": asdict(idea_state)}
    if attempt is not None:
        payload["attempt"] = asdict(attempt)
    return payload
