import assert from "node:assert/strict"
import test from "node:test"

import type { VocabularyLeaderboardEntry } from "../src/client/types.gen"
import { ApiError } from "../src/lib/api-error.ts"
import {
  canGoNextWeek,
  isLeaderboardUnavailable,
  nextWeekStart,
  padAliasNo,
  participantCountVisible,
  previousWeekStart,
  resolveEntryName,
  studentBoardVisible,
} from "../src/lib/leaderboard.ts"

const ANON_ENTRY: VocabularyLeaderboardEntry = {
  rank: 1,
  score: 5,
  alias_no: 7,
  display_name: null,
  suffix: null,
}

const NAMED_ENTRY: VocabularyLeaderboardEntry = {
  rank: 2,
  score: 3,
  alias_no: 12,
  display_name: "李梨",
  suffix: "二班",
}

test("padAliasNo: 编号补两位，异常值兜底为 00", () => {
  assert.equal(padAliasNo(7), "07")
  assert.equal(padAliasNo(12), "12")
  assert.equal(padAliasNo(0), "00")
  assert.equal(padAliasNo(NaN), "00")
  assert.equal(padAliasNo(-3), "00")
})

test("resolveEntryName: 匿名只给编号；实名给姓名与后缀；无姓名回落编号", () => {
  assert.deepEqual(resolveEntryName(ANON_ENTRY, true), {
    kind: "anonymous",
    aliasNo: 7,
  })
  assert.deepEqual(resolveEntryName(NAMED_ENTRY, false), {
    kind: "name",
    name: "李梨",
    suffix: "二班",
  })
  // 关闭匿名但后端未回传姓名（理论兜底）：仍按编号展示
  assert.deepEqual(resolveEntryName(ANON_ENTRY, false), {
    kind: "anonymous",
    aliasNo: 7,
  })
})

test("isLeaderboardUnavailable: 仅 403 且 detail=leaderboard_unavailable 命中", () => {
  const unavailable = new ApiError(
    403,
    { detail: "leaderboard_unavailable" },
    "",
  )
  assert.equal(isLeaderboardUnavailable(unavailable), true)

  assert.equal(
    isLeaderboardUnavailable(
      new ApiError(401, { detail: "token_expired" }, ""),
    ),
    false,
  )
  assert.equal(
    isLeaderboardUnavailable(new ApiError(403, { detail: "forbidden" }, "")),
    false,
  )
  assert.equal(isLeaderboardUnavailable(new Error("boom")), false)
  assert.equal(isLeaderboardUnavailable(null), false)
})

test("studentBoardVisible: 整班开启且对学生可见才展示", () => {
  assert.equal(
    studentBoardVisible({ settings: { enabled: true, audience: "students" } }),
    true,
  )
  assert.equal(
    studentBoardVisible({ settings: { enabled: true, audience: "teachers" } }),
    false,
  )
  assert.equal(
    studentBoardVisible({ settings: { enabled: false, audience: "students" } }),
    false,
  )
})

test("participantCountVisible: 仅教师视角回传计数时可见", () => {
  assert.equal(participantCountVisible(5), true)
  assert.equal(participantCountVisible(0), true)
  assert.equal(participantCountVisible(null), false)
  assert.equal(participantCountVisible(undefined), false)
})

test("周界加减：2026-11-23（周一）前后各一周仍是周一", () => {
  const monday = "2026-11-23"
  assert.equal(previousWeekStart(monday), "2026-11-16")
  assert.equal(nextWeekStart(monday), "2026-11-30")
})

test("canGoNextWeek: 不超过首次响应拿到的本周；无边界不可前进", () => {
  const boundary = "2026-11-23"
  assert.equal(canGoNextWeek("2026-11-16", boundary), true)
  assert.equal(canGoNextWeek(boundary, boundary), false)
  assert.equal(canGoNextWeek("2026-11-16", null), false)
})
