import assert from "node:assert/strict"
import { test } from "node:test"

import { sliceByCodepoints } from "../src/lib/word-alignment.ts"

test("slices by codepoints so non-BMP chars count as one unit", () => {
  const text = "🐾 Dogs run."
  // 🐾 = 1 码点（UTF-16 里 2 码元）：string.length 12，Array.from 11
  assert.equal(text.length, 12)
  assert.equal(Array.from(text).length, 11)
  assert.equal(sliceByCodepoints(text, 0, 1), "🐾")
  assert.equal(sliceByCodepoints(text, 2, 6), "Dogs")
  assert.equal(sliceByCodepoints(text, 7, 10), "run")
  assert.equal(sliceByCodepoints(text, 7), "run.")
})

test("reassembles the reference with backend codepoint offsets (non-BMP prefix)", () => {
  // 契约：后端 align_words 的偏移按 Unicode 码点。对 "🐾 Dogs run."，
  // 🐾 是间隔文本（码点 0-2，emoji+空格）、Dogs(2,6)、run(7,10)；
  // 前端按码点切片重建间隔文本与词文本，不得出现字母错位/重复
  // （旧 string.slice 按 UTF-16 会把 🐾 切成 2 个码元导致整体偏移）。
  const reference = "🐾 Dogs run."
  const words = [
    { start: 2, end: 6, status: "correct" },
    { start: 7, end: 10, status: "correct" },
  ]
  let rebuilt = ""
  let cursor = 0
  for (const word of words) {
    rebuilt += sliceByCodepoints(reference, cursor, word.start)
    rebuilt += sliceByCodepoints(reference, word.start, word.end)
    cursor = word.end
  }
  rebuilt += sliceByCodepoints(reference, cursor)
  assert.equal(rebuilt, "🐾 Dogs run.")
})

test("a longer surrogate-pair run keeps spacing and ordering intact", () => {
  const reference = "😀😀 hello world"
  // 两个 emoji（各 1 码点）+ 空格；hello(3,8) world(9,14)
  assert.equal(sliceByCodepoints(reference, 0, 2), "😀😀")
  assert.equal(sliceByCodepoints(reference, 3, 8), "hello")
  assert.equal(sliceByCodepoints(reference, 9), "world")
  assert.equal(
    sliceByCodepoints(reference, 0, 2) +
      "|" +
      sliceByCodepoints(reference, 2, 3) +
      "|" +
      sliceByCodepoints(reference, 3, 8),
    "😀😀| |hello",
  )
})
