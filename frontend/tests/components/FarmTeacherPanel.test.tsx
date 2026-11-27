import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ApiError, type FarmBoardSummary, VocabularyService } from "@/client"
import { FarmTeacherPanel } from "@/components/Teaching/VocabTasks/FarmTeacherPanel"
import { I18nProvider } from "@/lib/i18n"

/**
 * 教师端专注农场只读概览：聚合指标、徽章分布与收获榜；
 * 面板不触发种植/收获/改分等写接口。
 */

const SUMMARY: FarmBoardSummary = {
  participants: 12,
  mature_plots: 4,
  harvested_total: 9,
  badge_counts: [
    { key: "first_round", label: "初次开口", count: 8 },
    { key: "farm_first_harvest", label: "首次收获", count: 3 },
  ],
  top_harvesters: [{ display_name: "小红", harvest_count: 5 }],
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <FarmTeacherPanel code="DEMO01" />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  localStorage.setItem("esa:role", "teacher")
  vi.restoreAllMocks()
})

describe("FarmTeacherPanel", () => {
  it("汇总数据：展示参与/成熟/收获指标、徽章分布与收获榜，标注只读概览", async () => {
    vi.spyOn(VocabularyService, "readTeacherFarmSummary").mockResolvedValue(
      SUMMARY,
    )

    renderPanel()

    await waitFor(() =>
      expect(screen.getByText("初次开口")).toBeInTheDocument(),
    )
    expect(screen.getByText("只读概览")).toBeInTheDocument()
    expect(screen.getByText("12")).toBeInTheDocument()
    expect(screen.getByText("4")).toBeInTheDocument()
    expect(screen.getByText("9")).toBeInTheDocument()
    expect(screen.getByText("初次开口")).toBeInTheDocument()
    expect(screen.getByText("小红")).toBeInTheDocument()
  })

  it("空汇总：展示空态文案，不渲染指标卡片", async () => {
    vi.spyOn(VocabularyService, "readTeacherFarmSummary").mockResolvedValue({})

    renderPanel()

    await waitFor(() =>
      expect(
        screen.getByText("暂无农场数据，学生完成练习后会在这里汇总。"),
      ).toBeInTheDocument(),
    )
  })

  it("403：展示授权教师提示并提供重试入口", async () => {
    vi.spyOn(VocabularyService, "readTeacherFarmSummary").mockRejectedValue(
      new ApiError(403, { detail: "forbidden" }, ""),
    )

    renderPanel()

    await waitFor(() =>
      expect(
        screen.getByText(/你还不是这个课堂的授权教师/),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText("重新加载")).toBeInTheDocument()
  })
})
