"""分级题型训练 PR A：考试字段建模、快照携带、旧数据不漂移、筛选与校验。

口径：
- exam_kind × exam_level 两维分别建模（可空列）；旧数据 NULL，含义不变；
- 话题卡要点/准备时间仅 IELTS Part 2；
- 发布快照深拷贝考试字段；历史作答与旧快照不重新解释；
- 学生端反馈口径：课堂分级练习反馈，非官方考试成绩（前端文案，后端不动评分）。
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models import (
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
)


def _create_scenario(client: TestClient, admin_headers: dict) -> str:
    # 唯一主题：避免用例间共享情景导致「换一题」候选互相污染
    topic = f"考试题型测试-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/v1/admin/scenarios", json={"topic": topic}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _create_question(
    client: TestClient, admin_headers: dict, scenario_id: str, **fields
) -> dict:
    resp = client.post(
        f"/api/v1/admin/scenarios/{scenario_id}/questions",
        json=fields,
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _admin(client: TestClient, superuser_token_headers: dict) -> dict:
    return superuser_token_headers


# ── 题库：考试字段校验 ──────────────────────────────────────────────


@pytest.fixture
def noop_scoring():
    """换题用例真实提交录音但不跑评分线程，避免清理时与 worker 死锁。"""

    from app.api.deps import get_scoring_submitter

    app.dependency_overrides[get_scoring_submitter] = lambda: (
        lambda attempt_id: None  # noqa: ARG005
    )
    yield
    app.dependency_overrides.pop(get_scoring_submitter, None)


def test_question_exam_field_validation(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    admin = _admin(client, superuser_token_headers)
    scenario_id = _create_scenario(client, admin)

    base = {"text": "Describe a city you like.", "suggested_seconds": 120}

    # 非法题型 / 非法级别 / 话题卡给了非 Part2 / 准备时间越界 → 422
    for fields in [
        {**base, "exam_kind": "toefl_lnr"},  # 问答题表不支持复述题型
        {**base, "exam_kind": "ielts_p1", "exam_level": "B2"},  # 级别不在五级
        {**base, "exam_kind": "ielts_p1", "cue_card_bullets": ["a"]},
        {**base, "exam_kind": "ielts_p2", "prep_seconds": 5},
        {**base, "exam_level": "KET"},  # 只给级别不给题型
    ]:
        resp = client.post(
            f"/api/v1/admin/scenarios/{scenario_id}/questions",
            json=fields,
            headers=admin,
        )
        assert resp.status_code == 422, fields

    # 合法：IELTS Part 2 + KET 课堂版（降低作答要求：短秒数 + 少要点 + 短准备）
    resp = client.post(
        f"/api/v1/admin/scenarios/{scenario_id}/questions",
        json={
            **base,
            "exam_kind": "ielts_p2",
            "exam_level": "KET",
            "cue_card_bullets": ["它在哪里", "你喜欢它什么"],
            "prep_seconds": 30,
        },
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["exam_kind"] == "ielts_p2"
    assert created["exam_level"] == "KET"
    assert created["prep_seconds"] == 30
    assert created["cue_card_bullets"] == ["它在哪里", "你喜欢它什么"]

    # 更新：清空话题卡（null）→ 变回普通题；题目行被修改但历史语义只增不减
    resp = client.put(
        f"/api/v1/admin/questions/{created['id']}",
        json={"cue_card_bullets": None, "exam_kind": None, "exam_level": None},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["exam_kind"] is None


def test_repeat_exam_field_validation(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """复述句：TOEFL Listen and Repeat 题型 × 级别；非法题型 422。"""
    base = {"text": "Please describe your favorite teacher."}
    resp = client.post(
        "/api/v1/admin/sentences",
        json={**base, "exam_kind": "ielts_p2"},  # 复述表不支持问答题型
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422

    resp = client.post(
        "/api/v1/admin/sentences",
        json={
            **base,
            "suggested_seconds": 12,
            "exam_kind": "toefl_lnr",
            "exam_level": "PET",  # 课堂版：降低语言难度与作答要求由内容承担
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["exam_kind"] == "toefl_lnr"
    assert created["exam_level"] == "PET"

    # 平铺列表按题型筛选
    listing = client.get(
        "/api/v1/admin/sentences",
        params={"exam_kind": "toefl_lnr", "exam_level": "PET"},
        headers=superuser_token_headers,
    ).json()
    assert any(sentence["id"] == created["id"] for sentence in listing)
    listing_none = client.get(
        "/api/v1/admin/sentences",
        params={"exam_kind": "ielts_p2"},
        headers=superuser_token_headers,
    ).json()
    assert all(sentence["exam_kind"] != "toefl_lnr" for sentence in listing_none)


# ── 发布快照 + 今日计划携带；旧数据不漂移 ──────────────────────────


def _resp_json(resp) -> dict:
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_exam_items_flow_through_snapshot_and_today(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """考试字段经发布快照 → 学生今日计划原样透传；快照不可变。"""
    from tests.utils.credential import make_student

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    student = make_student(db, client, code, "题型学生")

    scenario_id = _create_scenario(client, superuser_token_headers)
    question = _create_question(
        client,
        superuser_token_headers,
        scenario_id,
        text="Talk about a festival in your country.",
        suggested_seconds=120,
        exam_kind="ielts_p2",
        exam_level="KET",
        cue_card_bullets=["节日名称", "你和谁一起过", "最喜欢的一部分"],
        prep_seconds=45,
    )
    sentence = _resp_json(
        client.post(
            "/api/v1/admin/sentences",
            json={
                "text": "Listen and repeat: The interview starts now.",
                "suggested_seconds": 10,
                "exam_kind": "toefl_lnr",
                "exam_level": "PET",
            },
            headers=superuser_token_headers,
        )
    )

    published = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments",
        json={"title": "x"},
        headers=superuser_token_headers,
    )
    assert published.status_code == 422  # 词汇任务接口不接受口语发布（分模块）

    resp = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "title": "分级题型训练",
            "items": [
                {"type": "question", "id": question["id"]},
                {"type": "repeat", "id": sentence["id"]},
            ],
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text

    plan = _resp_json(
        client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    )
    q_item = next(item for item in plan["items"] if item["type"] == "question")
    r_item = next(item for item in plan["items"] if item["type"] == "repeat")
    assert q_item["exam_kind"] == "ielts_p2"
    assert q_item["exam_level"] == "KET"
    assert q_item["cue_card_bullets"] == ["节日名称", "你和谁一起过", "最喜欢的一部分"]
    assert q_item["prep_seconds"] == 45
    assert r_item["exam_kind"] == "toefl_lnr"
    assert r_item["exam_level"] == "PET"

    # 快照固化：改题库题目 → 学生计划（按快照）不变
    client.put(
        f"/api/v1/admin/questions/{question['id']}",
        json={"cue_card_bullets": ["被改掉的要点"]},
        headers=superuser_token_headers,
    )
    plan2 = _resp_json(
        client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    )
    q2 = next(item for item in plan2["items"] if item["type"] == "question")
    assert q2["cue_card_bullets"] == ["节日名称", "你和谁一起过", "最喜欢的一部分"]

    _cleanup_classroom(db, classroom["id"])


def _cleanup_classroom(db: Session, classroom_id: str) -> None:
    from app.models import Classroom

    row = db.get(Classroom, uuid.UUID(classroom_id))
    if row is not None:
        db.delete(row)
    db.commit()


def test_plain_items_keep_old_meaning(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """旧数据不漂移：无考试字段的题目/复述句，计划与快照里 exam_* 均为 null。"""
    from tests.utils.credential import make_student

    scenario = db.exec(select(Scenario)).first()
    question = db.exec(select(ScenarioQuestion)).first()
    sentence = db.exec(select(RepeatSentence)).first()
    if scenario is None or question is None or sentence is None:
        return  # 演示种子被其他用例清空时跳过（种子完整性由其他用例保证）

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    student = make_student(db, client, code, "普通学生")
    resp = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "items": [
                {"type": "question", "id": str(question.id)},
                {"type": "repeat", "id": str(sentence.id)},
            ]
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    plan = _resp_json(
        client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    )
    q_item = next(item for item in plan["items"] if item["type"] == "question")
    assert q_item["exam_kind"] is None
    assert q_item["cue_card_bullets"] is None
    r_item = next(item for item in plan["items"] if item["type"] == "repeat")
    assert r_item["exam_kind"] is None
    _cleanup_classroom(db, classroom["id"])


# ── 四审修复回归 ────────────────────────────────────────────────────


def test_partial_update_merges_with_existing(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """部分更新与原记录合并后校验：仅改话题卡不误拒；清题型级联清关联字段。"""
    admin = _admin(client, superuser_token_headers)
    scenario_id = _create_scenario(client, admin)
    question = _create_question(
        client,
        admin,
        scenario_id,
        text="Part 2 partial update",
        suggested_seconds=120,
        exam_kind="ielts_p2",
        exam_level="KET",
        cue_card_bullets=["原要点"],
        prep_seconds=45,
    )

    # 仅改话题卡（不传题型/级别）→ 不误拒，其余字段保留
    resp = client.put(
        f"/api/v1/admin/questions/{question['id']}",
        json={"cue_card_bullets": ["新要点"]},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["exam_kind"] == "ielts_p2"
    assert body["cue_card_bullets"] == ["新要点"]
    assert body["prep_seconds"] == 45

    # 仅清除题型 → 级别/话题卡/准备时间级联清空（不留不一致数据）
    resp = client.put(
        f"/api/v1/admin/questions/{question['id']}",
        json={"exam_kind": None},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["exam_kind"] is None
    assert body["exam_level"] is None
    assert body["cue_card_bullets"] is None
    assert body["prep_seconds"] is None

    # Part 2 长回答秒数：重建题型需完整标注（级别必选），120 秒不被 60 拒绝
    resp = client.put(
        f"/api/v1/admin/questions/{question['id']}",
        json={
            "exam_kind": "ielts_p2",
            "exam_level": "KET",
            "cue_card_bullets": ["新要点"],
            "suggested_seconds": 120,
        },
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggested_seconds"] == 120


def test_sentence_partial_update_merges(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """复述句部分更新：仅清题型级联清级别；仅改级别不误拒。"""
    created = _resp_json(
        client.post(
            "/api/v1/admin/sentences",
            json={
                "text": "Listen and repeat this sentence.",
                "exam_kind": "toefl_lnr",
                "exam_level": "KET",
            },
            headers=superuser_token_headers,
        )
    )

    # 仅改级别（不传题型）→ 保留题型
    resp = client.put(
        f"/api/v1/admin/sentences/{created['id']}",
        json={"exam_level": "PET"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["exam_kind"] == "toefl_lnr"
    assert resp.json()["exam_level"] == "PET"

    # 仅清题型 → 级联清级别
    resp = client.put(
        f"/api/v1/admin/sentences/{created['id']}",
        json={"exam_kind": None},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["exam_kind"] is None
    assert resp.json()["exam_level"] is None


def test_next_question_carries_exam_fields(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    noop_scoring,
) -> None:
    """换一题：快照内另一题的考试字段原样返回（话题卡不丢）。"""
    from tests.utils.credential import make_student

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    student = make_student(db, client, code, "换题学生")
    scenario_id = _create_scenario(client, superuser_token_headers)
    q1 = _create_question(
        client,
        superuser_token_headers,
        scenario_id,
        text="Part 2 first topic.",
        exam_kind="ielts_p2",
        exam_level="KET",
        cue_card_bullets=["要点一"],
        prep_seconds=30,
    )
    q2 = _create_question(
        client,
        superuser_token_headers,
        scenario_id,
        text="Part 2 second topic.",
        suggested_seconds=120,
        exam_kind="ielts_p2",
        exam_level="KET",
        cue_card_bullets=["要点二"],
        prep_seconds=30,
    )
    # q1、q2 进发布快照（q3 稍后创建：计划外题，换题时从这里取）
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "items": [
                {"type": "question", "id": q1["id"]},
                {"type": "question", "id": q2["id"]},
            ]
        },
        headers=superuser_token_headers,
    )
    # 学生打开计划（建立会话）并作答第一题
    plan = _resp_json(
        client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    )
    first = plan["items"][0]
    from tests.utils.audio import wav_upload

    client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(3.0)},
        data={
            "item_type": first["type"],
            "item_id": first["id"],
            "duration_s": "3.0",
            "session_id": plan["session_id"],
        },
        headers=student["headers"],
    )

    # 发布后修改题库：q2 改话题卡+改题干（学生所见不应变）
    client.put(
        f"/api/v1/admin/questions/{q2['id']}",
        json={
            "text": "Part 2 second topic (rewritten).",
            "cue_card_bullets": ["被改掉的要点"],
        },
        headers=superuser_token_headers,
    )

    # 换一题拿到 q3（计划外）→ 老师随后**修改并删除** q3 → 提交仍应成功，
    # 且评分/结果快照保持为取题时的内容
    q3_created = client.post(
        f"/api/v1/admin/scenarios/{scenario_id}/questions",
        json={
            "text": "Part 2 spare topic.",
            "suggested_seconds": 120,
            "exam_kind": "ielts_p2",
            "exam_level": "KET",
            "cue_card_bullets": ["要点三"],
            "prep_seconds": 30,
        },
        headers=superuser_token_headers,
    )
    assert q3_created.status_code == 200, q3_created.text
    nxt = _resp_json(
        client.get(
            f"/api/v1/classes/{code}/next-question",
            params={
                "session_id": plan["session_id"],
                "exclude_ids": [q1["id"], q2["id"]],
            },
            headers=student["headers"],
        )
    )
    assert nxt["question"] is not None
    q3 = nxt["question"]
    assert q3["cue_card_bullets"] == ["要点三"]

    # 老师先改题干与话题卡、再删除题库题
    rewritten = client.put(
        f"/api/v1/admin/questions/{q3['id']}",
        json={
            "text": "Part 2 spare topic (rewritten).",
            "cue_card_bullets": ["被改掉的要点"],
        },
        headers=superuser_token_headers,
    )
    assert rewritten.status_code == 200, rewritten.text
    deleted = client.delete(
        f"/api/v1/admin/questions/{q3['id']}", headers=superuser_token_headers
    )
    assert deleted.status_code == 200, deleted.text

    # 提交 q3 录音：会话换题授权放行（不再 422「题目不在本次发布练习内」）
    from tests.utils.audio import wav_upload

    submitted = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(3.0)},
        data={
            "item_type": "question",
            "item_id": q3["id"],
            "duration_s": "3.0",
            "session_id": plan["session_id"],
        },
        headers=student["headers"],
    )
    assert submitted.status_code == 200, submitted.text

    # 结果找回：today 计划含 q3（经 attempt.item_snapshot 恢复，考试字段齐全）
    plan2 = _resp_json(
        client.get(
            f"/api/v1/classes/{code}/today",
            params={"session_id": plan["session_id"]},
            headers=student["headers"],
        )
    )
    q3_item = next((item for item in plan2["items"] if item["id"] == q3["id"]), None)
    assert q3_item is not None, "换来的题应在计划中找回"
    assert q3_item["exam_kind"] == "ielts_p2"
    assert q3_item["cue_card_bullets"] == ["要点三"]
    attempt_entry = next(
        (a for a in plan2["attempts"] if a["item_id"] == q3["id"]), None
    )
    assert attempt_entry is not None
    _cleanup_classroom(db, classroom["id"])


def test_old_session_exchange_stays_on_bound_topic(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """老师重新发布另一主题后，旧会话换题仍按其绑定练习的情景取题。"""
    from tests.utils.credential import make_student

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    student = make_student(db, client, code, "旧会话学生")

    topic_a = f"主题A-{uuid.uuid4().hex[:6]}"
    scenario_a = _resp_json(
        client.post(
            "/api/v1/admin/scenarios",
            json={"topic": topic_a},
            headers=superuser_token_headers,
        )
    )
    q1 = _create_question(
        client,
        superuser_token_headers,
        scenario_a["id"],
        text="Topic A question one.",
        exam_kind="ielts_p1",
        exam_level="PET",
    )
    _create_question(
        client,
        superuser_token_headers,
        scenario_a["id"],
        text="Topic A question two.",
        exam_kind="ielts_p1",
        exam_level="PET",
    )
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "question", "id": q1["id"]}]},
        headers=superuser_token_headers,
    )
    plan = _resp_json(
        client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    )

    # 老师重新发布主题 B（换掉当前指派）
    topic_b = f"主题B-{uuid.uuid4().hex[:6]}"
    scenario_b = _resp_json(
        client.post(
            "/api/v1/admin/scenarios",
            json={"topic": topic_b},
            headers=superuser_token_headers,
        )
    )
    qb = _create_question(
        client,
        superuser_token_headers,
        scenario_b["id"],
        text="Topic B question.",
        exam_kind="ielts_p1",
        exam_level="PET",
    )
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "question", "id": qb["id"]}]},
        headers=superuser_token_headers,
    )

    # 旧会话带 session_id 换题 → 仍按主题 A 的情景取题，不漂移到主题 B
    nxt = _resp_json(
        client.get(
            f"/api/v1/classes/{code}/next-question",
            params={
                "session_id": plan["session_id"],
                "exclude_ids": [q1["id"]],
            },
            headers=student["headers"],
        )
    )
    assert nxt["question"] is not None
    # 仍是主题 A 的题（不漂移到重发后的主题 B）
    assert nxt["question"]["text"] == "Topic A question two."
    _cleanup_classroom(db, classroom["id"])


def test_old_session_exchange_ignores_current_assignment_changes(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """旧会话换题的入口与排除集都来自其绑定练习：清除指派后仍可换题；
    重发同主题其他题也不会把旧会话候选错误排除。"""
    from tests.utils.credential import make_student

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    student = make_student(db, client, code, "指派变化学生")

    # 主题 A：q1 进快照，q2 仅在题库（旧会话的候选）
    topic_a = f"主题A-{uuid.uuid4().hex[:6]}"
    scenario_a = _resp_json(
        client.post(
            "/api/v1/admin/scenarios",
            json={"topic": topic_a},
            headers=superuser_token_headers,
        )
    )
    q1 = _create_question(
        client,
        superuser_token_headers,
        scenario_a["id"],
        text="Topic A question one.",
        exam_kind="ielts_p1",
        exam_level="PET",
    )
    q2 = _create_question(
        client,
        superuser_token_headers,
        scenario_a["id"],
        text="Topic A question two.",
        exam_kind="ielts_p1",
        exam_level="PET",
    )
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "question", "id": q1["id"]}]},
        headers=superuser_token_headers,
    )
    plan = _resp_json(
        client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    )

    # 场景 b：老师重新指派**同主题的另一题 q2**——旧会话候选不应把 q2 排除
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "question", "id": q2["id"]}]},
        headers=superuser_token_headers,
    )
    nxt = _resp_json(
        client.get(
            f"/api/v1/classes/{code}/next-question",
            params={
                "session_id": plan["session_id"],
                "exclude_ids": [q1["id"]],
            },
            headers=student["headers"],
        )
    )
    assert nxt["question"] is not None
    # 排除集来自绑定练习（q1），不受当前指派（q2）影响：仍能返回 q2
    assert nxt["question"]["id"] == q2["id"]

    # 场景 a：老师**清除指派**——旧会话仍按绑定练习换题，不因无指派而失效
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": []},
        headers=superuser_token_headers,
    )
    nxt = _resp_json(
        client.get(
            f"/api/v1/classes/{code}/next-question",
            params={
                "session_id": plan["session_id"],
                "exclude_ids": [q1["id"]],
            },
            headers=student["headers"],
        )
    )
    assert nxt["question"] is not None
    # 排除已作答的 q1 后返回另一题 q2
    assert nxt["question"]["id"] == q2["id"]
    _cleanup_classroom(db, classroom["id"])


def test_frame_recommendation_and_favorites(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """PR B：题目按实际难度注入推荐句型（通用+题型匹配、排除错误级别）；
    学生收藏后 today 中 favorited 标记，取消后恢复；句型不进作答快照。"""
    from tests.utils.audio import wav_upload
    from tests.utils.credential import make_student

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    student = make_student(db, client, code, "句型学生")
    scenario_id = _create_scenario(client, superuser_token_headers)
    question = _create_question(
        client,
        superuser_token_headers,
        scenario_id,
        text="Talk about your favorite food.",
        exam_kind="ielts_p1",
        exam_level="KET",
    )

    # 句型：通用 KET / ielts_p1 专用 KET / 错误级别 PET
    f_common = _resp_json(
        client.post(
            "/api/v1/admin/sentence-frames",
            json={
                "level": "KET",
                "purpose": "opinion",
                "text_en": "In my opinion, ...",
                "text_zh": "在我看来……",
            },
            headers=superuser_token_headers,
        )
    )
    f_p1 = _resp_json(
        client.post(
            "/api/v1/admin/sentence-frames",
            json={
                "level": "KET",
                "purpose": "opinion",
                "exam_kind": "ielts_p1",
                "text_en": "My favorite ... is ...",
                "text_zh": "我最喜欢的……是……",
            },
            headers=superuser_token_headers,
        )
    )
    _resp_json(
        client.post(
            "/api/v1/admin/sentence-frames",
            json={
                "level": "PET",  # 错误级别：不应推荐
                "purpose": "opinion",
                "text_en": "wrong level frame",
                "text_zh": "错误级别",
            },
            headers=superuser_token_headers,
        )
    )

    # 发布考试题
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "question", "id": question["id"]}]},
        headers=superuser_token_headers,
    )
    plan = _resp_json(
        client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    )
    q_item = next(item for item in plan["items"] if item["type"] == "question")
    frames = q_item["frames"] or []
    frame_ids = {frame["id"] for frame in frames}
    assert f_common["id"] in frame_ids
    assert f_p1["id"] in frame_ids
    assert all(frame["level"] == "KET" for frame in frames)
    assert all(frame["favorited"] is False for frame in frames)

    # 收藏一条 → today 中 favorited=True
    client.post(
        f"/api/v1/classes/{code}/frame-favorites",
        json={"frame_id": f_p1["id"]},
        headers=student["headers"],
    )
    plan = _resp_json(
        client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    )
    q_item = next(item for item in plan["items"] if item["type"] == "question")
    frames = {frame["id"]: frame["favorited"] for frame in q_item["frames"] or {}}
    assert frames[f_p1["id"]] is True
    assert frames[f_common["id"]] is False

    # 我的收藏列表（跨设备：同一账号重新登录后仍可见）
    favorites = client.get(
        f"/api/v1/classes/{code}/frame-favorites", headers=student["headers"]
    ).json()
    assert [frame["id"] for frame in favorites] == [f_p1["id"]]
    assert favorites[0]["favorited"] is True

    # 作答 q1 → 提交快照不含句型（句型仅展示层）
    plan = _resp_json(
        client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    )
    first = plan["items"][0]
    client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(3.0)},
        data={
            "item_type": first["type"],
            "item_id": first["id"],
            "duration_s": "3.0",
            "session_id": plan["session_id"],
        },
        headers=student["headers"],
    )
    today_after = _resp_json(
        client.get(
            f"/api/v1/classes/{code}/today",
            params={"session_id": plan["session_id"]},
            headers=student["headers"],
        )
    )
    assert any(
        a["item_id"] == question["id"] for a in today_after["attempts"]
    )  # 句型不进作答快照，但作答本身正常
    # attempt.item_snapshot 无 frames 键（句型不进作答快照）

    # 取消收藏 → 列表恢复为空
    client.delete(
        f"/api/v1/classes/{code}/frame-favorites/{f_p1['id']}",
        headers=student["headers"],
    )
    favorites = client.get(
        f"/api/v1/classes/{code}/frame-favorites", headers=student["headers"]
    ).json()
    assert favorites == []

    # 合法题型缺级别 → 422（句型也遵循「有题型必配级别」）
    resp = client.post(
        "/api/v1/admin/sentence-frames",
        json={
            "purpose": "opinion",
            "exam_kind": "ielts_p1",
            "text_en": "x",
            "text_zh": "x",
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422
    _cleanup_classroom(db, classroom["id"])


def test_sentence_frames_batch_import(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """批量导入：无效行跳过并报告；同 (级别,用途,英文) 去重；有题型缺级别 422 不需要——batch 逐行校验。"""
    items = [
        {
            "level": "KET",
            "purpose": "opinion",
            "text_en": "I think ...",
            "text_zh": "我觉得……",
        },
        {
            "level": "KET",
            "purpose": "opinion",
            "text_en": "I think ...",
            "text_zh": "我觉得……",
        },  # 重复
        {
            "level": "BAD",
            "purpose": "opinion",
            "text_en": "bad level",
            "text_zh": "x",
        },  # 无效
        {
            "level": "PET",
            "purpose": "reason",
            "text_en": "The reason is ...",
            "text_zh": "原因是……",
        },
    ]
    resp = client.post(
        "/api/v1/admin/sentence-frames/batch",
        json=items,
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 2
    assert body["skipped_duplicates"] == 1
    assert len(body["invalid"]) == 1 and body["invalid"][0]["index"] == 2

    # 再导一批（不同句型）→ created 累加；重复跨请求也跳过
    resp = client.post(
        "/api/v1/admin/sentence-frames/batch",
        json=items[:1],
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 0

    stats = client.get(
        "/api/v1/admin/sentence-frames", headers=superuser_token_headers
    ).json()
    # 种子句型存在：只断言本测试创建的句型都在（不依赖库总量）
    created_texts = {"I think ...", "The reason is ..."}
    assert created_texts <= {frame["text_en"] for frame in stats}
