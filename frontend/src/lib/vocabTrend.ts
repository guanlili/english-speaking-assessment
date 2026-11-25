import type { VocabularyTrendPeriod } from "@/client"

/**
 * 教师词汇趋势（#517 C）的展示判定与格式化纯函数。
 *
 * 口径约束（与后端 `services/vocabulary_trend.py` 一致）：
 * - 完成率 / 首答正确率为 0..100 取整；无目标 / 无首答时是 ``null``，
 *   界面显示 `–`，**不得**用 `?? 0` 折算成 0%。
 * - 图表缺失周期留空（断口），不补 0 点。
 * - `due_unreviewed` 是当前 FSRS 状态回算，历史周期仅供教学参考。
 */

export type TrendGranularity = "week" | "month"

export interface TrendPoint {
  /** x 轴周期短标签 */
  label: string
  /** 率值 0..100；缺失为 null（曲线断口） */
  value: number | null
}

/** 率值格式化：null/undefined → `–`；否则按 0..100 取整显示百分比。 */
export function formatTrendRate(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–"
  return `${Math.round(value)}%`
}

/**
 * 周期短标签：week 取周一起 `MM/DD`；month 取 `YYYY-MM`。
 * 只做字符串切片，不做时区换算（后端区间已按 PRACTICE_TZ 对齐）。
 */
export function trendPeriodLabel(
  periodStart: string,
  granularity: TrendGranularity,
): string {
  const datePart = periodStart.slice(0, 10)
  if (granularity === "month") return datePart.slice(0, 7)
  const [, month, day] = datePart.split("-")
  return `${month}/${day}`
}

/** 周期数组 → 图表点；缺失率保留 null，不补 0。 */
export function trendPoints(
  periods: VocabularyTrendPeriod[],
  pick: (period: VocabularyTrendPeriod) => number | null | undefined,
  granularity: TrendGranularity,
): TrendPoint[] {
  return periods.map((period) => ({
    label: trendPeriodLabel(period.period_start, granularity),
    value: pick(period) ?? null,
  }))
}

/** 任一周期存在可绘制率值即视为有趋势数据；全部缺失返回 false。 */
export function trendHasRate(
  periods: VocabularyTrendPeriod[],
  pick: (period: VocabularyTrendPeriod) => number | null | undefined,
): boolean {
  return periods.some((period) => {
    const value = pick(period)
    return value !== null && value !== undefined
  })
}

/** 掌握度分段词条总数（低 + 中 + 高 + 无数据）。 */
export function trendBandTotal(period: VocabularyTrendPeriod): number {
  return (
    (period.low_count ?? 0) +
    (period.mid_count ?? 0) +
    (period.high_count ?? 0) +
    (period.no_data_count ?? 0)
  )
}

/**
 * 某一分段占比（0..1）；总分母为 0 时返回 null，
 * 避免除零把空周期画成满条。
 */
export function trendBandShare(
  period: VocabularyTrendPeriod,
  key: "low" | "mid" | "high" | "no_data",
): number | null {
  const total = trendBandTotal(period)
  if (total <= 0) return null
  const count =
    key === "low"
      ? (period.low_count ?? 0)
      : key === "mid"
        ? (period.mid_count ?? 0)
        : key === "high"
          ? (period.high_count ?? 0)
          : (period.no_data_count ?? 0)
  return count / total
}

/**
 * 率值归一化到 [0,1] 纵向坐标；null 原样保留（断口）。
 * 超出 [min, max] 的值钳制在边界内。
 */
export function normalizeTrendRate(
  value: number | null | undefined,
  min = 0,
  max = 100,
): number | null {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return null
  }
  const span = max - min || 1
  const clamped = Math.min(max, Math.max(min, value))
  return (clamped - min) / span
}
