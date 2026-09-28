import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { UsersService } from "@/client"

/** 教师可用的内容管理子路由（出题用）；其余（用户/课堂管理）仅管理员 */
const TEACHER_ALLOWED = [
  "/admin/passages",
  "/admin/scenarios",
  "/admin/questions",
]

/**
 * /admin 的布局路由：用户管理在 index，内容管理在 /admin/passages 等子路由。
 * 权限：管理员全部可进；教师仅限内容四页（三种题型的出题与管理）。
 */
export const Route = createFileRoute("/_layout/admin")({
  beforeLoad: async ({ location }) => {
    const token = localStorage.getItem("access_token")
    if (!token) {
      throw redirect({ to: "/login" })
    }
    try {
      const user = await UsersService.readUserMe()
      if (!user.is_superuser) {
        const allowed =
          user.role === "teacher" &&
          TEACHER_ALLOWED.some((path) => location.pathname.startsWith(path))
        if (!allowed) {
          throw redirect({ to: "/" })
        }
      }
    } catch (err) {
      if ((err as { redirect?: unknown }).redirect) throw err
      throw redirect({ to: "/login" })
    }
  },
  component: () => <Outlet />,
})
