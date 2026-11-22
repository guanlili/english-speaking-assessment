import assert from "node:assert/strict"
import test from "node:test"

import {
  badgeSourceLabel,
  badgeText,
  FARM_MATURE_POINTS,
  FARM_XP_DAILY_CAP,
  farmStage,
  harvestState,
  pointsToMature,
} from "../src/lib/farm.ts"

test("farmStage: 四阶段阈值 0 / 5 / 12 / 20", () => {
  assert.equal(farmStage(0), 0)
  assert.equal(farmStage(4), 0)
  assert.equal(farmStage(5), 1)
  assert.equal(farmStage(11), 1)
  assert.equal(farmStage(12), 2)
  assert.equal(farmStage(19), 2)
  assert.equal(farmStage(20), 3)
  assert.equal(farmStage(25), 3)
})

test("pointsToMature: 距成熟点数，成熟后为 0", () => {
  assert.equal(pointsToMature(0), FARM_MATURE_POINTS)
  assert.equal(pointsToMature(12), 8)
  assert.equal(pointsToMature(20), 0)
  assert.equal(pointsToMature(25), 0)
})

test("harvestState: 未成熟 locked；成熟且 XP 未满 ready；满额 xp-capped", () => {
  assert.equal(
    harvestState({ ready_to_harvest: false, today_farm_xp: 0 }),
    "locked",
  )
  assert.equal(
    harvestState({ ready_to_harvest: true, today_farm_xp: 0 }),
    "ready",
  )
  assert.equal(
    harvestState({ ready_to_harvest: true, today_farm_xp: FARM_XP_DAILY_CAP }),
    "xp-capped",
  )
  // 缺省上限按 10 计
  assert.equal(
    harvestState({
      ready_to_harvest: true,
      today_farm_xp: 10,
      farm_xp_daily_cap: null,
    }),
    "xp-capped",
  )
})

test("badgeSourceLabel: farm_ 前缀或农场来源归专注农场，其余归课堂档案", () => {
  assert.deepEqual(
    badgeSourceLabel({ key: "farm_first_harvest" }).zh,
    "专注农场",
  )
  assert.deepEqual(
    badgeSourceLabel({ key: "first_round", source: "专注农场" }).zh,
    "专注农场",
  )
  assert.deepEqual(
    badgeSourceLabel({ key: "streak_3" }).zh,
    "课堂档案/每日计划",
  )
})

test("badgeText：农场与既有徽章英文名不直出中文", () => {
  for (const key of [
    "first_round",
    "streak_3",
    "streak_7",
    "ten_rounds",
    "reached_b2",
    "farm_first_harvest",
    "farm_harvest_7",
  ]) {
    const text = badgeText({ key, label: "中文", description: "中文描述" })
    assert.notEqual(text.label.en, "中文")
    assert.match(text.label.en, /[A-Za-z]/)
    assert.ok(text.description)
    assert.notEqual(text.description.en, "中文描述")
  }
})

test("badgeText：未知徽章保留后端原文，不崩", () => {
  const text = badgeText({ key: "future_badge", label: "未来徽章" })
  assert.deepEqual(text.label, { zh: "未来徽章", en: "未来徽章" })
  assert.equal(text.description, null)
})
