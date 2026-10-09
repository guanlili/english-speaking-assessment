/**
 * CSV 下载工具：统一三处各自实现的导出逻辑。
 *
 * - RFC 4180 转义：字段含引号/逗号/换行时整体加引号、内部引号翻倍
 *   （学生姓名含逗号曾破坏发布历史的导出列结构）
 * - 公式注入防护：用户可控文本以 =/+/-/@ 或制表/回车开头时加 `'` 前缀，
 *   防止表格软件把姓名等字段当公式执行（与后端 _csv_text_cell 同规则）
 * - <a> 必须 append 到 body 再 click：部分浏览器（Firefox）否则不触发下载
 * - BOM 前缀让 Excel 正确识别 UTF-8 中文
 */
const CSV_FORMULA_PREFIX_RE = /^[=+\-@\t\r]/

/** 单元格格式化：公式注入防护（' 前缀）+ RFC 4180 引号转义。 */
export function formatCsvCell(
  cell: string | number | null | undefined,
): string {
  let s = cell == null ? "" : String(cell)
  if (typeof cell === "string" && CSV_FORMULA_PREFIX_RE.test(s)) {
    s = `'${s}`
  }
  return /[",\r\n]/.test(s) ? `"${s.split('"').join('""')}"` : s
}

export function downloadCsv(
  rows: (string | number | null | undefined)[][],
  filename: string,
): void {
  const csv = rows.map((row) => row.map(formatCsvCell).join(",")).join("\r\n")
  const url = URL.createObjectURL(
    new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }),
  )
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
