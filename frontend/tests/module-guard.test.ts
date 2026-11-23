import assert from "node:assert/strict"
import test from "node:test"
import type { ModuleKey } from "../src/hooks/useModules.ts"
import { moduleGuardState } from "../src/lib/module-filter.ts"

function owned(keys: ModuleKey[]) {
  const set = new Set(keys)
  return (key: ModuleKey) => set.has(key)
}

test("speaking 已购且清单成功：放行", () => {
  assert.equal(
    moduleGuardState(
      { isPending: false, isError: false },
      owned(["speaking"]),
      "speaking",
    ),
    "allowed",
  )
})

test("speaking 未购（空清单）：拦截", () => {
  assert.equal(
    moduleGuardState(
      { isPending: false, isError: false },
      owned([]),
      "speaking",
    ),
    "denied",
  )
})

test("只买 vocabulary：speaking 仍按未购拦截", () => {
  assert.equal(
    moduleGuardState(
      { isPending: false, isError: false },
      owned(["vocabulary"]),
      "speaking",
    ),
    "denied",
  )
})

test("清单加载中：保持加载态，不闪拦截页", () => {
  assert.equal(
    moduleGuardState(
      { isPending: true, isError: false },
      owned([]),
      "speaking",
    ),
    "loading",
  )
})

test("请求失败：保守按未购拦截", () => {
  assert.equal(
    moduleGuardState(
      { isPending: false, isError: true },
      owned(["speaking"]),
      "speaking",
    ),
    "denied",
  )
})

test("加载中优先于失败态判定", () => {
  assert.equal(
    moduleGuardState({ isPending: true, isError: true }, owned([]), "speaking"),
    "loading",
  )
})
