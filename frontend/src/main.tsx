import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { ApiError, OpenAPI } from "./client"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import "./index.css"
import { routeTree } from "./routeTree.gen"

OpenAPI.BASE = import.meta.env.VITE_API_URL
OpenAPI.TOKEN = async () => {
  return localStorage.getItem("access_token") || ""
}

const handleApiError = (error: Error) => {
  // 只在 401（token 无效/过期）时登出；403 是"已登录但权限不足"，
  // 一并登出会把正常用户误踢下线（例如访问一个无权限的资源）
  if (error instanceof ApiError && error.status === 401) {
    const body = error.body as { detail?: unknown } | null
    const detail = typeof body?.detail === "string" ? body.detail : ""
    // 登录接口的 401（密码错误）不属于任何身份失效，走教师分支静默处理
    const isLoginCall = error.url.includes("/login/access-token")
    // 学生凭证失效：错误文案明确提到学生凭证/重新进入课堂时才清除，
    // 避免其他接口的 401 误把学生登录态清掉
    const isStudentCredentialFailure =
      !isLoginCall &&
      (detail.includes("学生凭证") ||
        detail.includes("重新进入课堂") ||
        detail.includes("缺少凭证") ||
        detail.includes("凭证无效"))
    if (isStudentCredentialFailure) {
      // 学生入班凭证失效（过期/课堂被重建）：清掉本地身份，
      // 重载后由各学生页跳回 /j/$code 加入页，而不是跳教师登录
      for (const key of Object.keys(localStorage)) {
        if (key.startsWith("esa:student:")) localStorage.removeItem(key)
      }
      window.location.reload()
      return
    }
    localStorage.removeItem("access_token")
    // 整页跳转而非 SPA 路由：应用完全重载会重建 queryClient，
    // 天然清空全部缓存与在途请求，与主动退出（useAuth.logout 的
    // cancelQueries + clear）等效
    window.location.href = "/login"
  }
}
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 5 * 60_000,
    },
  },
  queryCache: new QueryCache({
    onError: handleApiError,
  }),
  mutationCache: new MutationCache({
    onError: handleApiError,
  }),
})

const router = createRouter({ routeTree })
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider defaultTheme="light" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <Toaster richColors closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
