import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Passage, RepeatSentence
from tests.utils.credential import anonymous, make_student


@pytest.fixture(autouse=True)
def restore_sentence_library(db: Session) -> Generator[None]:
    # 本模块的分页样例不能混进后续 DEMO01 的默认题单。
    original = set(db.exec(select(RepeatSentence.id)).all())
    yield
    db.rollback()
    for row in db.exec(select(RepeatSentence)).all():
        if row.id not in original:
            db.delete(row)
    db.commit()


def test_sentence_page_filters_before_count_and_keeps_stable_order(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    marker = f"page-{uuid.uuid4().hex}"
    created_at = datetime.now(UTC)
    rows = [
        RepeatSentence(text=f"{marker} item {i}", order_index=i, created_at=created_at)
        for i in range(25)
    ]
    passage = db.exec(select(Passage)).first()
    assert passage is not None
    linked = RepeatSentence(
        text=f"{marker} linked", passage_id=passage.id, order_index=0
    )
    db.add_all([*rows, linked])
    db.commit()
    params = {"q": marker.upper(), "standalone_only": True, "limit": 20}
    first = client.get(
        "/api/v1/admin/sentences-page", params=params, headers=superuser_token_headers
    )
    second = client.get(
        "/api/v1/admin/sentences-page",
        params={**params, "skip": 20},
        headers=superuser_token_headers,
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["count"] == second.json()["count"] == 25
    ids = [row["id"] for page in [first, second] for row in page.json()["data"]]
    assert len(ids) == len(set(ids)) == 25
    assert set(ids) == {str(row.id) for row in rows}
    search = client.get(
        "/api/v1/admin/sentences-page",
        params={"q": f"{marker} linked"},
        headers=superuser_token_headers,
    ).json()
    assert search["count"] == 1
    assert search["data"][0]["passage_title"] == passage.title
    assert (
        client.get(
            "/api/v1/admin/sentences-page",
            params={"limit": 101},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )

    db.add_all(
        [
            RepeatSentence(text=f"{marker} 100% clear", order_index=0),
            RepeatSentence(text=f"{marker} 100X clear", order_index=1),
        ]
    )
    db.commit()
    literal = client.get(
        "/api/v1/admin/sentences-page",
        params={"q": f"{marker} 100%"},
        headers=superuser_token_headers,
    ).json()
    assert literal["count"] == 1
    assert literal["data"][0]["text"] == f"{marker} 100% clear"


def test_sentence_page_is_teacher_only(client: TestClient, db: Session) -> None:
    with anonymous(client):
        assert client.get("/api/v1/admin/sentences-page").status_code == 401
    student = make_student(db, client, "DEMO01", "分页权限")
    assert (
        client.get(
            "/api/v1/admin/sentences-page", headers=student["headers"]
        ).status_code
        == 403
    )


def test_composer_restores_selected_details_without_loading_unrelated_items(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    row = RepeatSentence(text="Selected composer detail", order_index=0)
    db.add(row)
    db.add(RepeatSentence(text="Unrelated composer detail", order_index=1))
    db.commit()
    missing = str(uuid.uuid4())
    result = client.post(
        "/api/v1/admin/composer-selection",
        headers=superuser_token_headers,
        json={
            "items": [
                {"type": "repeat", "id": str(row.id)},
                {"type": "question", "id": missing},
            ]
        },
    )
    assert result.status_code == 200, result.text
    data = result.json()
    assert [item["id"] for item in data["sentences"]] == [str(row.id)]
    assert data["missing_ids"] == [missing]
    assert data["passages"] == data["scenarios"] == data["instructions"] == []
    assert (
        client.post(
            "/api/v1/admin/composer-selection",
            headers=superuser_token_headers,
            json={"items": [{"type": "bad", "id": missing}]},
        ).status_code
        == 422
    )


def test_revision_changes_only_with_publication_state_and_checks_membership(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    from app.models import Classroom

    student = make_student(db, client, "DEMO01", "同步版本")
    url = "/api/v1/classes/DEMO01/revision"
    first = client.get(url, headers=student["headers"])
    assert first.status_code == 200
    assert client.get(url, headers=student["headers"]).json() == first.json()
    classroom = db.exec(select(Classroom).where(Classroom.code == "DEMO01")).one()
    old = classroom.assign_reading
    classroom.assign_reading = not old
    db.add(classroom)
    db.commit()
    try:
        changed = client.get(url, headers=student["headers"])
        assert changed.json()["revision"] != first.json()["revision"]
        assert set(changed.json()) == {"revision"}
        assert "X-Request-ID" in changed.headers
        assert changed.headers["X-Request-ID"] != first.headers["X-Request-ID"]
        supplied = client.get(
            url, headers={**student["headers"], "X-Request-ID": "support-case-1234"}
        )
        assert supplied.headers["X-Request-ID"] == "support-case-1234"
        with anonymous(client):
            assert client.get(url).status_code == 401
    finally:
        classroom.assign_reading = old
        db.add(classroom)
        db.commit()


def test_composer_resolves_legacy_reading_children_and_selected_question_topics(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    from app.models import Instruction, Scenario, ScenarioQuestion

    marker = uuid.uuid4().hex
    root = Passage(
        slug=f"root-{marker}",
        title="Root article",
        text="Root content.",
        cefr_band="B1",
    )
    db.add(root)
    db.flush()
    child = Passage(
        slug=f"child-{marker}",
        title="Old child",
        text="Child content.",
        cefr_band="B1",
        parent_passage_id=root.id,
    )
    scenario = Scenario(topic=f"Composer-{marker}")
    db.add_all([child, scenario])
    db.flush()
    question = ScenarioQuestion(
        scenario_id=scenario.id, text="Selected question?", band="B1", order_index=0
    )
    other = ScenarioQuestion(
        scenario_id=scenario.id,
        text="Other question in selected topic?",
        band="B1",
        order_index=1,
    )
    instruction = Instruction(text="Read this instruction.", suggested_seconds=20)
    db.add_all([question, other, instruction])
    db.commit()
    try:
        response = client.post(
            "/api/v1/admin/composer-selection",
            headers=superuser_token_headers,
            json={
                "items": [
                    {"type": "passage", "id": str(child.id)},
                    {"type": "question", "id": str(question.id)},
                    {"type": "instruction", "id": str(instruction.id)},
                ]
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["missing_ids"] == []
        assert [p["id"] for p in data["passages"]] == [str(root.id)]
        assert str(child.id) in data["passages"][0]["reading_child_ids"]
        assert {q["id"] for q in data["scenarios"][0]["questions"]} == {
            str(question.id),
            str(other.id),
        }
        assert [i["id"] for i in data["instructions"]] == [str(instruction.id)]
        student = make_student(db, client, "DEMO01", "组卷权限")
        assert (
            client.post(
                "/api/v1/admin/composer-selection",
                headers=student["headers"],
                json={"items": []},
            ).status_code
            == 403
        )
        with anonymous(client):
            assert (
                client.post(
                    "/api/v1/admin/composer-selection", json={"items": []}
                ).status_code
                == 401
            )
    finally:
        for row in (question, other, instruction, child, scenario, root):
            db.delete(row)
            db.flush()
        db.commit()
