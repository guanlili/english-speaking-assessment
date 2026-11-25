import assert from "node:assert/strict"
import test from "node:test"

import {
  farmBadgeTotal,
  sortFarmBadges,
  topFarmHarvesters,
} from "../src/lib/farm.ts"
import { formatNullableCount } from "../src/lib/utils.ts"

test("sortFarmBadges: 空值返回空数组；剔除 ≤0，按人数降序、key 次序稳定", () => {
  assert.deepEqual(sortFarmBadges(undefined), [])
  assert.deepEqual(sortFarmBadges([]), [])
  const badges = [
    { key: "streak_3", label: "三连胜", count: 3 },
    { key: "first_round", label: "初次开口", count: 12 },
    { key: "ten_rounds", label: "十轮达人", count: 0 },
    { key: "streak_7", label: "一周坚持", count: null },
    { key: "farm_harvest_7", label: "七次收获", count: 12 },
  ]
  const sorted = sortFarmBadges(badges)
  assert.deepEqual(
    sorted.map((badge) => badge.key),
    ["farm_harvest_7", "first_round", "streak_3"],
  )
  assert.equal(sorted[0].count, 12)
})

test("topFarmHarvesters: 剔除 0 次，按收获降序并截取前 n", () => {
  assert.deepEqual(topFarmHarvesters(undefined, 5), [])
  const harvesters = [
    { display_name: "小明", harvest_count: 2 },
    { display_name: "小红", harvest_count: 9 },
    { display_name: "小刚", harvest_count: 0 },
    { display_name: "小丽", harvest_count: 5 },
  ]
  const top = topFarmHarvesters(harvesters, 2)
  assert.deepEqual(
    top.map((h) => h.display_name),
    ["小红", "小丽"],
  )
  assert.equal(top.length, 2)
})

test("farmBadgeTotal: 空列表返回 null（不折算 0）；有记录时求和，缺值按 0", () => {
  assert.equal(farmBadgeTotal(undefined), null)
  assert.equal(farmBadgeTotal([]), null)
  assert.equal(farmBadgeTotal([{ count: 3 }, { count: 5 }, { count: null }]), 8)
})

test("formatNullableCount: null/undefined 显示 –，0 保留为 0", () => {
  assert.equal(formatNullableCount(null), "–")
  assert.equal(formatNullableCount(undefined), "–")
  assert.equal(formatNullableCount(0), "0")
  assert.equal(formatNullableCount(12), "12")
})
