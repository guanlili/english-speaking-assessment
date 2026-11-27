import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ModulesService, VocabularyService } from "@/client"
import { StudentCourseCards } from "@/components/Practice/StudentCourseCards"
import { I18nProvider } from "@/lib/i18n"

/**
 * 学生端「我的课程」：口语课/单词课并列，按已购课程显隐。
 * 课程未开通整卡不出现；单词课取数失败只降级自己那张卡。
 */
function renderCards(speakingDone = 0, speakingTotal = 3) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const rootRoute = createRootRoute({
    component: () => (
      <StudentCourseCards
        code="DEMO01"
        speakingDone={speakingDone}
        speakingTotal={speakingTotal}
      />
    ),
  })
  const routes = [
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/p/$code",
      component: () => null,
    }),
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/vocab/$code",
      component: () => null,
    }),
  ]
  const router = createRouter({
    routeTree: rootRoute.addChildren(routes),
    history: createMemoryHistory({ initialEntries: ["/p/DEMO01"] }),
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

function loginStudent() {
  localStorage.setItem("access_token", "mock-token")
  localStorage.setItem("esa:role", "student")
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  vi.restoreAllMocks()
})

describe("学生端我的课程卡片", () => {
  it("双开：两门课都出现，各带自己的进度与入口", async () => {
    loginStudent()
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking", "vocabulary"],
      statuses: [],
    })
    vi.spyOn(VocabularyService, "readVocabToday").mockResolvedValue({
      assignment: {
        id: "a1",
        classroom_id: "c1",
        title: "测试任务",
        mode: "practice",
        prompt_types: ["meaning"],
        status: "published",
        version_no: 1,
        word_count: 10,
        due_at: null,
        opens_at: null,
        duration_minutes: null,
        pass_line: 60,
        grades_published_at: null,
        answers_published_at: null,
        published_at: "2026-11-28T00:00:00Z",
        archived_at: null,
        created_by: null,
      },
      items: [],
    } as never)

    renderCards(0, 3)

    await waitFor(() =>
      expect(screen.getByText("我的课程")).toBeInTheDocument(),
    )
    expect(screen.getByText("口语课")).toBeInTheDocument()
    expect(screen.getByText("单词课")).toBeInTheDocument()
    expect(screen.getByText("今日练习 0 / 3")).toBeInTheDocument()
    expect(
      await screen.findByText("今日任务 10 词", {}, { timeout: 3000 }),
    ).toBeInTheDocument()
  })

  it("只开口语：单词课整卡不出现，也不请求词汇接口", async () => {
    loginStudent()
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking"],
      statuses: [],
    })
    const vocabSpy = vi.spyOn(VocabularyService, "readVocabToday")

    renderCards(2, 3)

    await waitFor(() => expect(screen.getByText("口语课")).toBeInTheDocument())
    expect(screen.queryByText("单词课")).not.toBeInTheDocument()
    expect(vocabSpy).not.toHaveBeenCalled()
  })

  it("单词课取数失败：只降级这张卡，口语课仍然展示", async () => {
    loginStudent()
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking", "vocabulary"],
      statuses: [],
    })
    vi.spyOn(VocabularyService, "readVocabToday").mockRejectedValue(
      new Error("boom"),
    )

    renderCards(1, 3)

    expect(
      await screen.findByText("暂时不可用", {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    expect(screen.getByText("口语课")).toBeInTheDocument()
  })
})
