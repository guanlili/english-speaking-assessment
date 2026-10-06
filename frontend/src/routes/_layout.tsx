import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { TeachingShell } from "@/components/Teaching/TeachingShell"
import { cachedRole, isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({ to: "/login" })
    }
    // 学生不进教学管理区：回「我的班级」选班（多班归属）
    if (cachedRole() === "student") {
      throw redirect({ to: "/join" })
    }
  },
})

function Layout() {
  return (
    <TeachingShell>
      <Outlet />
    </TeachingShell>
  )
}
