import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ModulesService } from "@/client"
import { useModules } from "@/hooks/useModules"

/**
 * useModules 是前端导航显隐与直连拦截的唯一模块清单来源，口径对齐服务端
 * /modules/me：缺行/关闭/未到生效时间均不计入；平台运营不发本端点请求。
 * 这里锁定：
 * 1. 后端返回的 key 才判 true，其余模块按未购处理；
 * 2. 双开/空清单与服务端返回一一对应；
 * 3. 运营身份与 disabled 场景不触发请求，避免运营侧误判 403。
 */

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

function login(role: "teacher" | "operator" = "teacher") {
  localStorage.setItem("access_token", "mock-token")
  localStorage.setItem("esa:role", role)
}

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe("useModules", () => {
  it("只返回后端下发的模块：speaking 开、vocabulary 关", async () => {
    login("teacher")
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking"],
    })

    const { result } = renderHook(() => useModules(), { wrapper })
    await act(async () => {
      await vi.waitFor(() => expect(result.current.isSuccess).toBe(true))
    })

    expect(result.current.hasModule("speaking")).toBe(true)
    expect(result.current.hasModule("vocabulary")).toBe(false)
    expect(ModulesService.readModulesMe).toHaveBeenCalledTimes(1)
  })

  it("双开时两个模块都可用", async () => {
    login("teacher")
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: ["speaking", "vocabulary"],
    })

    const { result } = renderHook(() => useModules(), { wrapper })
    await act(async () => {
      await vi.waitFor(() => expect(result.current.isSuccess).toBe(true))
    })

    expect(result.current.hasModule("speaking")).toBe(true)
    expect(result.current.hasModule("vocabulary")).toBe(true)
  })

  it("空清单视为两模块均未购", async () => {
    login("teacher")
    vi.spyOn(ModulesService, "readModulesMe").mockResolvedValue({
      modules: [],
    })

    const { result } = renderHook(() => useModules(), { wrapper })
    await act(async () => {
      await vi.waitFor(() => expect(result.current.isSuccess).toBe(true))
    })

    expect(result.current.hasModule("speaking")).toBe(false)
    expect(result.current.hasModule("vocabulary")).toBe(false)
  })

  it("平台运营身份不请求模块清单", () => {
    login("operator")
    vi.spyOn(ModulesService, "readModulesMe")

    const { result } = renderHook(() => useModules(), { wrapper })

    expect(ModulesService.readModulesMe).not.toHaveBeenCalled()
    expect(result.current.hasModule("speaking")).toBe(false)
    expect(result.current.hasModule("vocabulary")).toBe(false)
  })

  it("enabled=false 时不请求模块清单", () => {
    login("teacher")
    vi.spyOn(ModulesService, "readModulesMe")

    renderHook(() => useModules(false), { wrapper })

    expect(ModulesService.readModulesMe).not.toHaveBeenCalled()
  })
})
