import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AdminService, VocabularyService } from "@/client"
import { ContentReviewPanel } from "@/components/Vocabulary/ContentReviewPanel"
import { I18nProvider } from "@/lib/i18n"

/**
 * 审核面板交互：
 * - 队列渲染待审数量、来源（AI 单独标）与审核状态徽章；
 * - 拒绝必须填意见：空意见提交阻断并给出双语校验提示；
 * - 平台运营只读走 admin 跨校端点，不调学校端点，且无审核/编辑动作；
 * - 非待审行不可勾选、无通过/拒绝按钮，仅保留编辑；
 * - 筛选变化清空勾选，避免误提交已隐藏词条；
 * - 「全部」状态筛选显式传 status=all（后端显式约定），pending/rejected 原样透传；
 * - 服务调用走既有 SDK，测试不手写 API URL。
 *
 * 注：桌面表格与窄屏卡片两套标记同时在 DOM 中（CSS 切换显隐），
 * 同一控件在查询结果里会出现两次，断言按 getAll/长度 2 处理。
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
    {
      word_id: "w-3",
      headword: "desk",
      part_of_speech: "n.",
      meaning_zh: "书桌",
      source: "teacher",
      review_status: "approved",
      version: 3,
      book_id: "b-1",
      book_title: "Class A",
      reviewed_at: "2026-11-23T09:00:00Z",
    },
  ],
  total: 3,
  pending_count: 1,
  rejected_count: 1,
  approved_count: 1,
}

function renderPanel(options: { readonly?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ContentReviewPanel readonly={options.readonly ?? false} />
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

    expect(await screen.findAllByText("apple")).toHaveLength(2)
    expect(screen.getAllByText("bank")).toHaveLength(2)
    expect(screen.getByText(/待审 1/)).toBeInTheDocument()
    // AI 来源单独标记（下拉选项 + 两套视图徽章）
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

  it("只读（平台运营）走 admin 端点，不调学校端点，且无审核/编辑动作", async () => {
    const adminSpy = vi
      .spyOn(AdminService, "adminListVocabularyReviews")
      .mockResolvedValue(REVIEW_LIST)
    const vocabSpy = vi
      .spyOn(VocabularyService, "listVocabularyReviews")
      .mockResolvedValue(REVIEW_LIST)
    renderPanel({ readonly: true })

    expect(await screen.findAllByText("apple")).toHaveLength(2)
    expect(adminSpy).toHaveBeenCalledTimes(1)
    expect(vocabSpy).not.toHaveBeenCalled()
    // 只读模式不渲染通过/拒绝/编辑入口
    expect(screen.queryByRole("button", { name: /通过|拒绝|编辑/ })).toBeNull()
  })

  it("非待审行不可勾选、无通过/拒绝按钮，仅保留编辑入口", async () => {
    vi.spyOn(VocabularyService, "listVocabularyReviews").mockResolvedValue(
      REVIEW_LIST,
    )
    renderPanel()

    await screen.findAllByText("apple")
    // 待审行有勾选框与审核按钮（两套视图各一份）
    expect(screen.getAllByLabelText("选择 apple")).toHaveLength(2)
    expect(screen.getAllByRole("button", { name: "通过" })).toHaveLength(2)
    expect(screen.getAllByRole("button", { name: "拒绝" })).toHaveLength(2)

    // 已拒绝 / 已通过行没有勾选框与审核按钮，但保留编辑（两套视图各一份）
    expect(screen.queryAllByLabelText("选择 bank")).toHaveLength(0)
    expect(screen.queryAllByLabelText("选择 desk")).toHaveLength(0)
    expect(screen.getAllByRole("button", { name: "编辑" })).toHaveLength(6)
  })

  it("「全部」筛选显式传 status=all，pending/rejected 原样透传", async () => {
    const spy = vi
      .spyOn(VocabularyService, "listVocabularyReviews")
      .mockResolvedValue(REVIEW_LIST)
    renderPanel()

    await screen.findAllByText("apple")
    // 默认待审视图
    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(
        expect.objectContaining({ status: "pending" }),
      )
    })

    // 切到「全部」：SDK 真的发出 status=all（后端显式约定，不过滤状态）
    fireEvent.change(screen.getByLabelText("状态筛选"), {
      target: { value: "all" },
    })
    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(
        expect.objectContaining({ status: "all" }),
      )
    })

    // 已拒绝筛选原样透传
    fireEvent.change(screen.getByLabelText("状态筛选"), {
      target: { value: "rejected" },
    })
    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(
        expect.objectContaining({ status: "rejected" }),
      )
    })
  })

  it("筛选条件变化时清空已选，不会把隐藏词条提交批量审核", async () => {
    vi.spyOn(VocabularyService, "listVocabularyReviews").mockResolvedValue(
      REVIEW_LIST,
    )
    renderPanel()

    await screen.findAllByText("apple")
    fireEvent.click(screen.getAllByLabelText("选择 apple")[0])
    await waitFor(() => {
      expect(screen.getByText(/已选 1 条待审/)).toBeInTheDocument()
    })

    // 切换来源筛选为 AI：勾选应被清空
    fireEvent.change(screen.getByLabelText("来源筛选"), {
      target: { value: "ai" },
    })
    await waitFor(() => {
      expect(screen.getByText(/已选 0 条待审/)).toBeInTheDocument()
    })
  })
})
