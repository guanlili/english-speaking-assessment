import assert from "node:assert/strict"
import test from "node:test"
import { adviceText } from "../src/lib/bilingual.ts"

/** 批次10：双语建议取值——当前语言优先、缺语回退原文、旧字符串直通。 */

test("当前语言优先", () => {
  const item = { zh: "放慢语速", en: "Slow down" }
  assert.equal(adviceText(item, "zh"), "放慢语速")
  assert.equal(adviceText(item, "en"), "Slow down")
})

test("缺语回退另一种（不伪造翻译）", () => {
  assert.equal(
    adviceText({ en: "Use full sentences" }, "zh"),
    "Use full sentences",
  )
  assert.equal(adviceText({ zh: "多说完整句" }, "en"), "多说完整句")
})

test("两语全空返回空串；旧字符串直通", () => {
  assert.equal(adviceText({ zh: "", en: "" }, "zh"), "")
  assert.equal(adviceText("旧模型的中文建议", "en"), "旧模型的中文建议")
})
