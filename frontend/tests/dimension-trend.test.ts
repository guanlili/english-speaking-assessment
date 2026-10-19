import assert from "node:assert/strict"
import { test } from "node:test"

import {
  dimensionTrendCaption,
  dimensionTrendVisible,
} from "../src/lib/dimension-trend.ts"

test("单次作答也展示趋势图（回归：原 length > 1 条件吞掉单点）", () => {
  const singlePoint = [{ date: "2026-10-19", fluency: 3.2 }]
  assert.equal(dimensionTrendVisible(singlePoint), true)
  assert.equal(
    dimensionTrendVisible([...singlePoint, { date: "2026-10-18", fluency: 3 }]),
    true,
  )
})

test("无数据时不展示趋势图", () => {
  assert.equal(dimensionTrendVisible(null), false)
  assert.equal(dimensionTrendVisible(undefined), false)
  assert.equal(dimensionTrendVisible([]), false)
})

test("标题注明实际计入的作答次数（含最近 14 次截断口径）", () => {
  assert.deepEqual(dimensionTrendCaption(1), {
    zh: "四维趋势（最近 1 次问答）",
    en: "Dimension trend (last 1 Q&A rounds)",
  })
  assert.deepEqual(dimensionTrendCaption(14), {
    zh: "四维趋势（最近 14 次问答）",
    en: "Dimension trend (last 14 Q&A rounds)",
  })
  assert.equal(dimensionTrendCaption(0).zh, "四维趋势（最近 0 次问答）")
})
