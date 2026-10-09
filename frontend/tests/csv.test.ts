import assert from "node:assert/strict"
import test from "node:test"
import { formatCsvCell } from "../src/lib/csv.ts"

/**
 * CSV 单元格格式化：公式注入防护（=/+/-/@ 与制表/回车开头加 ' 前缀）
 * 与 RFC 4180 转义（引号/逗号/换行）共存；数字类型原样保留。
 * 与后端 _csv_text_cell 保持同一规则。
 */

test("公式开头的学生文本加单引号前缀", () => {
  assert.equal(formatCsvCell("=HYPERLINK(\"http://evil\",\"x\")"), `"'=HYPERLINK(""http://evil"",""x"")"`)
  assert.equal(formatCsvCell("+1|calc"), "'+1|calc")
  assert.equal(formatCsvCell("-2+3|cmd"), "'-2+3|cmd")
  assert.equal(formatCsvCell("@SUM(A1)", ), "'@SUM(A1)")
  assert.equal(formatCsvCell("\tTabStart"), "'\tTabStart")
  // 前缀后仍含 \r：既加 ' 前缀又按 RFC 4180 整体加引号
  assert.equal(formatCsvCell("\rCRStart"), '"\'\rCRStart"')
})

test("普通文本、数字与空值不受影响", () => {
  assert.equal(formatCsvCell("张三"), "张三")
  assert.equal(formatCsvCell(100), "100")
  assert.equal(formatCsvCell(-3), "-3")
  assert.equal(formatCsvCell(null), "")
  assert.equal(formatCsvCell(undefined), "")
  // 不以这些符号开头的文本即使包含它们也不加前缀
  assert.equal(formatCsvCell("a=b"), "a=b")
})

test("含引号/逗号/换行的字段按 RFC 4180 转义", () => {
  assert.equal(formatCsvCell("含,逗号"), `"含,逗号"`)
  assert.equal(formatCsvCell('含"引号'), `"含""引号"`)
  assert.equal(formatCsvCell("含\n换行"), `"含\n换行"`)
  // 公式前缀与转义共存：先加 ' 再整体按需加引号
  assert.equal(formatCsvCell("=a,b"), `"'=a,b"`)
})
