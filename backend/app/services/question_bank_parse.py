"""题库导入解析：xlsx / csv → ParsedFile（纯解析，不落库）。"""

import csv
import io
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
)

from fastapi import (
    HTTPException,
)

from app.core.storage import (
    CONTENT_AUDIO_URL_PREFIX,
)
from app.models import (
    EXAM_KIND_QUESTION,
    EXAM_KIND_REPEAT,
    VOCAB_LEVEL_ORDER,
    QuestionBankImportIssue,
    validate_exam_fields,
    validate_question_suggested_seconds,
)
from app.services.question_bank_spec import (
    COLUMNS_BY_TYPE,
    EXAM_KIND_ALIASES,
    EXAM_LEVEL_ALIASES,
    HEADER_LOOKUP,
    INSTRUCTION_SHEET_ALIASES,
    MAX_IMPORT_ROWS,
    MAX_SHEET_COLUMNS,
    MAX_SHEET_ROWS,
    REQUIRED_FIELDS,
    SHEET_NAME_ALIASES,
    STATUS_ACTIVE_ALIASES,
    STATUS_INACTIVE_ALIASES,
    TYPE_INSTRUCTION,
    TYPE_LABELS,
    TYPE_PASSAGE,
    TYPE_QUESTION,
    TYPE_REPEAT,
    VALID_BANDS,
    _cell_str,
    _csv_unguard,
    _norm_header,
)

# ── 行级解析工具 ─────────────────────────────────────────────────────


class _RowError(Exception):
    """行级校验失败：reason 为中文稳定标识（前端做双语映射）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _checked(call: Any) -> str | None:
    """跑共享校验函数（抛 HTTPException 422），把 detail 转成行级原因。"""
    try:
        call()
        return None
    except HTTPException as exc:
        return str(exc.detail)


def _parse_int(raw: str, *, default: int, lo: int, hi: int, label: str) -> int:
    s = (raw or "").strip()
    if not s:
        return default
    n: int | float
    try:
        n = int(s)
    except ValueError:
        try:
            f = float(s)
            n = int(f) if f.is_integer() else f
        except ValueError as exc:
            raise _RowError(f"{label}需为 {lo}–{hi} 之间的整数") from exc
    if not isinstance(n, int) or not lo <= n <= hi:
        raise _RowError(f"{label}需为 {lo}–{hi} 之间的整数")
    return n


def _parse_optional_text(raw: str, *, max_len: int, label: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    if len(s) > max_len:
        raise _RowError(f"{label}过长（>{max_len} 字符）")
    return s


def _parse_band(raw: str) -> str:
    s = (raw or "").strip().upper()
    if not s:
        return "B1"
    if s not in VALID_BANDS:
        raise _RowError("难度无效，可选：A2/B1/B2")
    return s


def _parse_status(raw: str) -> bool:
    s = _norm_header(raw)
    if not s:
        return True
    if s in STATUS_ACTIVE_ALIASES:
        return True
    if s in STATUS_INACTIVE_ALIASES:
        return False
    raise _RowError("状态无效，可选：启用/停用")


def _parse_audio(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    path = s
    for scheme in ("https://", "http://"):
        if path.startswith(scheme):
            rest = path[len(scheme) :]
            path = rest.split("/", 1)[1] if "/" in rest else ""
            break
    if not path.startswith(f"{CONTENT_AUDIO_URL_PREFIX}/"):
        raise _RowError(
            f"音频链接格式不正确（应为本站 {CONTENT_AUDIO_URL_PREFIX}/ 开头的链接，"
            "音频文件请在导入后到题目编辑里上传）"
        )
    return s


def _parse_exam_kind(raw: str, allowed: tuple[str, ...], type_label: str) -> str | None:
    s = _norm_header(raw)
    if not s:
        return None
    for code, aliases in EXAM_KIND_ALIASES.items():
        if s in aliases:
            if code not in allowed:
                raise _RowError(f"考试题型无效：{type_label}仅支持 {'/'.join(allowed)}")
            return code
    raise _RowError(f"未知考试题型：{(raw or '').strip()}")


def _parse_exam_level(raw: str) -> str | None:
    s = _norm_header(raw)
    if not s:
        return None
    for code, aliases in EXAM_LEVEL_ALIASES.items():
        if s in aliases:
            return code
    raise _RowError("考试级别无效，可选：" + "/".join(VOCAB_LEVEL_ORDER))


def _parse_bullets(raw: str) -> list[str] | None:
    """话题卡要点：仅按换行拆分（导出即换行连接，可逆）。

    不再按分号/竖线拆——要点本身含 ; 或 | 时按分隔符拆会改变结构，
    导出→导入往返不无损（评审 P2 实例：["where; why","who"] 变三条）。
    """
    s = (raw or "").strip()
    if not s:
        return None
    bullets = [p.strip() for p in s.splitlines()]
    bullets = [p for p in bullets if p]
    return bullets or None


def _parse_prep_seconds(raw: str) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        n = int(s)
    except ValueError as exc:
        raise _RowError("准备秒数需为 10–180 之间的整数") from exc
    if not 10 <= n <= 180:
        raise _RowError("准备时间须在 10–180 秒之间")
    return n


# ── 行构建（校验 + 产出落库 payload；失败抛 _RowError） ──────────────


def _build_passage(cells: dict[str, str]) -> dict[str, Any]:
    title = (cells.get("title") or "").strip()
    if not title:
        raise _RowError("标题不能为空")
    if len(title) > 255:
        raise _RowError("标题过长（>255 字符）")
    topic = (cells.get("topic") or "").strip()
    if len(topic) > 100:
        raise _RowError("主题过长（>100 字符）")
    text = (cells.get("text") or "").strip()
    if not text:
        raise _RowError("正文不能为空")
    return {
        "title": title,
        "unit_title": (cells.get("unit_title") or "").strip() or None,
        "topic": topic,
        "cefr_band": _parse_band(cells.get("cefr_band") or ""),
        "text": text,
        "translation": _parse_optional_text(
            cells.get("translation") or "", max_len=1024, label="中文提示"
        ),
        "suggested_seconds": _parse_int(
            cells.get("suggested_seconds") or "",
            default=45,
            lo=10,
            hi=180,
            label="建议秒数",
        ),
        "audio_url": _parse_audio(cells.get("audio_url") or ""),
        "is_active": _parse_status(cells.get("is_active") or ""),
    }


def _build_repeat(cells: dict[str, str]) -> dict[str, Any]:
    text = (cells.get("text") or "").strip()
    if not text:
        raise _RowError("句子不能为空")
    if len(text) > 1024:
        raise _RowError("句子过长（>1024 字符）")
    exam_kind = _parse_exam_kind(
        cells.get("exam_kind") or "", allowed=EXAM_KIND_REPEAT, type_label="听句复述"
    )
    exam_level = _parse_exam_level(cells.get("exam_level") or "")
    err = _checked(lambda: validate_exam_fields("repeat", exam_kind, exam_level))
    if err:
        raise _RowError(err)
    return {
        "text": text,
        "translation": _parse_optional_text(
            cells.get("translation") or "", max_len=1024, label="中文提示"
        ),
        "passage_title": (cells.get("passage_title") or "").strip() or None,
        "suggested_seconds": _parse_int(
            cells.get("suggested_seconds") or "",
            default=8,
            lo=3,
            hi=60,
            label="作答秒数",
        ),
        "replay_limit": _parse_int(
            cells.get("replay_limit") or "", default=3, lo=0, hi=9, label="可听次数"
        ),
        "exam_kind": exam_kind,
        "exam_level": exam_level,
        "audio_url": _parse_audio(cells.get("audio_url") or ""),
    }


def _build_question(cells: dict[str, str]) -> dict[str, Any]:
    topic = (cells.get("topic") or "").strip()
    if not topic:
        raise _RowError("主题不能为空")
    if len(topic) > 100:
        raise _RowError("主题过长（>100 字符）")
    text = (cells.get("text") or "").strip()
    if not text:
        raise _RowError("题目不能为空")
    if len(text) > 512:
        raise _RowError("题目过长（>512 字符）")
    exam_kind = _parse_exam_kind(
        cells.get("exam_kind") or "", allowed=EXAM_KIND_QUESTION, type_label="情景问答"
    )
    exam_level = _parse_exam_level(cells.get("exam_level") or "")
    bullets = _parse_bullets(cells.get("cue_card_bullets") or "")
    prep_seconds = _parse_prep_seconds(cells.get("prep_seconds") or "")
    seconds = _parse_int(
        cells.get("suggested_seconds") or "",
        default=20,
        lo=10,
        hi=300,
        label="作答秒数",
    )
    err = _checked(
        lambda: validate_exam_fields(
            "question", exam_kind, exam_level, bullets, prep_seconds
        )
    ) or _checked(lambda: validate_question_suggested_seconds(seconds, exam_kind))
    if err:
        raise _RowError(err)
    return {
        "topic": topic,
        "text": text,
        "translation": _parse_optional_text(
            cells.get("translation") or "", max_len=1024, label="中文提示"
        ),
        "suggested_seconds": seconds,
        "exam_kind": exam_kind,
        "exam_level": exam_level,
        "cue_card_bullets": bullets,
        "prep_seconds": prep_seconds,
        "audio_url": _parse_audio(cells.get("audio_url") or ""),
    }


def _build_instruction(cells: dict[str, str]) -> dict[str, Any]:
    text = (cells.get("text") or "").strip()
    if not text:
        raise _RowError("说明文字不能为空")
    if len(text) > 2000:
        raise _RowError("说明文字过长（>2000 字符）")
    return {
        "title": _parse_optional_text(
            cells.get("title") or "", max_len=100, label="小标题"
        ),
        "text": text,
        "suggested_seconds": _parse_int(
            cells.get("suggested_seconds") or "", default=20, lo=5, hi=300, label="秒数"
        ),
    }


BUILDERS: dict[str, Any] = {
    TYPE_PASSAGE: _build_passage,
    TYPE_REPEAT: _build_repeat,
    TYPE_QUESTION: _build_question,
    TYPE_INSTRUCTION: _build_instruction,
}


# ── 文件解析（xlsx / CSV → 行列表 + 解析期问题） ────────────────────


@dataclass
class _RawRow:
    qtype: str
    line: int  # 文件内实际行号（表头为第 1 行，数据从 2 起）
    cells: dict[str, str]


@dataclass
class ErrorRow:
    """错误行完整快照：驱动「下载待修正数据」——保留原始字段 + 工作表 +
    原始行号 + 原因，修正后可直接回传（辅助列被解析器忽略）。"""

    qtype: str  # "-" 表示题型列本身无效（仅 CSV 解析期）
    line: int
    reason: str
    cells: dict[str, str]  # canonical 字段 → 原始字符串值
    type_cell: str = ""  # 原始题型单元格值（题型列无效时保留原样）


@dataclass
class ParsedFile:
    rows: list[_RawRow]
    issues: list[QuestionBankImportIssue]  # 解析期问题（CSV 题型列无效等）
    error_rows: list[ErrorRow] = field(default_factory=list)
    fmt: str = "csv"  # 上传格式（错误文件按同格式生成）


def _match_sheet_type(name: str) -> str | None:
    norm = _norm_header(name)
    for qtype, aliases in SHEET_NAME_ALIASES.items():
        if norm in aliases:
            return qtype
    return None


def _is_guide_sheet(name: str) -> bool:
    return _norm_header(name) in INSTRUCTION_SHEET_ALIASES


def parse_upload(filename: str, raw: bytes) -> ParsedFile:
    """解析上传文件 → 行列表（不做校验/查重）。文件级问题直接 422。"""
    name = (filename or "").casefold()
    if name.endswith(".xlsx") or raw[:2] == b"PK":
        parsed = _parse_xlsx(raw)
        parsed.fmt = "xlsx"
    else:
        # 其余一律按 CSV 尝试（utf-8-sig → gb18030 兜底：Excel 中文环境
        # 「另存为 CSV」默认 GBK，直接拒绝会把老师挡在门外）
        parsed = _parse_csv(raw)
        parsed.fmt = "csv"
    if len(parsed.rows) > MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=422, detail=f"行数超过上限（{MAX_IMPORT_ROWS} 行），请分批导入"
        )
    if not parsed.rows and not parsed.issues:
        raise HTTPException(status_code=422, detail="文件中没有可导入的数据行")
    return parsed


def _parse_xlsx(raw: bytes) -> ParsedFile:
    """流式解析 xlsx，边读边限。

    行/列上限在读遍历**之前**按工作表声明范围（max_row/max_column）判定：
    只有格式的远端单元格（如整列设置格式）同样会扩大有效区——若读完再数
    数据行，一个 4.9KB 的文件就能让解析器遍历几十万个单元格（评审 P1）。
    无尺寸声明的合法文件 max_row/max_column 为 None（声明预检跳过），
    此时由遍历中的逐行实测兜底：行号上限 + 实际列数上限。
    """
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail="Excel 文件无法解析，请用 Excel/WPS 重新保存后重试"
        ) from exc
    rows: list[_RawRow] = []
    issues: list[QuestionBankImportIssue] = []
    matched_any = False
    # 同一题型只允许出现在一个工作表：行标识是 (type, line)，
    # 「情景问答」和「question」两表同用第 2 行会撞号（评审 P2）
    seen_types: set[str] = set()
    try:
        for sheet_name in workbook.sheetnames:
            if _is_guide_sheet(sheet_name):
                continue  # 说明页按名字跳过，不读内容
            sheet = workbook[sheet_name]
            max_row = sheet.max_row or 0
            max_column = sheet.max_column or 0
            if max_column > MAX_SHEET_COLUMNS:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"工作表「{sheet_name}」有 {max_column} 列，超过 "
                        f"{MAX_SHEET_COLUMNS} 列上限，请使用标准模板的列"
                    ),
                )
            if max_row > MAX_SHEET_ROWS:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"工作表「{sheet_name}」有效区共 {max_row} 行，超过 "
                        f"{MAX_IMPORT_ROWS} 行数据上限；若因整列设置格式导致，"
                        "请清除多余格式或把数据复制到新模板"
                    ),
                )
            header_done = False
            col_map: dict[int, str] = {}
            qtype: str | None = None
            # max_row=0（无尺寸声明）时不能下传 max_row——会一个单元格都不产出
            iter_kwargs: dict[str, Any] = {"values_only": True}
            if max_row:
                iter_kwargs["max_row"] = max_row
            for r_idx, row in enumerate(sheet.iter_rows(**iter_kwargs), start=1):
                # 防御声明范围偏小/缺失的畸形文件：实际行数超界立即拒绝
                if r_idx > MAX_SHEET_ROWS:
                    raise HTTPException(
                        status_code=422,
                        detail=f"行数超过上限（{MAX_IMPORT_ROWS} 行），请分批导入",
                    )
                # 无尺寸声明（max_column=None）时声明预检失效：逐行实测列数
                if len(row) > MAX_SHEET_COLUMNS:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"工作表「{sheet_name}」有 {len(row)} 列，超过 "
                            f"{MAX_SHEET_COLUMNS} 列上限，请使用标准模板的列"
                        ),
                    )
                row_cells = tuple(_cell_str(c) for c in row)
                if not any(row_cells):
                    continue
                if not header_done:
                    header_done = True
                    qtype = _match_sheet_type(sheet_name)
                    if qtype is None:
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                f"工作表「{sheet_name}」无法识别题型，"
                                "请勿重命名模板工作表"
                            ),
                        )
                    if qtype in seen_types:
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                f"题型「{TYPE_LABELS[qtype]}」出现在多个工作表，"
                                "请合并到同一工作表（行号按工作表区分会撞号）"
                            ),
                        )
                    seen_types.add(qtype)
                    matched_any = True
                    col_map = _map_header(row_cells)
                    _require_columns(qtype, col_map, sheet_name)
                    continue
                if len(rows) + 1 > MAX_IMPORT_ROWS:
                    raise HTTPException(
                        status_code=422,
                        detail=f"行数超过上限（{MAX_IMPORT_ROWS} 行），请分批导入",
                    )
                rows.append(
                    _RawRow(
                        qtype=qtype or "",
                        line=r_idx,
                        cells=_row_cells(col_map, row_cells),
                    )
                )
    finally:
        workbook.close()
    if not matched_any:
        raise HTTPException(
            status_code=422,
            detail="未找到可识别的工作表（需包含：文章朗读/听句复述/情景问答/题目说明）",
        )
    return ParsedFile(rows=rows, issues=issues)


def _parse_csv(raw: bytes) -> ParsedFile:
    text: str | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(status_code=422, detail="文件必须是 UTF-8 编码")
    reader = csv.reader(io.StringIO(text))
    header: list[str] | None = None
    col_map: dict[int, str] = {}
    type_col: int | None = None
    fields_present: set[str] = set()
    rows: list[_RawRow] = []
    issues: list[QuestionBankImportIssue] = []
    error_rows: list[ErrorRow] = []
    checked_types: set[str] = set()
    any_content = False
    # 数据行计数包含无效行（题型空/无效）——只数成功识别的行会让
    # 2001 行全无效的文件绕过行数上限（评审 P2）
    data_rows = 0
    try:
        for r_idx, raw_row in enumerate(reader, start=1):
            # 还原导出时的公式防护前缀（见 _csv_unguard）：往返必须无损
            row_cells = tuple(_csv_unguard(c.strip()) for c in raw_row)
            if not any(row_cells):
                continue
            any_content = True
            if header is None:
                header = list(row_cells)
                col_map = _map_header(header)
                type_col = next(
                    (c for c, f in col_map.items() if f == "__type__"), None
                )
                if type_col is None:
                    raise HTTPException(status_code=422, detail="CSV 缺少题型列")
                fields_present = set(col_map.values())
                continue
            data_rows += 1
            if data_rows > MAX_IMPORT_ROWS:
                raise HTTPException(
                    status_code=422,
                    detail=f"行数超过上限（{MAX_IMPORT_ROWS} 行），请分批导入",
                )
            assert type_col is not None
            type_cell = row_cells[type_col] if type_col < len(row_cells) else ""
            cells = _row_cells(
                {c: f for c, f in col_map.items() if f != "__type__"}, row_cells
            )
            if not type_cell:
                issues.append(
                    QuestionBankImportIssue(type="-", line=r_idx, reason="题型不能为空")
                )
                error_rows.append(
                    ErrorRow(qtype="-", line=r_idx, reason="题型不能为空", cells=cells)
                )
                continue
            qtype = _match_sheet_type(type_cell)
            if qtype is None:
                reason = f"题型列的值无效：{type_cell}"
                issues.append(
                    QuestionBankImportIssue(type="-", line=r_idx, reason=reason)
                )
                error_rows.append(
                    ErrorRow(
                        qtype="-",
                        line=r_idx,
                        reason=reason,
                        cells=cells,
                        type_cell=type_cell,
                    )
                )
                continue
            if qtype not in checked_types:
                checked_types.add(qtype)
                _require_columns_csv(qtype, fields_present)
            rows.append(_RawRow(qtype=qtype, line=r_idx, cells=cells))
    except csv.Error as exc:
        # field_size_limit 已抬高到上传上限之上，此处理论不可达——保留
        # 防御：任何 csv 模块级错误都以 422 呈现，绝不 500
        raise HTTPException(status_code=422, detail="CSV 字段过大，无法解析") from exc
    if not any_content:
        raise HTTPException(status_code=422, detail="文件为空")
    return ParsedFile(rows=rows, issues=issues, error_rows=error_rows)


def _map_header(header_cells: tuple[str, ...] | list[str]) -> dict[int, str]:
    """列号 → canonical 字段（未识别列忽略）。"""
    col_map: dict[int, str] = {}
    for idx, cell in enumerate(header_cells):
        mapped = HEADER_LOOKUP.get(_norm_header(cell))
        if mapped is not None:
            col_map[idx] = mapped
    return col_map


def _zh_of(qtype: str, fieldname: str) -> str:
    return next(c.zh for c in COLUMNS_BY_TYPE[qtype] if c.field == fieldname)


def _require_columns(qtype: str, col_map: dict[int, str], sheet_name: str) -> None:
    present = set(col_map.values())
    missing = [f for f in REQUIRED_FIELDS[qtype] if f not in present]
    if missing:
        names = "/".join(_zh_of(qtype, f) for f in missing)
        raise HTTPException(
            status_code=422, detail=f"工作表「{sheet_name}」缺少必填列：{names}"
        )


def _require_columns_csv(qtype: str, fields_present: set[str]) -> None:
    missing = [f for f in REQUIRED_FIELDS[qtype] if f not in fields_present]
    if missing:
        names = "/".join(_zh_of(qtype, f) for f in missing)
        raise HTTPException(
            status_code=422, detail=f"CSV 表头缺少{TYPE_LABELS[qtype]}必填列：{names}"
        )


def _row_cells(
    col_map: dict[int, str], row_cells: tuple[str, ...] | list[str]
) -> dict[str, str]:
    cells: dict[str, str] = {}
    for idx, fieldname in col_map.items():
        if idx < len(row_cells):
            cells[fieldname] = row_cells[idx]
    return cells
