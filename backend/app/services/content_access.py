"""题库编辑权限：创建者与管理员可改/删，存量无主内容（owner_id 为空）所有教师可改。

判定落在「根对象」上：挂篇目的复述句与旧版拆分子篇随原文章，情景问答按题，
主题（Scenario）是全校共用分组——只有组内每道题都可改时才能改名/启停/删除。
设计见 docs/question-bank-ownership-design.md。
"""

import uuid

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    Instruction,
    Passage,
    RepeatSentence,
    ScenarioQuestion,
    User,
)

FORBIDDEN_DETAIL = "没有权限：只能修改自己创建的题目"


def owner_for(user: User) -> uuid.UUID | None:
    """新建题目的归属：管理员录入的是全校公共内容（无主），教师录入的归本人。"""
    return None if user.is_superuser else user.id


def can_edit(user: User, owner_id: uuid.UUID | None) -> bool:
    return user.is_superuser or owner_id is None or owner_id == user.id


def _require(user: User, owner_id: uuid.UUID | None) -> None:
    if not can_edit(user, owner_id):
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)


def passage_owner(session: Session, passage: Passage) -> uuid.UUID | None:
    if passage.parent_passage_id is None:
        return passage.owner_id
    parent = session.get(Passage, passage.parent_passage_id)
    return parent.owner_id if parent is not None else passage.owner_id


def sentence_owner(session: Session, sentence: RepeatSentence) -> uuid.UUID | None:
    if sentence.passage_id is None:
        return sentence.owner_id
    passage = session.get(Passage, sentence.passage_id)
    return passage_owner(session, passage) if passage is not None else None


def sentence_owner_for(
    session: Session, user: User, passage: Passage | None
) -> uuid.UUID | None:
    """新复述句的归属：挂篇目时与篇目一致（列表据此判断可编辑），独立句归创建人。"""
    if passage is None:
        return owner_for(user)
    return passage_owner(session, passage)


def require_passage(session: Session, user: User, passage: Passage) -> None:
    _require(user, passage_owner(session, passage))


def require_sentence(session: Session, user: User, sentence: RepeatSentence) -> None:
    _require(user, sentence_owner(session, sentence))


def require_question(user: User, question: ScenarioQuestion) -> None:
    _require(user, question.owner_id)


def require_instruction(user: User, instruction: Instruction) -> None:
    _require(user, instruction.owner_id)


def require_scenario(session: Session, user: User, scenario_id: uuid.UUID) -> None:
    if user.is_superuser:
        return
    blocked = session.exec(
        select(ScenarioQuestion.id)
        .where(
            ScenarioQuestion.scenario_id == scenario_id,
            col(ScenarioQuestion.owner_id).is_not(None),
            ScenarioQuestion.owner_id != user.id,
        )
        .limit(1)
    ).first()
    if blocked is not None:
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)


def require_passage_ids(
    session: Session, user: User, passage_ids: set[uuid.UUID]
) -> None:
    """批量校验目标篇目（导入挂靠已有篇目时用）。"""
    if user.is_superuser or not passage_ids:
        return
    for passage in session.exec(
        select(Passage).where(col(Passage.id).in_(passage_ids))
    ).all():
        require_passage(session, user, passage)
