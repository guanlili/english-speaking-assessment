import { useRouterState } from "@tanstack/react-router"
import type { ReactNode } from "react"
import { Footer } from "@/components/Common/Footer"
import { LanguageToggle } from "@/components/Common/LanguageToggle"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { type BiString, useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

interface WorkspaceContext {
  title: BiString
  section: BiString
  description: BiString
}

const workspaceRoutes: Record<string, WorkspaceContext> = {
  "/classrooms": {
    title: { zh: "我的课堂", en: "My Classrooms" },
    section: { zh: "课堂教学", en: "Classroom Teaching" },
    description: {
      zh: "从课前准备，到每一次开口。",
      en: "From lesson prep to every spoken turn.",
    },
  },
  "/create": {
    title: { zh: "题目库", en: "Question Bank" },
    section: { zh: "教学准备", en: "Teaching Prep" },
    description: {
      zh: "为下一堂课，准备好题目。",
      en: "Prepare questions for your next class.",
    },
  },
  "/admin/passages": {
    title: { zh: "篇目管理", en: "Passages" },
    section: { zh: "题目库", en: "Question Bank" },
    description: {
      zh: "文章朗读与听句复述的教学材料。",
      en: "Teaching materials for Read Aloud and Listen & Repeat.",
    },
  },
  "/admin/scenarios": {
    title: { zh: "问答主题与出题", en: "Q&A Topics & Questions" },
    section: { zh: "题目库", en: "Question Bank" },
    description: {
      zh: "让情景问答贴近课堂主题。",
      en: "Bring Scenario Q&A close to class topics.",
    },
  },
  "/admin/questions": {
    title: { zh: "情景问答题库", en: "Scenario Q&A Bank" },
    section: { zh: "题目库", en: "Question Bank" },
    description: {
      zh: "整理题目，为课堂留出更多对话。",
      en: "Organize questions to leave more room for conversation in class.",
    },
  },
  "/admin/units": {
    title: { zh: "单元管理", en: "Units" },
    section: { zh: "平台设置", en: "Platform Settings" },
    description: {
      zh: "组织单元与主题，连接课堂内容。",
      en: "Organize units and topics to connect classroom content.",
    },
  },
  "/admin": {
    title: { zh: "用户与权限", en: "Users & Permissions" },
    section: { zh: "平台设置", en: "Platform Settings" },
    description: {
      zh: "管理平台成员与访问权限。",
      en: "Manage platform members and access.",
    },
  },
  "/admin/wordlist": {
    title: { zh: "分级词表", en: "Graded Word Lists" },
    section: { zh: "平台设置", en: "Platform Settings" },
    description: {
      zh: "维护词汇分析使用的参考词表。",
      en: "Maintain the reference word lists used by vocabulary analysis.",
    },
  },
  "/admin/vocabbooks": {
    title: { zh: "词库管理", en: "Word Books" },
    section: { zh: "平台设置", en: "Platform Settings" },
    description: {
      zh: "维护公共词库，供教师发布词汇任务。",
      en: "Maintain public word books for teachers to publish vocabulary tasks.",
    },
  },
  "/admin/classrooms": {
    title: { zh: "课堂管理", en: "Classroom Management" },
    section: { zh: "平台设置", en: "Platform Settings" },
    description: {
      zh: "管理课堂码与课堂访问。",
      en: "Manage classroom codes and access.",
    },
  },
  "/settings": {
    title: { zh: "个人设置", en: "Settings" },
    section: { zh: "我的账户", en: "My Account" },
    description: {
      zh: "管理个人资料与账户安全。",
      en: "Manage your profile and account security.",
    },
  },
}

function getWorkspaceContext(pathname: string): WorkspaceContext {
  const path = pathname.replace(/\/+$/, "") || "/"
  if (path.startsWith("/t/")) {
    const isStudentDetail = path.split("/")[3] === "s"
    const isVocab = path.split("/")[3] === "vocab"
    return {
      title: isStudentDetail
        ? TERMS.trailPage
        : isVocab
          ? TERMS.vocabLearning
          : { zh: "课堂面板", en: "Class Dashboard" },
      section: { zh: "我的课堂", en: "My Classrooms" },
      description: isStudentDetail
        ? {
            zh: "看见每一位学生的练习与进步。",
            en: "See each student's practice and progress.",
          }
        : isVocab
          ? {
              zh: "发布词汇任务，看见全班的拼写与错词。",
              en: "Publish vocabulary tasks and see the class's spelling and wrong words.",
            }
          : {
              zh: "安排今日练习，听见课堂里的进步。",
              en: "Assign today's practice and hear the class improve.",
            },
    }
  }
  return (
    workspaceRoutes[path] ?? {
      title: { zh: "教学工作空间", en: "Teaching Workspace" },
      section: { zh: "SpeakUp · 开口说", en: "SpeakUp" },
      description: {
        zh: "让每一次开口，都有收获。",
        en: "Make every attempt to speak count.",
      },
    }
  )
}

export function TeachingShell({ children }: { children: ReactNode }) {
  const { t } = useI18n()
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
        {t({ zh: "跳至主要内容", en: "Skip to main content" })}
      </a>
      <AppSidebar />
      <div className="relative flex min-w-0 flex-1 flex-col bg-background">
        <header className="sticky top-0 z-10 shrink-0 border-b border-border/80 bg-background/95 px-4 backdrop-blur-sm sm:px-6 lg:px-10">
          <div className="mx-auto flex min-h-20 max-w-7xl items-center gap-3 py-3 sm:gap-4">
            <SidebarTrigger
              aria-label={t({ zh: "切换导航栏", en: "Toggle navigation" })}
              className="size-9 shrink-0 rounded-lg border border-border/80 text-muted-foreground hover:text-foreground"
            />
            <div className="min-w-0 space-y-1">
              <p className="text-[11px] font-medium tracking-widest text-muted-foreground">
                {t(context.section)}
              </p>
              <p className="truncate text-sm font-semibold tracking-tight text-foreground sm:text-base">
                {t(context.title)}
              </p>
            </div>
            <p className="ml-auto hidden border-l border-border pl-5 text-xs leading-relaxed text-muted-foreground lg:block">
              {t(context.description)}
            </p>
            <LanguageToggle className="ml-auto lg:ml-4" />
          </div>
        </header>
        <main
          id="teaching-main"
          tabIndex={-1}
          aria-label={t(context.title)}
          className="min-w-0 flex-1 scroll-mt-24 px-4 py-6 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring sm:px-6 sm:py-8 lg:px-10 lg:py-10"
        >
          <div className="mx-auto w-full min-w-0 max-w-7xl">{children}</div>
        </main>
        <Footer />
      </div>
    </SidebarProvider>
  )
}
