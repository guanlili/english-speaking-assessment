import uuid
from copy import deepcopy

from fastapi import HTTPException
from sqlmodel import Session, col, func, select

from app import crud
from app.models import Instruction, Passage, RepeatSentence, Scenario, ScenarioQuestion


def copy_passage(
    session: Session, source: Passage, owner_id: uuid.UUID | None
) -> Passage:
    if source.parent_passage_id is not None:
        parent = session.get(Passage, source.parent_passage_id)
        if parent is None:
            raise HTTPException(404, detail="Passage not found")
        source = parent
    session.refresh(source, with_for_update=True)
    children = session.exec(
        select(Passage).where(Passage.parent_passage_id == source.id)
    ).all()
    sources = [source, *children]
    copies: dict[uuid.UUID, Passage] = {}
    for original in sources:
        payload = deepcopy(original.model_dump(exclude={"id", "created_at"}))
        payload.update(
            owner_id=owner_id,
            slug=crud.unique_passage_slug(session, f"{original.slug[:85]}-copy"),
            parent_passage_id=(
                copies[source.id].id if original.parent_passage_id is not None else None
            ),
        )
        if original.id == source.id:
            payload["title"] = f"{original.title[:248]} (copy)"
        copied = Passage.model_validate(payload)
        session.add(copied)
        session.flush()
        copies[original.id] = copied
    sentences = session.exec(
        select(RepeatSentence).where(col(RepeatSentence.passage_id).in_(copies))
    ).all()
    for sentence in sentences:
        assert sentence.passage_id is not None
        payload = deepcopy(sentence.model_dump(exclude={"id", "created_at"}))
        payload.update(owner_id=owner_id, passage_id=copies[sentence.passage_id].id)
        session.add(RepeatSentence.model_validate(payload))
    session.flush()
    return copies[source.id]


def copy_sentence(
    session: Session, source: RepeatSentence, owner_id: uuid.UUID | None
) -> RepeatSentence:
    payload = deepcopy(source.model_dump(exclude={"id", "created_at"}))
    payload.update(owner_id=owner_id, passage_id=None, order_index=0)
    copied = RepeatSentence.model_validate(payload)
    session.add(copied)
    session.flush()
    return copied


def copy_scenario(
    session: Session, source: Scenario, owner_id: uuid.UUID | None
) -> Scenario:
    session.refresh(source, with_for_update=True)
    base = f"{source.topic[:93]} (copy)"
    topic = base
    for index in range(2, 502):
        if (
            session.exec(select(Scenario.id).where(Scenario.topic == topic)).first()
            is None
        ):
            break
        suffix = f" {index}"
        topic = f"{base[: 100 - len(suffix)]}{suffix}"
    else:
        raise HTTPException(409, detail="Copy name conflict")
    copied = Scenario(topic=topic, is_active=source.is_active, owner_id=owner_id)
    session.add(copied)
    session.flush()
    questions = session.exec(
        select(ScenarioQuestion).where(ScenarioQuestion.scenario_id == source.id)
    ).all()
    for question in questions:
        payload = deepcopy(question.model_dump(exclude={"id"}))
        payload.update(owner_id=owner_id, scenario_id=copied.id)
        session.add(ScenarioQuestion.model_validate(payload))
    session.flush()
    return copied


def copy_question(
    session: Session, source: ScenarioQuestion, owner_id: uuid.UUID | None
) -> ScenarioQuestion:
    scenario = session.get(Scenario, source.scenario_id)
    if scenario is None:
        raise HTTPException(404, detail="Scenario not found")
    session.refresh(scenario, with_for_update=True)
    last_order = session.exec(
        select(func.max(ScenarioQuestion.order_index)).where(
            ScenarioQuestion.scenario_id == source.scenario_id
        )
    ).one()
    payload = deepcopy(source.model_dump(exclude={"id"}))
    payload.update(
        owner_id=owner_id,
        order_index=(last_order if last_order is not None else -1) + 1,
    )
    copied = ScenarioQuestion.model_validate(payload)
    session.add(copied)
    session.flush()
    return copied


def copy_instruction(
    session: Session, source: Instruction, owner_id: uuid.UUID | None
) -> Instruction:
    payload = deepcopy(source.model_dump(exclude={"id", "created_at", "updated_at"}))
    payload.update(
        owner_id=owner_id,
        title=f"{source.title[:93]} (copy)" if source.title else None,
    )
    copied = Instruction.model_validate(payload)
    session.add(copied)
    session.flush()
    return copied
