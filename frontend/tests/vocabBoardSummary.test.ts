import assert from "node:assert/strict"
import test from "node:test"

import { hasFarmSummary, hasPkSummary } from "../src/lib/vocabBoardSummary.ts"

test("hasPkSummary: null/undefined 与全空对象不渲染；任一字段存在即渲染", () => {
  assert.equal(hasPkSummary(null), false)
  assert.equal(hasPkSummary(undefined), false)
  assert.equal(hasPkSummary({}), false)
  assert.equal(hasPkSummary({ open: false }), true)
  assert.equal(hasPkSummary({ queue_count: 0 }), true)
  assert.equal(hasPkSummary({ matches_this_week: 4 }), true)
  assert.equal(
    hasPkSummary({ last_match: { at: "2026-11-25T10:00:00Z" } }),
    true,
  )
})

test("hasFarmSummary: null/undefined 与全空对象不渲染；标量/徽章/收获榜任一存在即渲染", () => {
  assert.equal(hasFarmSummary(null), false)
  assert.equal(hasFarmSummary(undefined), false)
  assert.equal(hasFarmSummary({}), false)
  assert.equal(hasFarmSummary({ participants: 0 }), true)
  assert.equal(
    hasFarmSummary({
      badge_counts: [{ key: "first_round", label: "初次开口", count: 1 }],
    }),
    true,
  )
  assert.equal(
    hasFarmSummary({
      top_harvesters: [{ display_name: "小红", harvest_count: 3 }],
    }),
    true,
  )
})
