"""管理员使用记录 CSV 导出：三口径形状 + 权限门。"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.models import Attempt, PracticeSession
from tests.utils.credential import make_student

tz = ZoneInfo(settings.PRACTICE_TZ)


def _purge(db: Session) -> None:
    db.exec(delete(Attempt))  # type: ignore[call-overload]
    db.exec(delete(PracticeSession))  # type: ignore[call-overload]
    db.commit()


def _seed(client: TestClient, headers: dict[str, str], db: Session, name: str) -> None:
    _purge(db)
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=headers
    ).json()
    ada = make_student(db, client, classroom["code"], name)
    ada_id = uuid.UUID(ada["student"]["id"])
    day = datetime.now(tz).date()
    ps = PracticeSession(
        classroom_id=uuid.UUID(classroom["id"]),
        student_id=ada_id,
        band="B1",
        session_date=day,
    )
    db.add(ps)
    db.flush()
    db.add(
        Attempt(
            item_type="question",
            item_id=uuid.uuid4(),
            student_id=ada_id,
            session_id=ps.id,
            audio_path="t.webm",
            duration_s=5.0,
            status="done",
            overall=80,
            created_at=datetime.combine(day, datetime.min.time().replace(hour=9), tz),
        )
    )
    db.commit()


def test_export_requires_superuser(client: TestClient) -> None:
    for path in ("attempts", "sessions", "students"):
        assert client.get(f"/api/v1/admin/export/{path}").status_code == 401, path


def test_export_attempts_csv(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(client, superuser_token_headers, db, "AdaA")
    resp = client.get("/api/v1/admin/export/attempts", headers=superuser_token_headers)
    assert resp.status_code == 200
    text = resp.text
    assert text[0] == "\ufeff"  # BOM（Excel 直开）
    lines = text.strip().splitlines()
    assert lines[0].startswith("\ufeff日期,时间,学生,区分码,学号,课堂")
    assert len(lines) == 2  # 表头 + 1 行作答
    assert "情景问答" in lines[1]
    assert ",80," in lines[1] or ",80" in lines[1]
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]


def test_export_attempts_days_filter(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(client, superuser_token_headers, db, "AdaA")
    # days=1：今天的作答在窗口内
    resp = client.get(
        "/api/v1/admin/export/attempts?days=1", headers=superuser_token_headers
    )
    assert len(resp.text.strip().splitlines()) == 2
    # days=0=全部 同样
    resp = client.get("/api/v1/admin/export/attempts", headers=superuser_token_headers)
    assert len(resp.text.strip().splitlines()) == 2


def test_export_sessions_and_students_csv(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(client, superuser_token_headers, db, "AdaS")
    resp = client.get("/api/v1/admin/export/sessions", headers=superuser_token_headers)
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("\ufeff练习日期,开始时间,学生")
    assert len(lines) == 2  # 一轮练习
    assert "课堂练习" in lines[1]

    resp = client.get("/api/v1/admin/export/students", headers=superuser_token_headers)
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("\ufeff学生,区分码,学号,课堂,当前档位,练习轮次")
    # 共享测试库可能残留其他档案——按本测试唯一名断言
    ada_rows = [ln for ln in lines[1:] if ln.split(",")[0] == "AdaS"]
    # 轮次/作答聚合列有值（本测试造的 1 轮 1 答）
    assert ada_rows[0].split(",")[5] == "1"  # 练习轮次
    assert ada_rows[0].split(",")[6] == "1"  # 作答总数
