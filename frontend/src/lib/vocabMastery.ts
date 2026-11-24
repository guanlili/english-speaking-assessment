import type {
  VocabularyMasteryReport,
  VocabularyMasteryWordRow,
} from "@/client"
import type { BiString } from "@/lib/i18n"

/**
 * 班级掌握度前端口径（与后端 `services/vocabulary_mastery.py` 对齐）：
 *
 * - 掌握度 = 窗口内教师任务轮首答正确率分段 + FSRS 状态分布 + 到期未复习条目数；
 *   **不是考试分数，也不是能力等级**，仅用于安排复习。
 * - 分段：<60% 偏弱；60–85%（含 60 与 85）中等；>85% 较稳；无首答 no_data。
 * - 零作答正确率为 null，界面显示 –，不折算成 0%。
 * - `wrong_count` 历史错误次数不进本口径。
 */

export const MASTERY_WINDOW_DAYS = [7, 30, 90] as const
export const MASTERY_DEFAULT_WINDOW_DAYS = 30

export type MasteryBand = "low" | "mid" | "high" | "no_data"
export type MasteryFsrsState = "new" | "learning" | "review"

export type MasteryReportSource = VocabularyMasteryReport
export type MasteryWordSource = VocabularyMasteryWordRow

export const MASTERY_BAND_LABEL: Record<MasteryBand, BiString> = {
  low: { zh: "偏弱（<60%）", en: "Below 60%" },
  mid: { zh: "中等（60–85%）", en: "60–85%" },
  high: { zh: "较稳（>85%）", en: "Above 85%" },
  no_data: { zh: "暂无首答", en: "No first answers" },
}

export const FSRS_STATE_LABEL: Record<MasteryFsrsState, BiString> = {
  new: { zh: "新词", en: "New" },
  learning: { zh: "学习中", en: "Learning" },
  review: { zh: "待复习", en: "Review" },
}

/** 正确率展示：无首答返回 –，不折算 0%。 */
export function masteryAccuracyText(rate: number | null | undefined): string {
  return rate == null ? "–" : `${rate}%`
}

export interface MasteryCsvLabels {
  headword: string
  meaningZh: string
  correctFirst: string
  answered: string
  accuracy: string
  band: string
  fsrsNew: string
  fsrsLearning: string
  fsrsReview: string
  due: string
  bandLow: string
  bandMid: string
  bandHigh: string
  bandNoData: string
}

const BAND_CSV: Record<MasteryBand, (labels: MasteryCsvLabels) => string> = {
  low: (l) => l.bandLow,
  mid: (l) => l.bandMid,
  high: (l) => l.bandHigh,
  no_data: (l) => l.bandNoData,
}

/** 逐词掌握度 CSV：表头 + 行；正确率无数据写 "-"，不写 0%。 */
export function masteryCsvTable(
  report: MasteryReportSource,
  labels: MasteryCsvLabels,
): (string | number | null)[][] {
  const words = report.words ?? []
  const header = [
    labels.headword,
    labels.meaningZh,
    labels.correctFirst,
    labels.answered,
    labels.accuracy,
    labels.band,
    labels.fsrsNew,
    labels.fsrsLearning,
    labels.fsrsReview,
    labels.due,
  ]
  const rows = words.map((row) => {
    const band = (row.band ?? "no_data") as MasteryBand
    return [
      row.headword,
      row.meaning_zh,
      row.correct_first_count ?? 0,
      row.answered_count ?? 0,
      row.accuracy_rate == null ? "-" : `${row.accuracy_rate}%`,
      BAND_CSV[band](labels),
      row.fsrs_new ?? 0,
      row.fsrs_learning ?? 0,
      row.fsrs_review ?? 0,
      row.due_count ?? 0,
    ]
  })
  return [header, ...rows]
}
