import assert from "node:assert/strict"
import { test } from "node:test"
import type { VocabularyTrendPeriod } from "../src/client/types.gen.ts"
import {
  formatTrendRate,
  normalizeTrendRate,
  trendBandShare,
  trendBandTotal,
  trendHasRate,
  trendPeriodLabel,
  trendPoints,
} from "../src/lib/vocabTrend.ts"

function period(
  overrides: Partial<VocabularyTrendPeriod> = {},
): VocabularyTrendPeriod {
  return {
    period_start: "2026-11-23",
    period_end: "2026-11-29",
    ...overrides,
  }
}

test("formatTrendRate：null / undefined 显示 –，不折算 0%", () => {
  assert.equal(formatTrendRate(null), "–")
  assert.equal(formatTrendRate(undefined), "–")
})

test("formatTrendRate：0 显示 0%，100 显示 100%", () => {
  assert.equal(formatTrendRate(0), "0%")
  assert.equal(formatTrendRate(100), "100%")
})

test("formatTrendRate：小数按四舍五入取整", () => {
  assert.equal(formatTrendRate(42.4), "42%")
  assert.equal(formatTrendRate(42.6), "43%")
})

test("trendPeriodLabel：week 取周一起 MM/DD", () => {
  assert.equal(trendPeriodLabel("2026-11-23", "week"), "11/23")
  assert.equal(trendPeriodLabel("2026-10-05T00:00:00", "week"), "10/05")
})

test("trendPeriodLabel：month 取 YYYY-MM", () => {
  assert.equal(trendPeriodLabel("2026-11-01", "month"), "2026-11")
  assert.equal(trendPeriodLabel("2026-02-15T00:00:00", "month"), "2026-02")
})

test("trendPoints：缺失率保留 null（曲线断口），不补 0", () => {
  const periods = [
    period({ period_start: "2026-11-16", completion_rate: 80 }),
    period({ period_start: "2026-11-23", completion_rate: null }),
  ]
  const points = trendPoints(periods, (p) => p.completion_rate, "week")
  assert.deepEqual(points, [
    { label: "11/16", value: 80 },
    { label: "11/23", value: null },
  ])
})

test("trendHasRate：全部缺失为 false，任一有值为 true", () => {
  assert.equal(
    trendHasRate([period({ first_accuracy: null })], (p) => p.first_accuracy),
    false,
  )
  assert.equal(
    trendHasRate([period({ first_accuracy: 0 })], (p) => p.first_accuracy),
    true,
  )
})

test("normalizeTrendRate：null 原样返回；0→0，100→1，50→0.5", () => {
  assert.equal(normalizeTrendRate(null), null)
  assert.equal(normalizeTrendRate(undefined), null)
  assert.equal(normalizeTrendRate(0), 0)
  assert.equal(normalizeTrendRate(100), 1)
  assert.equal(normalizeTrendRate(50), 0.5)
})

test("normalizeTrendRate：越界值钳制在 [0,1]", () => {
  assert.equal(normalizeTrendRate(-10), 0)
  assert.equal(normalizeTrendRate(120), 1)
})

test("trendBandTotal：四段计数求和", () => {
  const p = period({
    low_count: 3,
    mid_count: 5,
    high_count: 2,
    no_data_count: 4,
  })
  assert.equal(trendBandTotal(p), 14)
})

test("trendBandShare：分母为 0 返回 null，否则返回 0..1 占比", () => {
  const empty = period()
  assert.equal(trendBandShare(empty, "low"), null)
  const p = period({
    low_count: 3,
    mid_count: 5,
    high_count: 2,
    no_data_count: 0,
  })
  assert.equal(trendBandShare(p, "mid"), 0.5)
})
