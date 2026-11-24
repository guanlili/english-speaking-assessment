import assert from "node:assert/strict"
import { test } from "node:test"

import { formatCsvCell } from "../src/lib/csv.ts"
import {
  buildWrongWordCsvRows,
  summarizeClassFirstTry,
  type WrongWordCsvHeaders,
  type WrongWordCsvSource,
  wrongWordCsvTable,
} from "../src/lib/vocabResults.ts"

const HEADERS: WrongWordCsvHeaders = {
  headword: "Word",
  partOfSpeech: "POS",
  meaningZh: "Meaning",
  answeredOfRoster: "Answered/Roster",
  correctFirst: "First-try correct",
  errorCount: "Misses",
  errorRate: "Miss rate",
  misspellings: "Common misspellings",
}

function word(partial: Partial<WrongWordCsvSource>): WrongWordCsvSource {
  return {
    headword: "apple",
    meaning_zh: "苹果",
    answered_count: 4,
    correct_first_count: 3,
    error_count: 1,
    misspellings: [],
    ...partial,
  }
}

test("班级聚合：全班零作答时正确率为 null（界面显示 –）", () => {
  const summary = summarizeClassFirstTry([
    { answered_count: 0, correct_first_count: 0 },
    { answered_count: 0, correct_first_count: 0 },
  ])
  assert.deepEqual(summary, { answered: 0, correct: 0, accuracy: null })
})

test("班级聚合：混合正确/错误按分子分母求和并取整", () => {
  const summary = summarizeClassFirstTry([
    { answered_count: 4, correct_first_count: 3 },
    { answered_count: 6, correct_first_count: 2 },
    { answered_count: 0, correct_first_count: 0 },
  ])
  // 正确 5 / 已答 10 = 50%
  assert.deepEqual(summary, { answered: 10, correct: 5, accuracy: 50 })
})

test("错词行：仅保留 error_count > 0，零作答词错误率显示 –", () => {
  const rows = buildWrongWordCsvRows(
    [
      word({ headword: "correct", error_count: 0, answered_count: 5 }),
      word({
        headword: "miss",
        answered_count: 0,
        correct_first_count: 0,
        error_count: 2,
      }),
      word({
        headword: "mix",
        answered_count: 4,
        correct_first_count: 1,
        error_count: 3,
        misspellings: [
          { answer: "miks", count: 2 },
          { answer: "mixx", count: 1 },
        ],
      }),
    ],
    6,
  )
  assert.equal(rows.length, 2)
  assert.equal(rows[0].headword, "miss")
  assert.equal(rows[0].answeredOfRoster, "0/6")
  assert.equal(rows[0].errorRate, "–")
  assert.equal(rows[1].answeredOfRoster, "4/6")
  assert.equal(rows[1].correctFirst, 1)
  assert.equal(rows[1].errorCount, 3)
  // 3/4 = 75%
  assert.equal(rows[1].errorRate, "75%")
  assert.equal(rows[1].misspellings, "miks×2; mixx×1")
})

test("错词表：空错词载荷只输出表头，不产生数据行", () => {
  const table = wrongWordCsvTable([], 8, HEADERS)
  assert.equal(table.length, 1)
  assert.deepEqual(table[0], Object.values(HEADERS))
})

test("错词表：词性缺省时输出空字符串，不丢列", () => {
  const table = wrongWordCsvTable([word({ part_of_speech: null })], 5, HEADERS)
  assert.equal(table.length, 2)
  assert.equal(table[1][1], "")
})

test("CSV 转义：逗号/引号/换行与公式注入按 csv 规则处理", () => {
  const tricky: WrongWordCsvSource = word({
    headword: 'evil, "quote"',
    meaning_zh: "含\n换行，逗号",
    misspellings: [{ answer: "=SUM(A1)", count: 1 }],
  })
  const table = wrongWordCsvTable([tricky], 3, HEADERS)
  const escaped = table[1].map((cell) => formatCsvCell(cell))
  assert.equal(escaped[0], `"evil, ""quote"""`)
  // 词性缺省 → 空字符串，不触发转义
  assert.equal(escaped[1], "")
  assert.equal(escaped[2], `"含\n换行，逗号"`)
  // 误拼字段以 = 开头：加 ' 公式前缀；无逗号/引号/换行则不再加外层引号
  assert.equal(escaped[7], "'=SUM(A1)×1")
})
