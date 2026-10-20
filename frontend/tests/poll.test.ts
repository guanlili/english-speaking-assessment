import assert from "node:assert/strict"
import { test } from "node:test"

import { pollWhileVisible } from "../src/lib/poll.ts"

const query = {} as Parameters<typeof pollWhileVisible>[0] extends (
  query: infer Q,
) => unknown
  ? Q
  : never

function setHidden(hidden: boolean) {
  ;(globalThis as Record<string, unknown>).document = { hidden }
}

test("pollWhileVisible：document 不存在（SSR/单测）时按可见处理", () => {
  delete (globalThis as Record<string, unknown>).document
  assert.equal(pollWhileVisible(5000)(query), 5000)
})

test("pollWhileVisible：固定间隔，页面隐藏时暂停、可见时恢复", () => {
  setHidden(true)
  assert.equal(pollWhileVisible(5000)(query), false)
  setHidden(false)
  assert.equal(pollWhileVisible(5000)(query), 5000)
  delete (globalThis as Record<string, unknown>).document
})

test("pollWhileVisible：回调间隔，隐藏时暂停且不执行回调", () => {
  let called = 0
  const interval = pollWhileVisible(() => {
    called += 1
    return 3000
  })
  setHidden(true)
  assert.equal(interval(query), false)
  assert.equal(called, 0, "隐藏时不应执行回调")
  setHidden(false)
  assert.equal(interval(query), 3000)
  assert.equal(called, 1)
  delete (globalThis as Record<string, unknown>).document
})

test("pollWhileVisible：回调返回 false（条件停止）保持不变", () => {
  setHidden(false)
  const interval = pollWhileVisible(() => false)
  assert.equal(interval(query), false)
  delete (globalThis as Record<string, unknown>).document
})
