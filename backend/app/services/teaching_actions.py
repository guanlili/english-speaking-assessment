"""Persisted classroom teaching actions; all mutations use short transactions."""

import hashlib
import json
import uuid
from collections import defaultdict

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Classroom, ClassroomExercise, FollowupBatch, Student
from app.services import followups


def create_individual_followups(
    session: Session,
    classroom: Classroom,
    source: ClassroomExercise,
    students: list[Student],
    selections: dict[uuid.UUID, list[uuid.UUID]],
    title: str,
    creator: uuid.UUID,
    request_id: uuid.UUID,
) -> FollowupBatch:
    canonical = {
        str(sid): sorted({str(iid) for iid in ids}) for sid, ids in selections.items()
    }
    signature = hashlib.sha256(
        json.dumps(
            {"source": str(source.id), "title": title.strip(), "targets": canonical},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    # Serializes duplicate submissions and version allocation for the whole batch.
    session.exec(
        select(Classroom).where(Classroom.id == classroom.id).with_for_update()
    ).one()
    existing = session.get(FollowupBatch, request_id)
    if existing:
        if (
            existing.classroom_id != classroom.id
            or existing.created_by != creator
            or existing.payload_hash != signature
        ):
            raise HTTPException(409, detail="Followup batch request conflict")
        return existing
    if (
        not title.strip()
        or not selections
        or set(selections) != {s.id for s in students}
    ):
        raise HTTPException(422, detail="Invalid followup recipients")
    groups: dict[tuple[uuid.UUID, ...], list[Student]] = defaultdict(list)
    for student in students:
        ids = tuple(sorted(set(selections[student.id]), key=str))
        if not ids:
            raise HTTPException(422, detail="Invalid followup items")
        groups[ids].append(student)
    receipt = FollowupBatch(
        id=request_id,
        classroom_id=classroom.id,
        created_by=creator,
        payload_hash=signature,
    )
    session.add(receipt)
    task_ids = []
    for ids, targets in groups.items():
        task = followups.create_followup(
            session, classroom, source, targets, list(ids), title, creator, commit=False
        )
        task_ids.append(str(task.id))
    receipt.task_ids = task_ids
    session.add(receipt)
    session.commit()
    session.refresh(receipt)
    return receipt
