/**
 * 粗分档自适应小测（placement）前端共享口径。
 *
 * 边界：探针式粗分档，**不是定级、不是考试分数、不发认证**；结果只给建议起点
 * 级别与推荐词库。档位顺序与后端 `PLACEMENT_BAND_ORDER` 一致：
 * KET → PET → CET4 → ADVANCED（ACADEMIC + IELTS_TOEFL 合并顶档）。
 */

import type { BiString } from "@/lib/bi"

/** 本测四档代码（与后端 PLACEMENT_BAND_ORDER 对齐） */
export const PLACEMENT_BAND_ORDER = ["KET", "PET", "CET4", "ADVANCED"] as const

export type PlacementBand = (typeof PLACEMENT_BAND_ORDER)[number]

/** 档位代码 → 双语名称 */
export const PLACEMENT_BAND_LABELS: Record<PlacementBand, BiString> = {
  KET: { zh: "KET（基础）", en: "KET (Basic)" },
  PET: { zh: "PET（入门）", en: "PET (Elementary)" },
  CET4: { zh: "CET-4（中级）", en: "CET-4 (Intermediate)" },
  ADVANCED: {
    zh: "学术 / 雅思托福（进阶）",
    en: "Academic / IELTS-TOEFL (Advanced)",
  },
}

/** 素材限制标识 → 双语说明（与后端 limitation 标识对齐） */
export const PLACEMENT_LIMITATION_LABELS: Record<string, BiString> = {
  material_limited: {
    zh: "素材有限：仅按现有可练词出题，题量少于常规。",
    en: "Limited material: questions use only available words, so there are fewer items.",
  },
}

/** 未识别档位回退为代码本身 */
export function placementBandLabel(band: string): BiString {
  return PLACEMENT_BAND_LABELS[band as PlacementBand] ?? { zh: band, en: band }
}

/** 素材限制说明；none/空 返回 null */
export function placementLimitationLabel(
  limitation?: string | null,
): BiString | null {
  if (!limitation || limitation === "none") return null
  return (
    PLACEMENT_LIMITATION_LABELS[limitation] ?? {
      zh: limitation,
      en: limitation,
    }
  )
}
