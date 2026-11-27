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
import { ModuleDeniedPanel } from "@/components/Teaching/ModuleDeniedPanel"
import { useModules } from "@/hooks/useModules"
import { I18nProvider } from "@/lib/i18n"
import { moduleGuardState } from "@/lib/module-filter"

/** 与 t.$code/index.tsx 路由守卫同一套接线：useModules → moduleGuardState → 分支渲染。 */
function GuardHarness() {
  const { hasModule, isPending, isError } = useModules()
  const guard = moduleGuardState({ isPending, isError }, hasModule, "speaking")
  if (guard === "loading") {
    return <div role="status">模块加载中</div>
  }
  if (guard === "denied") {
    return <ModuleDeniedPanel module="speaking" />
  }
  return <div>课堂教学内容</div>
}

function renderHarness() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const rootRoute = createRootRoute({ component: GuardHarness })
  const classroomsRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/classrooms",
    component: () => null,
  })
  const routeTree = rootRoute.addChildren([classroomsRoute])
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/t/DEMO01"] }),
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

describe("教师口语入口守卫", () => {
  it("未购 speaking：不渲染教学内容，展示拦截页与回课堂列表入口", async () => {
    loginTeacher()
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: [],
      statuses: [],
    })

    renderHarness()

    await waitFor(() =>
      expect(screen.getByText("本校暂未开通口语模块。")).toBeInTheDocument(),
    )
    expect(screen.queryByText("课堂教学内容")).not.toBeInTheDocument()
    expect(screen.getByText("回课堂列表")).toBeInTheDocument()
  })

  it("已购 speaking：放行渲染教学内容，不出现拦截页", async () => {
    loginTeacher()
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking"],
      statuses: [],
    })

    renderHarness()

    await waitFor(() =>
      expect(screen.getByText("课堂教学内容")).toBeInTheDocument(),
    )
    expect(screen.queryByText("本校暂未开通口语模块。")).not.toBeInTheDocument()
  })

  it("模块请求失败：保守拦截，不渲染教学内容", async () => {
    loginTeacher()
    vi.spyOn(ModulesService, "readModulesMe").mockRejectedValue(
      new Error("network"),
    )

    renderHarness()

    await waitFor(() =>
      expect(screen.getByText("本校暂未开通口语模块。")).toBeInTheDocument(),
    )
    expect(screen.queryByText("课堂教学内容")).not.toBeInTheDocument()
  })

  it("清单加载中：展示骨架态，不渲染教学内容", async () => {
    loginTeacher()
    let resolveModules: (value: {
      modules: string[]
      statuses: never[]
    }) => void = () => {}
    vi.spyOn(ModulesService, "readModulesMe").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveModules = resolve
        }),
    )

    renderHarness()

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("模块加载中"),
    )
    expect(screen.queryByText("课堂教学内容")).not.toBeInTheDocument()
    resolveModules({ modules: ["speaking"], statuses: [] })
  })
})
