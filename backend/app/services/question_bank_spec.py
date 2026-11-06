"""题库导入规格：题型/限制常量、列规格、表头查找与 CSV 工具（模板/导出/解析共用的单一事实源）。"""

import csv
import io
import uuid
from dataclasses import (
    dataclass,
)
from typing import (
    Any,
)

from app import (
    crud,
)
from app.services import (
    content_dedup,
)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


MAX_IMPORT_ROWS = 2000


# 导出上限必须与导入上限一致：导出的文件要始终能直接回导（评审 P2 曾出现
# 2001 行可导出、回导被 2000 行上限拒绝）。更大规模请按题型/主题筛选分批导出
MAX_EXPORT_ROWS = MAX_IMPORT_ROWS


MAX_ISSUES = 200


# 疑似对照全量返回（上限=行数上限）：截断会让「全部导入」漏掉后续行，
# 无法在本轮完成确认（评审 P2）
MAX_SUSPECTED_LISTED = MAX_IMPORT_ROWS


# 并发导入防重：事务级咨询锁键（pg_advisory_xact_lock 的任意固定整数，
# 取自业务无关魔数，仅用于串行化导入确认这一件事）
IMPORT_ADVISORY_LOCK_KEY = 872_514_309


# csv 模块单字段默认 128KB 上限：长正文导出 CSV 后回导会触发 csv.Error → 500。
# 抬到上传上限之上，任何能通过 5MB 限制的文件都可解析（_parse_csv 另有兜底 422）
csv.field_size_limit(MAX_UPLOAD_BYTES + 1024)
# xlsx 解析资源上限（评审 P1）：按工作表声明范围在读遍历前判定，
# 防止「只有格式没有内容」的远端单元格把遍历量撑大（表头+说明行余量）
MAX_SHEET_ROWS = MAX_IMPORT_ROWS + 8


MAX_SHEET_COLUMNS = 64


# Excel 单元格字符串硬上限：openpyxl 写超长会静默截断，导出前显式拒绝
EXCEL_CELL_MAX_CHARS = 32767


TYPE_PASSAGE = "passage"


TYPE_REPEAT = "repeat"


TYPE_QUESTION = "question"


TYPE_INSTRUCTION = "instruction"


QUESTION_BANK_TYPE_ORDER = (TYPE_PASSAGE, TYPE_REPEAT, TYPE_QUESTION, TYPE_INSTRUCTION)


TYPE_LABELS = {
    TYPE_PASSAGE: "文章朗读",
    TYPE_REPEAT: "听句复述",
    TYPE_QUESTION: "情景问答",
    TYPE_INSTRUCTION: "题目说明",
}


# 工作表名 → 题型（模板工作表名/CSV 题型列共用；大小写与首尾空白不敏感）
SHEET_NAME_ALIASES: dict[str, set[str]] = {
    TYPE_PASSAGE: {
        "文章朗读",
        "文章朗读 · 篇目",
        "朗读",
        "read aloud",
        "passage",
        "reading",
    },
    TYPE_REPEAT: {
        "听句复述",
        "听令复述",
        "listen & repeat",
        "listen and repeat",
        "repeat",
    },
    TYPE_QUESTION: {
        "情景问答",
        "问答",
        "scenario q&a",
        "scenario qa",
        "question",
        "qa",
    },
    # 注意：「说明」不进题型别名——那是模板说明页的名字，不能当题目说明工作表
    TYPE_INSTRUCTION: {"题目说明", "instruction"},
}


# 说明页：有内容也整体跳过，不参与导入（「说明」从题型别名挪到这里）
INSTRUCTION_SHEET_ALIASES = {
    "说明",
    "填写说明",
    "使用说明",
    "说明页",
    "readme",
    "instructions",
    "help",
}


VALID_BANDS = {"A2", "B1", "B2"}


# 考试题型别名（值匹配用：casefold + 空白折叠后比对；含系统代码/中英文名）
EXAM_KIND_ALIASES: dict[str, set[str]] = {
    "toefl_lnr": {
        "toefl_lnr",
        "toefl",
        "托福",
        "toefl · 听令复述",
        "toefl听令复述",
        "toefl · 听句复述",
        "toefl听句复述",
        "listen & repeat",
        "listen and repeat",
    },
    "interview": {
        "interview",
        "toefl · 情景访谈",
        "toefl情景访谈",
        "take an interview",
        "访谈",
    },
    "ielts_p1": {"ielts_p1", "ielts · part 1", "ielts part 1", "ielts p1", "part 1"},
    "ielts_p2": {"ielts_p2", "ielts · part 2", "ielts part 2", "ielts p2", "part 2"},
    "ielts_p3": {"ielts_p3", "ielts · part 3", "ielts part 3", "ielts p3", "part 3"},
}


EXAM_LEVEL_ALIASES: dict[str, set[str]] = {
    "KET": {"ket", "ket 词汇"},
    "PET": {"pet", "pet 词汇"},
    "ACADEMIC": {"academic", "学术词汇", "学术"},
    "CET4": {"cet4", "cet-4", "cet 4", "四级"},
    "IELTS_TOEFL": {
        "ielts_toefl",
        "雅思&托福词汇",
        "雅思托福",
        "雅思和托福",
        "ielts & toefl",
        "ielts&toefl",
    },
}


STATUS_ACTIVE_ALIASES = {"启用", "是", "true", "active", "1"}


STATUS_INACTIVE_ALIASES = {"停用", "否", "false", "inactive", "0"}


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


CSV_MEDIA_TYPE = "text/csv"


# ── 规范化小工具（表头匹配/查重键/单元格转字符串） ──────────────────


def _norm_header(raw: Any) -> str:
    """表头/枚举值规范化：casefold + 空白折叠（双语合并表头的换行也折叠）。"""
    if raw is None:
        return ""
    return " ".join(str(raw).split()).casefold()


# 查重键归一化只有一份定义（services/content_dedup.py）：写入维护与
# 读取匹配共用，别处复制必然漂移
_norm_text = content_dedup.norm_text


def _cell_str(raw: Any) -> str:
    """单元格值 → 字符串（openpyxl 可能给 int/float/bool/None）。"""
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return "是" if raw else "否"
    if isinstance(raw, float):
        return str(int(raw)) if raw.is_integer() else str(raw)
    return str(raw).strip()


# ── 列规格（canonical 字段 → 双语表头；模板生成与解析共用） ─────────


@dataclass(frozen=True)
class ColumnSpec:
    """一列的规格：模板表头单元格为「中文\n英文」，解析时三种形式都认。"""

    field: str
    zh: str
    en: str
    extra_aliases: tuple[str, ...] = ()

    @property
    def header(self) -> str:
        return f"{self.zh}\n{self.en}"

    def aliases(self) -> set[str]:
        return {
            _norm_header(a)
            for a in (self.zh, self.en, self.header, *self.extra_aliases)
        }


PASSAGE_COLUMNS = (
    ColumnSpec("title", "标题", "Title"),
    ColumnSpec("unit_title", "单元", "Unit"),
    ColumnSpec("topic", "主题", "Topic"),
    ColumnSpec("cefr_band", "难度", "Level", ("cefr", "cefr_band", "cefr level")),
    ColumnSpec("text", "正文", "Text", ("文章正文", "内容", "body")),
    ColumnSpec("translation", "中文提示", "Chinese hint", ("翻译", "hint")),
    ColumnSpec("suggested_seconds", "建议秒数", "Seconds"),
    ColumnSpec("audio_url", "音频链接", "Audio URL", ("音频", "audio")),
    ColumnSpec("is_active", "状态", "Status", ("启用", "active", "is_active")),
)


REPEAT_COLUMNS = (
    ColumnSpec("text", "英文句子", "Sentence", ("句子", "sentence")),
    ColumnSpec("translation", "中文提示", "Chinese hint", ("翻译", "hint")),
    ColumnSpec(
        "passage_title",
        "挂靠篇目",
        "Passage",
        ("所属篇目", "篇目标题", "passage title"),
    ),
    ColumnSpec("suggested_seconds", "作答秒数", "Seconds"),
    ColumnSpec(
        "replay_limit", "可听次数", "Replays", ("重听次数", "replay", "replays")
    ),
    ColumnSpec("exam_kind", "考试题型", "Exam type", ("exam_kind",)),
    ColumnSpec("exam_level", "考试级别", "Exam level", ("exam_level",)),
    ColumnSpec("audio_url", "音频链接", "Audio URL", ("音频", "audio")),
)


QUESTION_COLUMNS = (
    ColumnSpec("topic", "主题", "Topic"),
    ColumnSpec("text", "英文题目", "Question", ("题目", "question")),
    ColumnSpec("translation", "中文提示", "Chinese hint", ("翻译", "hint")),
    ColumnSpec("suggested_seconds", "作答秒数", "Seconds"),
    ColumnSpec("exam_kind", "考试题型", "Exam type", ("exam_kind",)),
    ColumnSpec("exam_level", "考试级别", "Exam level", ("exam_level",)),
    ColumnSpec(
        "cue_card_bullets", "话题卡要点", "Cue card", ("话题卡", "cue_card_bullets")
    ),
    ColumnSpec(
        "prep_seconds", "准备秒数", "Prep seconds", ("准备时间", "prep", "prep_seconds")
    ),
    ColumnSpec("audio_url", "音频链接", "Audio URL", ("音频", "audio")),
)


INSTRUCTION_COLUMNS = (
    ColumnSpec("title", "小标题", "Title", ("标题",)),
    ColumnSpec("text", "说明文字", "Text", ("内容",)),
    ColumnSpec("suggested_seconds", "秒数", "Seconds"),
)


# CSV 单文件：题型列 + 四表列并集（列名跨题型复用同一 canonical 字段）
CSV_TYPE_COLUMN = ColumnSpec("__type__", "题型", "Type", ("item type", "kind"))


CSV_UNION_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("title", "标题", "Title", ("小标题",)),
    ColumnSpec("unit_title", "单元", "Unit"),
    ColumnSpec("topic", "主题", "Topic"),
    ColumnSpec("cefr_band", "难度", "Level", ("cefr",)),
    ColumnSpec(
        "text",
        "内容",
        "Text",
        (
            "正文",
            "英文句子",
            "句子",
            "英文题目",
            "题目",
            "说明文字",
            "sentence",
            "question",
            "body",
        ),
    ),
    ColumnSpec("translation", "中文提示", "Chinese hint", ("翻译", "hint")),
    ColumnSpec("passage_title", "挂靠篇目", "Passage", ("所属篇目", "篇目标题")),
    ColumnSpec(
        "suggested_seconds", "秒数", "Seconds", ("建议秒数", "作答秒数", "duration")
    ),
    ColumnSpec("replay_limit", "可听次数", "Replays", ("重听次数", "replay")),
    ColumnSpec("exam_kind", "考试题型", "Exam type", ("exam_kind",)),
    ColumnSpec("exam_level", "考试级别", "Exam level", ("exam_level",)),
    ColumnSpec("cue_card_bullets", "话题卡要点", "Cue card", ("话题卡",)),
    ColumnSpec("prep_seconds", "准备秒数", "Prep seconds", ("准备时间",)),
    ColumnSpec("audio_url", "音频链接", "Audio URL", ("音频", "audio")),
    ColumnSpec("is_active", "状态", "Status", ("启用", "active")),
)


COLUMNS_BY_TYPE: dict[str, tuple[ColumnSpec, ...]] = {
    TYPE_PASSAGE: PASSAGE_COLUMNS,
    TYPE_REPEAT: REPEAT_COLUMNS,
    TYPE_QUESTION: QUESTION_COLUMNS,
    TYPE_INSTRUCTION: INSTRUCTION_COLUMNS,
}


# 各题型必填列（canonical 字段）
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    TYPE_PASSAGE: ("title", "text"),
    TYPE_REPEAT: ("text",),
    TYPE_QUESTION: ("topic", "text"),
    TYPE_INSTRUCTION: ("text",),
}


def _build_header_lookup() -> dict[str, str]:
    """别名（规范化）→ canonical 字段。跨题型同名列（秒数/中文提示）指向同一字段。"""
    lookup: dict[str, str] = {}
    all_specs: list[ColumnSpec] = [CSV_TYPE_COLUMN, *CSV_UNION_COLUMNS]
    for specs in COLUMNS_BY_TYPE.values():
        all_specs.extend(specs)
    for spec in all_specs:
        for alias in spec.aliases():
            lookup.setdefault(alias, spec.field)
    return lookup


HEADER_LOOKUP = _build_header_lookup()


def _generate_slug(title: str, used: set[str]) -> str:
    """标题 → 唯一 slug（与 crud.unique_passage_slug 同规则，批内去重免逐行查询）。"""
    base = crud.slugify_title(title)
    slug = base
    for i in range(2, 500):
        if slug not in used:
            break
        suffix = f"-{i}"
        slug = f"{base[: 100 - len(suffix)]}{suffix}"
    else:
        slug = f"{base[:90]}-{uuid.uuid4().hex[:8]}"
    used.add(slug)
    return slug


_CSV_GUARD_CHARS = "=+-@\t\r'"


def _csv_guard(value: str) -> str:
    """CSV 公式注入防护（可逆方案的前半）。

    在前端同规则（= +/-/@/制表符/回车加 `'` 前缀）之上**追加一条**：原文
    本身以 `'` 开头时也加前缀（`'x` → `''x`）。这样导出的单元格只要以
    `'` 开头，第二字符必属于危险集或仍是 `'`——导入侧 _csv_unguard 依据
    该不变量无歧义还原，原文自带的引号不会被误删（评审 P3：
    `'-ed' marks…` 曾被剥成 `-ed' marks…`）。
    """
    if value and value[0] in _CSV_GUARD_CHARS:
        return "'" + value
    return value


def _csv_unguard(cell: str) -> str:
    """_csv_guard 的逆运算：还原导出时加的公式防护前缀。

    仅当首字符是 `'` 且第二字符属于 `_CSV_GUARD_CHARS` 时剥掉**一个**
    前缀——导出侧保证凡是它产出的 `'` 开头单元格都满足该形态：
    - `'-ed'…`（原文 `-ed'…`，防护前缀）→ `-ed'…`
    - `''-ed'…`（原文 `'-ed'…`，原文引号被转义）→ `'-ed'…`
    第二字符不在集合内的 `'hello`（手写、未经导出）按字面保留，与
    Excel 自身的 `'` 前缀语义一致。
    """
    if len(cell) >= 2 and cell[0] == "'" and cell[1] in _CSV_GUARD_CHARS:
        return cell[1:]
    return cell


def _csv_bytes(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows([[_csv_guard(c) for c in row] for row in rows])
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
