"""CSV 单元格安全：防 Excel/WPS 公式注入（OWASP CSV Injection）。

导出里的用户可控文本——学生自填姓名、教师批注、内容标题、班级名——如果
以 = + - @ 或制表符/回车开头，Excel 打开时会当公式求值（可触发 DDE、
外链或命令执行），把导出的 CSV 变成攻击载荷。

处理方式：字符串前缀加一个单引号，Excel 仍按文本显示；非字符串（数值）
原样保留，避免把负数列转成文本。
"""

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> object:
    """单个单元格的公式注入防护（幂等：已加引号的值不会重复加）。"""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def csv_safe_row(row: list[object]) -> list[object]:
    return [csv_safe(cell) for cell in row]
