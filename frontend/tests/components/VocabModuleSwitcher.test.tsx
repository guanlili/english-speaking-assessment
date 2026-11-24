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

import { ModulesService } from "@/client"
import { VocabModuleSwitcher } from "@/components/Teaching/VocabModuleSwitcher"
import { I18nProvider } from "@/lib/i18n"

/**
 * 词汇页头部「口语 / 词汇」切换：口语入口按 useModules 清单显隐。
 * 只买 vocabulary（B 校）时不渲染口语链接，避免点进被路由守卫弹回；双开时保留。
 */
function renderSwitcher() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const rootRoute = createRootRoute({
    component: () => <VocabModuleSwitcher code="DEMO01" />,
  })
  const boardRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/t/$code",
    component: () => null,
  })
  const vocabRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/t/$code/vocab",
    component: () => null,
  })
  const routeTree = rootRoute.addChildren([boardRoute, vocabRoute])
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/t/DEMO01/vocab"] }),
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

function loginTeacher() {
  localStorage.setItem("access_token", "mock-token")
  localStorage.setItem("esa:role", "teacher")
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  vi.restoreAllMocks()
})

describe("词汇页模块切换器", () => {
  it("只买 vocabulary：不渲染「口语练习」链接，保留词汇入口", async () => {
    loginTeacher()
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["vocabulary"],
      statuses: [],
    })

    renderSwitcher()

    await waitFor(() =>
      expect(screen.getByText("词汇学习")).toBeInTheDocument(),
    )
    expect(
      screen.queryByRole("link", { name: "口语练习" }),
    ).not.toBeInTheDocument()
  })

  it("双开：保留「口语练习」链接指向口语面板", async () => {
    loginTeacher()
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking", "vocabulary"],
      statuses: [],
    })

    renderSwitcher()

    await waitFor(() =>
      expect(screen.getByRole("link", { name: "口语练习" })).toHaveAttribute(
        "href",
        "/t/DEMO01",
      ),
    )
    expect(screen.getByText("词汇学习")).toBeInTheDocument()
  })
})
