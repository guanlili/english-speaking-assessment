import type { ReactNode } from "react"
import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
export function TeachingShell({ children }: { children: ReactNode }) {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b bg-card/95 px-4 backdrop-blur">
          <SidebarTrigger className="-ml-1 text-muted-foreground" />
          <span className="ml-2 text-sm font-semibold">口语教学</span>
          <span className="ml-auto rounded-full bg-secondary px-3 py-1 text-xs text-primary">
            教师工作空间
          </span>
        </header>
        <main className="flex-1 bg-background p-4 md:p-8">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}
