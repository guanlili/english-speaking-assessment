import assert from "node:assert/strict"
import { beforeEach, test } from "node:test"

import type { StoredStudent } from "../src/lib/classroom-student.ts"
import {
  LEGACY_SAVED_EXPRESSIONS_KEY,
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
