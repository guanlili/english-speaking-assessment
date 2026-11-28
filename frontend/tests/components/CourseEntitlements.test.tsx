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
import { CourseEntitlements } from "@/components/Teaching/CourseEntitlements"
import { I18nProvider } from "@/lib/i18n"

/**
 * 校管「课程与授权」：按课程包展示状态、到期与内容入口。
 * 口径：状态徽标复用同一状态机；未开通课程不给内容入口。
 */
function renderEntitlements() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const rootRoute = createRootRoute({
    component: () => <CourseEntitlements />,
  })
  const routes = [
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/admin/units",
      component: () => null,
    }),
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/admin/sentenceframes",
      component: () => null,
    }),
    createRoute({
      getParentRoute: () => rootRoute,
      path: "/admin/vocabbooks",
      component: () => null,
    }),
  ]
  const router = createRouter({
    routeTree: rootRoute.addChildren(routes),
    history: createMemoryHistory({ initialEntries: ["/admin/courses"] }),
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
  localStorage.setItem("esa:role", "school_admin")
  vi.restoreAllMocks()
})

describe("校管课程与授权", () => {
  it("双开：两门课都显示使用中、到期日与内容入口", async () => {
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking", "vocabulary"],
      statuses: [
        {
          module_key: "speaking",
          state: "active",
          enabled: true,
          grant_type: "manual",
          expires_at: "2027-06-30T00:00:00Z",
          days_left: 214,
        },
        {
          module_key: "vocabulary",
          state: "active",
          enabled: true,
          grant_type: "manual",
          expires_at: "2027-06-30T00:00:00Z",
          days_left: 214,
        },
      ],
    } as never)

    renderEntitlements()

    await waitFor(() => expect(screen.getByText("口语课")).toBeInTheDocument())
    expect(screen.getByText("单词课")).toBeInTheDocument()
    expect(screen.getAllByText("使用中").length).toBe(2)
    expect(screen.getAllByText("2027-06-30").length).toBe(2)
    expect(screen.getByText("单元管理")).toBeInTheDocument()
    expect(screen.getByText("词库管理")).toBeInTheDocument()
  })

  it("单词课未开通：显示未开通且不出现内容入口", async () => {
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking"],
      statuses: [
        {
          module_key: "speaking",
          state: "active",
          enabled: true,
          grant_type: "manual",
          expires_at: null,
          days_left: null,
        },
      ],
    } as never)

    renderEntitlements()

    await waitFor(() => expect(screen.getByText("未开通")).toBeInTheDocument())
    expect(screen.queryByText("词库管理")).not.toBeInTheDocument()
    expect(screen.getByText("单元管理")).toBeInTheDocument()
  })
})
