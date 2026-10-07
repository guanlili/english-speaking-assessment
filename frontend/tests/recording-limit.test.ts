import assert from "node:assert/strict"
import test from "node:test"
import { resolveRecordLimitSeconds } from "../src/lib/recording-limit.ts"

test("recording limit follows each question setting", () => {
  assert.equal(resolveRecordLimitSeconds(8), 8)
  assert.equal(resolveRecordLimitSeconds(45), 45)
  assert.equal(resolveRecordLimitSeconds(180), 180)
  assert.equal(resolveRecordLimitSeconds(300), 300)
})

test("missing or invalid legacy limits fall back safely", () => {
  assert.equal(resolveRecordLimitSeconds(null), 60)
  assert.equal(resolveRecordLimitSeconds(0), 60)
  assert.equal(resolveRecordLimitSeconds(Number.NaN), 60)
  assert.equal(resolveRecordLimitSeconds(999), 300)
})
