import assert from "node:assert/strict"
import test from "node:test"
import { nextUnansweredIndex } from "../src/lib/practice-navigation.ts"

test("next item advances even when the just-scored attempt has not reached the plan cache", () => {
  assert.equal(nextUnansweredIndex(["a", "b", "c"], 0, new Set()), 1)
  assert.equal(nextUnansweredIndex(["a", "b", "c"], 0, new Set(["b"])), 2)
})

test("next item wraps to earlier unanswered items and ends when all others are done", () => {
  assert.equal(nextUnansweredIndex(["a", "b", "c"], 2, new Set(["b"])), 0)
  assert.equal(nextUnansweredIndex(["a", "b", "c"], 2, new Set(["a", "b"])), -1)
})
