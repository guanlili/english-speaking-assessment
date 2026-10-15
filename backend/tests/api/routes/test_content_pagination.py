import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Passage, RepeatSentence
from tests.utils.credential import anonymous, make_student


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
