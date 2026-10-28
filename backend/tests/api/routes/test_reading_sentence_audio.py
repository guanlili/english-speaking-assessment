"""Per-sentence TTS audio：按句子原文寻址，发布进快照，不随正文编辑整体失效。"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import Classroom, ClassroomExercise, Passage
from app.services.reading import expand_reading_items
from tests.api.routes.test_exam import _cleanup_classroom


def test_sentence_audio_set_publish_clear_and_prune(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    headers = superuser_token_headers
    passage = Passage(
        slug=f"sent-audio-{uuid.uuid4()}",
        title="Audio",
        text="Read this. Read that!",
        reading_split=True,
    )
    db.add(passage)
    db.commit()
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 10}, headers=headers
    ).json()
    endpoint = f"/api/v1/admin/passages/{passage.id}"
    try:
        # 只配第二句
        response = client.put(
            endpoint,
            json={
                "reading_sentence_texts": ["Read this.", "Read that!"],
                "reading_sentence_audio": {"Read that!": "/api/v1/audio/content/a.wav"},
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["reading_sentence_audio"] == {
            "Read that!": "/api/v1/audio/content/a.wav"
        }
        db.refresh(passage)
        assert [i["audio_url"] for i in expand_reading_items(passage)] == [
            None,
            "/api/v1/audio/content/a.wav",
        ]
        # 发布快照携带句子标准音
        response = client.put(
            f"/api/v1/classes/{classroom['code']}/assignment",
            json={
                "items": [{"type": "passage", "id": str(passage.id)}],
                "is_exam": True,
                "automated_exam": True,
                "time_limit_minutes": 5,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        row = db.get(Classroom, uuid.UUID(classroom["id"]))
        assert row is not None
        db.refresh(row)
        published = db.get(ClassroomExercise, row.current_exercise_id)
        assert published is not None
        assert [i["audio_url"] for i in published.snapshot_items] == [
            None,
            "/api/v1/audio/content/a.wav",
        ]
        # 清空配音：已发布快照不变（不可变）
        response = client.put(
            endpoint,
            json={
                "reading_sentence_texts": ["Read this.", "Read that!"],
                "reading_sentence_audio": {},
            },
            headers=headers,
        )
        assert response.status_code == 200
        db.refresh(passage)
        assert expand_reading_items(passage)[1]["audio_url"] is None
        assert [i["audio_url"] for i in published.snapshot_items] == [
            None,
            "/api/v1/audio/content/a.wav",
        ]
        # 正文改第一句、未传字典：第二句配音按原文保留，不被重置。
        # （先重新配音，上面清空校验已经把字典清成 {}）
        response = client.put(
            endpoint,
            json={
                "reading_sentence_texts": ["Read this.", "Read that!"],
                "reading_sentence_audio": {"Read that!": "/api/v1/audio/content/a.wav"},
            },
            headers=headers,
        )
        assert response.status_code == 200
        response = client.put(
            endpoint, json={"text": "Changed first. Read that!"}, headers=headers
        )
        assert response.status_code == 200
        db.refresh(passage)
        assert [i["audio_url"] for i in expand_reading_items(passage)] == [
            None,
            "/api/v1/audio/content/a.wav",
        ]
        # 传字典时失配旧键被修剪（"Gone." 不是当前分句）
        response = client.put(
            endpoint,
            json={
                "reading_sentence_texts": ["Changed first.", "Read that!"],
                "reading_sentence_audio": {
                    "Read that!": "/api/v1/audio/content/a.wav",
                    "Gone.": "/api/v1/audio/content/g.wav",
                },
            },
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["reading_sentence_audio"] == {
            "Read that!": "/api/v1/audio/content/a.wav"
        }
        # URL 超长 422
        response = client.put(
            endpoint,
            json={
                "reading_sentence_texts": ["Changed first.", "Read that!"],
                "reading_sentence_audio": {"Read that!": "x" * 1025},
            },
            headers=headers,
        )
        assert response.status_code == 422
    finally:
        _cleanup_classroom(db, classroom["id"])
        db.delete(passage)
        db.commit()


def test_sentence_audio_whole_passage_untouched(db: Session) -> None:
    """未拆句/单句正文走整篇分支：句子配音表不影响整篇 audio_url。"""
    passage = Passage(
        slug=f"sent-audio-{uuid.uuid4()}",
        title="Whole",
        text="One whole sentence.",
        reading_split=False,
        audio_url="/api/v1/audio/content/w.wav",
        reading_sentence_audio={"One whole sentence.": "/api/v1/audio/content/s.wav"},
    )
    db.add(passage)
    db.commit()
    try:
        items = expand_reading_items(passage)
        assert len(items) == 1
        assert items[0]["audio_url"] == "/api/v1/audio/content/w.wav"
    finally:
        db.delete(passage)
        db.commit()
