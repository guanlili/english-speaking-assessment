"""题库批量导入导出：模板/预览/确认/导出全链测试。

覆盖（本期验收口径）：
- 模板下载（xlsx 分工作表可被自家解析器读回、CSV 题型列）；
- 预览行号定位：错误定位到 工作表+行号+原因，原因复用建题校验口径；
- 重复两级：库内/批内完全重复默认跳过；疑似重复确认开关控制是否导入；
- 兜底：问答题主题自动新建 Scenario、单元降级、挂靠篇目三分支；
- 确认导入单事务：注入提交失败整体回滚；
- 导出→导入往返：题干/题型/级别/秒数/话题卡/准备时间等关键配置不丢；
- 权限：学生 403、未登录 401。
"""

import csv
import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.models import (
    Instruction,
    Passage,
    QuestionBankImportPreview,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    Unit,
    UserCreate,
)
from tests.utils.credential import anonymous, create_student_user, login_headers
from tests.utils.utils import random_email, random_lower_string

QB = "/api/v1/admin/question-bank"

# 基线：本模块首个用例前库内既有的内容行 ID（见 _isolate_content_tables）
_BASELINE_IDS: dict[str, set] | None = None

# CSV 并集列顺序（与模板一致）
CSV_FIELDS = [
    "标题", "单元", "主题", "难度", "内容", "中文提示", "挂靠篇目",
    "秒数", "可听次数", "考试题型", "考试级别", "话题卡要点", "准备秒数",
    "音频链接", "状态",
]
FIELD_TO_HEADER = {
    "title": "标题", "unit_title": "单元", "topic": "主题", "cefr_band": "难度",
    "text": "内容", "translation": "中文提示", "passage_title": "挂靠篇目",
    "suggested_seconds": "秒数", "replay_limit": "可听次数", "exam_kind": "考试题型",
    "exam_level": "考试级别", "cue_card_bullets": "话题卡要点",
    "prep_seconds": "准备秒数", "audio_url": "音频链接", "is_active": "状态",
}


BASELINE_TABLES = (ScenarioQuestion, RepeatSentence, Instruction, Passage, Scenario, Unit)


@pytest.fixture(autouse=True)
def _isolate_content_tables(db: Session):
    """只清本模块新增的题库行（基线保护式清理）。

    db 是 session 级共享库：其他模块（如 recovery 的 DEMO01 课堂）依赖
    早前种下的内容，绝不能整表清空（共享库污染规约）。首个用例前记下
    既有行 ID，每个用例后只删本模块新增的行。
    """
    global _BASELINE_IDS
    if _BASELINE_IDS is None:
        _BASELINE_IDS = {
            model.__name__: set(db.exec(select(model.id)).all())  # type: ignore[attr-defined]
            for model in BASELINE_TABLES
        }

    yield

    for model in BASELINE_TABLES:
        baseline = _BASELINE_IDS[model.__name__]
        for row in db.exec(select(model)).all():
            if row.id not in baseline:
                db.delete(row)
    db.commit()


def _new_rows(db: Session, model: type) -> list:
    """查询结果里只留本模块新增的行（排除 init_db 种子与既有内容）。"""
    assert _BASELINE_IDS is not None
    baseline = _BASELINE_IDS[model.__name__]
    return [row for row in db.exec(select(model)).all() if row.id not in baseline]  # type: ignore[attr-defined]


def _one_new(db: Session, model: type):
    rows = _new_rows(db, model)
    assert len(rows) == 1, f"expected exactly 1 new {model.__name__}, got {len(rows)}"
    return rows[0]


def _login_teacher(db: Session, client: TestClient) -> dict[str, str]:
    email, password = random_email(), random_lower_string()
    crud.create_user(session=db, user_create=UserCreate(email=email, password=password))
    resp = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _csv_file(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["题型", *CSV_FIELDS])
    for row in rows:
        qtype = row.get("__type__", "")
        writer.writerow([qtype, *[str(row.get(f, "")) for f in FIELD_TO_HEADER]])
    return buffer.getvalue().encode("utf-8")


def _xlsx_bytes(sheets: dict[str, list[list[Any]]]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _upload(
    client: TestClient,
    headers: dict[str, str],
    data: bytes,
    *,
    confirm: bool = False,
    include_suspected: bool = False,
    filename: str = "bank.csv",
    media_type: str = "text/csv",
):
    files = {"file": (filename, data, media_type)}
    if confirm:
        return client.post(
            f"{QB}/import-confirm",
            files=files,
            data={"include_suspected": "true" if include_suspected else "false"},
            headers=headers,
        )
    return client.post(f"{QB}/import-preview", files=files, headers=headers)


def _preview(client: TestClient, headers: dict[str, str], data: bytes, **kwargs: Any) -> dict:
    resp = _upload(client, headers, data, **kwargs)
    assert resp.status_code == 200, resp.text
    return resp.json()


PASSAGE_ROW = {
    "__type__": "文章朗读",
    "title": "Morning Routine",
    "unit_title": "",
    "topic": "Daily Life",
    "cefr_band": "B1",
    "text": "I usually wake up at six o'clock and walk to school.",
    "translation": "我通常六点起床走路去上学。",
    "suggested_seconds": "45",
    "is_active": "启用",
}
QUESTION_ROW = {
    "__type__": "情景问答",
    "topic": "Travel",
    "text": "Do you prefer travelling alone or with friends?",
    "translation": "你喜欢独自旅行还是和朋友一起？",
    "suggested_seconds": "20",
}


# ── 模板下载 ─────────────────────────────────────────────────────────


def test_template_download(client: TestClient, db: Session) -> None:
    headers = _login_teacher(db, client)
    resp = client.get(f"{QB}/import-template?format=xlsx", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.content[:2] == b"PK"
    assert "question-bank-import-template.xlsx" in resp.headers["content-disposition"]
    assert "spreadsheetml" in resp.headers["content-type"]
    # 模板能被自家解析器读回：示例行落在正确的工作表
    from app.services import question_bank_io as svc

    parsed = svc.parse_upload("t.xlsx", resp.content)
    assert {(r.qtype) for r in parsed.rows} == {"passage", "repeat", "question", "instruction"}

    resp = client.get(f"{QB}/import-template?format=csv", headers=headers)
    assert resp.status_code == 200, resp.text
    text = resp.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("题型,标题,单元,主题,难度,内容")


# ── 预览：计数 / 行号 / 原因 ────────────────────────────────────────


def test_preview_csv_counts_and_line_numbers(client: TestClient, db: Session) -> None:
    headers = _login_teacher(db, client)
    data = _csv_file(
        [
            PASSAGE_ROW,
            {**QUESTION_ROW, "text": "Question A"},
            # 行 4：题目为空
            {"__type__": "情景问答", "topic": "Travel", "text": ""},
            # 行 5：普通题秒数越界（>60）
            {**QUESTION_ROW, "text": "Question B", "suggested_seconds": "61"},
            # 行 6：难度无效
            {"__type__": "文章朗读", "title": "X", "cefr_band": "C1", "text": "hello"},
            # 行 7：题型列无效
            {"__type__": "阅读理解", "text": "zzz"},
        ]
    )
    body = _preview(client, headers, data)
    counts = {s["type"]: s for s in body["sheets"]}
    assert counts["passage"]["valid_count"] == 1
    assert counts["question"]["valid_count"] == 1
    issues = {(i["type"], i["line"]): i["reason"] for i in body["issues"]}
    assert issues[("question", 4)] == "题目不能为空"
    assert issues[("question", 5)] == "建议秒数需在 10–60 之间（考试题型支持长回答）"
    assert issues[("passage", 6)] == "难度无效，可选：A2/B1/B2"
    invalid_type = [i for i in body["issues"] if i["type"] == "-"]
    assert invalid_type[0]["line"] == 7
    assert invalid_type[0]["reason"].startswith("题型列的值无效")
    assert body["total_valid"] == 2


def test_preview_exam_field_validation_reuse(client: TestClient, db: Session) -> None:
    """考试字段校验复用建题口径：有题型必配级别、话题卡仅 Part2、准备时间区间。"""
    headers = _login_teacher(db, client)
    data = _csv_file(
        [
            {**QUESTION_ROW, "text": "Q1", "exam_kind": "interview"},  # 缺级别
            {**QUESTION_ROW, "text": "Q2", "exam_kind": "ielts_p1", "exam_level": "PET",
             "cue_card_bullets": "what\nwhen"},  # 话题卡仅 p2
            {**QUESTION_ROW, "text": "Q3", "exam_kind": "ielts_p2", "exam_level": "PET",
             "prep_seconds": "200"},  # 准备时间越界
            {"__type__": "听句复述", "text": "Repeat me.", "exam_kind": "ielts_p2",
             "exam_level": "PET"},  # 复述句不支持 ielts_p2
            {**QUESTION_ROW, "text": "Q4", "exam_level": "PET"},  # 无题型不能配级别
        ]
    )
    body = _preview(client, headers, data)
    reasons = {i["reason"] for i in body["issues"]}
    assert "选择考试题型时需同时标注级别" in reasons
    assert "话题卡要点仅支持 IELTS Part 2 题型" in reasons
    assert "准备时间须在 10–180 秒之间" in reasons
    assert "考试题型无效：听句复述仅支持 toefl_lnr" in reasons
    assert "未选择考试题型时不能单独设置级别/话题卡/准备时间" in reasons
    assert body["total_valid"] == 0


def test_preview_xlsx_sheets(client: TestClient, db: Session) -> None:
    headers = _login_teacher(db, client)
    data = _xlsx_bytes(
        {
            "文章朗读": [
                ["标题", "单元", "主题", "难度", "正文", "中文提示", "建议秒数", "音频链接", "状态"],
                ["A Trip", "", "Travel", "B1", "We went to the sea.", "", "45", "", ""],
            ],
            "情景问答": [
                ["主题", "英文题目", "中文提示", "作答秒数", "考试题型", "考试级别",
                 "话题卡要点", "准备秒数", "音频链接"],
                ["Travel", "Where did you go?", "", "20", "", "", "", "", ""],
            ],
        }
    )
    body = _preview(client, headers, data, filename="b.xlsx")
    counts = {s["type"]: s for s in body["sheets"]}
    assert counts["passage"]["valid_count"] == 1
    assert counts["question"]["valid_count"] == 1

    unknown = _xlsx_bytes({"随便": [["标题", "正文"], ["a", "b"]]})
    resp = _upload(client, headers, unknown, filename="b.xlsx")
    assert resp.status_code == 422
    assert "无法识别题型" in resp.json()["detail"]

    missing = _xlsx_bytes({"文章朗读": [["标题", "难度"], ["Only title", "B1"]]})
    resp = _upload(client, headers, missing, filename="b.xlsx")
    assert resp.status_code == 422
    assert "缺少必填列：正文" in resp.json()["detail"]


def test_preview_csv_file_level_errors(client: TestClient, db: Session) -> None:
    headers = _login_teacher(db, client)
    no_type_col = "标题,内容\nT,hello".encode("utf-8")
    resp = _upload(client, headers, no_type_col)
    assert resp.status_code == 422
    assert "CSV 缺少题型列" in resp.json()["detail"]

    # 行数上限
    rows = [{**QUESTION_ROW, "text": f"Q{i}"} for i in range(2001)]
    resp = _upload(client, headers, _csv_file(rows))
    assert resp.status_code == 422
    assert "行数超过上限" in resp.json()["detail"]

    # GBK 编码兜底（Excel 中文环境「另存为 CSV」默认 GBK）
    gbk = _csv_file([{**QUESTION_ROW, "text": "Encoding check?"}]).decode("utf-8").encode("gb18030")
    body = _preview(client, headers, gbk)
    assert body["total_valid"] == 1


def test_audio_url_validation(client: TestClient, db: Session) -> None:
    headers = _login_teacher(db, client)
    data = _csv_file(
        [
            {**QUESTION_ROW, "text": "Q audio ok", "audio_url": "/api/v1/audio/content/a.mp3"},
            {**QUESTION_ROW, "text": "Q audio bad", "audio_url": "https://x.com/a.mp3"},
        ]
    )
    body = _preview(client, headers, data)
    reasons = [i["reason"] for i in body["issues"]]
    assert any(r.startswith("音频链接格式不正确") for r in reasons)
    assert body["total_valid"] == 1


# ── 确认导入：落库 / 兜底 / 事务 ────────────────────────────────────


def test_confirm_creates_all_types_and_auto_scenario(
    client: TestClient, db: Session
) -> None:
    headers = _login_teacher(db, client)
    data = _csv_file(
        [
            PASSAGE_ROW,
            {"__type__": "听句复述", "text": "The sea was calm.", "translation": "大海很平静。",
             "suggested_seconds": "8", "replay_limit": "5", "exam_kind": "toefl_lnr",
             "exam_level": "PET"},
            {**QUESTION_ROW, "text": "Describe your favourite place.", "suggested_seconds": "120",
             "exam_kind": "IELTS · Part 2", "exam_level": "四级",
             "cue_card_bullets": "where it is\nhow often you go", "prep_seconds": "60"},
            {"__type__": "题目说明", "title": "Part B", "text": "Now talk about the topic.",
             "suggested_seconds": "30"},
        ]
    )
    resp = _upload(client, headers, data, confirm=True)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sheets = {s["type"]: s for s in body["sheets"]}
    assert sheets["passage"]["created"] == 1
    assert sheets["repeat"]["created"] == 1
    assert sheets["question"]["created"] == 1
    assert sheets["instruction"]["created"] == 1
    assert body["created_topics"] == ["Travel"]

    question = _one_new(db, ScenarioQuestion)
    assert question.exam_kind == "ielts_p2"
    assert question.exam_level == "CET4"
    assert question.cue_card_bullets == ["where it is", "how often you go"]
    assert question.prep_seconds == 60
    assert question.suggested_seconds == 120
    assert question.scenario_id == _one_new(db, Scenario).id

    sentence = _one_new(db, RepeatSentence)
    assert sentence.replay_limit == 5
    assert sentence.exam_kind == "toefl_lnr"
    assert sentence.exam_level == "PET"

    passage = _one_new(db, Passage)
    assert passage.topic == "Daily Life"
    assert passage.slug  # 自动生成
    instruction = _one_new(db, Instruction)
    assert instruction.title == "Part B"

    # 缺音频提示（信息性）
    assert sheets["passage"]["missing_audio_count"] == 1
    assert body["missing_audio_total"] >= 3


def test_confirm_fallbacks_unit_and_passage_linkage(
    client: TestClient, db: Session
) -> None:
    headers = _login_teacher(db, client)
    data = _csv_file(
        [
            # 单元不存在 → 降级无单元
            {**PASSAGE_ROW, "unit_title": "不存在的单元"},
            # 挂靠本次导入的篇目 → 挂靠成功
            {"__type__": "听句复述", "text": "Attached to new passage.", "passage_title": "Morning Routine"},
            # 挂靠不存在的篇目 → 独立句
            {"__type__": "听句复述", "text": "No such passage.", "passage_title": "Ghost"},
        ]
    )
    body = _preview(client, headers, data)
    assert body["unit_fallback_count"] == 1
    assert body["standalone_sentence_count"] == 1

    resp = _upload(client, headers, data, confirm=True)
    assert resp.status_code == 200, resp.text
    passage = _one_new(db, Passage)
    assert passage.unit_id is None
    attached, standalone = _new_rows(db, RepeatSentence)
    assert attached.passage_id == passage.id
    assert standalone.passage_id is None

    # 再建一个同名篇目后，挂靠同名篇目 → 歧义报错
    resp = client.post(
        "/api/v1/admin/passages",
        json={"title": "Morning Routine", "text": "duplicate title body"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    again = _csv_file([{"__type__": "听句复述", "text": "Ambiguous link.", "passage_title": "Morning Routine"}])
    body = _preview(client, headers, again)
    assert any("挂靠篇目匹配到多个同名篇目" in i["reason"] for i in body["issues"])


def test_confirm_unit_match_attaches_existing(client: TestClient, db: Session) -> None:
    headers = _login_teacher(db, client)
    unit = Unit(title="Unit 1", topic="School Life")
    db.add(unit)
    db.commit()
    db.refresh(unit)
    data = _csv_file([{**PASSAGE_ROW, "unit_title": "unit 1"}])  # 大小写不敏感匹配
    resp = _upload(client, headers, data, confirm=True)
    assert resp.status_code == 200, resp.text
    passage = _one_new(db, Passage)
    assert passage.unit_id == unit.id
    assert passage.topic == "School Life"  # topic 派生自单元


def test_confirm_rollback_on_failure(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import question_bank_io as svc

    headers = _login_teacher(db, client)
    before_counts = (
        len(_new_rows(db, Passage)),
        len(_new_rows(db, Scenario)),
    )

    def _boom(session: Session) -> None:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(svc, "_commit", _boom)
    resp = _upload(client, headers, _csv_file([QUESTION_ROW]), confirm=True)
    assert resp.status_code == 500
    assert len(_new_rows(db, Passage)) == before_counts[0]
    assert len(_new_rows(db, Scenario)) == before_counts[1]
    assert _new_rows(db, ScenarioQuestion) == []


# ── 重复处理 ─────────────────────────────────────────────────────────


def test_duplicate_tiers_and_reupload_safety(client: TestClient, db: Session) -> None:
    headers = _login_teacher(db, client)
    file1 = _csv_file([{**QUESTION_ROW, "text": "Same question."}])
    resp = _upload(client, headers, file1, confirm=True)
    assert resp.json()["sheets"][0]["created"] == 1

    # 重传同一文件：预览全判重，确认不产生新题
    body = _preview(client, headers, file1)
    assert body["total_valid"] == 0
    counts = body["sheets"][0]
    assert counts["exact_duplicate_count"] == 1
    assert counts["valid_count"] == 0
    resp = _upload(client, headers, file1, confirm=True)
    assert resp.json()["sheets"][0]["created"] == 0
    assert len(_new_rows(db, ScenarioQuestion)) == 1

    # 同题干不同配置 → 疑似重复：默认排除，勾选后导入
    file2 = _csv_file([{**QUESTION_ROW, "text": "Same question.", "suggested_seconds": "30"}])
    body = _preview(client, headers, file2)
    assert body["sheets"][0]["suspected_duplicate_count"] == 1
    assert body["suspected"][0]["line"] == 2
    resp = _upload(client, headers, file2, confirm=True)
    assert resp.json()["sheets"][0]["skipped_suspected"] == 1
    assert len(_new_rows(db, ScenarioQuestion)) == 1
    resp = _upload(client, headers, file2, confirm=True, include_suspected=True)
    assert resp.json()["sheets"][0]["created"] == 1
    assert len(_new_rows(db, ScenarioQuestion)) == 2

    # 批内重复：同文件两行一样 → 1 valid + 1 exact dup
    file3 = _csv_file([{**QUESTION_ROW, "text": "In-file dup."}, {**QUESTION_ROW, "text": "In-file dup."}])
    body = _preview(client, headers, file3)
    counts = body["sheets"][0]
    assert counts["valid_count"] == 1
    assert counts["exact_duplicate_count"] == 1

    # 跨主题同题干 → 疑似重复（其他主题已存在）
    file4 = _csv_file([{**QUESTION_ROW, "text": "Same question.", "topic": "Music"}])
    body = _preview(client, headers, file4)
    assert body["sheets"][0]["suspected_duplicate_count"] == 1
    assert "其他主题" in body["suspected"][0]["reason"]


# ── 导出 → 导入往返 ──────────────────────────────────────────────────


def test_export_reimport_roundtrip(client: TestClient, db: Session) -> None:
    headers = _login_teacher(db, client)
    data = _csv_file(
        [
            PASSAGE_ROW,
            {"__type__": "听句复述", "text": "The sea was calm.", "suggested_seconds": "10",
             "replay_limit": "4", "exam_kind": "toefl_lnr", "exam_level": "KET"},
            {**QUESTION_ROW, "text": "Describe your favourite place.",
             "suggested_seconds": "120", "exam_kind": "ielts_p2", "exam_level": "PET",
             "cue_card_bullets": "where it is\nhow often you go", "prep_seconds": "60"},
            {"__type__": "题目说明", "title": "Part B", "text": "Now talk about the topic.",
             "suggested_seconds": "30"},
        ]
    )
    resp = _upload(client, headers, data, confirm=True)
    assert resp.status_code == 200, resp.text

    resp = client.get(f"{QB}/export", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.content[:2] == b"PK"
    assert "question-bank-export-" in resp.headers["content-disposition"]

    # 导出再预览：全部判为完全重复、无错误、无疑似——关键配置无丢失
    body = _preview(client, headers, resp.content, filename="export.xlsx")
    assert QuestionBankImportPreview(**body)  # schema 形状校验
    assert body["total_valid"] == 0
    assert body["issues"] == []
    assert body["suspected"] == []
    counts = {s["type"]: s for s in body["sheets"]}
    for qtype in ("passage", "repeat", "question", "instruction"):
        # 库里可能还有 init_db 种子内容一并被导出：只要求全部判完全重复
        assert counts[qtype]["exact_duplicate_count"] >= 1, counts
        assert counts[qtype]["valid_count"] == 0
        assert counts[qtype]["suspected_duplicate_count"] == 0


def test_export_csv_with_filters(client: TestClient, db: Session) -> None:
    headers = _login_teacher(db, client)
    data = _csv_file(
        [
            {**QUESTION_ROW, "text": "Travelling question.", "topic": "Travel"},
            {**QUESTION_ROW, "text": "Music question.", "topic": "Music"},
        ]
    )
    resp = _upload(client, headers, data, confirm=True)
    assert resp.status_code == 200, resp.text

    resp = client.get(f"{QB}/export?format=csv&types=question&topic=Travel", headers=headers)
    assert resp.status_code == 200, resp.text
    text = resp.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("题型,标题,单元,主题,难度,内容")
    assert "Travelling question." in text
    assert "Music question." not in text

    resp = client.get(f"{QB}/export?band=C1", headers=headers)
    assert resp.status_code == 422
    assert "难度无效" in resp.json()["detail"]


# ── 权限 ─────────────────────────────────────────────────────────────


def test_permissions_student_403_and_anonymous_401(
    client: TestClient, db: Session
) -> None:
    student = create_student_user(db)
    student_headers = login_headers(client, student.username)
    resp = client.get(f"{QB}/import-template", headers=student_headers)
    assert resp.status_code == 403
    with anonymous(client):
        resp = client.get(f"{QB}/import-template")
        assert resp.status_code == 401
