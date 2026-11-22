import { describe, expect, it } from "vitest"
import type { VocabularyWordPublic } from "@/client"

import {
  buildClozeSentence,
  choicePoolSufficient,
  countEligibleByPromptType,
  describeSelfSession422,
  morphologyAssembles,
  wordSupportsPromptType,
} from "@/lib/vocab-prompt-availability"

/**
 * 题型素材可用性判定（口径对齐后端 vocabulary_prompt_types.py）：
 * - 语境填空：例句必须含完整词形（词边界、忽略大小写），否则不出题；
 * - 词根拼装：词法拆解按序拼回原词，且至少两段；
 * - 选择题：词条本身都可出，但干扰项要求词库至少 4 词；
 * - 422 按原因分流双语说明，不抛后端中文 detail。
 */

function word(overrides: Partial<VocabularyWordPublic>): VocabularyWordPublic {
  return {
    id: "w-1",
    headword: "apple",
    meaning_zh: "苹果",
    ...overrides,
  }
}

describe("语境填空可用性", () => {
  it("例句包含完整词形（忽略大小写）才可挖空", () => {
    expect(
      buildClozeSentence("apple", "I ate an Apple after lunch."),
    ).toBeTruthy()
    expect(
      wordSupportsPromptType(
        word({ example_en: "I ate an apple after lunch." }),
        "cloze",
      ),
    ).toBe(true)
  })

  it("例句不含该词时不可出语境填空", () => {
    expect(
      wordSupportsPromptType(
        word({ example_en: "The banana is yellow." }),
        "cloze",
      ),
    ).toBe(false)
    expect(wordSupportsPromptType(word({ example_en: null }), "cloze")).toBe(
      false,
    )
    expect(wordSupportsPromptType(word({ example_en: "" }), "cloze")).toBe(
      false,
    )
  })

  it("只命中词形片段（如 play 出现在 player 里）不算包含原词", () => {
    expect(
      wordSupportsPromptType(
        word({ headword: "play", example_en: "He is a player." }),
        "cloze",
      ),
    ).toBe(false)
  })
})

describe("词根拼装可用性", () => {
  const assemble = [
    { text: "teach", gloss: "教", kind: "root" },
    { text: "er", gloss: "表人", kind: "suffix" },
  ]

  it("拆解块按序拼回原词且至少两段才可出题", () => {
    expect(morphologyAssembles("teacher", assemble)).toBe(true)
    expect(
      wordSupportsPromptType(
        word({ headword: "teacher", morphology: assemble }),
        "roots",
      ),
    ).toBe(true)
  })

  it("拆解拼不回原词时不可出题", () => {
    expect(
      wordSupportsPromptType(
        word({
          headword: "teacher",
          morphology: [
            { text: "teach", gloss: "教", kind: "root" },
            { text: "ly", gloss: "副词", kind: "suffix" },
          ],
        }),
        "roots",
      ),
    ).toBe(false)
  })

  it("只有一段拆解或拆解为空时不可出题", () => {
    expect(
      wordSupportsPromptType(
        word({ morphology: [{ text: "teach", gloss: "教", kind: "root" }] }),
        "roots",
      ),
    ).toBe(false)
    expect(wordSupportsPromptType(word({ morphology: [] }), "roots")).toBe(
      false,
    )
    expect(wordSupportsPromptType(word({ morphology: null }), "roots")).toBe(
      false,
    )
  })
})

describe("选择题与词数门槛", () => {
  it("英译中/中译英对词条素材无要求，单条即可出", () => {
    const bare = word({ example_en: null, morphology: null })
    expect(wordSupportsPromptType(bare, "en_zh")).toBe(true)
    expect(wordSupportsPromptType(bare, "zh_en")).toBe(true)
  })

  it("干扰项门槛：词库至少 4 词", () => {
    const words = (n: number) =>
      Array.from({ length: n }, (_, index) =>
        word({ id: `w-${index}`, headword: `word${index}` }),
      )
    expect(choicePoolSufficient(words(3))).toBe(false)
    expect(choicePoolSufficient(words(4))).toBe(true)
  })

  it("汇总每类可出题词数", () => {
    const summary = countEligibleByPromptType([
      word({
        id: "w-a",
        headword: "apple",
        example_en: "I ate an apple.",
        morphology: null,
      }),
      word({
        id: "w-b",
        headword: "teacher",
        example_en: null,
        morphology: [
          { text: "teach", gloss: "教", kind: "root" },
          { text: "er", gloss: "表人", kind: "suffix" },
        ],
      }),
    ])
    expect(summary.en_zh).toBe(2)
    expect(summary.zh_en).toBe(2)
    expect(summary.cloze).toBe(1)
    expect(summary.roots).toBe(1)
  })
})

describe("开练 422 文案分流", () => {
  it("缺例句 / 缺词法拆解 / 词数不足 4 词分别给出双语说明", () => {
    expect(
      describeSelfSession422("语境填空要求词条带例句且例句包含该词本身"),
    ).toMatchObject({
      zh: expect.stringContaining("例句"),
      en: expect.stringContaining("example"),
    })
    expect(
      describeSelfSession422("词根拼装要求词条带词法拆解，且拆解能拼回原词"),
    ).toMatchObject({
      zh: expect.stringContaining("词法拆解"),
      en: expect.stringContaining("parts"),
    })
    expect(
      describeSelfSession422("选择题至少需要 4 个词才能生成干扰项"),
    ).toMatchObject({
      zh: expect.stringContaining("4 个词"),
      en: expect.stringContaining("4 words"),
    })
  })

  it("未知原因回落到通用双语提示，不展示后端 detail", () => {
    const fallback = describeSelfSession422("未知出题方式：foo")
    expect(fallback.zh).toBeTruthy()
    expect(fallback.en).toBeTruthy()
  })
})
