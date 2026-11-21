import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"

import { SentenceReview } from "@/components/Practice/SentenceReview"
import { I18nProvider } from "@/lib/i18n"

/**
 * 逐句批改的最小契约：
 * - 有问题的句子必须给出原文 span、最小改写与解释；
 * - 无问题句子显示 clean，不硬凑问题；
 * - pending/unavailable 必须显式降级，不能出假批改；
 * - 发音区只能显示「待接入」，不能编造发音问题。
 */

function reviewPayload() {
  return {
    status: "done",
    truncated: false,
    sentences: [
      {
        index: 0,
        text: "I very like play basketball.",
        start: 0,
        end: 29,
        clean: false,
        corrected: "I really like playing basketball.",
        issues: [
          {
            type: "grammar",
            start: 2,
            end: 6,
            span: "very",
            suggestion: "really",
            why: {
              zh: "very 不能直接修饰动词，用 really",
              en: "Use 'really' before a verb.",
            },
          },
          {
            type: "expression",
            start: 12,
            end: 16,
            span: "play",
            suggestion: "playing",
            why: {
              zh: "like 后面接动名词",
              en: "Use the -ing form after 'like'.",
            },
          },
        ],
      },
      {
        index: 1,
        text: "It is fun.",
        start: 30,
        end: 40,
        clean: true,
        corrected: "It is fun.",
        issues: [],
      },
    ],
    summary: {
      zh: "共 2 句，1 句有问题：1 处语法、1 处表达。",
      en: "2 sentences, 1 with issues: 1 grammar, 1 expression.",
    },
  }
}

function renderReview(review: unknown) {
  render(
    <I18nProvider>
      <SentenceReview review={review} />
    </I18nProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
})

describe("SentenceReview", () => {
  it("有问题句给 span、最小改写与解释，无问题句不硬凑", () => {
    renderReview(reviewPayload())
    expect(screen.getByText("逐句批改")).toBeInTheDocument()
    expect(
      screen.getByText("I really like playing basketball."),
    ).toBeInTheDocument()
    expect(screen.getByText("very → really")).toBeInTheDocument()
    expect(screen.getByText("play → playing")).toBeInTheDocument()
    expect(
      screen.getByText("very 不能直接修饰动词，用 really"),
    ).toBeInTheDocument()
    expect(screen.getByText("这句没问题")).toBeInTheDocument()
    // 发音只允许占位，不得出现虚构的发音问题。
    expect(screen.getByText(/发音评测待接入/)).toBeInTheDocument()
  })

  it("pending 状态显示生成中，不显示句子", () => {
    renderReview({ status: "pending" })
    expect(screen.getByText("逐句批改正在生成…")).toBeInTheDocument()
    expect(screen.queryByText("这句没问题")).not.toBeInTheDocument()
  })

  it("unavailable 状态显式降级，不出假批改", () => {
    renderReview({ status: "unavailable" })
    expect(screen.getByText(/本次逐句批改暂缺/)).toBeInTheDocument()
    expect(screen.queryByText("这句没问题")).not.toBeInTheDocument()
  })

  it("超过 12 句时提示只批改前 12 句", () => {
    const payload = reviewPayload()
    payload.truncated = true
    renderReview(payload)
    expect(
      screen.getByText("本次只批改前 12 句，其余句子未纳入。"),
    ).toBeInTheDocument()
  })

  it("英文环境文案同步切换", () => {
    localStorage.setItem("esa:lang", "en")
    renderReview(reviewPayload())
    expect(screen.getByText("Sentence review")).toBeInTheDocument()
    expect(screen.getByText("No issue")).toBeInTheDocument()
    expect(
      screen.getByText(
        "Pronunciation assessment is not connected yet; this review covers grammar and expression only and does not change scores.",
      ),
    ).toBeInTheDocument()
  })
})
