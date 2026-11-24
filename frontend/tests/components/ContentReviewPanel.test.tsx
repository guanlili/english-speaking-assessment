import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { VocabularyService } from "@/client"
import { ContentReviewPanel } from "@/components/Vocabulary/ContentReviewPanel"
import { I18nProvider } from "@/lib/i18n"

/**
 * 审核面板交互：
 * - 队列渲染待审数量、来源（AI 单独标）与审核状态徽章；
 * - 拒绝必须填意见：空意见提交阻断并给出双语校验提示；
 * - 服务调用走既有 SDK，测试不手写 API URL。
 */

const REVIEW_LIST = {
  items: [
    {
      word_id: "w-1",
      headword: "apple",
      part_of_speech: "n.",
      meaning_zh: "苹果",
      source: "ai",
      review_status: "pending",
      version: 1,
      book_id: "b-1",
      book_title: "Class A",
    },
    {
      word_id: "w-2",
      headword: "bank",
      part_of_speech: "n.",
      meaning_zh: "银行",
      source: "import",
      review_status: "rejected",
      review_note: "释义不准",
      version: 2,
      book_id: "b-1",
      book_title: "Class A",
      reviewed_at: "2026-11-24T10:00:00Z",
    },
  ],
  total: 2,
  pending_count: 1,
  rejected_count: 1,
  approved_count: 0,
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ContentReviewPanel />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  vi.restoreAllMocks()
})

describe("ContentReviewPanel", () => {
  it("渲染待审数量、来源与审核状态徽章", async () => {
    vi.spyOn(VocabularyService, "listVocabularyReviews").mockResolvedValue(
      REVIEW_LIST,
    )
    renderPanel()

    expect(await screen.findByText("apple")).toBeInTheDocument()
    expect(screen.getByText("bank")).toBeInTheDocument()
    expect(screen.getByText(/待审 1/)).toBeInTheDocument()
    // AI 来源单独标记（下拉选项 + 行内徽章各一处）
    expect(screen.getAllByText("AI").length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText("已拒绝").length).toBeGreaterThan(0)
  })

  it("拒绝时空意见阻断提交并提示必填", async () => {
    vi.spyOn(VocabularyService, "listVocabularyReviews").mockResolvedValue(
      REVIEW_LIST,
    )
    const reviewSpy = vi
      .spyOn(VocabularyService, "reviewVocabularyWords")
      .mockResolvedValue({ updated: 1, status: "rejected" })
    renderPanel()

    const rejectButtons = await screen.findAllByRole("button", {
      name: "拒绝",
    })
    fireEvent.click(rejectButtons[0])

    await waitFor(() => {
      expect(screen.getByText("拒绝词条")).toBeInTheDocument()
    })
    // 不填意见直接确认：阻断且不发请求
    fireEvent.click(screen.getByRole("button", { name: "确认拒绝" }))
    await waitFor(() => {
      expect(screen.getByText("拒绝必须填写审核意见。")).toBeInTheDocument()
    })
    expect(reviewSpy).not.toHaveBeenCalled()
  })
})
