import assert from "node:assert/strict"
import test from "node:test"

import { toBookWordInput } from "../src/components/Teaching/VocabTasks/types.ts"

test("CSV 预览映射保留 morphology，不再静默丢词法拆解", () => {
  const morphology = [
    { text: "help", gloss: "帮助", kind: "root" },
    { text: "ful", gloss: "形容词后缀", kind: "suffix" },
  ]
  const mapped = toBookWordInput({
    headword: "helpful",
    part_of_speech: "adj.",
    meaning_zh: "有帮助的",
    meaning_en: "giving help",
    accepted_spellings: ["helpfull"],
    example_en: "She is helpful.",
    morphology,
  })

  assert.deepEqual(mapped.morphology, morphology)
  assert.equal(mapped.example_en, "She is helpful.")
  assert.equal(mapped.meaning_en, "giving help")
})

test("CSV 预览映射把后端 null 原样保留，不臆造空数组", () => {
  const mapped = toBookWordInput({
    headword: "plain",
    meaning_zh: "普通",
    morphology: null,
  })

  assert.equal(mapped.morphology, null)
  assert.equal(mapped.part_of_speech, null)
  assert.equal(mapped.accepted_spellings, null)
})
