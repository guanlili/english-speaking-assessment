import type { DimensionPoint } from "@/client"

/**
 * 四维趋势的展示判定与标题文案（成长页诊断卡用）。
 *
 * 判定规则：只要有作答数据点（≥1 个）就展示图表——单次作答也要显示
 * 单点，避免用户看到空白区域；组件内部对完全无点的维度自行降级。
 * 标题注明实际计入的作答次数：接口按时间窗聚合，最多给出最近 14 次，
 * 明确范围防止被误读为"全程趋势"。
 */

export function dimensionTrendVisible(
  points: DimensionPoint[] | null | undefined,
): boolean {
  return Array.isArray(points) && points.length > 0
}

export function dimensionTrendCaption(count: number): {
  zh: string
  en: string
} {
  const n = Math.max(count, 0)
  return {
    zh: `四维趋势（最近 ${n} 次问答）`,
    en: `Dimension trend (last ${n} Q&A rounds)`,
  }
}
