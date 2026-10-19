import type { ClassTrendDay } from "@/client"

/**
 * 班级趋势卡片的数据判定（纯函数，供单测与渲染共用）。
 */

/** 是否有可绘制的均分数据（任一练习日存在问答均分）。 */
export function classTrendHasData(days: ClassTrendDay[]): boolean {
  return days.some(
    (d) => d.question_avg !== null && d.question_avg !== undefined,
  )
}

/** 映射成 TrailChart 点：日期 + 问答均分（缺失日取 null，曲线断口）。 */
export function classTrendPoints(days: ClassTrendDay[]) {
  return days.map((d) => ({
    label: d.date,
    value: d.question_avg ?? null,
  }))
}
