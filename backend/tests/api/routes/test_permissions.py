"""权限与音频保护测试（账号制 JWT）。

口径：
- 课堂码只用于学生入班，不构成任何教师权限；
- 教师 = 独立登录账号 + 课堂 owner 范围校验（401=未登录/JWT 无效，403=权限不足）；
- 学生 = role=student 的账号 JWT，服务端从 token 自识别（不再传 student_id/token）；
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
from app.core.security import DEFAULT_STUDENT_PASSWORD
from app.main import app
from app.models import User, UserCreate
from tests.utils.audio import wav_upload
from tests.utils.credential import anonymous, make_student
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


def _submit_first_attempt(client: TestClient, code: str, student: dict) -> str:
    plan = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
    ).json()
    item = plan["items"][0]
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(5.0)},
        data={
            "item_type": item["type"],
            "item_id": item["id"],
            "duration_s": "5.0",
            "session_id": plan["session_id"],
        },
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# ── 课堂码 ≠ 教师权限 ────────────────────────────────────────────────


def test_classroom_code_grants_no_teacher_power(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """只知道课堂码拿不到教师面板：未登录 401，学生 JWT 也只有学生视角（403）。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = make_student(db, client, code, "小明")

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
        # 学生 JWT：登录有效但角色不足 → 403（不触发登出）
        assert (
            client.get(
                f"/api/v1/classes/{code}/board", headers=student["headers"]
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/classes/{code}/units", headers=student["headers"]
            ).status_code
            == 403
        )
        assert (
            client.put(
                f"/api/v1/classes/{code}/assignment",
                json={"unit_id": str(uuid.uuid4())},
                headers=student["headers"],
            ).status_code
            == 403
        )
        # 学生 JWT 查自己的今日计划 → 200
        ok = client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
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


def test_teacher_creates_classroom_and_lists_own(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """教师（非管理员）现在可以建课堂：创建者即属主，列表只见自己名下的。"""
    _teacher_a, headers_a = _login_teacher(db, client)
    _teacher_b, headers_b = _login_teacher(db, client)

    created = client.post("/api/v1/classes", json={"class_size": 25}, headers=headers_a)
    assert created.status_code == 200, created.text
    classroom = created.json()
    assert len(classroom["code"]) == 6
    assert classroom["owner_id"] is not None

    mine = client.get("/api/v1/classes", headers=headers_a).json()
    assert [c["code"] for c in mine] == [classroom["code"]]
    # 别的教师看不到这间课堂
    others = client.get("/api/v1/classes", headers=headers_b).json()
    assert classroom["code"] not in [c["code"] for c in others]
    # 管理员看得到全部
    admin_view = client.get("/api/v1/classes", headers=superuser_token_headers).json()
    assert classroom["code"] in [c["code"] for c in admin_view]

    # 学生建课堂 → 403；学生列表 → 200 且为空（名下无课堂）
    student = make_student(db, client, classroom["code"], "建班学生")
    with anonymous(client):
        assert (
            client.post(
                "/api/v1/classes", json={"class_size": 10}, headers=student["headers"]
            ).status_code
            == 403
        )
        assert client.get("/api/v1/classes", headers=student["headers"]).json() == []


# ── 学生 JWT ─────────────────────────────────────────────────────────


def test_join_requires_student_login(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """入班需要学生 JWT：匿名/坏 token 401，教师 JWT 403，学生 200 且幂等。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    url = f"/api/v1/classes/{code}/join"

    with anonymous(client):
        assert client.post(url, json={"display_name": "甲"}).status_code == 401
        assert (
            client.post(
                url, json={"display_name": "甲"}, headers={"Authorization": "Bearer x"}
            ).status_code
            == 401
        )
        _teacher, teacher_headers = _login_teacher(db, client)
        assert (
            client.post(
                url, json={"display_name": "甲"}, headers=teacher_headers
            ).status_code
            == 403
        )

    student = make_student(db, client, code, "甲")
    data = student["student"]
    assert data["display_name"] == "甲"
    assert data["user_id"] == str(student["user"].id)
    assert "access_token" not in data  # 入班响应不再携带轻量凭证

    # 重复入班幂等：同一账号再 join 返回已有档案
    again = client.post(url, json={"display_name": "甲"}, headers=student["headers"])
    assert again.status_code == 200, again.text
    assert again.json()["id"] == data["id"]


def test_student_endpoints_validate_jwt(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """学生查询凭 JWT 自识别：缺失/篡改 401，本人 200，他人 JWT 只见自己的。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = make_student(db, client, code, "小红")
    other = make_student(db, client, code, "小刚")

    with anonymous(client):
        missing = client.get(f"/api/v1/classes/{code}/today")
        assert missing.status_code == 401

        # JWT 无效/过期（篡改签名）→ 401
        tampered = client.get(
            f"/api/v1/classes/{code}/today",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert tampered.status_code == 401

        # 教师 JWT 访问学生端点 → 403（角色不足）
        _teacher, teacher_headers = _login_teacher(db, client)
        assert (
            client.get(
                f"/api/v1/classes/{code}/today", headers=teacher_headers
            ).status_code
            == 403
        )

    own = client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    assert own.status_code == 200
    own_plan = own.json()

    # 别人的有效学生 JWT → 200，但拿到的是他自己的计划（读不到小红的数据）
    foreign = client.get(f"/api/v1/classes/{code}/today", headers=other["headers"])
    assert foreign.status_code == 200
    assert foreign.json()["session_id"] != own_plan["session_id"]

    # 拿别人的会话 ID 查计划 → 404（会话归属校验）
    with anonymous(client):
        hijack = client.get(
            f"/api/v1/classes/{code}/today",
            params={"session_id": own_plan["session_id"]},
            headers=other["headers"],
        )
        assert hijack.status_code == 404


def test_submit_requires_own_jwt(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    noop_scoring: None,
) -> None:
    """交作业必须是登录学生本人：匿名 401，借他人会话 403。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = make_student(db, client, code, "提交人")
    other = make_student(db, client, code, "冒名者")
    plan = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
    ).json()
    item = plan["items"][0]

    base = {
        "item_type": item["type"],
        "item_id": item["id"],
        "duration_s": "5.0",
        "session_id": plan["session_id"],
    }
    with anonymous(client):
        no_login = client.post(
            "/api/v1/attempts",
            files={"audio": wav_upload(5.0)},
            data={**base},
        )
        assert no_login.status_code == 401

        forged = client.post(
            "/api/v1/attempts",
            files={"audio": wav_upload(5.0)},
            data={**base},
            headers=other["headers"],
        )
        assert forged.status_code == 403

    own = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(5.0)},
        data={**base},
        headers=student["headers"],
    )
    assert own.status_code == 200, own.text


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

    student = make_student(db, client, code, "录音人")
    other = make_student(db, client, code, "旁听人")
    attempt_id = _submit_first_attempt(client, code, student)
    url = f"/api/v1/attempts/{attempt_id}/audio"

    with anonymous(client):
        # 匿名：401（UUID 猜不到也没用）
        assert client.get(url).status_code == 401
        # 别人的学生 JWT：403
        assert client.get(url, headers=other["headers"]).status_code == 403
        # 本人 JWT：200 且字节可回放
        own = client.get(url, headers=student["headers"])
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
    db: Session,
    noop_scoring: None,
) -> None:
    """轮询作答状态同样校验归属：匿名 401、他人 JWT 403、本人 200。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = make_student(db, client, code, "轮询人")
    other = make_student(db, client, code, "别人")
    attempt_id = _submit_first_attempt(client, code, student)

    with anonymous(client):
        assert client.get(f"/api/v1/attempts/{attempt_id}").status_code == 401
        assert (
            client.get(
                f"/api/v1/attempts/{attempt_id}", headers=other["headers"]
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/attempts/{attempt_id}", headers=student["headers"]
            ).status_code
            == 200
        )


def test_trail_access_matrix(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """轨迹：学生看自己；教师缺 student_id 422、非属主 403、属主/管理员 200。"""
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

    student = make_student(db, client, code, "轨迹人")
    trail_url = f"/api/v1/classes/{code}/trail"

    # 学生：省略 student_id 看自己
    own = client.get(trail_url, headers=student["headers"])
    assert own.status_code == 200
    assert own.json()["student_id"] == student["student"]["id"]

    with anonymous(client):
        # 未登录 401
        assert client.get(trail_url).status_code == 401
        # 教师必须传 student_id（缺参 422，而不是看自己）
        assert client.get(trail_url, headers=owner_headers).status_code == 422
        # 非属主教师传 student_id → 403
        assert (
            client.get(
                trail_url,
                params={"student_id": student["student"]["id"]},
                headers=stranger_headers,
            ).status_code
            == 403
        )
        # 属主教师 → 200
        assert (
            client.get(
                trail_url,
                params={"student_id": student["student"]["id"]},
                headers=owner_headers,
            ).status_code
            == 200
        )
        # 管理员 → 200
        assert (
            client.get(
                trail_url,
                params={"student_id": student["student"]["id"]},
                headers=superuser_token_headers,
            ).status_code
            == 200
        )


# ── 停用课堂 / 凭证失效 ─────────────────────────────────────────────


def test_closed_classroom_hides_from_students(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """课堂停用后学生请求 404（前端据此清身份回加入页），不再出题。"""
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = make_student(db, client, code, "在班人")

    ok = client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    assert ok.status_code == 200

    closed = client.put(
        f"/api/v1/admin/classrooms/{classroom['id']}",
        json={"is_active": False},
        headers=superuser_token_headers,
    )
    assert closed.status_code == 200
    assert closed.json()["is_active"] is False

    resp = client.get(f"/api/v1/classes/{code}/today", headers=student["headers"])
    assert resp.status_code == 404


# ── 上传音频校验（付费评分前拦截坏输入）──────────────────────────────


def test_upload_rejects_non_audio_and_accepts_wav(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    noop_scoring: None,
) -> None:
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = make_student(db, client, code, "录音校验")
    plan = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
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
            data={**base},
            headers=student["headers"],
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
        data={**base, "duration_s": "30.0"},
        headers=student["headers"],
    )
    assert short_claim.status_code == 200
    assert short_claim.json()["duration_s"] == 1.0


def test_upload_rejects_too_short_recording(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    noop_scoring: None,
) -> None:
    classroom = _create_classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = make_student(db, client, code, "短录音")
    plan = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
    ).json()
    item = plan["items"][0]
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(0.4)},
        data={
            "item_type": item["type"],
            "item_id": item["id"],
            "duration_s": "0.4",
            "session_id": plan["session_id"],
        },
        headers=student["headers"],
    )
    assert resp.status_code == 422


def test_bulk_reset_passwords(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """批量重置：课堂内全部已绑定账号生成新初始密码并置改密标记。"""
    from tests.utils.credential import create_student_user, join_as

    resp = client.post(
        "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
    )
    assert resp.status_code == 200
    classroom = resp.json()
    joined1 = join_as(
        client, classroom["code"], create_student_user(db, "学生一"), "学生一"
    )
    join_as(client, classroom["code"], create_student_user(db, "学生二"), "学生二")

    reset = client.post(
        "/api/v1/students/bulk-reset-password",
        params={"classroom_id": classroom["id"]},
        headers=superuser_token_headers,
    )
    assert reset.status_code == 200, reset.text
    data = reset.json()
    assert data["reset"] == 2
    passwords = {r["username"]: r["new_password"] for r in data["rows"]}
    # 重置后统一为默认密码，不再强制改密
    assert all(p == DEFAULT_STUDENT_PASSWORD for p in passwords.values())

    # 默认密码能直接登录，无改密标记
    sample_user = joined1["user"]
    login = client.post(
        "/api/v1/login/access-token",
        data={
            "username": sample_user.username,
            "password": passwords[sample_user.username],
        },  # type: ignore[index]
    )
    assert login.status_code == 200
    me = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    ).json()
    assert me["must_change_password"] is False

    client.delete("/api/v1/classes", headers=superuser_token_headers) if False else None
