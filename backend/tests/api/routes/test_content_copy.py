import uuid
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.models import (
    Instruction,
    Passage,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    User,
)
from app.services.content_access import FORBIDDEN_DETAIL
from tests.api.routes import test_content_ownership

teachers = test_content_ownership.teachers
API = "/api/v1/admin"


def test_copy_passage_copies_tree_audio_and_settings(
    client: TestClient, db: Session, teachers
) -> None:
    owner_headers, other_headers, owner = teachers
    source = Passage(
        title="Original reading",
        text="One. Two.",
        slug=f"copy-source-{uuid.uuid4().hex}",
        owner_id=owner.id,
        reading_split=True,
        reading_sentence_seconds=[12, 18],
        audio_url="/api/v1/content-audio/source.wav",
        exam_settings={
            "wait_seconds": 3,
            "audio_url": "/api/v1/content-audio/exam.wav",
        },
    )
    db.add(source)
    db.flush()
    child = Passage(
        title="Legacy child",
        text="One.",
        slug=f"child-{uuid.uuid4().hex}",
        parent_passage_id=source.id,
        owner_id=owner.id,
    )
    db.add(child)
    db.flush()
    sentences = [
        RepeatSentence(
            passage_id=pid,
            owner_id=owner.id,
            order_index=index,
            text="Repeat me.",
            audio_url="/api/v1/content-audio/repeat.wav",
            replay_limit=2,
            exam_kind="toefl_lnr",
            exam_level="PET",
            exam_settings={"wait_seconds": 5},
        )
        for index, pid in enumerate([source.id, child.id])
    ]
    db.add_all(sentences)
    db.commit()
    db.refresh(source)
    original = deepcopy(source.model_dump())

    response = client.post(f"{API}/passages/{child.id}/copy", headers=other_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    copied = db.get(Passage, uuid.UUID(body["id"]))
    assert copied is not None
    assert copied.id != source.id
    assert copied.owner_id is not None and copied.owner_id != owner.id
    assert copied.parent_passage_id is None
    assert copied.audio_url == source.audio_url
    assert copied.exam_settings == source.exam_settings
    assert copied.reading_sentence_seconds == [12, 18]
    assert body["reading_segments"] == ["One.", "Two."]
    assert len(body["sentences"]) == len(body["reading_child_ids"]) == 1
    copied_child_id = uuid.UUID(body["reading_child_ids"][0])
    copied_sentences = db.exec(
        select(RepeatSentence).where(
            col(RepeatSentence.passage_id).in_([copied.id, copied_child_id])
        )
    ).all()
    assert len(copied_sentences) == 2
    assert all(s.owner_id == copied.owner_id for s in copied_sentences)
    assert all(s.id not in {row.id for row in sentences} for s in copied_sentences)
    assert all(
        s.audio_url == sentences[0].audio_url and s.replay_limit == 2
        for s in copied_sentences
    )
    assert all(s.exam_settings == {"wait_seconds": 5} for s in copied_sentences)
    changed = client.put(
        f"{API}/passages/{copied.id}",
        headers=other_headers,
        json={"text": "My new reading."},
    )
    assert changed.status_code == 200, changed.text
    db.refresh(source)
    assert source.model_dump() == original
    forbidden = client.put(
        f"{API}/passages/{copied.id}",
        headers=owner_headers,
        json={"title": "Cannot change"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == FORBIDDEN_DETAIL
    repeated = client.post(f"{API}/passages/{source.id}/copy", headers=other_headers)
    assert repeated.status_code == 200
    assert repeated.json()["slug"] != body["slug"]


def test_copy_attached_sentence_becomes_owned_standalone(
    client: TestClient, db: Session, teachers
) -> None:
    _, other_headers, owner = teachers
    passage = Passage(
        title="Root", text="Root.", slug=uuid.uuid4().hex, owner_id=owner.id
    )
    db.add(passage)
    db.flush()
    source = RepeatSentence(
        passage_id=passage.id,
        owner_id=owner.id,
        order_index=4,
        text="Original.",
        translation="原文",
        replay_limit=0,
        audio_url="/api/v1/content-audio/original.wav",
        exam_settings={"wait_seconds": 2},
    )
    db.add(source)
    db.commit()
    response = client.post(f"{API}/sentences/{source.id}/copy", headers=other_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passage_id"] is None and body["passage_title"] is None
    assert body["owner_id"] != str(owner.id)
    assert body["replay_limit"] == 0
    assert body["audio_url"] == source.audio_url
    assert body["exam_settings"] == source.exam_settings
    assert (
        client.put(
            f"{API}/sentences/{body['id']}",
            headers=other_headers,
            json={"text": "Changed."},
        ).status_code
        == 200
    )
    db.refresh(source)
    assert source.text == "Original."


def test_copy_scenario_and_question_keep_content_but_not_ownership(
    client: TestClient, db: Session, teachers
) -> None:
    _, other_headers, owner = teachers
    scenario = Scenario(topic=f"Topic {uuid.uuid4().hex}", owner_id=owner.id)
    db.add(scenario)
    db.flush()
    question = ScenarioQuestion(
        scenario_id=scenario.id,
        owner_id=owner.id,
        order_index=2,
        text="Describe a pet.",
        translation="描述宠物",
        audio_url="/api/v1/content-audio/question.wav",
        exam_kind="ielts_p2",
        exam_level="PET",
        suggested_seconds=120,
        prep_seconds=60,
        cue_card_bullets=["What it is", "Why you like it"],
        exam_settings={
            "wait_seconds": 4,
            "audio_url": "/api/v1/content-audio/question-exam.wav",
        },
    )
    db.add(question)
    db.commit()
    response = client.post(f"{API}/scenarios/{scenario.id}/copy", headers=other_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["topic"] != scenario.topic
    assert body["owner_id"] != str(owner.id)
    assert len(body["questions"]) == 1
    copied = db.get(ScenarioQuestion, uuid.UUID(body["questions"][0]["id"]))
    assert copied is not None
    assert copied.scenario_id == uuid.UUID(body["id"])
    assert copied.owner_id == uuid.UUID(body["owner_id"])
    excluded = {"id", "owner_id", "scenario_id"}
    db.refresh(question)
    assert copied.model_dump(exclude=excluded) == question.model_dump(exclude=excluded)
    again = client.post(f"{API}/scenarios/{scenario.id}/copy", headers=other_headers)
    assert again.status_code == 200
    assert again.json()["topic"] != body["topic"]
    single = client.post(f"{API}/questions/{question.id}/copy", headers=other_headers)
    assert single.status_code == 200, single.text
    assert single.json()["scenario_id"] == str(scenario.id)
    assert single.json()["audio_url"] == question.audio_url
    assert single.json()["order_index"] == 3
    assert (
        client.put(
            f"{API}/questions/{single.json()['id']}",
            headers=other_headers,
            json={"text": "My question."},
        ).status_code
        == 200
    )
    db.refresh(question)
    assert question.text == "Describe a pet."


def test_copy_instruction_preserves_audio_settings(
    client: TestClient, db: Session, teachers, superuser_token_headers: dict[str, str]
) -> None:
    _, other_headers, owner = teachers
    source = Instruction(
        title="Start",
        text="Listen carefully.",
        suggested_seconds=45,
        owner_id=owner.id,
        exam_settings={"audio_url": "/api/v1/content-audio/intro.wav"},
    )
    db.add(source)
    db.commit()
    response = client.post(
        f"{API}/instructions/{source.id}/copy", headers=other_headers
    )
    assert response.status_code == 200, response.text
    copied = db.get(Instruction, uuid.UUID(response.json()["id"]))
    assert copied is not None
    assert copied.text == source.text and copied.suggested_seconds == 45
    assert copied.owner_id != owner.id
    assert copied.exam_settings == source.exam_settings
    public_copy = client.post(
        f"{API}/instructions/{source.id}/copy", headers=superuser_token_headers
    )
    assert public_copy.status_code == 200, public_copy.text
    assert public_copy.json()["owner_id"] is None
    public = db.get(Instruction, uuid.UUID(public_copy.json()["id"]))
    assert public is not None
    db.delete(public)
    db.commit()


def test_copy_scenario_name_stays_unique_at_max_length(
    client: TestClient, db: Session, teachers
) -> None:
    _, headers, owner = teachers
    topic = f"{uuid.uuid4().hex}{'x' * 68}"
    source = Scenario(topic=topic, owner_id=owner.id)
    db.add(source)
    db.commit()
    names = []
    for _ in range(3):
        response = client.post(f"{API}/scenarios/{source.id}/copy", headers=headers)
        assert response.status_code == 200, response.text
        names.append(response.json()["topic"])
    assert all(len(name) <= 100 for name in names)
    assert len(set(names)) == 3
    db.refresh(source)
    assert source.topic == topic


@pytest.mark.parametrize(
    "kind", ["passages", "sentences", "scenarios", "questions", "instructions"]
)
def test_copy_requires_teacher_and_existing_source(
    client: TestClient, db: Session, teachers, kind: str
) -> None:
    _, other_headers, _ = teachers
    path = f"{API}/{kind}/{uuid.uuid4()}/copy"
    assert client.post(path).status_code == 401
    assert client.post(path, headers=other_headers).status_code == 404
    current = client.get("/api/v1/users/me", headers=other_headers).json()
    user = db.get(User, uuid.UUID(current["id"]))
    assert user is not None
    user.role = "student"
    db.add(user)
    db.commit()
    assert client.post(path, headers=other_headers).status_code == 403
