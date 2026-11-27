import type { FarmBoardSummary, PkBoardSummary } from "@/client"

/**
 * 课堂看板词汇摘要纯判定：PK / 农场卡片是否有可展示内容。
 *
 * 模块未开通或整段为 null/全空时整卡不渲染；这里只做空值归一，不聚合学生端数据。
 */

/** PK 摘要是否有可展示内容；模块未开通 / 全空时整卡不渲染。 */
export function hasPkSummary(pk: PkBoardSummary | null | undefined): boolean {
  if (!pk) return false
  return [
    pk.open,
    pk.queue_count,
    pk.active_match_count,
    pk.matches_this_week,
    pk.last_match_at,
    pk.last_match,
  ].some((value) => value !== null && value !== undefined)
}

/** 农场摘要是否有可展示内容；模块未开通 / 全空时整卡不渲染。 */
export function hasFarmSummary(
  farm: FarmBoardSummary | null | undefined,
): boolean {
  if (!farm) return false
  const scalar = [
    farm.participants,
    farm.mature_plots,
    farm.harvested_total,
  ].some((value) => value !== null && value !== undefined)
  return (
    scalar ||
    (farm.badge_counts?.length ?? 0) > 0 ||
    (farm.top_harvesters?.length ?? 0) > 0
  )
}
