import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import type { VocabularyTodayItem } from "@/client"
import PromptBody, {
  ChoiceOptions,
} from "@/components/Vocabulary/Practice/PromptBody"
import { I18nProvider } from "@/lib/i18n"

/**
 * 四类玩法的题面语义：
 * 1. 英译中给英文题干、中译英给中文题干（隐藏部分由服务端下发控制）
 * 2. 语境填空把目标词挖成横线，不能把答案印在题面上
 * 3. 词根拼装把前缀/词根/后缀作为可拼的词块展示
 * 4. 选项按服务端 is_answer 高亮，点击只回传词条 ID（不在前端判分）
 */

function item(overrides: Partial<VocabularyTodayItem>): VocabularyTodayItem {
  return {
    item_index: 0,
    prompt_type: "meaning",
    meaning_zh: "",
    ...overrides,
  }
}

const CHOICES = [
  {
    word_id: "w-apple",
    headword: "apple",
    meaning_zh: "苹果",
    part_of_speech: "n.",
    is_answer: false,
  },
  {
    word_id: "w-banana",
    headword: "banana",
    meaning_zh: "香蕉",
    part_of_speech: "n.",
    is_answer: false,
  },
  {
    word_id: "w-teacher",
    headword: "teacher",
    meaning_zh: "老师",
    part_of_speech: "n.",
    is_answer: false,
  },
  {
    word_id: "w-corn",
    headword: "corn",
    meaning_zh: "玉米",
    part_of_speech: "n.",
    is_answer: false,
  },
]

function renderBody(value: VocabularyTodayItem) {
  render(
    <I18nProvider>
      <PromptBody item={value} />
    </I18nProvider>,
  )
}

describe("PromptBody", () => {
  it("英译中展示英文题干与选项释义，不提前印出答案", () => {
    renderBody(
      item({ prompt_type: "en_zh", headword: "apple", meaning_zh: "" }),
    )
    expect(screen.getByText("apple")).toBeTruthy()
    expect(screen.queryByText("苹果")).toBeNull()
  })

  it("中译英展示中文题干、不展示英文拼写", () => {
    renderBody(
      item({
        prompt_type: "zh_en",
        headword: undefined,
        meaning_zh: "香蕉",
        meaning_en: "a banana",
      }),
    )
    expect(screen.getByText("香蕉")).toBeTruthy()
    expect(screen.queryByText("banana")).toBeNull()
  })

  it("语境填空把目标词挖成横线且不留答案", () => {
    renderBody(
      item({
        prompt_type: "cloze",
        headword: undefined,
        cloze_sentence: "I ate an ____ after lunch.",
      }),
    )
    expect(screen.queryByText("apple")).toBeNull()
    expect(screen.queryByText(/____/)).toBeNull()
    expect(screen.getByText(/after lunch/)).toBeTruthy()
  })

  it("词根拼装按词块展示并标注前缀/词根/后缀", () => {
    renderBody(
      item({
        prompt_type: "roots",
        headword: undefined,
        morph_segments: [
          { text: "teach", gloss: "教", kind: "root" },
          { text: "er", gloss: "表人", kind: "suffix" },
        ],
      }),
    )
    expect(screen.getByText("teach")).toBeTruthy()
    expect(screen.getByText("表人")).toBeTruthy()
    expect(screen.getByText("词根")).toBeTruthy()
    expect(screen.getByText("后缀")).toBeTruthy()
  })
})

describe("ChoiceOptions", () => {
  it("点击选项回传词条 ID，不在前端判断对错", () => {
    const onPick = vi.fn()
    render(
      <I18nProvider>
        <ChoiceOptions
          item={item({ prompt_type: "zh_en", choices: CHOICES })}
          answered={false}
          disabled={false}
          onPick={onPick}
        />
      </I18nProvider>,
    )
    fireEvent.click(screen.getByRole("button", { name: /banana/i }))
    expect(onPick).toHaveBeenCalledWith("w-banana")
  })

  it("答后按服务端 is_answer 高亮正确项并禁用", () => {
    const onPick = vi.fn()
    render(
      <I18nProvider>
        <ChoiceOptions
          item={item({
            prompt_type: "en_zh",
            choices: CHOICES.map((choice) => ({
              ...choice,
              is_answer: choice.word_id === "w-apple",
            })),
            first_choice_word_id: "w-banana",
          })}
          answered
          disabled
          onPick={onPick}
        />
      </I18nProvider>,
    )
    expect(screen.getByText("正确")).toBeTruthy()
    const [firstChoice] = screen.getAllByRole("button") as HTMLButtonElement[]
    expect(firstChoice.disabled).toBe(true)
  })
})
