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
    "标题",
    "单元",
    "主题",
    "难度",
    "内容",
    "中文提示",
    "挂靠篇目",
    "秒数",
    "可听次数",
    "考试题型",
    "考试级别",
    "话题卡要点",
    "准备秒数",
    "音频链接",
    "状态",
]
FIELD_TO_HEADER = {
    "title": "标题",
    "unit_title": "单元",
    "topic": "主题",
    "cefr_band": "难度",
    "text": "内容",
    "translation": "中文提示",
    "passage_title": "挂靠篇目",
    "suggested_seconds": "秒数",
    "replay_limit": "可听次数",
    "exam_kind": "考试题型",
    "exam_level": "考试级别",
    "cue_card_bullets": "话题卡要点",
    "prep_seconds": "准备秒数",
    "audio_url": "音频链接",
    "is_active": "状态",
}


BASELINE_TABLES = (
    ScenarioQuestion,
    RepeatSentence,
    Instruction,
    Passage,
    Scenario,
    Unit,
)


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
    # getattr+noqa：直接 row.id 会被 ty 拦（object 无该属性），getattr 常量
    # 又被 ruff B009 拦——两者取 getattr + noqa 是唯一交集
    return [
        row
        for row in db.exec(select(model)).all()
        if getattr(row, "id") not in baseline  # noqa: B009
    ]


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


def _preview(
    client: TestClient, headers: dict[str, str], data: bytes, **kwargs: Any
) -> dict:
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
    assert {(r.qtype) for r in parsed.rows} == {
        "passage",
        "repeat",
        "question",
        "instruction",
    }

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
            {
                **QUESTION_ROW,
                "text": "Q2",
                "exam_kind": "ielts_p1",
                "exam_level": "PET",
                "cue_card_bullets": "what\nwhen",
            },  # 话题卡仅 p2
            {
                **QUESTION_ROW,
                "text": "Q3",
                "exam_kind": "ielts_p2",
                "exam_level": "PET",
                "prep_seconds": "200",
            },  # 准备时间越界
            {
                "__type__": "听句复述",
                "text": "Repeat me.",
                "exam_kind": "ielts_p2",
                "exam_level": "PET",
            },  # 复述句不支持 ielts_p2
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
                [
                    "标题",
                    "单元",
                    "主题",
                    "难度",
                    "正文",
                    "中文提示",
                    "建议秒数",
                    "音频链接",
                    "状态",
                ],
                ["A Trip", "", "Travel", "B1", "We went to the sea.", "", "45", "", ""],
            ],
            "情景问答": [
                [
                    "主题",
                    "英文题目",
                    "中文提示",
                    "作答秒数",
                    "考试题型",
                    "考试级别",
                    "话题卡要点",
                    "准备秒数",
                    "音频链接",
                ],
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
    no_type_col = "标题,内容\nT,hello".encode()
    resp = _upload(client, headers, no_type_col)
    assert resp.status_code == 422
    assert "CSV 缺少题型列" in resp.json()["detail"]

    # 行数上限
    rows = [{**QUESTION_ROW, "text": f"Q{i}"} for i in range(2001)]
    resp = _upload(client, headers, _csv_file(rows))
    assert resp.status_code == 422
    assert "行数超过上限" in resp.json()["detail"]

    # GBK 编码兜底（Excel 中文环境「另存为 CSV」默认 GBK）
    gbk = (
        _csv_file([{**QUESTION_ROW, "text": "Encoding check?"}])
        .decode("utf-8")
        .encode("gb18030")
    )
    body = _preview(client, headers, gbk)
    assert body["total_valid"] == 1


def test_audio_url_validation(client: TestClient, db: Session) -> None:
    headers = _login_teacher(db, client)
    data = _csv_file(
        [
            {
                **QUESTION_ROW,
                "text": "Q audio ok",
                "audio_url": "/api/v1/audio/content/a.mp3",
            },
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
            {
                "__type__": "听句复述",
                "text": "The sea was calm.",
                "translation": "大海很平静。",
                "suggested_seconds": "8",
                "replay_limit": "5",
                "exam_kind": "toefl_lnr",
                "exam_level": "PET",
            },
            {
                **QUESTION_ROW,
                "text": "Describe your favourite place.",
                "suggested_seconds": "120",
                "exam_kind": "IELTS · Part 2",
                "exam_level": "四级",
                "cue_card_bullets": "where it is\nhow often you go",
                "prep_seconds": "60",
            },
            {
                "__type__": "题目说明",
                "title": "Part B",
                "text": "Now talk about the topic.",
                "suggested_seconds": "30",
            },
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
            {
                "__type__": "听句复述",
                "text": "Attached to new passage.",
                "passage_title": "Morning Routine",
            },
            # 挂靠不存在的篇目 → 独立句
            {
                "__type__": "听句复述",
                "text": "No such passage.",
                "passage_title": "Ghost",
            },
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
    again = _csv_file(
        [
            {
                "__type__": "听句复述",
                "text": "Ambiguous link.",
                "passage_title": "Morning Routine",
            }
        ]
    )
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
    file2 = _csv_file(
        [{**QUESTION_ROW, "text": "Same question.", "suggested_seconds": "30"}]
    )
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
    file3 = _csv_file(
        [
            {**QUESTION_ROW, "text": "In-file dup."},
            {**QUESTION_ROW, "text": "In-file dup."},
        ]
    )
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


def _delete_new_rows(db: Session) -> None:
    """删除本模块新增的内容行（保留单元：回导还要按单元名匹配）。"""
    for model in (ScenarioQuestion, RepeatSentence, Passage, Instruction, Scenario):
        for row in _new_rows(db, model):
            db.delete(row)
    db.commit()


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_export_roundtrip_field_level(
    client: TestClient, db: Session, fmt: str
) -> None:
    """导出 → 删除本批数据 → 回导 → 逐字段比较（评审要求：不能用查重成功
    代替无损验证）。CSV 与 XLSX 双格式各跑一遍。"""
    headers = _login_teacher(db, client)
    db.add(Unit(title="RT Unit", topic="Roundtrip Topic"))
    db.commit()
    source = _csv_file(
        [
            {
                "__type__": "文章朗读",
                "title": "RT Passage",
                "unit_title": "RT Unit",
                "topic": "",  # 挂单元：落库 topic 派生为单元主题
                "cefr_band": "B2",
                "text": "Roundtrip passage body.",
                "translation": "往返篇目。",
                "suggested_seconds": "60",
                "audio_url": "/api/v1/audio/content/rt-p.mp3",
                "is_active": "停用",
            },
            {
                "__type__": "听句复述",
                "text": "RT sentence attached.",
                "translation": "挂靠句。",
                "passage_title": "RT Passage",
                "suggested_seconds": "12",
                "replay_limit": "4",
                "exam_kind": "toefl_lnr",
                "exam_level": "KET",
                "audio_url": "/api/v1/audio/content/rt-s.mp3",
            },
            {
                "__type__": "听句复述",
                "text": "RT sentence standalone.",
            },
            {
                **QUESTION_ROW,
                "topic": "Roundtrip QA",
                "text": "RT question?",
                "translation": "往返题目。",
                "suggested_seconds": "90",
                "exam_kind": "ielts_p2",
                "exam_level": "PET",
                # 要点含 ; 和 |：拆分只认换行才可逆（评审 P2）
                "cue_card_bullets": "where; why\nwho| what",
                "prep_seconds": "45",
                "audio_url": "/api/v1/audio/content/rt-q.mp3",
            },
            {
                "__type__": "题目说明",
                "title": "RT Part",
                "text": "RT instruction body.",
                "suggested_seconds": "40",
            },
        ]
    )
    resp = _upload(client, headers, source, confirm=True)
    assert resp.status_code == 200, resp.text

    # 先验「重上传导出文件全部判重」（含种子内容，无疑似/错误）
    export = client.get(f"{QB}/export?format={fmt}", headers=headers)
    assert export.status_code == 200, export.text
    body = _preview(
        client,
        headers,
        export.content,
        filename=f"export.{fmt}",
        media_type="text/csv"
        if fmt == "csv"
        else ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )
    assert body["total_valid"] == 0, body
    # 共享库里早前模块可能留下同名单元：其篇目回判「单元歧义」属预期报错，
    # 不算往损失真——真正的回归信号是「无疑似、零新建」；本批数据的无损
    # 由下一段（删除→回导→逐字段比较）强验证
    assert body["suspected"] == []

    # 删除本批数据后回导：所有行应重建，逐字段无损
    _delete_new_rows(db)
    resp = _upload(
        client,
        headers,
        export.content,
        confirm=True,
        filename=f"export.{fmt}",
        media_type="text/csv"
        if fmt == "csv"
        else ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )
    assert resp.status_code == 200, resp.text
    created = {s["type"]: s["created"] for s in resp.json()["sheets"]}
    assert created == {"passage": 1, "repeat": 2, "question": 1, "instruction": 1}, (
        resp.json()["sheets"]
    )

    passage = _one_new(db, Passage)
    assert passage.title == "RT Passage"
    assert passage.topic == "Roundtrip Topic"  # 单元派生主题回导不丢
    assert passage.cefr_band == "B2"
    assert passage.text == "Roundtrip passage body."
    assert passage.translation == "往返篇目。"
    assert passage.suggested_seconds == 60
    assert passage.audio_url == "/api/v1/audio/content/rt-p.mp3"
    assert passage.is_active is False
    unit = db.exec(select(Unit).where(Unit.title == "RT Unit")).one()
    assert passage.unit_id == unit.id

    attached = db.exec(
        select(RepeatSentence).where(RepeatSentence.text == "RT sentence attached.")
    ).one()
    standalone = db.exec(
        select(RepeatSentence).where(RepeatSentence.text == "RT sentence standalone.")
    ).one()
    assert attached.passage_id == passage.id  # 挂靠关系回导不丢
    assert attached.translation == "挂靠句。"
    assert attached.suggested_seconds == 12
    assert attached.replay_limit == 4
    assert attached.exam_kind == "toefl_lnr"
    assert attached.exam_level == "KET"
    assert attached.audio_url == "/api/v1/audio/content/rt-s.mp3"
    assert standalone.passage_id is None
    assert standalone.suggested_seconds == 8  # 缺省值
    assert standalone.replay_limit == 3

    question = db.exec(
        select(ScenarioQuestion).where(ScenarioQuestion.text == "RT question?")
    ).one()
    scenario = db.exec(select(Scenario).where(Scenario.topic == "Roundtrip QA")).one()
    assert question.scenario_id == scenario.id
    assert question.translation == "往返题目。"
    assert question.suggested_seconds == 90
    assert question.exam_kind == "ielts_p2"
    assert question.exam_level == "PET"
    assert question.cue_card_bullets == ["where; why", "who| what"]  # 结构不变
    assert question.prep_seconds == 45
    assert question.audio_url == "/api/v1/audio/content/rt-q.mp3"

    instruction = _one_new(db, Instruction)
    assert instruction.title == "RT Part"
    assert instruction.text == "RT instruction body."
    assert instruction.suggested_seconds == 40


def test_export_xlsx_rejects_overlong_text(client: TestClient, db: Session) -> None:
    """Excel 单元格 32767 上限：超长正文必须显式拒绝并指明 CSV 替代。"""
    headers = _login_teacher(db, client)
    resp = client.post(
        "/api/v1/admin/passages",
        json={"title": "Overlong", "text": "a" * 40000},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(f"{QB}/export?format=xlsx", headers=headers)
    assert resp.status_code == 422
    assert "32767" in resp.json()["detail"]
    assert "CSV" in resp.json()["detail"]
    # 字段名必须是真实列名而非误引用（曾打印 <function field ...>）
    assert "的text超过" in resp.json()["detail"]
    assert "<function" not in resp.json()["detail"]

    resp = client.get(f"{QB}/export?format=csv", headers=headers)
    assert resp.status_code == 200, resp.text


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

    resp = client.get(
        f"{QB}/export?format=csv&types=question&topic=Travel", headers=headers
    )
    assert resp.status_code == 200, resp.text
    text = resp.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("题型,标题,单元,主题,难度,内容")
    assert "Travelling question." in text
    assert "Music question." not in text

    resp = client.get(f"{QB}/export?band=C1", headers=headers)
    assert resp.status_code == 422
    assert "难度无效" in resp.json()["detail"]


def test_unit_passage_reupload_is_exact_duplicate(
    client: TestClient, db: Session
) -> None:
    """查重口径必须用落库后的最终值：挂单元（topic 派生）的篇目重传同文件
    应判完全重复，而不是疑似重复（评审 P2）。"""
    headers = _login_teacher(db, client)
    db.add(Unit(title="U1", topic="Derived Topic"))
    db.commit()
    file = _csv_file(
        [
            {
                "__type__": "文章朗读",
                "title": "Derived Passage",
                "unit_title": "U1",
                "topic": "",
                "text": "Topic follows the unit.",
            }
        ]
    )
    resp = _upload(client, headers, file, confirm=True)
    assert resp.json()["sheets"][0]["created"] == 1
    body = _preview(client, headers, file)
    counts = body["sheets"][0]
    assert counts["exact_duplicate_count"] == 1
    assert counts["suspected_duplicate_count"] == 0, body
    assert counts["valid_count"] == 0
    # 勾选「仍导入疑似重复」也不会新增（无疑似行）
    resp = _upload(client, headers, file, confirm=True, include_suspected=True)
    assert resp.json()["sheets"][0]["created"] == 0


def test_audio_difference_is_suspected(client: TestClient, db: Session) -> None:
    """音频属于题目配置：换音频的同题干应判疑似重复（可勾选导入），而不是
    完全重复被静默跳过（评审 P2）。"""
    headers = _login_teacher(db, client)
    first = _csv_file(
        [
            {
                **QUESTION_ROW,
                "text": "Audio differs.",
                "audio_url": "/api/v1/audio/content/a-one.mp3",
            }
        ]
    )
    resp = _upload(client, headers, first, confirm=True)
    assert resp.json()["sheets"][0]["created"] == 1

    second = _csv_file(
        [
            {
                **QUESTION_ROW,
                "text": "Audio differs.",
                "audio_url": "/api/v1/audio/content/a-two.mp3",
            }
        ]
    )
    body = _preview(client, headers, second)
    counts = body["sheets"][0]
    assert counts["suspected_duplicate_count"] == 1, body
    assert counts["exact_duplicate_count"] == 0
    resp = _upload(client, headers, second, confirm=True, include_suspected=True)
    assert resp.json()["sheets"][0]["created"] == 1
    rows = db.exec(
        select(ScenarioQuestion).where(ScenarioQuestion.text == "Audio differs.")
    ).all()
    assert sorted(r.audio_url or "" for r in rows) == [
        "/api/v1/audio/content/a-one.mp3",
        "/api/v1/audio/content/a-two.mp3",
    ]


def test_bullets_split_on_newline_only(client: TestClient, db: Session) -> None:
    """话题卡要点只按换行拆：含分号/竖线的要点保持原样（序列化可逆）。"""
    headers = _login_teacher(db, client)
    data = _csv_file(
        [
            {
                **QUESTION_ROW,
                "text": "Bullets keep separators.",
                "exam_kind": "ielts_p2",
                "exam_level": "PET",
                "cue_card_bullets": "where; why\nwho| what",
            }
        ]
    )
    resp = _upload(client, headers, data, confirm=True)
    assert resp.status_code == 200, resp.text
    question = db.exec(
        select(ScenarioQuestion).where(
            ScenarioQuestion.text == "Bullets keep separators."
        )
    ).one()
    assert question.cue_card_bullets == ["where; why", "who| what"]


def test_excel_resource_caps(client: TestClient, db: Session) -> None:
    """xlsx 解析资源上限在读遍历前判定：远端格式单元格撑大有效区、超列数、
    跨表累计数据行超限都要立即 422（评审 P1）。"""
    headers = _login_teacher(db, client)
    from openpyxl import Workbook

    passage_header = [
        "标题",
        "单元",
        "主题",
        "难度",
        "正文",
        "中文提示",
        "建议秒数",
        "音频链接",
        "状态",
    ]

    # ① 只有格式、只有一行数据的远端单元格（如 J2010 设过格式）→ 有效区超限
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet = workbook.create_sheet("文章朗读")
    sheet.append(passage_header)
    sheet.cell(row=2010, column=10, value="格式尾巴")
    buffer = io.BytesIO()
    workbook.save(buffer)
    resp = _upload(
        client,
        headers,
        buffer.getvalue(),
        filename="cap.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert resp.status_code == 422
    assert "有效区" in resp.json()["detail"]

    # ② 列数超限
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet = workbook.create_sheet("文章朗读")
    sheet.append(passage_header + [""] * 90)
    sheet.append(["Cap", "", "", "B1", "Too many columns.", "", "", "", ""])
    buffer = io.BytesIO()
    workbook.save(buffer)
    resp = _upload(
        client,
        headers,
        buffer.getvalue(),
        filename="cap.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert resp.status_code == 422
    assert "列" in resp.json()["detail"]

    # ③ 跨表累计数据行超限（单表都在行上限内：1100 + 1100）
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name in ("文章朗读", "情景问答"):
        sheet = workbook.create_sheet(name)
        sheet.append(passage_header if name == "文章朗读" else ["主题", "英文题目"])
        for i in range(1100):
            if name == "文章朗读":
                sheet.append(
                    [f"Cap {i}", "", "", "B1", "Row cap body.", "", "", "", ""]
                )
            else:
                sheet.append(["Cap", f"Row cap question {i}?"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    resp = _upload(
        client,
        headers,
        buffer.getvalue(),
        filename="cap.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert resp.status_code == 422
    assert "行数超过上限" in resp.json()["detail"]


# ── 第二轮评审回归 ───────────────────────────────────────────────────


def test_csv_guard_roundtrip_reversible(client: TestClient, db: Session) -> None:
    """公式防护前缀可逆：以 - / = 开头的内容导出→回导不变形、不新增重复。"""
    headers = _login_teacher(db, client)
    file = _csv_file(
        [
            {
                "__type__": "题目说明",
                "text": "- Explain your choice.",
                "suggested_seconds": "30",
            },
            {
                "__type__": "题目说明",
                "text": "= not a formula",
                "suggested_seconds": "20",
            },
        ]
    )
    resp = _upload(client, headers, file, confirm=True)
    assert resp.json()["sheets"][0]["created"] == 2, resp.text

    export = client.get(f"{QB}/export?format=csv", headers=headers)
    assert export.status_code == 200, export.text
    text = export.content.decode("utf-8-sig")
    assert "'- Explain your choice." in text  # 导出侧确有防护前缀

    body = _preview(client, headers, export.content, filename="export.csv")
    counts = {s["type"]: s for s in body["sheets"]}["instruction"]
    assert counts["exact_duplicate_count"] >= 2, body  # unguard 还原后判重
    assert counts["valid_count"] == 0
    assert counts["suspected_duplicate_count"] == 0

    instructions = {i.text for i in _new_rows(db, Instruction)}
    assert "- Explain your choice." in instructions  # 库内内容未被前缀污染
    assert "= not a formula" in instructions


def test_repeat_ghost_linkage_reupload_exact_dup(
    client: TestClient, db: Session
) -> None:
    """挂靠篇目找不到而降级独立句后，重传同文件应判完全重复（cfg 用最终
    关联），勾选疑似导入也不会建出第二条相同独立句。"""
    headers = _login_teacher(db, client)
    file = _csv_file(
        [
            {
                "__type__": "听句复述",
                "text": "Ghost linked sentence.",
                "passage_title": "Ghost",
            }
        ]
    )
    resp = _upload(client, headers, file, confirm=True)
    assert resp.json()["sheets"][0]["created"] == 1

    body = _preview(client, headers, file)
    counts = body["sheets"][0]
    assert counts["exact_duplicate_count"] == 1, body
    assert counts["suspected_duplicate_count"] == 0

    resp = _upload(client, headers, file, confirm=True, include_suspected=True)
    assert resp.json()["sheets"][0]["created"] == 0
    assert len(_new_rows(db, RepeatSentence)) == 1


def test_scenario_exact_match_first_and_case_collision(
    client: TestClient, db: Session
) -> None:
    """库内 Travel/travel 并存：精确名优先；大小写都不同的写法命中多个 →
    行级报错，绝不静默挑一个。"""
    headers = _login_teacher(db, client)
    upper = Scenario(topic="Travel")
    lower = Scenario(topic="travel")
    db.add(upper)
    db.add(lower)
    db.commit()
    db.refresh(upper)
    db.refresh(lower)

    # 精确命中：文件写 Travel → 进 Travel（不被规范化字典覆盖到 travel）
    file = _csv_file([{**QUESTION_ROW, "topic": "Travel", "text": "Exact match?"}])
    resp = _upload(client, headers, file, confirm=True)
    assert resp.json()["sheets"][0]["created"] == 1
    question = db.exec(
        select(ScenarioQuestion).where(ScenarioQuestion.text == "Exact match?")
    ).one()
    assert question.scenario_id == upper.id

    # 规范化命中多个（TRAVEL）→ 行级错误
    file = _csv_file([{**QUESTION_ROW, "topic": "TRAVEL", "text": "Ambiguous case?"}])
    body = _preview(client, headers, file)
    assert body["total_valid"] == 0
    assert any("多个大小写不同的同名主题" in i["reason"] for i in body["issues"])

    # 精确命中小写主题
    file = _csv_file([{**QUESTION_ROW, "topic": "travel", "text": "Lower exact?"}])
    resp = _upload(client, headers, file, confirm=True)
    assert resp.json()["sheets"][0]["created"] == 1
    question = db.exec(
        select(ScenarioQuestion).where(ScenarioQuestion.text == "Lower exact?")
    ).one()
    assert question.scenario_id == lower.id


def _strip_xlsx_dimension(data: bytes) -> bytes:
    """去掉工作表 XML 的 dimension 声明：模拟无尺寸声明的合法 xlsx
    （max_row/max_column 为 None，声明预检必须被逐行实测兜底）。"""
    import re as re_mod
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename.startswith("xl/worksheets/") and item.filename.endswith(
                ".xml"
            ):
                content = re_mod.sub(rb"<dimension[^>]*/>", b"", content)
            zout.writestr(item, content)
    return out.getvalue()


def test_xlsx_column_cap_without_dimension(client: TestClient, db: Session) -> None:
    """无尺寸声明的 100 列文件绕不过列上限：逐行实测列数兜底。"""
    headers = _login_teacher(db, client)
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet = workbook.create_sheet("文章朗读")
    sheet.append(["标题", "正文"] + [""] * 98)
    sheet.append(["No dimension", "Column cap via row width."])
    buffer = io.BytesIO()
    workbook.save(buffer)
    raw = _strip_xlsx_dimension(buffer.getvalue())

    resp = _upload(
        client,
        headers,
        raw,
        filename="nodim.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert resp.status_code == 422
    assert "列" in resp.json()["detail"]
    assert "100" in resp.json()["detail"]


def test_csv_invalid_rows_count_toward_cap(client: TestClient, db: Session) -> None:
    """无效题型行也计入行数上限：2001 行全无效 → 422，不再绕过。"""
    headers = _login_teacher(db, client)
    rows = [{"__type__": "不存在题型", "text": f"Invalid {i}"} for i in range(2001)]
    resp = _upload(client, headers, _csv_file(rows))
    assert resp.status_code == 422
    assert "行数超过上限" in resp.json()["detail"]


def test_csv_huge_field_parses(client: TestClient, db: Session) -> None:
    """超长字段（> csv 默认 128KB 上限）解析不 500：field_size_limit 已抬高。"""
    headers = _login_teacher(db, client)
    huge = "a" * 200_000
    file = _csv_file([{"__type__": "文章朗读", "title": "Huge field", "text": huge}])
    resp = _upload(client, headers, file)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_valid"] == 1


def test_export_capped_at_reimportable_rows(client: TestClient, db: Session) -> None:
    """导出上限与导入一致（2000）：超出即 422 提示分批——导出的文件必须
    始终可直接回导。"""
    headers = _login_teacher(db, client)
    scenario = Scenario(topic="Export Cap Topic")
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    for start in (0, 1000):
        items = [
            {"text": f"Cap question {start + i}?", "suggested_seconds": 20}
            for i in range(1000)
        ]
        resp = client.post(
            f"/api/v1/admin/scenarios/{scenario.id}/questions/batch",
            json={"items": items},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
    # 批量端点单批上限 1000：第 2001 条走单题接口补足
    resp = client.post(
        f"/api/v1/admin/scenarios/{scenario.id}/questions",
        json={"text": "Cap question 2000?", "suggested_seconds": 20},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(f"{QB}/export?types=question", headers=headers)
    assert resp.status_code == 422
    assert "2000" in resp.json()["detail"]
    assert "分批" in resp.json()["detail"]


def test_in_batch_same_text_passages_suspected(client: TestClient, db: Session) -> None:
    """批内两篇不同标题、相同正文：第二篇应判疑似（不只查库内正文）。"""
    headers = _login_teacher(db, client)
    file = _csv_file(
        [
            {
                "__type__": "文章朗读",
                "title": "First title",
                "text": "Identical body across titles.",
            },
            {
                "__type__": "文章朗读",
                "title": "Second title",
                "text": "Identical body across titles.",
            },
        ]
    )
    body = _preview(client, headers, file)
    counts = body["sheets"][0]
    assert counts["valid_count"] == 1
    assert counts["suspected_duplicate_count"] == 1, body
    assert "相同正文已存在于其他篇目" in body["suspected"][0]["reason"]


# ── 权限 ─────────────────────────────────────────────────────────────


def test_permissions_student_403_and_anonymous_401(
    client: TestClient, db: Session
) -> None:
    student = create_student_user(db)
    assert student.username is not None
    student_headers = login_headers(client, student.username)
    resp = client.get(f"{QB}/import-template", headers=student_headers)
    assert resp.status_code == 403
    with anonymous(client):
        resp = client.get(f"{QB}/import-template")
        assert resp.status_code == 401
