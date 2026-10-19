import assert from "node:assert/strict"
import { test } from "node:test"

import { localDateStamp } from "../src/lib/dates.ts"

test("本地日期：输出与本地构造的年月日一致（与运行态时区无关）", () => {
  assert.equal(localDateStamp(new Date(2026, 0, 5)), "2026-01-05")
  assert.equal(localDateStamp(new Date(2026, 9, 19)), "2026-10-19")
  assert.equal(localDateStamp(new Date(2024, 11, 31)), "2024-12-31")
})

test("本地日期：单月/单日补零", () => {
  assert.equal(localDateStamp(new Date(2026, 2, 8)), "2026-03-08")
  assert.equal(localDateStamp(new Date(2026, 10, 1)), "2026-11-01")
})

test("本地日期：修复点——UTC 日期可能差一天，本地字段不偏移", () => {
  // 东八区 2026-10-19 凌晨 01:30 时，UTC 仍是 10-18；
  // localDateStamp 取本地字段 → 10-19（修复前 toISOString 会给 10-18）。
  const d = new Date(2026, 9, 19, 1, 30)
  assert.equal(localDateStamp(d), "2026-10-19")
})
