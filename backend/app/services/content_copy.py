import uuid
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app import crud
from app.models import Instruction, Passage, RepeatSentence, Scenario, ScenarioQuestion


def commit_copy(session: Session) -> None:
    """复制类落库的统一提交口：名字探测与插入之间的并发窗口撞唯一
    约束（主题/slug）时转 409，而不是把 IntegrityError 泄成 500。"""
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, detail="Copy name conflict") from None


def copy_passage(
    session: Session,
    source: Passage,
    owner_id: uuid.UUID | None,
    target_tenant_id: uuid.UUID | None = None,
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
        if target_tenant_id is not None:
            # C2 复制到本校：租户与 slug 查重都按目标校（deepcopy 会带源校值）
            payload["tenant_id"] = target_tenant_id
        payload.update(
            owner_id=owner_id,
            copied_from_id=original.id,
            slug=crud.unique_passage_slug(
                session, f"{original.slug[:85]}-copy", tenant_id=target_tenant_id
            ),
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
        if target_tenant_id is not None:
            payload["tenant_id"] = target_tenant_id
        payload.update(
            owner_id=owner_id,
            copied_from_id=sentence.id,
            passage_id=copies[sentence.passage_id].id,
        )
        session.add(RepeatSentence.model_validate(payload))
    session.flush()
    return copies[source.id]


def copy_sentence(
    session: Session,
    source: RepeatSentence,
    owner_id: uuid.UUID | None,
    target_tenant_id: uuid.UUID | None = None,
) -> RepeatSentence:
    payload = deepcopy(source.model_dump(exclude={"id", "created_at"}))
    if target_tenant_id is not None:
        # C2 复制到本校：deepcopy 会带源校 tenant_id，覆盖为目标校
        payload["tenant_id"] = target_tenant_id
    payload.update(
        owner_id=owner_id, copied_from_id=source.id, passage_id=None, order_index=0
    )
    copied = RepeatSentence.model_validate(payload)
    session.add(copied)
    session.flush()
    return copied


def copy_scenario(
    session: Session,
    source: Scenario,
    owner_id: uuid.UUID | None,
    target_tenant_id: uuid.UUID | None = None,
) -> Scenario:
    session.refresh(source, with_for_update=True)
    # 跨校复制保留原主题：情景问答按 topic 与本校单元主题精确匹配
    # （class_shared._scenario_for_topic），加 "(copy)" 会让副本永远匹配不上
    # 篇目，问答位在学生端恒为空。同校复制仍加后缀避让同名。
    same_tenant = target_tenant_id is None or target_tenant_id == source.tenant_id
    base = f"{source.topic[:93]} (copy)" if same_tenant else source.topic[:100]
    # 一次拉回同前缀已占用名（LIKE 通配符转义），不再逐后缀探测查询。
    # 前缀取所有候选名的公共前缀（最长后缀 " 501"=4 字符 → 100-4=96），
    # 保证任何候选的碰撞都落在集合内
    probe_prefix = base[:96]
    escaped = probe_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    taken_stmt = select(Scenario.topic).where(
        col(Scenario.topic).like(f"{escaped}%", escape="\\")
    )
    if target_tenant_id is not None:
        # C2：占用名探测限定目标校（topic 校内唯一）
        taken_stmt = taken_stmt.where(Scenario.tenant_id == target_tenant_id)
    taken = set(session.exec(taken_stmt).all())
    topic = base if base not in taken else None
    # 仅当 base 已被占用时才逐个后缀探测；修复前该循环无条件执行，会把已
    # 选好的 base 覆盖成 "{base} 2"（同校复制出来的主题永远多一个 " 2"）
    if topic is None:
        for index in range(2, 502):
            suffix = f" {index}"
            candidate = f"{base[: 100 - len(suffix)]}{suffix}"
            if candidate in taken:
                continue
            topic = candidate
            break
    if topic is None:
        raise HTTPException(409, detail="Copy name conflict")
    copied = Scenario(
        topic=topic,
        is_active=source.is_active,
        owner_id=owner_id,
        **({"tenant_id": target_tenant_id} if target_tenant_id is not None else {}),
    )
    session.add(copied)
    session.flush()
    questions = session.exec(
        select(ScenarioQuestion).where(ScenarioQuestion.scenario_id == source.id)
    ).all()
    for question in questions:
        payload = deepcopy(question.model_dump(exclude={"id"}))
        if target_tenant_id is not None:
            payload["tenant_id"] = target_tenant_id
        payload.update(
            owner_id=owner_id, copied_from_id=question.id, scenario_id=copied.id
        )
        session.add(ScenarioQuestion.model_validate(payload))
    session.flush()
    return copied


def _target_scenario_for(
    session: Session,
    source_scenario: Scenario,
    owner_id: uuid.UUID | None,
    target_tenant_id: uuid.UUID,
) -> Scenario:
    """跨校复制单条问答时的容器：目标校已有同主题情景即复用，否则建一条同主题的。

    必须把容器落到目标校：``deepcopy`` 会保留源校 ``scenario_id``，副本挂在
    他校情景上，目标校在 RLS 下查不到，等于复制无效（#597）。
    主题沿用源值不加后缀——情景问答按 topic 与本校单元主题精确匹配，加后缀
    会让问答位匹配不上篇目。
    """
    existing = session.exec(
        select(Scenario).where(
            Scenario.topic == source_scenario.topic,
            Scenario.tenant_id == target_tenant_id,
        )
    ).first()
    if existing is not None:
        return existing
    created = Scenario(
        topic=source_scenario.topic,
        is_active=source_scenario.is_active,
        owner_id=owner_id,
        tenant_id=target_tenant_id,
    )
    session.add(created)
    session.flush()
    return created


def copy_question(
    session: Session,
    source: ScenarioQuestion,
    owner_id: uuid.UUID | None,
    target_tenant_id: uuid.UUID | None = None,
) -> ScenarioQuestion:
    scenario = session.get(Scenario, source.scenario_id)
    if scenario is None:
        raise HTTPException(404, detail="Scenario not found")
    if target_tenant_id is not None and target_tenant_id != scenario.tenant_id:
        scenario = _target_scenario_for(session, scenario, owner_id, target_tenant_id)
    session.refresh(scenario, with_for_update=True)
    last_order = session.exec(
        select(func.max(ScenarioQuestion.order_index)).where(
            ScenarioQuestion.scenario_id == scenario.id
        )
    ).one()
    payload = deepcopy(source.model_dump(exclude={"id"}))
    if target_tenant_id is not None:
        # C2 复制到本校：deepcopy 会带源校 tenant_id，覆盖为目标校
        payload["tenant_id"] = target_tenant_id
    payload.update(
        owner_id=owner_id,
        copied_from_id=source.id,
        scenario_id=scenario.id,
        order_index=(last_order if last_order is not None else -1) + 1,
    )
    copied = ScenarioQuestion.model_validate(payload)
    session.add(copied)
    session.flush()
    return copied


def copy_instruction(
    session: Session,
    source: Instruction,
    owner_id: uuid.UUID | None,
    target_tenant_id: uuid.UUID | None = None,
) -> Instruction:
    payload = deepcopy(source.model_dump(exclude={"id", "created_at", "updated_at"}))
    if target_tenant_id is not None:
        # C2 复制到本校：deepcopy 会带源校 tenant_id，覆盖为目标校
        payload["tenant_id"] = target_tenant_id
    payload.update(
        owner_id=owner_id,
        copied_from_id=source.id,
        title=f"{source.title[:93]} (copy)" if source.title else None,
    )
    copied = Instruction.model_validate(payload)
    session.add(copied)
    session.flush()
    return copied
