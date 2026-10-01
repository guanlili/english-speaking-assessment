import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { isStudentLoggedIn, mustChangePassword } from "@/hooks/useAuth"

/**
 * /vocab/$code 的布局路由：词汇任务首页在 index，拼写练习在 /vocab/$code/practice。
 * 学生登录守卫与 /p/$code 一致。
 */
export const Route = createFileRoute("/vocab/$code")({
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
