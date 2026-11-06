"""题库批量导入导出：老师自助录题（2026-10-14 本期范围）。

数据流：模板下载 → 老师填 Excel/CSV → import-preview（解析+校验+查重，
不落库）→ import-confirm（重新上传同一文件，单事务落库）。数据只写现有
四张题型表（Passage / RepeatSentence / ScenarioQuestion / Instruction），
零迁移、零新表。

口径：
- 只 INSERT 不 UPDATE：导入永不覆盖旧题（发布快照与历史成绩不受影响的
  根基），改题仍走现有编辑页；
- 校验与手动建题同一套：validate_exam_fields /
  validate_question_suggested_seconds / band 白名单 / 字段长度与秒数区间；
- 重复两级（规范化 = NFKC + strip + casefold + 空白折叠）：
  完全重复（题干与配置都相同，含批内）默认跳过；疑似重复（题干相同、
  配置/主题不同）预览逐行列出，确认时由 include_suspected 决定；
- 兜底：问答题主题不存在 → 自动新建 Scenario（预览明示）；篇目单元
  不匹配 → 降级为无单元；复述句挂靠篇目 0 命中 → 独立句、多命中 → 报错；
- 音频两步走：导入只收音频链接（须为本站 /api/v1/audio/content/ 前缀），
  音频文件上传沿用现有入口；缺音频按题型计数提示，不阻断——「题目已
  导入」不等于「音频已齐备」。

xlsx 模板与解析共用本文件的列规格（单一事实源）；CSV 与导出格式同构，
导出→导入往返不丢教师可填的关键配置（拆句/逐题计时不入模板，属声明的
例外，模板说明页注明）。

本模块保留为对外门面：实现按 spec / parse / plan / apply 四层拆分，
既有 `from app.services.question_bank_io import X` 与 `io_service.X` 用法全部不变。
"""

from app.services.question_bank_apply import (
    _commit as _commit,
)
from app.services.question_bank_apply import (
    apply_import as apply_import,
)
from app.services.question_bank_parse import (
    BUILDERS as BUILDERS,
)
from app.services.question_bank_parse import (
    ErrorRow as ErrorRow,
)
from app.services.question_bank_parse import (
    ParsedFile as ParsedFile,
)
from app.services.question_bank_parse import (
    _build_instruction as _build_instruction,
)
from app.services.question_bank_parse import (
    _build_passage as _build_passage,
)
from app.services.question_bank_parse import (
    _build_question as _build_question,
)
from app.services.question_bank_parse import (
    _build_repeat as _build_repeat,
)
from app.services.question_bank_parse import (
    _checked as _checked,
)
from app.services.question_bank_parse import (
    _is_guide_sheet as _is_guide_sheet,
)
from app.services.question_bank_parse import (
    _map_header as _map_header,
)
from app.services.question_bank_parse import (
    _match_sheet_type as _match_sheet_type,
)
from app.services.question_bank_parse import (
    _parse_audio as _parse_audio,
)
from app.services.question_bank_parse import (
    _parse_band as _parse_band,
)
from app.services.question_bank_parse import (
    _parse_bullets as _parse_bullets,
)
from app.services.question_bank_parse import (
    _parse_csv as _parse_csv,
)
from app.services.question_bank_parse import (
    _parse_exam_kind as _parse_exam_kind,
)
from app.services.question_bank_parse import (
    _parse_exam_level as _parse_exam_level,
)
from app.services.question_bank_parse import (
    _parse_int as _parse_int,
)
from app.services.question_bank_parse import (
    _parse_optional_text as _parse_optional_text,
)
from app.services.question_bank_parse import (
    _parse_prep_seconds as _parse_prep_seconds,
)
from app.services.question_bank_parse import (
    _parse_status as _parse_status,
)
from app.services.question_bank_parse import (
    _parse_xlsx as _parse_xlsx,
)
from app.services.question_bank_parse import (
    _RawRow as _RawRow,
)
from app.services.question_bank_parse import (
    _require_columns as _require_columns,
)
from app.services.question_bank_parse import (
    _require_columns_csv as _require_columns_csv,
)
from app.services.question_bank_parse import (
    _row_cells as _row_cells,
)
from app.services.question_bank_parse import (
    _RowError as _RowError,
)
from app.services.question_bank_parse import (
    _zh_of as _zh_of,
)
from app.services.question_bank_parse import (
    parse_upload as parse_upload,
)
from app.services.question_bank_plan import (
    QuestionBankPlan as QuestionBankPlan,
)
from app.services.question_bank_plan import (
    _CreateItem as _CreateItem,
)
from app.services.question_bank_plan import (
    _excerpt as _excerpt,
)
from app.services.question_bank_plan import (
    _issue as _issue,
)
from app.services.question_bank_plan import (
    _pid_key as _pid_key,
)
from app.services.question_bank_plan import (
    _plan_instructions as _plan_instructions,
)
from app.services.question_bank_plan import (
    _plan_passages as _plan_passages,
)
from app.services.question_bank_plan import (
    _plan_questions as _plan_questions,
)
from app.services.question_bank_plan import (
    _plan_repeats as _plan_repeats,
)
from app.services.question_bank_plan import (
    _row_digest as _row_digest,
)
from app.services.question_bank_plan import (
    _scenario_active as _scenario_active,
)
from app.services.question_bank_plan import (
    _summarize_instruction_model as _summarize_instruction_model,
)
from app.services.question_bank_plan import (
    _summarize_passage_model as _summarize_passage_model,
)
from app.services.question_bank_plan import (
    _summarize_payload as _summarize_payload,
)
from app.services.question_bank_plan import (
    _summarize_question_model as _summarize_question_model,
)
from app.services.question_bank_plan import (
    _summarize_sentence_model as _summarize_sentence_model,
)
from app.services.question_bank_plan import (
    _suspected as _suspected,
)
from app.services.question_bank_plan import (
    _TypeCounts as _TypeCounts,
)
from app.services.question_bank_plan import (
    plan_fingerprint as plan_fingerprint,
)
from app.services.question_bank_plan import (
    plan_import as plan_import,
)
from app.services.question_bank_plan import (
    preview_import as preview_import,
)
from app.services.question_bank_ref import (
    _load_reference as _load_reference,
)
from app.services.question_bank_ref import (
    _matching_ids as _matching_ids,
)
from app.services.question_bank_ref import (
    _Ref as _Ref,
)
from app.services.question_bank_spec import (
    _CSV_GUARD_CHARS as _CSV_GUARD_CHARS,
)
from app.services.question_bank_spec import (
    COLUMNS_BY_TYPE as COLUMNS_BY_TYPE,
)
from app.services.question_bank_spec import (
    CSV_MEDIA_TYPE as CSV_MEDIA_TYPE,
)
from app.services.question_bank_spec import (
    CSV_TYPE_COLUMN as CSV_TYPE_COLUMN,
)
from app.services.question_bank_spec import (
    CSV_UNION_COLUMNS as CSV_UNION_COLUMNS,
)
from app.services.question_bank_spec import (
    EXAM_KIND_ALIASES as EXAM_KIND_ALIASES,
)
from app.services.question_bank_spec import (
    EXAM_LEVEL_ALIASES as EXAM_LEVEL_ALIASES,
)
from app.services.question_bank_spec import (
    EXCEL_CELL_MAX_CHARS as EXCEL_CELL_MAX_CHARS,
)
from app.services.question_bank_spec import (
    HEADER_LOOKUP as HEADER_LOOKUP,
)
from app.services.question_bank_spec import (
    IMPORT_ADVISORY_LOCK_KEY as IMPORT_ADVISORY_LOCK_KEY,
)
from app.services.question_bank_spec import (
    INSTRUCTION_COLUMNS as INSTRUCTION_COLUMNS,
)
from app.services.question_bank_spec import (
    INSTRUCTION_SHEET_ALIASES as INSTRUCTION_SHEET_ALIASES,
)
from app.services.question_bank_spec import (
    MAX_EXPORT_ROWS as MAX_EXPORT_ROWS,
)
from app.services.question_bank_spec import (
    MAX_IMPORT_ROWS as MAX_IMPORT_ROWS,
)
from app.services.question_bank_spec import (
    MAX_ISSUES as MAX_ISSUES,
)
from app.services.question_bank_spec import (
    MAX_SHEET_COLUMNS as MAX_SHEET_COLUMNS,
)
from app.services.question_bank_spec import (
    MAX_SHEET_ROWS as MAX_SHEET_ROWS,
)
from app.services.question_bank_spec import (
    MAX_SUSPECTED_LISTED as MAX_SUSPECTED_LISTED,
)
from app.services.question_bank_spec import (
    MAX_UPLOAD_BYTES as MAX_UPLOAD_BYTES,
)
from app.services.question_bank_spec import (
    PASSAGE_COLUMNS as PASSAGE_COLUMNS,
)
from app.services.question_bank_spec import (
    QUESTION_BANK_TYPE_ORDER as QUESTION_BANK_TYPE_ORDER,
)
from app.services.question_bank_spec import (
    QUESTION_COLUMNS as QUESTION_COLUMNS,
)
from app.services.question_bank_spec import (
    REPEAT_COLUMNS as REPEAT_COLUMNS,
)
from app.services.question_bank_spec import (
    REQUIRED_FIELDS as REQUIRED_FIELDS,
)
from app.services.question_bank_spec import (
    SHEET_NAME_ALIASES as SHEET_NAME_ALIASES,
)
from app.services.question_bank_spec import (
    STATUS_ACTIVE_ALIASES as STATUS_ACTIVE_ALIASES,
)
from app.services.question_bank_spec import (
    STATUS_INACTIVE_ALIASES as STATUS_INACTIVE_ALIASES,
)
from app.services.question_bank_spec import (
    TYPE_INSTRUCTION as TYPE_INSTRUCTION,
)
from app.services.question_bank_spec import (
    TYPE_LABELS as TYPE_LABELS,
)
from app.services.question_bank_spec import (
    TYPE_PASSAGE as TYPE_PASSAGE,
)
from app.services.question_bank_spec import (
    TYPE_QUESTION as TYPE_QUESTION,
)
from app.services.question_bank_spec import (
    TYPE_REPEAT as TYPE_REPEAT,
)
from app.services.question_bank_spec import (
    VALID_BANDS as VALID_BANDS,
)
from app.services.question_bank_spec import (
    XLSX_MEDIA_TYPE as XLSX_MEDIA_TYPE,
)
from app.services.question_bank_spec import (
    ColumnSpec as ColumnSpec,
)
from app.services.question_bank_spec import (
    _build_header_lookup as _build_header_lookup,
)
from app.services.question_bank_spec import (
    _cell_str as _cell_str,
)
from app.services.question_bank_spec import (
    _csv_bytes as _csv_bytes,
)
from app.services.question_bank_spec import (
    _csv_guard as _csv_guard,
)
from app.services.question_bank_spec import (
    _csv_unguard as _csv_unguard,
)
from app.services.question_bank_spec import (
    _generate_slug as _generate_slug,
)
from app.services.question_bank_spec import (
    _norm_header as _norm_header,
)
from app.services.question_bank_spec import (
    _norm_text as _norm_text,
)
