import assert from "node:assert/strict"
import test from "node:test"

import {
  canStartReview,
  overdueLabel,
  practiceRoundTitle,
  REVIEW_CAPABILITY_LABELS,
  remainingQuota,
} from "../src/lib/vocab-review.ts"

/**
 * 复习队列摘要派生：额度兜底、开轮条件、能力维度与逾期双语文案。
 * 入参取后端摘要最小结构；不触达调度间隔与留存率口径。
 */

test("remainingQuota：上限减已复习，下限为 0，不出现负额度", () => {
  assert.equal(remainingQuota({ dailyLimit: 20, reviewedTodayCount: 5 }), 15)
  assert.equal(remainingQuota({ dailyLimit: 20, reviewedTodayCount: 20 }), 0)
  assert.equal(remainingQuota({ dailyLimit: 20, reviewedTodayCount: 24 }), 0)
})

test("canStartReview：有到期词条且额度未用完才可开轮", () => {
  assert.equal(
    canStartReview({
      dailyLimit: 20,
      reviewedTodayCount: 0,
      dueTodayCount: 3,
      remainingTodayCount: 20,
    }),
    true,
  )
  assert.equal(
    canStartReview({
      dailyLimit: 20,
      reviewedTodayCount: 20,
      dueTodayCount: 3,
      remainingTodayCount: 0,
    }),
    false,
  )
  assert.equal(
    canStartReview({
      dailyLimit: 20,
      reviewedTodayCount: 0,
      dueTodayCount: 0,
      remainingTodayCount: 20,
    }),
    false,
  )
})

test("overdueLabel：0 为今日到期；逾期单复数与中英分别正确", () => {
  assert.deepEqual(overdueLabel(0), { zh: "今日到期", en: "Due today" })
  assert.deepEqual(overdueLabel(1), { zh: "逾期 1 天", en: "1 day overdue" })
  assert.deepEqual(overdueLabel(3), { zh: "逾期 3 天", en: "3 days overdue" })
  assert.deepEqual(overdueLabel(-2), { zh: "今日到期", en: "Due today" })
})

test("能力维度标签：认读/拼写双语齐全，两套状态互不顶替", () => {
  assert.equal(REVIEW_CAPABILITY_LABELS.recognition.zh, "认读")
  assert.equal(REVIEW_CAPABILITY_LABELS.recognition.en, "Recognition")
  assert.equal(REVIEW_CAPABILITY_LABELS.spelling.zh, "拼写")
  assert.equal(REVIEW_CAPABILITY_LABELS.spelling.en, "Spelling")
})

test("practiceRoundTitle：复习轮标题双语兜底，任务内容标题不翻译", () => {
  assert.deepEqual(practiceRoundTitle("review_fsrs", "复习队列"), {
    zh: "记忆复习",
    en: "Scheduled Review",
  })
  assert.deepEqual(practiceRoundTitle("review", "错词复习"), {
    zh: "错词复习",
    en: "Wrong-word Review",
  })
  assert.deepEqual(practiceRoundTitle("task", "E2E517 第一批四题型任务"), {
    zh: "E2E517 第一批四题型任务",
    en: "E2E517 第一批四题型任务",
  })
  assert.deepEqual(practiceRoundTitle("self", ""), {
    zh: "自主练习",
    en: "Self Practice",
  })
})
