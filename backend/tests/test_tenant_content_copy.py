"""多租户 C5：跨校复制收口（copy 端点源归属校验 + 副本落位本校）。

漏洞（P1，已实测复现）：copy 端点 session.get(源, id) 按主键直取，
SQLAlchemy 不带租户过滤——乙校教师
POST /admin/content/passage/{甲校篇目id}/copy 返回 200，可读取并复制
他校私有题库；且 sentence/question/instruction 副本 deepcopy 继承源校
tenant_id，数据落进他校。

修复语义（设计稿 §5.2 应用层显式过滤，复用 require_same_tenant）：
- 跨校源 → 404（按不存在处理，不泄露存在性）
- 副本 tenant_id 一律等于当前用户所在校（与 passage/scenario 既有行为一致）

覆盖 9 条复制入口：/admin/{passages,sentences,scenarios,questions,
instructions}/{id}/copy 与共享复制 /admin/content/{kind}/{id}/copy。
另含共享复制前的源预览（GET /admin/content/{kind}/{id}，P1 同类读侧
越权：session.get 直取 + 仅教师门，跨校可读他校私有内容标题/正文/作者）
的同口径收口测试。
"""

import uuid
from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, func, select

from app.core import security
from app.core.tenant_context import tenant_scope
from app.models import (
    DEFAULT_TENANT_ID,
    Instruction,
    Passage,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    Tenant,
    User,
)
from app.services import content_copy

_MODELS = (Passage, RepeatSentence, Scenario, ScenarioQuestion, Instruction)


def _uid() -> str:
    """用例级唯一标识：module 级共享测试库，重跑/顺序不能撞唯一键。"""
    return uuid.uuid4().hex[:8]


def _mk_teacher(db: Session, tenant_id, name: str) -> User:
    user = User(
        email=f"copyc5-{name}-{_uid()}@example.com",
        hashed_password="x",
        role="teacher",
        tenant_id=tenant_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _token(user: User, tenant_id) -> dict[str, str]:
    token = security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=10),
        role=user.role,
        password_hash=user.hashed_password,
        tenant_id=str(tenant_id),
    )
    return {"Authorization": f"Bearer {token}"}


def _mk_pack(db: Session, tenant_id) -> dict[str, tuple[str, type, Any]]:
    """在一所学校建齐五类源内容，返回 9 条复制入口 → (URL, 副本模型, 源对象)。"""
    with tenant_scope(tenant_id):
        passage = Passage(
            title=f"复制源-{_uid()}", text="One. Two.", slug=f"copyc5-{_uid()}"
        )
        db.add(passage)
        db.flush()
        sentence = RepeatSentence(order_index=0, text="Repeat me.")
        db.add(sentence)
        db.flush()
        scenario = Scenario(topic=f"主题-{_uid()}")
        db.add(scenario)
        db.flush()
        question = ScenarioQuestion(
            scenario_id=scenario.id, order_index=0, text="Describe a pet."
        )
        db.add(question)
        db.flush()
        instruction = Instruction(text="Listen carefully.")
        db.add(instruction)
        db.commit()
    return {
        "passage": (f"/api/v1/admin/passages/{passage.id}/copy", Passage, passage),
        "sentence": (
            f"/api/v1/admin/sentences/{sentence.id}/copy",
            RepeatSentence,
            sentence,
        ),
        "scenario": (
            f"/api/v1/admin/scenarios/{scenario.id}/copy",
            Scenario,
            scenario,
        ),
        "question": (
            f"/api/v1/admin/questions/{question.id}/copy",
            ScenarioQuestion,
            question,
        ),
        "instruction": (
            f"/api/v1/admin/instructions/{instruction.id}/copy",
            Instruction,
            instruction,
        ),
        "shared:passage": (
            f"/api/v1/admin/content/passage/{passage.id}/copy",
            Passage,
            passage,
        ),
        "shared:sentence": (
            f"/api/v1/admin/content/repeat/{sentence.id}/copy",
            RepeatSentence,
            sentence,
        ),
        "shared:question": (
            f"/api/v1/admin/content/question/{question.id}/copy",
            ScenarioQuestion,
            question,
        ),
        "shared:instruction": (
            f"/api/v1/admin/content/instruction/{instruction.id}/copy",
            Instruction,
            instruction,
        ),
    }


def _tenant_counts(db: Session, tenant_id) -> dict[str, int]:
    return {
        model.__name__: db.exec(
            select(func.count())
            .select_from(model)
            .where(col(model.tenant_id) == tenant_id)
        ).one()
        for model in _MODELS
    }


@pytest.fixture(scope="module")
def b_tenant(db: Session) -> Tenant:
    row = Tenant(slug=f"copyc5b-{_uid()}", name_zh="复制收口乙校")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture(scope="module")
def teacher_a(db: Session) -> User:
    return _mk_teacher(db, DEFAULT_TENANT_ID, "a")


@pytest.fixture(scope="module")
def teacher_b(db: Session, b_tenant: Tenant) -> User:
    return _mk_teacher(db, b_tenant.id, "b")


def test_cross_school_copy_404(
    client: TestClient, db: Session, b_tenant: Tenant, teacher_b: User
) -> None:
    """跨校复制源一律 404（按不存在处理，不泄露存在性），且两校行数
    前后一致——不产生任何副本（修复前 sentence/question/instruction 的
    副本会落进源校，passage/scenario 副本落进乙校）。"""
    pack = _mk_pack(db, DEFAULT_TENANT_ID)
    headers = _token(teacher_b, b_tenant.id)
    tenants = (DEFAULT_TENANT_ID, b_tenant.id)
    before = {str(tid): _tenant_counts(db, tid) for tid in tenants}
    for key, (url, _model, _source) in pack.items():
        resp = client.post(url, headers=headers)
        assert resp.status_code == 404, (key, resp.status_code, resp.text)
    after = {str(tid): _tenant_counts(db, tid) for tid in tenants}
    assert after == before


def test_same_school_copy_ok_and_lands_in_own_tenant(
    client: TestClient, db: Session, b_tenant: Tenant, teacher_b: User
) -> None:
    """同校复制保持 200（既有能力不回归）；9 条入口的副本 tenant_id 都等于
    当前用户租户——先前三处 deepcopy 继承源校 tenant_id 的路径在此收口。"""
    pack = _mk_pack(db, b_tenant.id)
    headers = _token(teacher_b, b_tenant.id)
    for key, (url, model, _source) in pack.items():
        resp = client.post(url, headers=headers)
        assert resp.status_code == 200, (key, resp.status_code, resp.text)
        copied = db.get(model, uuid.UUID(resp.json()["id"]))
        assert copied is not None, key
        copied_row = cast(Any, copied)
        assert copied_row.tenant_id == b_tenant.id, key
        assert copied_row.tenant_id != DEFAULT_TENANT_ID, key


def test_same_school_copy_default_tenant(
    client: TestClient, db: Session, teacher_a: User
) -> None:
    """甲校（默认租户）教师复制本校内容：仍 200、副本归甲校。"""
    pack = _mk_pack(db, DEFAULT_TENANT_ID)
    headers = _token(teacher_a, DEFAULT_TENANT_ID)
    for key, (url, model, _source) in pack.items():
        resp = client.post(url, headers=headers)
        assert resp.status_code == 200, (key, resp.status_code, resp.text)
        copied = db.get(model, uuid.UUID(resp.json()["id"]))
        copied_row = cast(Any, copied)
        assert copied_row is not None and copied_row.tenant_id == DEFAULT_TENANT_ID, key


def _preview_url(copy_url: str) -> str:
    """共享复制入口 URL → 源预览 URL（/admin/content/{kind}/{id}）。"""
    assert copy_url.endswith("/copy")
    return copy_url[: -len("/copy")]


def test_cross_school_preview_404(
    client: TestClient, db: Session, b_tenant: Tenant, teacher_b: User
) -> None:
    """跨校源预览 404（中性文案，与 copy 同口径）——修复前 session.get
    直取 + 仅教师门，乙校教师可读到甲校私有内容的标题/正文/作者。"""
    pack = _mk_pack(db, DEFAULT_TENANT_ID)
    headers = _token(teacher_b, b_tenant.id)
    for key, (url, _model, _source) in pack.items():
        if not key.startswith("shared:"):
            continue  # 预览端点只有共享复制这一族
        resp = client.get(_preview_url(url), headers=headers)
        assert resp.status_code == 404, (key, resp.status_code, resp.text)
        assert resp.json()["detail"] == "资源不存在或不可访问"


def test_same_school_preview_ok(
    client: TestClient, db: Session, b_tenant: Tenant, teacher_b: User
) -> None:
    """同校源预览保持 200，响应结构不变（修复只加守卫不动形状）。"""
    pack = _mk_pack(db, b_tenant.id)
    headers = _token(teacher_b, b_tenant.id)
    for key, (url, _model, source) in pack.items():
        if not key.startswith("shared:"):
            continue
        db.refresh(source)  # _mk_pack 已 commit，显式重载防属性过期
        resp = client.get(_preview_url(url), headers=headers)
        assert resp.status_code == 200, (key, resp.status_code, resp.text)
        body = resp.json()
        assert body["id"] == str(source.id), key
        assert body["text"] == source.text, key
        assert set(body) == {"id", "title", "text", "author_name"}, key


def test_copy_services_land_in_target_tenant(db: Session, b_tenant: Tenant) -> None:
    """副本落位与路由守卫解耦：服务层显式 target_tenant_id 时，deepcopy
    继承的源校 tenant_id 被覆盖——守卫若被未来改动绕过，副本也不污染源校。"""
    pack = _mk_pack(db, DEFAULT_TENANT_ID)
    owner = _mk_teacher(db, b_tenant.id, "svc")
    tid = b_tenant.id
    # 建包/建用户两次 commit 会把共享 session 里的源对象置为过期；
    # model_dump() 不触发懒加载（属性缺失会静默丢字段），先显式重载。
    # 生产路径无此坑：路由 session.get 刚取的源对象属性是全量加载态。
    for _url, _model, source in pack.values():
        db.refresh(source)
    copied_passage = content_copy.copy_passage(
        db, pack["passage"][2], owner.id, target_tenant_id=tid
    )
    assert copied_passage.tenant_id == tid
    copied_sentence = content_copy.copy_sentence(
        db, pack["sentence"][2], owner.id, target_tenant_id=tid
    )
    assert copied_sentence.tenant_id == tid
    copied_scenario = content_copy.copy_scenario(
        db, pack["scenario"][2], owner.id, target_tenant_id=tid
    )
    assert copied_scenario.tenant_id == tid
    copied_question = content_copy.copy_question(
        db, pack["question"][2], owner.id, target_tenant_id=tid
    )
    assert copied_question.tenant_id == tid
    copied_instruction = content_copy.copy_instruction(
        db, pack["instruction"][2], owner.id, target_tenant_id=tid
    )
    assert copied_instruction.tenant_id == tid
    db.commit()
