import assert from "node:assert/strict"
import { test } from "node:test"

import { classTrendHasData, classTrendPoints } from "../src/lib/class-trend.ts"

function day(date: string, questionAvg: number | null = null) {
  return { date, question_avg: questionAvg }
}

test("classTrendHasData：空数组无数据", () => {
  assert.equal(classTrendHasData([]), false)
})

test("classTrendHasData：全部缺失均分时无数据", () => {
  assert.equal(classTrendHasData([day("2026-10-19"), day("2026-10-20")]), false)
})

test("classTrendHasData：任一练习日有均分即视为有数据", () => {
  assert.equal(
    classTrendHasData([day("2026-10-19"), day("2026-10-20", 78.5)]),
    true,
  )
})

test("classTrendPoints：空数组映射为空点集", () => {
  assert.deepEqual(classTrendPoints([]), [])
})

test("classTrendPoints：保留日期并把缺失均分映射为 null（曲线断口）", () => {
  assert.deepEqual(
    classTrendPoints([day("2026-10-19", 80), day("2026-10-20")]),
    [
      { label: "2026-10-19", value: 80 },
      { label: "2026-10-20", value: null },
    ],
  )
})
