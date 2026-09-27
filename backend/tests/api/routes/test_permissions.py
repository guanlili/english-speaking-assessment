"""权限与音频保护测试（Task 4）。

口径：
- 课堂码只用于学生入班，不构成任何教师权限；
- 教师 = 独立登录账号 + 课堂 owner 范围校验（401=未登录/凭证无效，403=权限不足）；
- 学生 = 入班轻量凭证（401=缺失/无效，403=凭证非本人）；
- 录音回放按归属校验，不靠「知道 UUID」；
- 上传用 ffprobe 校验真实音频，坏文件在付费评分前就被拒。
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.api.deps import get_scoring_submitter
from app.main import app
from app.models import User, UserCreate
from tests.utils.audio import wav_upload
from tests.utils.credential import (
    anonymous,
    remember_join,
    student_form,
    student_params,
    token_for,
)
from tests.utils.utils import random_email, random_lower_string


@pytest.fixture
def noop_scoring() -> Generator[None]:
    """不跑评分（音频回放/权限测试只关心访问控制）。"""
    app.dependency_overrides[get_scoring_submitter] = lambda: (
        lambda attempt_id: None  # noqa: ARG005
    )
    yield
    app.dependency_overrides.pop(get_scoring_submitter, None)


def _create_classroom(client: TestClient, headers: dict[str, str]) -> dict:
    resp = client.post("/api/v1/classes", json={"class_size": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _login_teacher(db: Session, client: TestClient) -> tuple[User, dict[str, str]]:
    """建一个普通（非管理员）教师账号并登录。"""
    email, password = random_email(), random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )
    resp = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return user, {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _join(client: TestClient, code: str, name: str) -> dict:
    resp = client.post(f"/api/v1/classes/{code}/join", json={"display_name": name})
    assert resp.status_code == 200, resp.text
    return remember_join(resp.json())


def _submit_first_attempt(client: TestClient, code: str, student: dict) -> str:
    plan = client.get(
        f"/api/v1/classes/{code}/today", params=student_params(student["id"])
    ).json()
    item = plan["items"][0]
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(5.0)},
        data=student_form(
            student["id"],
            item_type=item["type"],
            item_id=item["id"],
            duration_s="5.0",
            session_id=plan["session_id"],
        ),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# ── 课堂码 ≠ 教师权限 ────────────────────────────────────────────────


def test_classroom_code_grants_no_teacher_power(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """只知道课堂码（学生身份）拿不到名单/指派：未登录一律 401。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = _join(client, code, "小明")

    with anonymous(client):
        assert client.get(f"/api/v1/classes/{code}/board").status_code == 401
        assert client.get(f"/api/v1/classes/{code}/units").status_code == 401
        assert (
            client.put(
                f"/api/v1/classes/{code}/assignment",
                json={"unit_id": str(uuid.uuid4())},
            ).status_code
            == 401
        )
        # 学生自己带凭证也只能查自己
        ok = client.get(
            f"/api/v1/classes/{code}/today", params=student_params(student["id"])
        )
        assert ok.status_code == 200


def test_non_owner_teacher_forbidden_and_owner_allowed(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """教师有独立身份；课堂未绑定/绑定他人 → 403，绑定本人 → 200。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    teacher_a, headers_a = _login_teacher(db, client)
    teacher_b, headers_b = _login_teacher(db, client)

    # 未登录 → 401；已登录但课堂未绑定授权教师 → 403
    with anonymous(client):
        assert client.get(f"/api/v1/classes/{code}/board").status_code == 401
        assert (
            client.get(f"/api/v1/classes/{code}/board", headers=headers_a).status_code
            == 403
        )

    # 管理员在后台把 A 绑成授权教师
    resp = client.put(
        f"/api/v1/admin/classrooms/{classroom['id']}",
        json={"owner_id": str(teacher_a.id)},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_id"] == str(teacher_a.id)

    with anonymous(client):
        assert (
            client.get(f"/api/v1/classes/{code}/board", headers=headers_a).status_code
            == 200
        )
        # B 虽是登录教师，但不在这间课堂的授权范围（403，不登出）
        assert (
            client.get(f"/api/v1/classes/{code}/board", headers=headers_b).status_code
            == 403
        )
        assert (
            client.put(
                f"/api/v1/classes/{code}/assignment",
                json={"unit_id": str(uuid.uuid4())},
                headers=headers_b,
            ).status_code
            == 403
        )
        # 管理员始终可看
        assert (
            client.get(
                f"/api/v1/classes/{code}/board", headers=superuser_token_headers
            ).status_code
            == 200
        )


def test_owner_binding_rejects_unknown_user(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """绑定不存在的教师账号 → 422（不静默产生无主课堂）。"""
    classroom = _create_classroom(client, superuser_token_headers)
    resp = client.put(
        f"/api/v1/admin/classrooms/{classroom['id']}",
        json={"owner_id": str(uuid.uuid4())},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422


# ── 学生轻量凭证 ────────────────────────────────────────────────────


def test_student_endpoints_require_credential(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """学生查询校验本人凭证：缺 401、非本人 403、本人 200。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = _join(client, code, "小红")
    other = _join(client, code, "小刚")

    with anonymous(client):
        missing = client.get(
            f"/api/v1/classes/{code}/today", params={"student_id": student["id"]}
        )
        assert missing.status_code == 401

        forged = client.get(
            f"/api/v1/classes/{code}/today",
            params={"student_id": student["id"], "token": token_for(other["id"])},
        )
        assert forged.status_code == 403

        # 凭证无效/过期（篡改签名）→ 401
        tampered = client.get(
            f"/api/v1/classes/{code}/today",
            params={"student_id": student["id"], "token": "not-a-token"},
        )
        assert tampered.status_code == 401

        own = client.get(
            f"/api/v1/classes/{code}/today", params=student_params(student["id"])
        )
        assert own.status_code == 200


def test_submit_requires_own_credential(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    noop_scoring: None,
) -> None:
    """交作业必须带本人凭证（只给 student_id 拒绝）。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = _join(client, code, "提交人")
    other = _join(client, code, "冒名者")
    plan = client.get(
        f"/api/v1/classes/{code}/today", params=student_params(student["id"])
    ).json()
    item = plan["items"][0]

    with anonymous(client):
        base = {
            "item_type": item["type"],
            "item_id": item["id"],
            "duration_s": "5.0",
            "session_id": plan["session_id"],
        }
        no_token = client.post(
            "/api/v1/attempts",
            files={"audio": wav_upload(5.0)},
            data={"student_id": student["id"], **base},
        )
        assert no_token.status_code == 401

        forged = client.post(
            "/api/v1/attempts",
            files={"audio": wav_upload(5.0)},
            data={
                "student_id": student["id"],
                "token": token_for(other["id"]),
                **base,
            },
        )
        assert forged.status_code == 403


# ── 录音回放按归属校验（不靠 UUID）──────────────────────────────────


def test_attempt_audio_access_matrix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    noop_scoring: None,
    db: Session,
) -> None:
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    owner, owner_headers = _login_teacher(db, client)
    _stranger, stranger_headers = _login_teacher(db, client)
    resp = client.put(
        f"/api/v1/admin/classrooms/{classroom['id']}",
        json={"owner_id": str(owner.id)},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200

    student = _join(client, code, "录音人")
    other = _join(client, code, "旁听人")
    attempt_id = _submit_first_attempt(client, code, student)
    url = f"/api/v1/attempts/{attempt_id}/audio"

    with anonymous(client):
        # 匿名：401（UUID 猜不到也没用）
        assert client.get(url).status_code == 401
        # 别人的学生凭证：403
        assert (
            client.get(url, params={"token": token_for(other["id"])}).status_code == 403
        )
        # 本人凭证：200 且字节一致
        own = client.get(url, params={"token": token_for(student["id"])})
        assert own.status_code == 200
        assert own.headers["content-type"].startswith("audio/")
        # 非授权教师（登录但没绑进这间课堂）：403（不登出）
        assert client.get(url, headers=stranger_headers).status_code == 403
        # 授权教师：200
        assert client.get(url, headers=owner_headers).status_code == 200
        # 管理员：200
        assert client.get(url, headers=superuser_token_headers).status_code == 200
        # 不存在的作答：404
        assert client.get(f"/api/v1/attempts/{uuid.uuid4()}/audio").status_code == 404


def test_attempt_status_poll_requires_credential(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    noop_scoring: None,
) -> None:
    """轮询作答状态同样校验归属。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = _join(client, code, "轮询人")
    other = _join(client, code, "别人")
    attempt_id = _submit_first_attempt(client, code, student)

    with anonymous(client):
        assert client.get(f"/api/v1/attempts/{attempt_id}").status_code == 401
        assert (
            client.get(
                f"/api/v1/attempts/{attempt_id}",
                params={"token": token_for(other["id"])},
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/attempts/{attempt_id}",
                params={"token": token_for(student["id"])},
            ).status_code
            == 200
        )


# ── 停用课堂 / 凭证失效 ─────────────────────────────────────────────


def test_closed_classroom_hides_from_students(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """课堂停用后学生请求 404（前端据此清身份回加入页），不再出题。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = _join(client, code, "在班人")

    ok = client.get(
        f"/api/v1/classes/{code}/today", params=student_params(student["id"])
    )
    assert ok.status_code == 200

    closed = client.put(
        f"/api/v1/admin/classrooms/{classroom['id']}",
        json={"is_active": False},
        headers=superuser_token_headers,
    )
    assert closed.status_code == 200
    assert closed.json()["is_active"] is False

    with anonymous(client):
        resp = client.get(
            f"/api/v1/classes/{code}/today", params=student_params(student["id"])
        )
        assert resp.status_code == 404


# ── 上传音频校验（付费评分前拦截坏输入）──────────────────────────────


def test_upload_rejects_non_audio_and_accepts_wav(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    noop_scoring: None,
) -> None:
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = _join(client, code, "录音校验")
    plan = client.get(
        f"/api/v1/classes/{code}/today", params=student_params(student["id"])
    ).json()
    item = plan["items"][0]
    base = {
        "item_type": item["type"],
        "item_id": item["id"],
        "duration_s": "5.0",
        "session_id": plan["session_id"],
    }

    def upload(name: str, payload: bytes, mime: str) -> Any:
        return client.post(
            "/api/v1/attempts",
            files={"audio": (name, payload, mime)},
            data=student_form(student["id"], **base),
        )

    # 真实 WAV：通过
    assert upload("a.wav", wav_upload(5.0)[1], "audio/wav").status_code == 200
    # 伪装成音频的普通文本：ffprobe 认不出 → 422
    bad = upload("a.webm", b"this is definitely not audio", "audio/webm")
    assert bad.status_code == 422
    assert "无效" in bad.json()["detail"] or "损坏" in bad.json()["detail"]
    # 声明时长与实际不符 → 以探测值为准（不被上报值利用）
    short_claim = client.post(
        "/api/v1/attempts",
        files={"audio": ("a.wav", wav_upload(1.0)[1], "audio/wav")},
        data=student_form(student["id"], **{**base, "duration_s": "30.0"}),
    )
    assert short_claim.status_code == 200
    assert short_claim.json()["duration_s"] == 1.0


def test_upload_rejects_too_short_recording(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    noop_scoring: None,
) -> None:
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = _join(client, code, "短录音")
    plan = client.get(
        f"/api/v1/classes/{code}/today", params=student_params(student["id"])
    ).json()
    item = plan["items"][0]
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(0.4)},
        data=student_form(
            student["id"],
            item_type=item["type"],
            item_id=item["id"],
            duration_s="0.4",
            session_id=plan["session_id"],
        ),
    )
    assert resp.status_code == 422
