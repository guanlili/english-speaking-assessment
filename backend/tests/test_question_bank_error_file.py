"""题目库「下载待修正数据」：build_error_file 拆出的 helper 单元验证。

此前只有「没有需要修正的行」这条 422 早退路径被测试覆盖，xlsx / CSV
两条实际生成分支从未执行——拆分成 helper 后正好按分支补齐。
"""

import io

from openpyxl import load_workbook

from app.services.question_bank_export import (
    _build_error_workbook,
    _error_file_csv_rows,
    _partition_errors_by_type,
)
from app.services.question_bank_io import (
    COLUMNS_BY_TYPE,
    CSV_TYPE_COLUMN,
    CSV_UNION_COLUMNS,
    TYPE_INSTRUCTION,
    TYPE_LABELS,
    TYPE_QUESTION,
    TYPE_REPEAT,
    ErrorRow,
)


def _row(qtype: str, line: int, type_cell: str = "", **cells: str) -> ErrorRow:
    return ErrorRow(
        qtype=qtype,
        line=line,
        reason="缺必填列",
        cells=cells,
        type_cell=type_cell,
    )


def test_csv_error_rows_keep_template_header_and_append_helper_columns():
    """CSV 修正文件：表头 = 标准模板列 + 原行号/错误原因，数据行按题型取标签。"""
    rows = _error_file_csv_rows([_row(TYPE_REPEAT, 7, sentence="Hello")])
    assert rows[0][0] == CSV_TYPE_COLUMN.zh
    assert rows[0][1:-2] == [c.zh for c in CSV_UNION_COLUMNS]
    # CSV 分支沿用原实现的短表头（与 xlsx 的双语表头不同，回传时都会被忽略）
    assert rows[0][-2:] == ["原行号", "错误原因"]
    assert rows[1][0] == TYPE_LABELS[TYPE_REPEAT]
    assert rows[1][-2:] == ["7", "缺必填列"]


def test_csv_type_cell_prefers_original_cell_value():
    """题型列本身无效（qtype="-"）时，保留学生填的原值而不是空标签。"""
    rows = _error_file_csv_rows([_row("-", 4, type_cell="机器阅读")])
    assert rows[1][0] == "机器阅读"


def test_partition_folds_invalid_type_column_into_instruction():
    by_type = _partition_errors_by_type(
        [
            _row(TYPE_QUESTION, 3),
            _row("-", 4, type_cell="机器阅读"),
            _row(TYPE_QUESTION, 5),
        ]
    )
    assert [e.line for e in by_type[TYPE_QUESTION]] == [3, 5]
    assert [e.line for e in by_type[TYPE_INSTRUCTION]] == [4]


def test_error_workbook_one_sheet_per_type_with_formula_guard():
    """xlsx 修正文件：每题型一个 sheet，`=` 开头的值按文本写，不变成公式。"""
    repeat_field = COLUMNS_BY_TYPE[TYPE_REPEAT][0].field
    instruction_field = COLUMNS_BY_TYPE[TYPE_INSTRUCTION][0].field
    data = _build_error_workbook(
        [
            _row(TYPE_REPEAT, 2, **{repeat_field: "=SUM(A1:A2)"}),
            _row(TYPE_INSTRUCTION, 9, **{instruction_field: "说明文字"}),
        ]
    )
    workbook = load_workbook(io.BytesIO(data))
    assert set(workbook.sheetnames) == {
        TYPE_LABELS[TYPE_REPEAT],
        TYPE_LABELS[TYPE_INSTRUCTION],
    }
    sheet = workbook[TYPE_LABELS[TYPE_REPEAT]]
    assert sheet.freeze_panes == "A2"
    # 数据从第 2 行开始；首列就是 `=` 开头的值，必须落成字符串
    assert sheet.cell(row=2, column=1).value == "=SUM(A1:A2)"
    assert sheet.cell(row=2, column=1).data_type == "s"
    assert sheet.max_row >= 2
