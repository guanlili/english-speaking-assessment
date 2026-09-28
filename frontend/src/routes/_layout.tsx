import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { TeachingShell } from "@/components/Teaching/TeachingShell"
import { cachedRole, isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({ to: "/login" })
    }
    // 学生不进教学管理区：回学生流程（已入班回课堂，否则加入页）
    if (cachedRole() === "student") {
      const { lastJoinedCode } = await import("@/lib/classroom-student")
      const code = lastJoinedCode()
      throw redirect(
        code ? { to: "/home/$code", params: { code } } : { to: "/join" },
      )
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
