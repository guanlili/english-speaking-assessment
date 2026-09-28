import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
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
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b bg-card/95 px-4 backdrop-blur">
          <SidebarTrigger className="-ml-1 text-muted-foreground" />
          <span className="ml-2 text-sm font-semibold">教学管理</span>
          <span className="ml-auto rounded-full bg-secondary px-3 py-1 text-xs text-primary">
            SpeakUp 教师工作空间
          </span>
        </header>
        <main className="flex-1 bg-background p-4 md:p-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}
