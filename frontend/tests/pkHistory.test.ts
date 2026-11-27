import assert from "node:assert/strict"
import test from "node:test"

import {
  pkHistoryResultKey,
  pkHistoryStatusKey,
  pkHistoryTime,
  pkHistoryWinnerName,
} from "../src/lib/pk.ts"

test("pkHistoryStatusKey: finished / abandoned / 未知与空值归类", () => {
  assert.equal(pkHistoryStatusKey("finished"), "finished")
  assert.equal(pkHistoryStatusKey("abandoned"), "abandoned")
  assert.equal(pkHistoryStatusKey("active"), "other")
  assert.equal(pkHistoryStatusKey(null), "other")
  assert.equal(pkHistoryStatusKey(undefined), "other")
})

test("pkHistoryResultKey: win / lose / 平，空值与未知按平局兜底", () => {
  assert.equal(pkHistoryResultKey("win"), "win")
  assert.equal(pkHistoryResultKey("lose"), "lose")
  assert.equal(pkHistoryResultKey("draw"), "draw")
  assert.equal(pkHistoryResultKey(null), "draw")
  assert.equal(pkHistoryResultKey(undefined), "draw")
  assert.equal(pkHistoryResultKey("unknown"), "draw")
})

test("pkHistoryWinnerName: 去除首尾空白；空名 / 无胜者返回 null", () => {
  assert.equal(pkHistoryWinnerName({ winner_display_name: "小红" }), "小红")
  assert.equal(pkHistoryWinnerName({ winner_display_name: "  小刚  " }), "小刚")
  assert.equal(pkHistoryWinnerName({ winner_display_name: null }), null)
  assert.equal(pkHistoryWinnerName({ winner_display_name: undefined }), null)
  assert.equal(pkHistoryWinnerName({ winner_display_name: "   " }), null)
})

test("pkHistoryTime: 优先结束时间，其次开始时间；都空返回 null", () => {
  assert.equal(
    pkHistoryTime({
      finished_at: "2026-11-25T10:00:00Z",
      started_at: "2026-11-25T09:55:00Z",
    }),
    "2026-11-25T10:00:00Z",
  )
  assert.equal(
    pkHistoryTime({ finished_at: null, started_at: "2026-11-25T09:55:00Z" }),
    "2026-11-25T09:55:00Z",
  )
  assert.equal(pkHistoryTime({ finished_at: null, started_at: null }), null)
  assert.equal(pkHistoryTime({}), null)
})
