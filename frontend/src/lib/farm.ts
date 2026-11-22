/**
 * 专注农场纯函数（无 JSX，node --test 可直接测）。
 *
 * 口径对齐后端 `docs/vocabulary-pk-farm-design-20261122.md` §4：
 * - 四阶段阈值 0 / 5 / 12 / 20；≥20 成熟可收获；
 * - 每有效首答 +1，每日成长上限 30；收获 +10 XP，每日农场 XP 上限 10；
 * - XP / streak / 徽章都复用既有课堂账本，本模块不新建并行积分。
 */

import type { BiString } from "@/lib/i18n"

export const FARM_STAGE_THRESHOLDS = [0, 5, 12, 20] as const
export const FARM_MATURE_POINTS = 20
export const FARM_GROWTH_DAILY_CAP = 30
export const FARM_HARVEST_XP = 10
export const FARM_XP_DAILY_CAP = 10

export type FarmStage = 0 | 1 | 2 | 3

/** 由当前地块点数派生四阶段：0 种子 / 1 发芽 / 2 生长 / 3 成熟。 */
export function farmStage(points: number): FarmStage {
  if (points >= FARM_STAGE_THRESHOLDS[3]) return 3
  if (points >= FARM_STAGE_THRESHOLDS[2]) return 2
  if (points >= FARM_STAGE_THRESHOLDS[1]) return 1
  return 0
}

/** 距成熟还差几点；已成熟为 0。 */
export function pointsToMature(points: number): number {
  return Math.max(0, FARM_MATURE_POINTS - points)
}

export type HarvestState = "ready" | "locked" | "xp-capped"

export interface HarvestStateInput {
  ready_to_harvest: boolean
  today_farm_xp?: number | null
  farm_xp_daily_cap?: number | null
}

/**
 * 收获按钮三态：
 * - `locked`：未成熟；
 * - `xp-capped`：已成熟但今日农场 XP 已达上限；
 * - `ready`：可收获。
 */
export function harvestState(view: HarvestStateInput): HarvestState {
  if (!view.ready_to_harvest) return "locked"
  const xp = view.today_farm_xp ?? 0
  const cap = view.farm_xp_daily_cap ?? FARM_XP_DAILY_CAP
  if (xp >= cap) return "xp-capped"
  return "ready"
}

export const FARM_STAGE_LABELS: Record<FarmStage, BiString> = {
  0: { zh: "种子", en: "Seed" },
  1: { zh: "发芽", en: "Sprout" },
  2: { zh: "生长", en: "Growing" },
  3: { zh: "成熟", en: "Mature" },
}

export const FARM_STAGE_HINTS: Record<FarmStage, BiString> = {
  0: { zh: "完成练习种下种子", en: "Complete practice to plant the seed" },
  1: {
    zh: "继续练习，芽正在长大",
    en: "Keep practicing — the sprout is growing",
  },
  2: { zh: "再练一练，快成熟了", en: "A bit more practice and it will mature" },
  3: { zh: "已经成熟，可以收获", en: "It's mature and ready to harvest" },
}

export const FARM_SOURCE_FARM: BiString = {
  zh: "专注农场",
  en: "Focus Farm",
}
export const FARM_SOURCE_CLASSROOM: BiString = {
  zh: "课堂档案/每日计划",
  en: "Classroom profile / daily plan",
}

/** 徽章来源双语标注：农场徽章归农场，其余归既有课堂档案/每日计划。 */
export function badgeSourceLabel(badge: {
  key: string
  source?: string | null
}): BiString {
  if (badge.key.startsWith("farm_") || badge.source === "专注农场") {
    return FARM_SOURCE_FARM
  }
  return FARM_SOURCE_CLASSROOM
}

/**
 * 徽章名称/描述的双语映射。
 *
 * 徽章定义在后端中文账本（`scoring/gamification.py`），前端不能把中文直接
 * 显示在英文界面；这里按 key 提供双语，未知 key 回落后端原文（不改后端契约）。
 */
export const FARM_BADGE_TEXT: Record<
  string,
  { label: BiString; description: BiString }
> = {
  first_round: {
    label: { zh: "初次开口", en: "First Words" },
    description: { zh: "完成第一轮练习", en: "Complete your first round" },
  },
  streak_3: {
    label: { zh: "三连胜", en: "3-Day Streak" },
    description: { zh: "连续 3 天完成练习", en: "Practice 3 days in a row" },
  },
  streak_7: {
    label: { zh: "一周坚持", en: "One Week Streak" },
    description: { zh: "连续 7 天完成练习", en: "Practice 7 days in a row" },
  },
  ten_rounds: {
    label: { zh: "十轮达人", en: "Ten Rounds" },
    description: {
      zh: "累计完成 10 轮练习",
      en: "Complete 10 rounds in total",
    },
  },
  reached_b2: {
    label: { zh: "登上高档", en: "Reached B2" },
    description: {
      zh: "练习档位升到 B2",
      en: "Your practice level reached B2",
    },
  },
  farm_first_harvest: {
    label: { zh: "首次收获", en: "First Harvest" },
    description: {
      zh: "第一次收获成熟的作物",
      en: "Harvest your first mature crop",
    },
  },
  farm_harvest_7: {
    label: { zh: "七次收获", en: "Seven Harvests" },
    description: { zh: "累计收获 7 次", en: "Harvest 7 times in total" },
  },
}

/** 徽章双语文本；未知 key 保留后端原文，避免英文界面出现中文直出。 */
export function badgeText(badge: {
  key: string
  label: string
  description?: string | null
}): { label: BiString; description: BiString | null } {
  const mapped = FARM_BADGE_TEXT[badge.key]
  if (mapped) return { label: mapped.label, description: mapped.description }
  return {
    label: { zh: badge.label, en: badge.label },
    description: badge.description
      ? { zh: badge.description, en: badge.description }
      : null,
  }
}
