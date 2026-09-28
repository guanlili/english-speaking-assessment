import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { isStudentLoggedIn, mustChangePassword } from "@/hooks/useAuth"

/**
 * /p/$code 的布局路由：练习页在 index，结果页在 /p/$code/result。
 * 学生登录守卫：未登录学生跳登录页；批量导入的初始密码先强制改密。
 */
export const Route = createFileRoute("/p/$code")({
  beforeLoad: () => {
    if (!isStudentLoggedIn()) {
      throw redirect({ to: "/login" })
    }
    if (mustChangePassword()) {
      throw redirect({ to: "/change-password" })
    }
  },
  component: () => <Outlet />,
})
