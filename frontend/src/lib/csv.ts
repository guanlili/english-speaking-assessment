/**
 * CSV 下载工具：统一三处各自实现的导出逻辑。
 *
 * - RFC 4180 转义：字段含引号/逗号/换行时整体加引号、内部引号翻倍
 *   （学生姓名含逗号曾破坏发布历史的导出列结构）
 * - <a> 必须 append 到 body 再 click：部分浏览器（Firefox）否则不触发下载
 * - BOM 前缀让 Excel 正确识别 UTF-8 中文
 */
export function downloadCsv(
  rows: (string | number | null | undefined)[][],
  filename: string,
): void {
  const quoteCell = (cell: string | number | null | undefined): string => {
    const s = cell == null ? "" : String(cell)
    return /[",\r\n]/.test(s) ? `"${s.split('"').join('""')}"` : s
  }
  const csv = rows.map((row) => row.map(quoteCell).join(",")).join("\r\n")
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
