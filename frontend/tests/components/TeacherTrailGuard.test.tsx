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

import { ClassesService, ModulesService } from "@/client"
import { I18nProvider } from "@/lib/i18n"
import { Route as TrailRoute } from "@/routes/t.$code.s.$studentId"

/**
 * 教师进步轨迹子路由 `/t/$code/s/$studentId` 的 speaking 守卫。
 * 挂载真实路由组件，复用 useModules / moduleGuardState / ModuleDeniedPanel：
 * - 未购 speaking：展示拦截页，且不发轨迹 / 面板数据请求（避免 403 噪音）；
 * - 清单加载中：骨架态，不闪拦截页，也不发数据请求；
 * - 已购 speaking：放行，轨迹 / 面板请求正常发出。
 */
function renderTrailPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const rootRoute = createRootRoute()
  const trailRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/t/$code/s/$studentId",
    component: TrailRoute.options.component,
  })
  const routeTree = rootRoute.addChildren([trailRoute])
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({
      initialEntries: ["/t/DEMO01/s/student-1"],
    }),
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

function spyDataRequests() {
  const trailSpy = vi.spyOn(ClassesService, "readStudentTrail")
  const boardSpy = vi.spyOn(ClassesService, "readClassBoard")
  return { trailSpy, boardSpy }
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem("esa:lang", "zh")
  vi.restoreAllMocks()
})

describe("教师进步轨迹子路由守卫", () => {
  it("未购 speaking：显示拦截文案与回课堂列表入口，不发数据请求", async () => {
    loginTeacher()
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: [],
      statuses: [],
    })
    const { trailSpy, boardSpy } = spyDataRequests()

    renderTrailPage()

    await waitFor(() =>
      expect(screen.getByText("本校暂未开通口语模块。")).toBeInTheDocument(),
    )
    expect(screen.getByText("回课堂列表")).toBeInTheDocument()
    expect(trailSpy).not.toHaveBeenCalled()
    expect(boardSpy).not.toHaveBeenCalled()
  })

  it("清单加载中：展示骨架态，不闪拦截页，也不发数据请求", async () => {
    loginTeacher()
    vi.spyOn(ModulesService, "readModulesMe").mockImplementation(
      () => new Promise(() => {}),
    )
    const { trailSpy, boardSpy } = spyDataRequests()

    renderTrailPage()

    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument())
    expect(screen.queryByText("本校暂未开通口语模块。")).not.toBeInTheDocument()
    expect(trailSpy).not.toHaveBeenCalled()
    expect(boardSpy).not.toHaveBeenCalled()
  })

  it("已购 speaking：放行加载轨迹，拦截页不出现，数据请求正常发出", async () => {
    loginTeacher()
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking"],
      statuses: [],
    })
    const { trailSpy, boardSpy } = spyDataRequests()
    // 保持轨迹 / 面板请求挂起，只验证放行后请求已发出，不渲染后续子面板。
    trailSpy.mockImplementation(() => new Promise(() => {}))
    boardSpy.mockImplementation(() => new Promise(() => {}))

    renderTrailPage()

    await waitFor(() =>
      expect(screen.getByText("正在加载进步轨迹…")).toBeInTheDocument(),
    )
    expect(screen.queryByText("本校暂未开通口语模块。")).not.toBeInTheDocument()
    expect(trailSpy).toHaveBeenCalled()
    expect(boardSpy).toHaveBeenCalled()
  })
})
