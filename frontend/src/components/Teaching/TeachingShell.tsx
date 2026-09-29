import { useRouterState } from "@tanstack/react-router"
import type { ReactNode } from "react"
import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"

interface WorkspaceContext {
  title: string
  section: string
  description: string
}

const workspaceRoutes: Record<string, WorkspaceContext> = {
  "/classrooms": {
    title: "我的课堂",
    section: "课堂教学",
    description: "从课前准备，到每一次开口。",
  },
  "/create": {
    title: "题目库",
    section: "教学准备",
    description: "为下一堂课，准备好题目。",
  },
  "/admin/passages": {
    title: "篇目管理",
    section: "题目库",
    description: "文章朗读与听句复述的教学材料。",
  },
  "/admin/scenarios": {
    title: "问答主题与出题",
    section: "题目库",
    description: "让情景问答贴近课堂主题。",
  },
  "/admin/questions": {
    title: "情景问答题库",
    section: "题目库",
    description: "整理题目，为课堂留出更多对话。",
  },
  "/admin/units": {
    title: "单元管理",
    section: "平台设置",
    description: "组织单元与主题，连接课堂内容。",
  },
  "/admin": {
    title: "用户与权限",
    section: "平台设置",
    description: "管理平台成员与访问权限。",
  },
  "/admin/wordlist": {
    title: "分级词表",
    section: "平台设置",
    description: "维护词汇分析使用的参考词表。",
  },
  "/admin/classrooms": {
    title: "课堂管理",
    section: "平台设置",
    description: "管理课堂码与课堂访问。",
  },
  "/settings": {
    title: "个人设置",
    section: "我的账户",
    description: "管理个人资料与账户安全。",
  },
}

function getWorkspaceContext(pathname: string): WorkspaceContext {
  const path = pathname.replace(/\/+$/, "") || "/"
  if (path.startsWith("/t/")) {
    const isStudentDetail = path.split("/")[3] === "s"
    return {
      title: isStudentDetail ? "进步轨迹" : "课堂面板",
      section: "我的课堂",
      description: isStudentDetail
        ? "看见每一位学生的练习与进步。"
        : "安排今日练习，听见课堂里的进步。",
    }
  }
  return (
    workspaceRoutes[path] ?? {
      title: "教学工作空间",
      section: "SpeakUp · 开口说",
      description: "让每一次开口，都有收获。",
    }
  )
}

export function TeachingShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const context = getWorkspaceContext(pathname)

  return (
    <SidebarProvider>
      <a
        href="#teaching-main"
        className="sr-only z-50 rounded-lg bg-primary text-sm font-medium text-primary-foreground shadow-lg focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:px-4 focus:py-3 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
      >
        跳至主要内容
      </a>
      <AppSidebar />
      <div className="relative flex min-w-0 flex-1 flex-col bg-background">
        <header className="sticky top-0 z-10 shrink-0 border-b border-border/80 bg-background/95 px-4 backdrop-blur-sm sm:px-6 lg:px-10">
          <div className="mx-auto flex min-h-20 max-w-7xl items-center gap-3 py-3 sm:gap-4">
            <SidebarTrigger
              aria-label="切换导航栏"
              className="size-9 shrink-0 rounded-lg border border-border/80 text-muted-foreground hover:text-foreground"
            />
            <div className="min-w-0 space-y-1">
              <p className="text-[11px] font-medium tracking-widest text-muted-foreground">
                {context.section}
              </p>
              <p className="truncate text-sm font-semibold tracking-tight text-foreground sm:text-base">
                {context.title}
              </p>
            </div>
            <p className="ml-auto hidden border-l border-border pl-5 text-xs leading-relaxed text-muted-foreground lg:block">
              {context.description}
            </p>
          </div>
        </header>
        <main
          id="teaching-main"
          tabIndex={-1}
          aria-label={context.title}
          className="min-w-0 flex-1 scroll-mt-24 px-4 py-6 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring sm:px-6 sm:py-8 lg:px-10 lg:py-10"
        >
          <div className="mx-auto w-full min-w-0 max-w-7xl">{children}</div>
        </main>
        <Footer />
      </div>
    </SidebarProvider>
  )
}
