"""升级表达收藏挂课堂档案，换设备仍在。"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.credential import make_student


def test_expression_favorites_follow_the_student_account(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
    ).json()
    code = classroom["code"]
    ada = make_student(db, client, code, "Ada")
    ben = make_student(db, client, code, "Ben")
    path = f"/api/v1/classes/{code}/expression-favorites"

    saved = client.post(
        path,
        json={"texts": [" I usually visit museums. ", "I usually visit museums."]},
        headers=ada["headers"],
    )
    assert saved.status_code == 200, saved.text
    assert [row["text"] for row in saved.json()] == ["I usually visit museums."]

    again = client.post(
        path,
        json={"texts": ["I usually visit museums."]},
        headers=ada["headers"],
    )
    assert again.status_code == 200
    assert len(again.json()) == 1

    listed = client.get(path, headers=ada["headers"])
    assert listed.status_code == 200
    favorite_id = listed.json()[0]["id"]

    other = client.get(path, headers=ben["headers"])
    assert other.json() == []

    # 管理员没有这份学生档案，进不了学生收藏
    teacher = client.get(path, headers=superuser_token_headers)
    assert teacher.status_code == 404

    removed = client.delete(f"{path}/{favorite_id}", headers=ada["headers"])
    assert removed.status_code == 200
    assert removed.json() == []
    # 别人的删除请求不能清掉（此时已空）；幂等再删仍是空列表
    assert client.delete(f"{path}/{favorite_id}", headers=ben["headers"]).json() == []
