import type { MySessionSummary } from "@/client"
import type { BiString } from "@/lib/bi"

/** 历史练习行的可搜索文案：发布练习用题单标题，自主/探索轮出双语文案。 */
export function sessionSearchLabel(
  row: MySessionSummary,
  t: (b: BiString) => string,
): string {
  return (
    row.title ??
    t(
      row.mode === "explore"
        ? { zh: "主题探索", en: "Topic explore" }
        : { zh: "自主练习", en: "Self practice" },
    )
  )
}

/**
 * 历史练习关键词过滤（本地过滤，数据已全量返回）。
 * 匹配字段：题单标题 / 双语文案 / 练习日期（YYYY-MM-DD），忽略大小写。
 */
export function filterSessions(
  rows: MySessionSummary[],
  query: string,
  t: (b: BiString) => string,
): MySessionSummary[] {
  const q = query.trim().toLowerCase()
  if (!q) return rows
  return rows.filter((row) => {
    const label = sessionSearchLabel(row, t)
    return (
      label.toLowerCase().includes(q) || String(row.session_date).includes(q)
    )
  })
}
