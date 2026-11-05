"""CSV 公式注入防护（OWASP CSV Injection）。"""

from app.services.csv_safety import csv_safe, csv_safe_row
from app.services.usage_export import _csv

PAYLOAD = "=cmd|' /C calc'!A0"


def test_formula_prefixes_are_neutralized() -> None:
    for prefix in ("=", "+", "-", "@", "\t", "\r"):
        assert csv_safe(prefix + PAYLOAD) == "'" + prefix + PAYLOAD


def test_plain_text_is_untouched() -> None:
    assert csv_safe("张三") == "张三"
    assert csv_safe("") == ""
    assert csv_safe("hello=world") == "hello=world"


def test_non_string_cells_are_untouched() -> None:
    # 数值列（含负数）不能被加引号，否则 Excel 里从数值退化成文本
    assert csv_safe(-12.5) == -12.5
    assert csv_safe(0) == 0
    assert csv_safe(None) is None


def test_csv_safe_row_maps_every_cell() -> None:
    assert csv_safe_row(["=1", 2, None, "-3"]) == ["'=1", 2, None, "'-3"]


def test_usage_export_csv_neutralizes_user_text() -> None:
    """student_name / teacher_feedback 这类用户可控列走真实导出入口。"""
    buf = _csv([["学生", "反馈", "总分"], [PAYLOAD, "-42", 3.5]])
    content = buf.getvalue()
    assert f"'{PAYLOAD}" in content
    assert "'-42" in content
    assert "3.5" in content
