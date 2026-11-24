import assert from "node:assert/strict"
import { test } from "node:test"

import {
  type MasteryCsvLabels,
  type MasteryReportSource,
  masteryAccuracyText,
  masteryCsvTable,
} from "../src/lib/vocabMastery.ts"

const LABELS: MasteryCsvLabels = {
  headword: "Word",
  meaningZh: "Meaning",
  correctFirst: "First-try correct",
  answered: "Answered",
  accuracy: "First-try accuracy",
  band: "Band",
  fsrsNew: "New",
  fsrsLearning: "Learning",
  fsrsReview: "Review",
  due: "Due",
  bandLow: "Below 60%",
  bandMid: "60–85%",
  bandHigh: "Above 85%",
  bandNoData: "No first answers",
}

function report(): MasteryReportSource {
  return {
    classroom_code: "DEMO01",
    generated_at: "2026-11-24T00:00:00Z",
    window_days: 30,
    scope: "assignment",
    assignment_id: null,
    answered_count: 3,
    correct_first_count: 2,
    accuracy_rate: 67,
    low_count: 1,
    mid_count: 1,
    high_count: 0,
    no_data_count: 1,
    fsrs_new: 1,
    fsrs_learning: 1,
    fsrs_review: 1,
    due_count: 1,
    words: [
      {
        word_id: "11111111-1111-1111-1111-111111111111",
        headword: "apple",
        meaning_zh: "苹果",
        answered_count: 2,
        correct_first_count: 1,
        accuracy_rate: 50,
        band: "low",
        fsrs_new: 0,
        fsrs_learning: 1,
        fsrs_review: 0,
        due_count: 1,
      },
      {
        word_id: "22222222-2222-2222-2222-222222222222",
        headword: "banana",
        meaning_zh: "香蕉",
        answered_count: 1,
        correct_first_count: 1,
        accuracy_rate: 100,
        band: "high",
        fsrs_new: 0,
        fsrs_learning: 0,
        fsrs_review: 1,
        due_count: 0,
      },
      {
        word_id: "33333333-3333-3333-3333-333333333333",
        headword: "cat",
        meaning_zh: "猫",
        answered_count: 0,
        correct_first_count: 0,
        accuracy_rate: null,
        band: "no_data",
        fsrs_new: 1,
        fsrs_learning: 0,
        fsrs_review: 0,
        due_count: 0,
      },
    ],
  }
}

test("正确率展示：无首答为 –，有数据带百分号", () => {
  assert.equal(masteryAccuracyText(null), "–")
  assert.equal(masteryAccuracyText(50), "50%")
})

test("CSV：表头 10 列；无数据行正确率写 -，分段与 FSRS 条目数透传", () => {
  const table = masteryCsvTable(report(), LABELS)
  assert.equal(table.length, 4)
  assert.equal(table[0].length, 10)

  const apple = table[1]
  assert.deepEqual(apple, [
    "apple",
    "苹果",
    1,
    2,
    "50%",
    "Below 60%",
    0,
    1,
    0,
    1,
  ])

  const cat = table[3]
  assert.equal(cat[4], "-")
  assert.equal(cat[5], "No first answers")
  assert.equal(cat[6], 1) // 新词
  assert.equal(cat[8], 0) // 待复习
})
