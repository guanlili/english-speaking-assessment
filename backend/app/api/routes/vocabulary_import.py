"""词汇学习（背单词）模块接口：import 域。

由原 vocabulary.py 按域拆出：端点路径、参数、响应模型与实现均未改动。

    /vocabulary/books                 词库 CRUD + 词库内加词（教师/管理员）
    /vocabulary/books/import-preview  CSV 解析预览（不落库）
    /vocabulary/words/{id}            词条编辑
    /classes/{code}/vocabulary/...    课堂发布 / 学生任务 / 结果 / 错词本
    /vocabulary/sessions/{id}/answers 学生作答（服务端判分）

权限口径（设计文档 §5）：词库编辑/发布 = 课堂所有者教师或管理员；
学生任务仅目标名单内的本班学生；原始作答仅本人与该班教师可读。
401 只表示登录失效；权限不足一律 403。
"""

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.deps import TeacherUserDep
from app.core.config import settings
from app.models import (
    VocabularyImportIssue,
    VocabularyImportPreview,
    VocabularyImportRow,
    VocabularyWordIn,
)

router = APIRouter()


# ── CSV 导入预览 ────────────────────────────────────────────────────


async def _read_csv_upload(file: UploadFile) -> str:
    max_bytes = settings.MAX_VOCAB_CSV_MB * 1024 * 1024
    raw = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"CSV 超过 {settings.MAX_VOCAB_CSV_MB}MB 上限",
            )
    try:
        return raw.decode("utf-8-sig")  # 兼容 Excel 导出的 BOM
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV 必须是 UTF-8 编码") from exc


def _parse_vocab_csv(text: str) -> VocabularyImportPreview:
    reader = csv.DictReader(io.StringIO(text))
    if (
        not reader.fieldnames
        or "headword" not in reader.fieldnames
        or "meaning_zh" not in reader.fieldnames
    ):
        raise HTTPException(
            status_code=422,
            detail="CSV 需要表头：headword,meaning_zh（第一行，可选 part_of_speech/"
            "meaning_en/accepted_spellings/example_en）",
        )
    rows: list[VocabularyImportRow] = []
    invalid: list[VocabularyImportIssue] = []
    duplicates: list[VocabularyImportIssue] = []
    seen: set[tuple[str, str]] = set()
    for lineno, row in enumerate(reader, start=2):
        headword = (row.get("headword") or "").strip()
        meaning_zh = (row.get("meaning_zh") or "").strip()
        if not headword:
            invalid.append(
                VocabularyImportIssue(line=lineno, reason="缺少单词（headword）")
            )
            continue
        if len(headword) > 64:
            invalid.append(
                VocabularyImportIssue(line=lineno, reason=f"单词超长：{headword[:20]}…")
            )
            continue
        if not meaning_zh:
            invalid.append(
                VocabularyImportIssue(
                    line=lineno, reason=f"{headword} 缺少中文释义（meaning_zh）"
                )
            )
            continue
        key = (headword.casefold(), meaning_zh)
        if key in seen:
            duplicates.append(
                VocabularyImportIssue(line=lineno, reason=f"{headword} 与前文重复")
            )
            continue
        seen.add(key)
        accepted = [
            spelling.strip()
            for spelling in (row.get("accepted_spellings") or "").split("|")
            if spelling.strip()
        ]
        rows.append(
            VocabularyImportRow(
                line=lineno,
                word=VocabularyWordIn(
                    headword=headword,
                    part_of_speech=(row.get("part_of_speech") or "").strip() or None,
                    meaning_zh=meaning_zh,
                    meaning_en=(row.get("meaning_en") or "").strip() or None,
                    accepted_spellings=accepted or None,
                    example_en=(row.get("example_en") or "").strip() or None,
                ),
            )
        )
    return VocabularyImportPreview(rows=rows, invalid=invalid, duplicates=duplicates)


@router.post("/vocabulary/books/import-preview", response_model=VocabularyImportPreview)
async def import_vocab_preview(_teacher: TeacherUserDep, file: UploadFile) -> Any:
    """CSV 导入预览：解析与校验，不写库；确认后在创建词库/加词时提交。"""
    text = await _read_csv_upload(file)
    return await run_in_threadpool(_parse_vocab_csv, text)
