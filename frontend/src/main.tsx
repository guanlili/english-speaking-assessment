import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { lazy, StrictMode, Suspense } from "react"
import ReactDOM from "react-dom/client"
import { ApiError, OpenAPI } from "./client"
import RoutePending from "./components/Pending/RoutePending"
import { ThemeProvider } from "./components/theme-provider"
import "./index.css"
import { routeTree } from "./routeTree.gen"

// 前端错误上报（学生端 JS 异常生产不可见的问题）：默认关闭，
// 服务器 .env 配置 VITE_SENTRY_DSN 后经 compose build args 在构建期生效。
// 动态 import：未配 DSN 时不打包进首屏，配了也在首帧之后加载
// （代价是 init 之前的极早期错误不上报，可接受）
if (import.meta.env.VITE_SENTRY_DSN) {
  void import("@sentry/react").then((Sentry) => {
    Sentry.init({
      dsn: import.meta.env.VITE_SENTRY_DSN,
      environment: import.meta.env.MODE,
      tracesSampleRate: 0.1,
    })
  })
}

// Toaster 纯展示容器且几乎总在首帧之后才需要（toast 由交互触发）：
// lazy 拆出 entry，sonner + radix dialog 一串都不进首屏关键路径
const Toaster = lazy(() =>
  import("./components/ui/sonner").then((m) => ({ default: m.Toaster })),
)

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

// 路由级统一等待态：懒加载路由 chunk / loader pending 时展示骨架
const router = createRouter({
  routeTree,
  defaultPendingComponent: () => <RoutePending />,
})
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
        <Suspense fallback={null}>
          <Toaster richColors closeButton />
        </Suspense>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
