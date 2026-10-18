"""Classroom ownership and pagination for targeted-practice evidence."""

import uuid

from fastapi import Query

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.class_followups import task_of
from app.api.routes.class_shared import (
    _get_classroom,
    _require_classroom_teacher,
    router,
)
from app.services import followup_outcomes
from app.services.followup_outcomes import FollowupOutcomes


@router.get("/{code}/followups/{task_id}/outcomes", response_model=FollowupOutcomes)
def read_followup_outcomes(
    session: SessionDep,
    code: str,
    task_id: uuid.UUID,
    current_user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=20),
) -> FollowupOutcomes:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    task = task_of(session, classroom.id, task_id)
    return followup_outcomes.read_outcomes(session, classroom, task, offset, limit)
