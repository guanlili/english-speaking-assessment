import assert from "node:assert/strict"
import { test } from "node:test"

import type { MySessionSummary } from "../src/client/types.gen.ts"
import { filterSessions } from "../src/lib/practice-history.ts"

function row(overrides: Partial<MySessionSummary>): MySessionSummary {
  return {
    attempt_ids: [],
    is_exam: false,
    exam_ended: false,
    session_id: "00000000-0000-0000-0000-000000000001",
    session_date: "2026-10-19",
    mode: "daily",
    title: null,
    done_count: 5,
    total_count: 6,
    overall_avg: 82,
    ...overrides,
  }
}

const zh = (b: { zh: string; en: string }) => b.zh

test("空关键词返回全部（不去重、顺序不变）", () => {
  const rows = [row({ session_id: "a" }), row({ session_id: "b" })]
  assert.deepEqual(filterSessions(rows, "  ", zh), rows)
})

test("按题单标题匹配（忽略大小写、支持部分匹配）", () => {
  const rows = [
    row({ title: "School Life – Daily Routine", session_id: "a" }),
    row({ title: "Travel & Culture", session_id: "b" }),
  ]
  assert.deepEqual(
    filterSessions(rows, "travel", zh).map((r) => r.session_id),
    ["b"],
  )
  assert.deepEqual(
    filterSessions(rows, "daily", zh).map((r) => r.session_id),
    ["a"],
  )
})

test("按练习日期匹配（YYYY-MM-DD 子串）", () => {
  const rows = [
    row({ session_date: "2026-10-12", session_id: "a" }),
    row({ session_date: "2026-10-19", session_id: "b" }),
  ]
  assert.deepEqual(
    filterSessions(rows, "10-19", zh).map((r) => r.session_id),
    ["b"],
  )
})

test("无题单标题时按双语文案匹配（主题探索/自主练习）", () => {
  const rows = [
    row({ mode: "explore", session_id: "a" }),
    row({ mode: "daily", title: null, session_id: "b" }),
  ]
  assert.deepEqual(
    filterSessions(rows, "主题探索", zh).map((r) => r.session_id),
    ["a"],
  )
  assert.deepEqual(
    filterSessions(rows, "自主练习", zh).map((r) => r.session_id),
    ["b"],
  )
})

test("多轮匹配一并返回", () => {
  const rows = [
    row({ title: "Spring Festival", session_id: "a" }),
    row({ title: "Festival Food", session_id: "b" }),
    row({ title: "Weather", session_id: "c" }),
  ]
  assert.deepEqual(
    filterSessions(rows, "festival", zh).map((r) => r.session_id),
    ["a", "b"],
  )
})
