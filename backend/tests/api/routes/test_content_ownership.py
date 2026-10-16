"""题库归属：教师只能改/删自己创建的题目；管理员录入与存量内容所有教师可改。"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from app.models import (
    Instruction,
    Passage,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    User,
)
from app.services.content_access import FORBIDDEN_DETAIL
from tests.api.routes.test_students import _login_teacher

API = "/api/v1/admin"


@pytest.fixture
def teachers(
    client: TestClient, db: Session
) -> Iterator[tuple[dict[str, str], dict[str, str], User]]:
    owner, owner_headers = _login_teacher(db, client)
    other, other_headers = _login_teacher(db, client)
    yield owner_headers, other_headers, owner
    for model in (RepeatSentence, ScenarioQuestion, Instruction):
        db.exec(  # type: ignore[call-overload]
            delete(model).where(col(model.owner_id).in_([owner.id, other.id]))
        )
    db.exec(  # type: ignore[call-overload]
        delete(Passage).where(col(Passage.owner_id).in_([owner.id, other.id]))
    )
    db.commit()
    for user in (owner, other):
        row = db.get(User, user.id)
        if row is not None:
            db.delete(row)
    db.commit()


def _forbidden(response) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == FORBIDDEN_DETAIL


def _passage(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        f"{API}/passages",
        json={"title": f"Own {uuid.uuid4().hex[:6]}", "text": "One. Two. Three."},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_teacher_cannot_edit_or_delete_others_passage(
    client: TestClient, teachers, superuser_token_headers: dict[str, str]
) -> None:
    owner_headers, other_headers, owner = teachers
    passage = _passage(client, owner_headers)
    assert passage["owner_id"] == str(owner.id)
    pid = passage["id"]

    _forbidden(
        client.put(f"{API}/passages/{pid}", json={"title": "x"}, headers=other_headers)
    )
    _forbidden(client.delete(f"{API}/passages/{pid}", headers=other_headers))
    _forbidden(client.post(f"{API}/passages/{pid}/split", headers=other_headers))
    _forbidden(
        client.post(
            f"{API}/passages/{pid}/sentences",
            json={"text": "Hijack."},
            headers=other_headers,
        )
    )
    _forbidden(
        client.post(
            f"{API}/sentences",
            json={"text": "Attach.", "passage_id": pid},
            headers=other_headers,
        )
    )
    # 考试计时在组卷排序行就地设置：选用他人题目组考试也要能调
    timing = client.put(
        f"{API}/exam-items/passage/{pid}/settings", json={}, headers=other_headers
    )
    assert timing.status_code == 200, timing.text

    mine = client.put(
        f"{API}/passages/{pid}", json={"title": "Renamed"}, headers=owner_headers
    )
    assert mine.status_code == 200, mine.text
    admin = client.put(
        f"{API}/passages/{pid}",
        json={"title": "By admin"},
        headers=superuser_token_headers,
    )
    assert admin.status_code == 200, admin.text


def test_sentences_follow_passage_owner_and_standalone_owner(
    client: TestClient, teachers
) -> None:
    owner_headers, other_headers, owner = teachers
    passage = _passage(client, owner_headers)
    attached = client.post(
        f"{API}/passages/{passage['id']}/sentences",
        json={"text": "Attached."},
        headers=owner_headers,
    ).json()
    assert attached["owner_id"] == str(owner.id)
    standalone = client.post(
        f"{API}/sentences", json={"text": "Alone."}, headers=owner_headers
    ).json()
    mine = client.post(
        f"{API}/sentences", json={"text": "Mine."}, headers=other_headers
    ).json()

    for sid in (attached["id"], standalone["id"]):
        _forbidden(
            client.put(
                f"{API}/sentences/{sid}", json={"text": "x"}, headers=other_headers
            )
        )
        _forbidden(client.delete(f"{API}/sentences/{sid}", headers=other_headers))
    # 不能把自己的句子挂到别人的篇目下
    _forbidden(
        client.put(
            f"{API}/sentences/{mine['id']}",
            json={"passage_id": passage["id"]},
            headers=other_headers,
        )
    )
    assert (
        client.delete(
            f"{API}/sentences/{mine['id']}", headers=other_headers
        ).status_code
        == 200
    )


def test_admin_and_legacy_content_stay_editable_by_teachers(
    client: TestClient, teachers, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _owner_headers, other_headers, _owner = teachers
    shared = _passage(client, superuser_token_headers)
    assert shared["owner_id"] is None
    try:
        response = client.put(
            f"{API}/passages/{shared['id']}",
            json={"title": "Edited by teacher"},
            headers=other_headers,
        )
        assert response.status_code == 200, response.text
        # 挂到公共篇目下的句子随篇目，仍是公共内容
        sentence = client.post(
            f"{API}/passages/{shared['id']}/sentences",
            json={"text": "Shared sentence."},
            headers=other_headers,
        )
        assert sentence.status_code == 200, sentence.text
        assert sentence.json()["owner_id"] is None
    finally:
        row = db.get(Passage, uuid.UUID(shared["id"]))
        if row is not None:
            db.delete(row)
            db.commit()


def test_questions_are_owned_per_item_and_topic_is_shared(
    client: TestClient, teachers, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner_headers, other_headers, owner = teachers
    scenario = client.post(
        f"{API}/scenarios",
        json={"topic": f"Owned topic {uuid.uuid4().hex[:6]}"},
        headers=owner_headers,
    ).json()
    sid = scenario["id"]
    try:
        question = client.post(
            f"{API}/scenarios/{sid}/questions",
            json={"text": "What pets do you like?"},
            headers=owner_headers,
        ).json()
        assert question["owner_id"] == str(owner.id)
        qid = question["id"]

        _forbidden(
            client.put(
                f"{API}/questions/{qid}", json={"text": "x"}, headers=other_headers
            )
        )
        _forbidden(client.delete(f"{API}/questions/{qid}", headers=other_headers))
        _forbidden(
            client.put(
                f"{API}/scenarios/{sid}", json={"topic": "x"}, headers=other_headers
            )
        )
        _forbidden(client.delete(f"{API}/scenarios/{sid}", headers=other_headers))

        # 主题是共用分组：别的老师可以往里加自己的题
        added = client.post(
            f"{API}/scenarios/{sid}/questions",
            json={"text": "Do you have a pet?"},
            headers=other_headers,
        )
        assert added.status_code == 200, added.text
        batch = client.post(
            f"{API}/scenarios/{sid}/questions/batch",
            json={"items": [{"text": "Why?", "suggested_seconds": 20}]},
            headers=other_headers,
        )
        assert batch.status_code == 200, batch.text
        assert (
            client.put(
                f"{API}/questions/{added.json()['id']}",
                json={"text": "Do you have pets?"},
                headers=other_headers,
            ).status_code
            == 200
        )
        # 组内有他人的题：原作者也不能单方面删整组；管理员可以
        _forbidden(client.delete(f"{API}/scenarios/{sid}", headers=owner_headers))
        assert (
            client.delete(
                f"{API}/scenarios/{sid}", headers=superuser_token_headers
            ).status_code
            == 200
        )
    finally:
        row = db.get(Scenario, uuid.UUID(sid))
        if row is not None:
            db.delete(row)
            db.commit()


def test_import_records_owner_and_rejects_attaching_to_others_passage(
    client: TestClient, teachers, db: Session
) -> None:
    from tests.api.routes.test_question_bank_io import _csv_file, _upload

    owner_headers, other_headers, owner = teachers
    passage = _passage(client, owner_headers)
    attach = _csv_file(
        [
            {
                "__type__": "听句复述",
                "text": f"Attach {uuid.uuid4().hex[:6]}.",
                "passage_title": passage["title"],
            }
        ]
    )
    _forbidden(_upload(client, other_headers, attach, confirm=True))

    text = f"Imported {uuid.uuid4().hex[:6]}."
    own = _upload(
        client,
        owner_headers,
        _csv_file([{"__type__": "听句复述", "text": text}]),
        confirm=True,
    )
    assert own.status_code == 200, own.text
    row = db.exec(select(RepeatSentence).where(RepeatSentence.text == text)).one()
    assert row.owner_id == owner.id


def test_instruction_owner_guard(client: TestClient, teachers) -> None:
    owner_headers, other_headers, owner = teachers
    instruction = client.post(
        f"{API}/instructions", json={"text": "Part A begins."}, headers=owner_headers
    ).json()
    assert instruction["owner_id"] == str(owner.id)
    iid = instruction["id"]
    _forbidden(
        client.put(
            f"{API}/instructions/{iid}", json={"text": "x"}, headers=other_headers
        )
    )
    _forbidden(client.delete(f"{API}/instructions/{iid}", headers=other_headers))
    assert (
        client.delete(f"{API}/instructions/{iid}", headers=owner_headers).status_code
        == 200
    )
