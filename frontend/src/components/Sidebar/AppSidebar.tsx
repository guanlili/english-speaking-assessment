import { useRouterState } from "@tanstack/react-router"
import {
  BookA,
  ChevronDown,
  GraduationCap,
  Layers,
  Library,
  MessageSquareQuote,
  School,
  Users,
  UsersRound,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { LanguageToggle } from "@/components/Common/LanguageToggle"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
} from "@/components/ui/sidebar"
import useAuth, { cachedRole } from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"
import { type Item, isItemActive, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  {
    icon: School,
    title: { zh: "我的课堂", en: "My Classrooms" },
    path: "/classrooms",
  },
]

const createHubItem: Item[] = [
  {
    icon: Library,
    title: { zh: "题目库", en: "Question Bank" },
    path: "/create",
  },
]

// 仅管理员：用户/词表/课堂管理
const adminOnlyItems: Item[] = [
  {
    icon: Layers,
    title: { zh: "单元管理", en: "Units" },
    path: "/admin/units",
  },
  {
    icon: Users,
    title: { zh: "用户与权限", en: "Users & Permissions" },
    path: "/admin",
  },
  {
    icon: GraduationCap,
    title: { zh: "分级词表", en: "Word List" },
    path: "/admin/wordlist",
  },
  {
    icon: BookA,
    title: { zh: "五级词库", en: "Leveled Word Source" },
    path: "/admin/vocablevels",
  },
  {
    icon: BookA,
    title: { zh: "词库管理", en: "Word Books" },
    path: "/admin/vocabbooks",
  },
  {
    icon: MessageSquareQuote,
    title: { zh: "句型库", en: "Sentence Frames" },
    path: "/admin/sentenceframes",
  },
  {
    icon: UsersRound,
    title: { zh: "课堂管理", en: "Classrooms" },
    path: "/admin/classrooms",
  },
]

export function AppSidebar() {
  const { t } = useI18n()
  const { user: currentUser } = useAuth()
  const currentPath = useRouterState({
    select: (state) => state.location.pathname,
  })
  const isAdminActive = adminOnlyItems.some((item) =>
    isItemActive(item.path, currentPath),
  )

  // 教师只需理解课堂与题目；系统配置收纳在管理员区域。
  const items =
    currentUser?.is_superuser || cachedRole() === "teacher"
      ? [...baseItems, ...createHubItem]
      : baseItems

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-5 py-7 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-0">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent className="gap-4 pb-4 group-data-[collapsible=icon]:overflow-y-auto">
        <Main
          items={items}
          label={{ zh: "教学工作台", en: "Teaching Workspace" }}
        />
        <p className="mx-5 border-l border-sidebar-border pl-3 text-[11px] leading-6 text-muted-foreground group-data-[collapsible=icon]:hidden">
          {t({
            zh: "课前准备，课堂练习，课后回顾。",
            en: "Prepare before class, practice in class, review after.",
          })}
          <br />
          {t({
            zh: "把更多时间，留给学生开口。",
            en: "Leave more time for students to speak.",
          })}
        </p>
        {currentUser?.is_superuser && (
          <div className="mt-4 border-t border-sidebar-border pt-4">
            {/* 新的管理页面默认展开，原生 details 仍允许手动收起。 */}
            <details
              key={currentPath}
              open={isAdminActive}
              className="group/admin group-data-[collapsible=icon]:hidden"
            >
              <summary className="mx-2 mb-2 flex cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-muted-foreground outline-none transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring [&::-webkit-details-marker]:hidden">
                <span className={isAdminActive ? "text-primary" : undefined}>
                  {t({ zh: "平台设置", en: "Platform Settings" })}
                </span>
                <span className="text-[10px] font-normal text-muted-foreground">
                  {t({ zh: "管理员", en: "Admin" })}
                </span>
                <ChevronDown
                  aria-hidden="true"
                  className="ml-auto size-3.5 -rotate-90 transition-transform group-open/admin:rotate-0 motion-reduce:transition-none"
                />
              </summary>
              <Main items={adminOnlyItems} />
            </details>
            <div className="hidden group-data-[collapsible=icon]:block">
              <Main items={adminOnlyItems} />
            </div>
          </div>
        )}
      </SidebarContent>
      <SidebarFooter className="gap-2 border-t border-sidebar-border p-2 pt-3">
        <SidebarMenu>
          <SidebarAppearance />
          <div className="flex justify-center pt-1">
            <LanguageToggle />
          </div>
        </SidebarMenu>
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
