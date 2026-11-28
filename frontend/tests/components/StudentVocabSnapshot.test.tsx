import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ModulesService, VocabularyService } from "@/client"
import { StudentVocabSnapshot } from "@/components/Practice/StudentVocabSnapshot"
import { I18nProvider } from "@/lib/i18n"

/**
 * 学生成长页的单词课快照：只在开通时出现，失败静默隐藏，不影响口语区。
 */
function renderSnapshot() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const rootRoute = createRootRoute({
    component: () => <StudentVocabSnapshot code="DEMO01" />,
  })
  const routes = [
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/vocab/$code",
      component: () => null,
    }),
  ]
  const router = createRouter({
    routeTree: rootRoute.addChildren(routes),
    history: createMemoryHistory({ initialEntries: ["/me/DEMO01"] }),
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  localStorage.setItem("access_token", "mock-token")
  localStorage.setItem("esa:role", "student")
  vi.restoreAllMocks()
})

describe("学生单词课快照", () => {
  it("开通时展示真实计数", async () => {
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking", "vocabulary"],
      statuses: [],
    } as never)
    vi.spyOn(VocabularyService, "readReviewStats").mockResolvedValue({
      tracked_count: 42,
      due_count: 7,
      reviewed_today_count: 12,
      learning_count: 10,
      review_count: 32,
      recognition_count: 25,
      spelling_count: 17,
    } as never)

    renderSnapshot()

    expect(await screen.findByText("单词课")).toBeInTheDocument()
    expect(await screen.findByText("42")).toBeInTheDocument()
    expect(screen.getByText("7")).toBeInTheDocument()
    expect(screen.getByText("12")).toBeInTheDocument()
  })

  it("取数失败时整块隐藏，不抛错", async () => {
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking", "vocabulary"],
      statuses: [],
    } as never)
    vi.spyOn(VocabularyService, "readReviewStats").mockRejectedValue(
      new Error("boom"),
    )

    const { container } = renderSnapshot()

    await new Promise((r) => setTimeout(r, 50))
    expect(container.textContent).not.toContain("单词课")
  })

  it("未开通单词课：不出现、不请求接口", async () => {
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking"],
      statuses: [],
    } as never)
    const statsSpy = vi.spyOn(VocabularyService, "readReviewStats")

    const { container } = renderSnapshot()

    await new Promise((r) => setTimeout(r, 50))
    expect(container.textContent).not.toContain("单词课")
    expect(statsSpy).not.toHaveBeenCalled()
  })
})
