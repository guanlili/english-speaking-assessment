import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { UsersService } from "@/client"

/**
 * /admin 的布局路由：用户管理在 index，内容管理在 /admin/passages 等子路由。
 *
 * 在父级 loader 中统一做 superuser 权限校验，子路由无需重复调用接口。
 */
export const Route = createFileRoute("/_layout/admin")({
  beforeLoad: async () => {
    const token = localStorage.getItem("access_token")
    if (!token) {
      throw redirect({ to: "/login" })
    }
    try {
      const user = await UsersService.readUserMe()
      if (!user.is_superuser) {
        throw redirect({ to: "/" })
      }
    } catch {
      throw redirect({ to: "/login" })
    }
  },
  component: () => <Outlet />,
})
