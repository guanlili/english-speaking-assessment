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
    # q3：同情景的计划外题（页面换题=追加计划外新题时从这里取）
    q3 = _create_question(
        client,
        superuser_token_headers,
        scenario_id,
        text="Part 2 spare topic.",
        suggested_seconds=120,
        exam_kind="ielts_p2",
        exam_level="KET",
        cue_card_bullets=["要点三"],
        prep_seconds=30,
    )
    # q1、q2 进发布快照
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

    # 发布后修改题库 q2 的话题卡（快照不受影响）
    client.put(
        f"/api/v1/admin/questions/{q2['id']}",
        json={"cue_card_bullets": ["被改掉的要点"]},
        headers=superuser_token_headers,
    )
    # 页面真实参数：前端把计划内全部题目 id 作为 excludeIds 发送
    # （换题语义 = 追加一道计划外新题，结算仍按原题单）；换来的 q3 带考试字段
    nxt = _resp_json(
        client.get(
            f"/api/v1/classes/{code}/next-question",
            params={
                "session_id": plan["session_id"],
                "excludeIds": [first["id"], q2["id"]],
            },
            headers=student["headers"],
        )
    )
    assert nxt["question"] is not None
    q = nxt["question"]
    assert q["id"] == q3["id"]
    assert q["exam_kind"] == "ielts_p2"
    assert q["exam_level"] == "KET"
    assert q["cue_card_bullets"] == ["要点三"]
    assert q["prep_seconds"] == 30
    _cleanup_classroom(db, classroom["id"])
