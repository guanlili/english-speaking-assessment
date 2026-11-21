import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"

import { WordAlignment } from "@/components/Practice/WordAlignment"
import { I18nProvider } from "@/lib/i18n"

/**
 * P0 逐词标注是「文本匹配」不是发音评分：
 * correct 必须绿线，missing/error 必须红线；图例与免责声明不能丢。
 */

function renderAlignment() {
  render(
    <I18nProvider>
      <WordAlignment
        reference="I like cats"
        alignment={{
          words: [
            { start: 0, end: 1, text: "I", status: "correct" },
            {
              start: 2,
              end: 6,
              text: "like",
              status: "error",
              heard: "lake",
            },
            { start: 7, end: 11, text: "cats", status: "missing" },
          ],
          extras: [],
        }}
      />
    </I18nProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
})

describe("WordAlignment", () => {
  it("correct 绿线、error/missing 红线，并标明非发音评分", () => {
    renderAlignment()
    const correct = screen.getByText("I")
    expect(correct.className).toContain("decoration-emerald-500")
    const error = screen.getByText("like")
    expect(error.className).toContain("decoration-red-500")
    const missing = screen.getByText("cats")
    expect(missing.className).toContain("decoration-red-500")
    expect(screen.getByText("文本匹配正确")).toBeInTheDocument()
    expect(screen.getByText(/不代表发音评分/)).toBeInTheDocument()
  })

  it("读错时显示听到的形式", () => {
    renderAlignment()
    expect(screen.getByText(/lak/)).toBeInTheDocument()
  })
})
