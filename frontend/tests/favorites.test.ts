import assert from "node:assert/strict"
import { beforeEach, test } from "node:test"

import type { StoredStudent } from "../src/lib/classroom-student.ts"
import {
  expressionsStillLocal,
  LEGACY_SAVED_EXPRESSIONS_KEY,
  manualSaveOutcome,
  readSavedExpressions,
  savedExpressionsKey,
  saveSavedExpressions,
} from "../src/lib/favorites.ts"

// Node 无 localStorage：给一个内存 mock（favorites.ts 在调用时才读全局）。
const storage = new Map<string, string>()
Object.defineProperty(globalThis, "localStorage", {
  value: {
    getItem: (key: string) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key: string, value: string) => {
      storage.set(key, String(value))
    },
    removeItem: (key: string) => {
      storage.delete(key)
    },
  },
  configurable: true,
})

function student(id: string, user_id: string | null): StoredStudent {
  return { id, user_id, display_name: "x", suffix: null }
}

beforeEach(() => {
  storage.clear()
})

test("收藏键按登录用户隔离（user_id）", () => {
  const a = student("sA", "uA")
  const b = student("sB", "uB")
  assert.notEqual(savedExpressionsKey(a), savedExpressionsKey(b))
  assert.ok(savedExpressionsKey(a).includes("uA"))
  assert.ok(savedExpressionsKey(b).includes("uB"))
})

test("匿名学生按学生档案 id 隔离，且不与登录用户混用", () => {
  const anon1 = student("s1", null)
  const anon2 = student("s2", null)
  const logged = student("s1", "uA")
  assert.notEqual(savedExpressionsKey(anon1), savedExpressionsKey(anon2))
  assert.notEqual(savedExpressionsKey(anon1), savedExpressionsKey(logged))
  assert.ok(savedExpressionsKey(anon1).includes("anon:s1"))
})

test("同设备 A→退出→B→A：收藏互不串号且 A 能找回自己的", () => {
  const a = student("sA", "uA")
  const b = student("sB", "uB")

  // A 收藏
  saveSavedExpressions(a, ["I think… because…"])
  assert.deepEqual(readSavedExpressions(a), ["I think… because…"])

  // A 退出 → B 登录收藏：看不到 A 的，且不覆盖 A
  saveSavedExpressions(b, ["It depends on…"])
  assert.deepEqual(readSavedExpressions(b), ["It depends on…"])
  assert.deepEqual(readSavedExpressions(a), ["I think… because…"])

  // A 再次登录：找回自己的收藏（B 的仍在 B 名下）
  assert.deepEqual(readSavedExpressions(a), ["I think… because…"])
  assert.deepEqual(readSavedExpressions(b), ["It depends on…"])
})

test("旧的无归属收藏不分配给下一位登录者", () => {
  // 模拟老版本写下的无归属收藏键
  storage.set(LEGACY_SAVED_EXPRESSIONS_KEY, JSON.stringify(["old unowned"]))
  const a = student("sA", "uA")
  assert.deepEqual(readSavedExpressions(a), [])
  // 新收藏写入按用户键，不污染旧键
  saveSavedExpressions(a, ["mine"])
  assert.deepEqual(
    JSON.parse(storage.get(LEGACY_SAVED_EXPRESSIONS_KEY) ?? "[]"),
    ["old unowned"],
  )
})

test("收藏去重且保留顺序", () => {
  const a = student("sA", "uA")
  saveSavedExpressions(a, ["first", "second", "first"])
  assert.deepEqual(readSavedExpressions(a), ["first", "second", "first"])
})

test("迁移只清掉服务端确认保存的文本", () => {
  const stored = Array.from({ length: 50 }, (_, index) => `saved ${index}`)
  const pending = [...stored.slice(0, 5), "  extra one  ", "extra two", "   "]
  assert.deepEqual(expressionsStillLocal(pending, stored), [
    "  extra one  ",
    "extra two",
  ])
})

test("账号已有 50 条时，新表达不算收藏成功", () => {
  const stored = Array.from({ length: 50 }, (_, index) => `kept ${index}`)
  const outcome = manualSaveOutcome(["brand new"], stored)
  assert.equal(outcome.complete, false)
  assert.deepEqual(outcome.missing, ["brand new"])
})

test("账号已有 49 条时，一次两条只确认已经入库的那条", () => {
  const stored = [
    ...Array.from({ length: 48 }, (_, index) => `kept ${index}`),
    "first",
  ]
  const outcome = manualSaveOutcome([" first ", "second"], stored)
  assert.equal(outcome.complete, false)
  assert.deepEqual(outcome.missing, ["second"])
})

test("请求里的文本都在账号收藏里才算成功", () => {
  const outcome = manualSaveOutcome(
    ["  first  ", "second"],
    ["first", "second", "older"],
  )
  assert.equal(outcome.complete, true)
  assert.deepEqual(outcome.missing, [])
})
