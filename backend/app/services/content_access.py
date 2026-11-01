"""题库编辑权限：创建者与管理员可改/删，存量无主内容（owner_id 为空）所有教师可改。

判定落在「根对象」上：挂篇目的复述句与旧版拆分子篇随原文章，情景问答按题。
主题（Scenario）是共用分组：任何教师都能往里加题；改名/启停归主题创建者，
删除会级联删题，所以组内还有别人的题时只有管理员能删。存量无主主题沿用
「组内每道题都可改才能管理」。设计见 docs/question-bank-ownership-design.md。
"""

import uuid

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    Instruction,
    Passage,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    User,
)

FORBIDDEN_DETAIL = "没有权限：只能修改自己创建的题目"
SCENARIO_HAS_OTHERS_DETAIL = "没有权限：主题下有其他老师的题目，不能删除"
EXAM_AUDIO_DETAIL = "没有权限：不能替换其他老师题目的考试音频"


def owner_for(user: User) -> uuid.UUID | None:
    """新建题目的归属：管理员录入的是全校公共内容（无主），教师录入的归本人。"""
    return None if user.role == "admin" else user.id


def can_edit(user: User, owner_id: uuid.UUID | None) -> bool:
    return user.role == "admin" or owner_id is None or owner_id == user.id


def _require(user: User, owner_id: uuid.UUID | None) -> None:
    if not can_edit(user, owner_id):
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)


def require_same_tenant(user: User, obj: object) -> None:
    """多租户 C5a：跨校对象按不存在处理（404）。

    owner 编辑权（can_edit）不含租户维度——公共内容（owner_id=None）
    在旧单校语义下全校可编辑，多租户后他校教师不得触碰。生产 RLS 会
    在数据库层拦 WITH CHECK；本守卫是应用层纵深防御，也让无 RLS 的
    测试环境锁住同一语义。对象无 tenant_id 属性时跳过（未挂租户的
    平台资源）。
    """
    obj_tenant = getattr(obj, "tenant_id", None)
    if obj_tenant is not None and obj_tenant != user.tenant_id:
        # 中性文案：跨校对象按不存在处理（不泄露具体资源类型与存在性）
        raise HTTPException(status_code=404, detail="资源不存在或不可访问")


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


def item_owner(
    session: Session,
    item: Passage | RepeatSentence | ScenarioQuestion | Instruction,
) -> uuid.UUID | None:
    if isinstance(item, Passage):
        return passage_owner(session, item)
    if isinstance(item, RepeatSentence):
        return sentence_owner(session, item)
    return item.owner_id


def sentence_owner_for(
    session: Session, user: User, passage: Passage | None
) -> uuid.UUID | None:
    """新复述句的归属：挂篇目时与篇目一致（列表据此判断可编辑），独立句归创建人。"""
    if passage is None:
        return owner_for(user)
    return passage_owner(session, passage)


def require_passage(session: Session, user: User, passage: Passage) -> None:
    require_same_tenant(user, passage)
    _require(user, passage_owner(session, passage))


def require_sentence(session: Session, user: User, sentence: RepeatSentence) -> None:
    require_same_tenant(user, sentence)
    _require(user, sentence_owner(session, sentence))


def require_question(user: User, question: ScenarioQuestion) -> None:
    require_same_tenant(user, question)
    _require(user, question.owner_id)


def require_instruction(user: User, instruction: Instruction) -> None:
    require_same_tenant(user, instruction)
    _require(user, instruction.owner_id)


def _has_others_questions(session: Session, user: User, scenario_id: uuid.UUID) -> bool:
    return (
        session.exec(
            select(ScenarioQuestion.id)
            .where(
                ScenarioQuestion.scenario_id == scenario_id,
                col(ScenarioQuestion.owner_id).is_not(None),
                ScenarioQuestion.owner_id != user.id,
            )
            .limit(1)
        ).first()
        is not None
    )


def can_manage_scenario(session: Session, user: User, scenario: Scenario) -> bool:
    if user.role == "admin" or scenario.owner_id == user.id:
        return True
    if scenario.owner_id is not None:
        return False
    return not _has_others_questions(session, user, scenario.id)


def require_scenario(session: Session, user: User, scenario: Scenario) -> None:
    """改名/启停。"""
    require_same_tenant(user, scenario)
    if not can_manage_scenario(session, user, scenario):
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)


def require_scenario_delete(session: Session, user: User, scenario: Scenario) -> None:
    require_scenario(session, user, scenario)
    if user.role != "admin" and _has_others_questions(session, user, scenario.id):
        raise HTTPException(status_code=403, detail=SCENARIO_HAS_OTHERS_DETAIL)
