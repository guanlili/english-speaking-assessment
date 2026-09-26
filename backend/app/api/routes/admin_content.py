"""管理员内容管理接口（PRD：内容槽由校方录入，软件只留槽位）。

全部需要超级管理员权限。EIP 文本只进数据库，不进 git。

    /admin/passages            篇目 CRUD（含复述句子路由）
    /admin/scenarios           情景 + 分档问法 CRUD
    /admin/wordlist            词表统计 / CSV 导入（学校分级词表）
    /admin/classrooms          课堂码列表 / 停用
"""

import csv
import io
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from sqlmodel import Field, SQLModel, col, select

from app.api.deps import SessionDep, SuperUserDep
from app.core.config import settings
from app.core.storage import content_audio_url, save_content_audio
from app.models import (
    Classroom,
    ClassroomPublic,
    Passage,
    PassageCreate,
    PassagePublic,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    ScenarioQuestionPublic,
    Unit,
    UnitCreate,
    UnitPublic,
    UnitUpdate,
    WordlistEntry,
)

router = APIRouter(prefix="/admin", tags=["admin"])

VALID_BANDS = {"A2", "B1", "B2"}


# ── 篇目与复述句 ─────────────────────────────────────────────────────


class PassageWithSentences(PassagePublic):
    sentences: list[RepeatSentence] = []


@router.get("/passages", response_model=list[PassageWithSentences])
def list_passages(session: SessionDep, _admin: SuperUserDep) -> Any:
    passages = session.exec(select(Passage).order_by(col(Passage.created_at))).all()
    result = []
    for passage in passages:
        sentences = session.exec(
            select(RepeatSentence)
            .where(RepeatSentence.passage_id == passage.id)
            .order_by(col(RepeatSentence.order_index))
        ).all()
        item = PassageWithSentences.model_validate(passage)
        item.sentences = list(sentences)
        result.append(item)
    return result


@router.post("/passages", response_model=PassagePublic)
def create_passage(
    session: SessionDep, _admin: SuperUserDep, passage_in: PassageCreate
) -> Any:
    duplicate = session.exec(
        select(Passage).where(Passage.slug == passage_in.slug)
    ).first()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="slug 已存在")
    passage = Passage.model_validate(passage_in)
    session.add(passage)
    session.commit()
    session.refresh(passage)
    return passage


@router.put("/passages/{passage_id}", response_model=PassagePublic)
def update_passage(
    session: SessionDep,
    _admin: SuperUserDep,
    passage_id: uuid.UUID,
    passage_in: PassageCreate,
) -> Any:
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    update = passage_in.model_dump(exclude={"slug"}, exclude_unset=True)
    passage.sqlmodel_update(update)
    session.add(passage)
    session.commit()
    session.refresh(passage)
    return passage


@router.delete("/passages/{passage_id}")
def delete_passage(
    session: SessionDep, _admin: SuperUserDep, passage_id: uuid.UUID
) -> dict[str, str]:
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    session.delete(passage)  # 复述句/作答按外键级联
    session.commit()
    return {"message": "deleted"}


@router.post("/passages/{passage_id}/sentences", response_model=RepeatSentence)
def create_sentence(
    session: SessionDep,
    _admin: SuperUserDep,
    passage_id: uuid.UUID,
    sentence: RepeatSentence,
) -> Any:
    if session.get(Passage, passage_id) is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    sentence.passage_id = passage_id
    session.add(sentence)
    session.commit()
    session.refresh(sentence)
    return sentence


@router.put("/sentences/{sentence_id}", response_model=RepeatSentence)
def update_sentence(
    session: SessionDep,
    _admin: SuperUserDep,
    sentence_id: uuid.UUID,
    sentence_in: RepeatSentence,
) -> Any:
    sentence = session.get(RepeatSentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="Sentence not found")
    update = sentence_in.model_dump(exclude={"id", "passage_id"}, exclude_unset=True)
    sentence.sqlmodel_update(update)
    session.add(sentence)
    session.commit()
    session.refresh(sentence)
    return sentence


@router.delete("/sentences/{sentence_id}")
def delete_sentence(
    session: SessionDep, _admin: SuperUserDep, sentence_id: uuid.UUID
) -> dict[str, str]:
    sentence = session.get(RepeatSentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="Sentence not found")
    session.delete(sentence)
    session.commit()
    return {"message": "deleted"}


# ── 情景与问法 ───────────────────────────────────────────────────────


class ScenarioOut(SQLModel):
    """list_scenarios 的响应形状：情景 + 其问法列表。"""

    id: uuid.UUID
    topic: str
    is_active: bool
    questions: list[ScenarioQuestionPublic]


@router.get("/scenarios", response_model=list[ScenarioOut])
def list_scenarios(session: SessionDep, _admin: SuperUserDep) -> Any:
    scenarios = session.exec(select(Scenario)).all()
    result = []
    for scenario in scenarios:
        questions = session.exec(
            select(ScenarioQuestion)
            .where(ScenarioQuestion.scenario_id == scenario.id)
            .order_by(col(ScenarioQuestion.order_index))
        ).all()
        result.append(
            ScenarioOut(
                id=scenario.id,
                topic=scenario.topic,
                is_active=scenario.is_active,
                questions=[ScenarioQuestionPublic.model_validate(q) for q in questions],
            )
        )
    return result


@router.post("/scenarios")
def create_scenario(
    session: SessionDep, _admin: SuperUserDep, scenario: Scenario
) -> Any:
    duplicate = session.exec(
        select(Scenario).where(Scenario.topic == scenario.topic)
    ).first()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="主题已存在")
    session.add(scenario)
    session.commit()
    session.refresh(scenario)
    return scenario


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(
    session: SessionDep, _admin: SuperUserDep, scenario_id: uuid.UUID
) -> dict[str, str]:
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    session.delete(scenario)
    session.commit()
    return {"message": "deleted"}


@router.post(
    "/scenarios/{scenario_id}/questions", response_model=ScenarioQuestionPublic
)
def create_question(
    session: SessionDep,
    _admin: SuperUserDep,
    scenario_id: uuid.UUID,
    question_in: ScenarioQuestion,
) -> Any:
    if session.get(Scenario, scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if question_in.band not in VALID_BANDS:
        raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
    question_in.scenario_id = scenario_id
    session.add(question_in)
    session.commit()
    session.refresh(question_in)
    return question_in


@router.delete("/questions/{question_id}")
def delete_question(
    session: SessionDep, _admin: SuperUserDep, question_id: uuid.UUID
) -> dict[str, str]:
    question = session.get(ScenarioQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    session.delete(question)
    session.commit()
    return {"message": "deleted"}


# ── 词表 ─────────────────────────────────────────────────────────────


class WordlistStats(SQLModel):
    total: int
    by_band: dict[str, int]
    name: str | None = None


@router.get("/wordlist", response_model=WordlistStats)
def wordlist_stats(session: SessionDep, _admin: SuperUserDep) -> Any:
    entries = session.exec(select(WordlistEntry)).all()
    by_band: dict[str, int] = dict.fromkeys(sorted(VALID_BANDS), 0)
    for entry in entries:
        by_band[entry.band] = by_band.get(entry.band, 0) + 1
    return {
        "total": len(entries),
        "by_band": by_band,
        "name": "内置演示词表（待学校分级词表 CSV 替换）" if entries else None,
    }


class WordlistImportResult(SQLModel):
    imported: int
    invalid_rows: list[int] = []


@router.post("/wordlist/import", response_model=WordlistImportResult)
async def import_wordlist_csv(
    session: SessionDep,
    _admin: SuperUserDep,
    file: UploadFile,
) -> Any:
    """导入学校分级词表 CSV（表头 lemma,band；整体替换内置词表）。"""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")  # 兼容 Excel 导出的 BOM
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV 必须是 UTF-8 编码") from exc

    reader = csv.DictReader(io.StringIO(text))
    if (
        not reader.fieldnames
        or "lemma" not in reader.fieldnames
        or "band" not in reader.fieldnames
    ):
        raise HTTPException(
            status_code=422, detail="CSV 需要表头：lemma,band（第一行）"
        )

    seen: set[str] = set()
    staged: list[WordlistEntry] = []
    invalid_rows: list[int] = []
    for lineno, row in enumerate(reader, start=2):
        lemma = (row.get("lemma") or "").strip().lower()
        band = (row.get("band") or "").strip().upper()
        if not lemma or band not in VALID_BANDS:
            invalid_rows.append(lineno)
            continue
        if lemma in seen:
            continue
        seen.add(lemma)
        staged.append(WordlistEntry(lemma=lemma, band=band))

    if not staged:
        raise HTTPException(
            status_code=422,
            detail=f"没有有效行（示例：friendly,B1）。无效行号：{invalid_rows[:10]}",
        )

    # 整体替换（学校词表是权威来源）。先删后插、分两次提交：
    # 同一 flush 内 SQLAlchemy 先执行 INSERT 后 DELETE，会撞 lemma 唯一索引
    for entry in session.exec(select(WordlistEntry)).all():
        session.delete(entry)
    session.commit()
    for entry in staged:
        session.add(entry)
    session.commit()

    return WordlistImportResult(imported=len(staged), invalid_rows=invalid_rows[:20])


# ── 学习单元（关卡）─────────────────────────────────────────────────


@router.get("/units", response_model=list[UnitPublic])
def list_units(session: SessionDep, _admin: SuperUserDep) -> Any:
    return session.exec(select(Unit).order_by(col(Unit.order_index))).all()


@router.post("/units", response_model=UnitPublic)
def create_unit(session: SessionDep, _admin: SuperUserDep, unit_in: UnitCreate) -> Any:
    unit = Unit.model_validate(unit_in)
    session.add(unit)
    session.commit()
    session.refresh(unit)
    return unit


@router.put("/units/{unit_id}", response_model=UnitPublic)
def update_unit(
    session: SessionDep,
    _admin: SuperUserDep,
    unit_id: uuid.UUID,
    unit_in: UnitUpdate,
) -> Any:
    unit = session.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found")
    unit.sqlmodel_update(unit_in.model_dump(exclude_unset=True))
    session.add(unit)
    session.commit()
    session.refresh(unit)
    return unit


@router.delete("/units/{unit_id}")
def delete_unit(
    session: SessionDep, _admin: SuperUserDep, unit_id: uuid.UUID
) -> dict[str, str]:
    unit = session.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found")
    session.delete(unit)  # 篇目 unit_id 置空（SET NULL）
    session.commit()
    return {"message": "deleted"}


class ClassroomUpdate(SQLModel):
    unlock_all: bool | None = None


# ── 课堂码 ───────────────────────────────────────────────────────────


@router.get("/classrooms", response_model=list[ClassroomPublic])
def list_classrooms(session: SessionDep, _admin: SuperUserDep) -> Any:
    return session.exec(select(Classroom).order_by(col(Classroom.created_at))).all()


@router.delete("/classrooms/{classroom_id}")
def deactivate_classroom(
    session: SessionDep, _admin: SuperUserDep, classroom_id: uuid.UUID
) -> dict[str, str]:
    classroom = session.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="Classroom not found")
    classroom.is_active = False
    session.add(classroom)
    session.commit()
    return {"message": "deactivated"}


@router.put("/classrooms/{classroom_id}", response_model=ClassroomPublic)
def update_classroom(
    session: SessionDep,
    _admin: SuperUserDep,
    classroom_id: uuid.UUID,
    classroom_in: ClassroomUpdate,
) -> Any:
    """更新课堂设置（当前仅 unlock_all：一键解锁全部关卡）。"""
    classroom = session.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="Classroom not found")
    classroom.sqlmodel_update(classroom_in.model_dump(exclude_unset=True))
    session.add(classroom)
    session.commit()
    session.refresh(classroom)
    return classroom


# ── 情景编辑与 AI 出题 ────────────────────────────────────────────────


class ScenarioUpdate(SQLModel):
    topic: str | None = None
    is_active: bool | None = None


@router.put("/scenarios/{scenario_id}")
def update_scenario(
    session: SessionDep,
    _admin: SuperUserDep,
    scenario_id: uuid.UUID,
    scenario_in: ScenarioUpdate,
) -> Any:
    """编辑情景（改名/启停）。"""
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    update = scenario_in.model_dump(exclude_unset=True)
    if "topic" in update:
        duplicate = session.exec(
            select(Scenario).where(Scenario.topic == update["topic"])
        ).first()
        if duplicate is not None and duplicate.id != scenario_id:
            raise HTTPException(status_code=409, detail="主题已存在")
    scenario.sqlmodel_update(update)
    session.add(scenario)
    session.commit()
    session.refresh(scenario)
    return scenario


class GenerateRequest(SQLModel):
    band: str
    count: int = Field(default=3, ge=1, le=10)
    hint: str | None = None


class DraftQuestionOut(SQLModel):
    text: str
    suggested_seconds: int


@router.post(
    "/scenarios/{scenario_id}/questions/generate", response_model=list[DraftQuestionOut]
)
def generate_questions(
    session: SessionDep,
    _admin: SuperUserDep,
    scenario_id: uuid.UUID,
    body: GenerateRequest,
) -> Any:
    """AI 按主题/档位起草问法（不入库，老师审改后走创建接口）。

    PRD 红线：模型只起草，不直接服务学生。
    """
    from app.scoring.question_gen import generate_draft_questions

    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if body.band not in VALID_BANDS:
        raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
    try:
        drafts = generate_draft_questions(
            topic=scenario.topic, band=body.band, count=body.count, hint=body.hint
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 无密钥/调用失败 → 503
        raise HTTPException(status_code=503, detail=f"AI 生成暂不可用：{exc}") from exc
    return [
        DraftQuestionOut(text=d.text, suggested_seconds=d.suggested_seconds)
        for d in drafts
    ]


class AutoSplitResult(SQLModel):
    created: int


@router.post(
    "/passages/{passage_id}/sentences/auto-split", response_model=AutoSplitResult
)
def auto_split_sentences(
    session: SessionDep,
    _admin: SuperUserDep,
    passage_id: uuid.UUID,
    target_count: int = 3,
) -> Any:
    """从篇目正文自动拆分复述句（本地算法非 AI）：按句切、由短到长取 3 句。

    幂等：已有人工维护的句子时拒绝（避免覆盖老师内容）。
    """
    import re as _re

    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    existing = session.exec(
        select(RepeatSentence).where(RepeatSentence.passage_id == passage_id)
    ).all()
    if existing:
        raise HTTPException(status_code=409, detail="已有复述句，请先清空再自动拆分")

    sentences = [s.strip() for s in _re.split(r"[.!?]+\s*", passage.text) if s.strip()]
    if len(sentences) < target_count:
        raise HTTPException(
            status_code=422, detail=f"正文句子不足 {target_count} 句，无法拆分"
        )
    # 由短到长取 target_count 句，再按原文顺序输出（保持叙述顺序）
    picked = sorted(range(len(sentences)), key=lambda i: len(sentences[i].split()))[
        :target_count
    ]
    picked.sort()

    created = []
    for order, idx in enumerate(picked):
        text = sentences[idx]
        words = len(text.split())
        seconds = max(4, min(30, round(words / 2.5) + 2))
        sentence = RepeatSentence(
            passage_id=passage_id,
            order_index=order,
            text=text,
            suggested_seconds=seconds,
        )
        session.add(sentence)
        created.append(sentence)
    session.commit()
    for sentence_ in created:
        session.refresh(sentence_)
    return AutoSplitResult(created=len(created))


# ── 内容标准音 ───────────────────────────────────────────────────────


class TtsRequest(SQLModel):
    text: str
    voice: str | None = None


class AudioUrlResult(SQLModel):
    audio_url: str


@router.post("/audio/tts", response_model=AudioUrlResult)
def generate_standard_audio(_admin: SuperUserDep, body: TtsRequest) -> Any:
    """用语音合成生成标准音并落盘，返回可回放的相对 URL。"""
    from app.scoring.tts import TtsError, build_tts_provider

    try:
        audio = build_tts_provider().synthesize(body.text)
    except TtsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    path = save_content_audio(audio, ".mp3")
    return AudioUrlResult(audio_url=content_audio_url(path.name))


class QuestionUpdate(SQLModel):
    band: str | None = None
    text: str | None = None
    audio_url: str | None = None
    suggested_seconds: int | None = None
    order_index: int | None = None


@router.put("/questions/{question_id}", response_model=ScenarioQuestionPublic)
def update_question(
    session: SessionDep,
    _admin: SuperUserDep,
    question_id: uuid.UUID,
    question_in: QuestionUpdate,
) -> Any:
    question = session.get(ScenarioQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    update = question_in.model_dump(exclude_unset=True)
    if "band" in update and update["band"] not in VALID_BANDS:
        raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
    question.sqlmodel_update(update)
    session.add(question)
    session.commit()
    session.refresh(question)
    return question


@router.post("/audio/upload", response_model=AudioUrlResult)
async def upload_standard_audio(_admin: SuperUserDep, file: UploadFile) -> Any:
    """上传现成音频（学校已有的录音/外教音频），作为标准音使用。"""
    from pathlib import PurePosixPath

    suffix = PurePosixPath(file.filename or "").suffix.lower()
    if suffix not in {".mp3", ".wav", ".m4a", ".ogg", ".webm"}:
        raise HTTPException(status_code=422, detail="仅支持 mp3/wav/m4a/ogg/webm")
    data = await file.read()
    if len(data) > settings.MAX_AUDIO_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"音频超过 {settings.MAX_AUDIO_MB}MB 上限"
        )
    if not data:
        raise HTTPException(status_code=422, detail="音频为空")
    path = save_content_audio(data, suffix)
    return AudioUrlResult(audio_url=content_audio_url(path.name))
