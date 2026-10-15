"""组卷按页浏览、按引用恢复详情；不改发布快照或题库内容。"""

import uuid

from fastapi import APIRouter, HTTPException
from sqlmodel import Field, SQLModel, col, select

from app.api.deps import SessionDep, TeacherUserDep
from app.api.routes.admin_content import (
    PassageWithSentences,
    ScenarioOut,
    SentenceWithPassage,
    list_passages,
    list_scenarios,
    list_sentences_flat,
)
from app.models import (
    AssignmentItemIn,
    Instruction,
    InstructionPublic,
    ScenarioQuestion,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class ComposerLibraryData(SQLModel):
    passages: list[PassageWithSentences] = Field(default_factory=list)
    sentences: list[SentenceWithPassage] = Field(default_factory=list)
    scenarios: list[ScenarioOut] = Field(default_factory=list)
    instructions: list[InstructionPublic] = Field(default_factory=list)
    missing_ids: list[uuid.UUID] = Field(default_factory=list)


class ComposerSelectionIn(SQLModel):
    items: list[AssignmentItemIn] = Field(max_length=4000)


@router.post("/composer-selection", response_model=ComposerLibraryData)
def read_composer_selection(
    session: SessionDep,
    current_user: TeacherUserDep,
    body: ComposerSelectionIn,
) -> ComposerLibraryData:
    buckets: dict[str, list[uuid.UUID]] = {
        kind: []
        for kind in ("passage", "repeat", "scenario", "question", "instruction")
    }
    for item in body.items:
        if item.type not in buckets:
            raise HTTPException(422, detail="Unknown item type")
        buckets[item.type].append(item.id)
    passages = (
        list_passages(
            session, current_user, q=None, skip=0, limit=None, ids=buckets["passage"]
        ).data
        if buckets["passage"]
        else []
    )
    sentences = (
        list_sentences_flat(
            session,
            current_user,
            exam_kind=None,
            exam_level=None,
            ids=buckets["repeat"],
            q=None,
            skip=0,
            limit=None,
        )
        if buckets["repeat"]
        else []
    )
    scenario_ids = set(buckets["scenario"])
    if buckets["question"]:
        scenario_ids.update(
            session.exec(
                select(ScenarioQuestion.scenario_id).where(
                    col(ScenarioQuestion.id).in_(buckets["question"])
                )
            ).all()
        )
    scenarios = (
        list_scenarios(
            session, current_user, q=None, skip=0, limit=None, ids=list(scenario_ids)
        ).data
        if scenario_ids
        else []
    )
    instructions = (
        session.exec(
            select(Instruction).where(col(Instruction.id).in_(buckets["instruction"]))
        ).all()
        if buckets["instruction"]
        else []
    )
    found = (
        {p.id for p in passages}
        | {child for p in passages for child in p.reading_child_ids}
        | {s.id for s in sentences}
        | {s.id for s in scenarios}
        | {q.id for s in scenarios for q in s.questions}
        | {i.id for i in instructions}
    )
    return ComposerLibraryData(
        passages=passages,
        sentences=sentences,
        scenarios=scenarios,
        instructions=[InstructionPublic.model_validate(row) for row in instructions],
        missing_ids=sorted({item.id for item in body.items} - found),
    )
