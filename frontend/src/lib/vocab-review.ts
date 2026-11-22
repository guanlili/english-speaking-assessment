/**
 * FSRS 复习队列前端派生计算（纯函数层，无 JSX，node --test 可直接测）。
 * 后端摘要口径见 `GET /vocabulary/student/review-queue`；这里只做展示侧兜底推导，
 * 不重新计算调度间隔，也不估算记忆留存率。
 */

import type { BiString } from "@/lib/bi"

/** 能力维度：recognition 认读（选择题类）/ spelling 拼写（输入词形类） */
export type ReviewCapability = "recognition" | "spelling"

export interface ReviewQueueSummary {
  dailyLimit: number
  reviewedTodayCount: number
  dueTodayCount: number
  remainingTodayCount: number
}

/** 今日剩余额度：上限 − 今日已复习，下限 0（与后端截断口径一致）。 */
export function remainingQuota(
  summary: Pick<ReviewQueueSummary, "dailyLimit" | "reviewedTodayCount">,
): number {
  return Math.max(0, summary.dailyLimit - summary.reviewedTodayCount)
}

/** 是否能开一轮：有到期词条且今日额度未用完。 */
export function canStartReview(summary: ReviewQueueSummary): boolean {
  return summary.dueTodayCount > 0 && summary.remainingTodayCount > 0
}

/** 认读 / 拼写能力维度双语文案（两套状态各自独立，不互相顶替）。 */
export const REVIEW_CAPABILITY_LABELS: Record<ReviewCapability, BiString> = {
  recognition: { zh: "认读", en: "Recognition" },
  spelling: { zh: "拼写", en: "Spelling" },
}

/**
 * 轮次标题的双语兜底。
 *
 * 任务轮标题是教师/词库内容（人名、书名），原样展示；自主/复习轮的
 * 标题来自后端固定串，英文界面下必须翻译，否则出现「复习队列」直出。
 */
export function practiceRoundTitle(kind: string, title: string): BiString {
  if (kind === "review_fsrs") return { zh: "记忆复习", en: "Scheduled Review" }
  if (kind === "review") return { zh: "错词复习", en: "Wrong-word Review" }
  if (kind === "self" && !title.trim())
    return { zh: "自主练习", en: "Self Practice" }
  return { zh: title, en: title }
}

/** 逾期天数 → 双语展示文案（0 = 今日到期，不足一天不计逾期）。 */
export function overdueLabel(days: number): BiString {
  if (days <= 0) return { zh: "今日到期", en: "Due today" }
  return {
    zh: `逾期 ${days} 天`,
    en: `${days} day${days === 1 ? "" : "s"} overdue`,
  }
}
