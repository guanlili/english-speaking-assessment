import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { type VocabularyMasteryReport, VocabularyService } from "@/client"
import { MasteryCard } from "@/components/Teaching/VocabTasks/MasteryCard"
import { I18nProvider } from "@/lib/i18n"

/**
 * 班级掌握度卡：分段徽标 / 无数据显示 – / 到期提示 / 时间窗切换重取。
 * 口径断言：无首答不折算 0%；到期数是条目数提示。
 */
const REPORT: VocabularyMasteryReport = {
  classroom_code: "DEMO01",
  generated_at: "2026-11-24T00:00:00Z",
  window_days: 30,
  scope: "assignment",
  assignment_id: "11111111-1111-1111-1111-111111111111",
  answered_count: 3,
  correct_first_count: 2,
  accuracy_rate: 67,
  low_count: 1,
  mid_count: 1,
  high_count: 0,
  no_data_count: 1,
  fsrs_new: 1,
  fsrs_learning: 1,
  fsrs_review: 1,
  due_count: 1,
  words: [
    {
      word_id: "11111111-1111-1111-1111-111111111111",
      headword: "apple",
      meaning_zh: "苹果",
      answered_count: 2,
      correct_first_count: 1,
      accuracy_rate: 50,
      band: "low",
      fsrs_new: 0,
      fsrs_learning: 1,
      fsrs_review: 0,
      due_count: 1,
    },
    {
      word_id: "22222222-2222-2222-2222-222222222222",
      headword: "banana",
      meaning_zh: "香蕉",
      answered_count: 1,
      correct_first_count: 1,
      accuracy_rate: 100,
      band: "high",
      fsrs_new: 0,
      fsrs_learning: 0,
      fsrs_review: 1,
      due_count: 0,
    },
    {
      word_id: "33333333-3333-3333-3333-333333333333",
      headword: "cat",
      meaning_zh: "猫",
      answered_count: 0,
      correct_first_count: 0,
      accuracy_rate: null,
      band: "no_data",
      fsrs_new: 1,
      fsrs_learning: 0,
      fsrs_review: 0,
      due_count: 0,
    },
  ],
}

function renderCard(assignmentId: string | null = null) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const spy = vi
    .spyOn(VocabularyService, "readVocabMastery")
    .mockResolvedValue(REPORT)
  render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MasteryCard code="DEMO01" assignmentId={assignmentId} />
      </I18nProvider>
    </QueryClientProvider>,
  )
  return spy
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  vi.restoreAllMocks()
})

describe("MasteryCard", () => {
  it("展示分段、无数据 –、到期提示与 FSRS 条目分布", async () => {
    renderCard()

    expect(await screen.findByText("班级掌握度")).toBeInTheDocument()
    expect(screen.getAllByText("偏弱（<60%）").length).toBeGreaterThan(0)
    expect(screen.getAllByText("较稳（>85%）").length).toBeGreaterThan(0)
    expect(screen.getAllByText("暂无首答").length).toBeGreaterThan(0)

    // 无首答的词正确率显示 –，不出现 0%
    const catRow = screen.getByRole("row", { name: /cat/ })
    expect(catRow).toHaveTextContent("–")
    expect(catRow).not.toHaveTextContent("0%")

    // 到期提示带条目数
    expect(screen.getByText(/1 条复习条目已到期/)).toBeInTheDocument()
    // FSRS 条目：新词 · 学习中 · 待复习
    expect(screen.getByText(/1 · 1 · 1/)).toBeInTheDocument()
  })

  it("切换时间窗后按新 window_days 重新拉取", async () => {
    const spy = renderCard()
    await screen.findByText("班级掌握度")

    fireEvent.change(screen.getByLabelText("时间窗："), {
      target: { value: "7" },
    })

    await waitFor(() => {
      expect(spy).toHaveBeenLastCalledWith(
        expect.objectContaining({ code: "DEMO01", window_days: 7 }),
      )
    })
  })

  it("空数据时给出无首答提示，不渲染词条表", async () => {
    vi.spyOn(VocabularyService, "readVocabMastery").mockResolvedValue({
      ...REPORT,
      words: [],
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <I18nProvider>
          <MasteryCard code="DEMO01" assignmentId={null} />
        </I18nProvider>
      </QueryClientProvider>,
    )

    expect(
      await screen.findByText("该时间窗内暂无首答数据。"),
    ).toBeInTheDocument()
  })
})
