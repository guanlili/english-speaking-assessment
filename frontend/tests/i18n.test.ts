import assert from "node:assert/strict"
import { test } from "node:test"
import { resolveBi } from "../src/lib/bi.ts"

test("resolveBi 按语言取双语文案", () => {
  const bi = { zh: "登录", en: "Sign in" }
  assert.equal(resolveBi(bi, "zh"), "登录")
  assert.equal(resolveBi(bi, "en"), "Sign in")
})

test("BiString 必须同时提供中英文（类型层约束的运行时自检）", () => {
  // 双语准则：缺一侧在类型上就不成立；这里保证 resolveBi 对合法对象行为确定
  const pairs: { zh: string; en: string }[] = [
    { zh: "听示范", en: "Listen" },
    { zh: "", en: "" },
  ]
  for (const p of pairs) {
    assert.equal(resolveBi(p, "en"), p.en)
    assert.equal(resolveBi(p, "zh"), p.zh)
  }
})
