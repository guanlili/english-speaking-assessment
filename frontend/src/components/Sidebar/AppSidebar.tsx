import { useRouterState } from "@tanstack/react-router"
import {
  BookA,
  ChevronDown,
  FolderArchive,
  Layers,
  LayoutDashboard,
  Library,
  Megaphone,
  MessageSquareQuote,
  School,
  ShieldCheck,
  UserRoundCog,
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
import { useChangelogHasNew } from "@/hooks/useChangelog"
import { useExports } from "@/hooks/useExports"
import { useModules } from "@/hooks/useModules"
import { COURSES } from "@/lib/courses"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"
import { filterItemsByModule, type Item, isItemActive, Main } from "./Main"
import { User } from "./User"

// 共享底座：班级是口语课、单词课共用的组织单位，不随课程开关隐藏。
const baseItems: Item[] = [
  {
    icon: School,
    title: { zh: "我的课堂", en: "My Classrooms" },
    path: "/classrooms",
  },
]

// 口语课：题目与录音是这门课的教学资产。
const speakingItems: Item[] = [
  {
    icon: Library,
    title: { zh: "题目库", en: "Question Bank" },
    path: "/create",
    module: "speaking",
  },
  {
    icon: FolderArchive,
    title: { zh: "录音导出", en: "Audio Export" },
    path: "/exports",
    module: "speaking",
  },
]

// 校级管理员在口语课下额外维护单元与句型。
const speakingAdminItems: Item[] = [
  {
    icon: Layers,
    title: { zh: "单元管理", en: "Units" },
    path: "/admin/units",
    module: "speaking",
  },
  {
    icon: MessageSquareQuote,
    title: { zh: "句型库", en: "Sentence Frames" },
    path: "/admin/sentenceframes",
    module: "speaking",
  },
]

// 单词课：词库管理归校级管理员；教师在自己的课堂内发词汇任务。
const vocabularyItems: Item[] = [
  {
    icon: BookA,
    title: { zh: "词库管理", en: "Word Books" },
    path: "/admin/vocabbooks",
    module: "vocabulary",
  },
]

// 仅平台运营（B3 身份拆分）：大盘/用户/词表目录/单元/句型/课堂管理
const adminOnlyItems: Item[] = [
  {
    icon: LayoutDashboard,
    title: { zh: "平台大盘", en: "Dashboard" },
    path: "/admin/dashboard",
  },
  {
    icon: Users,
    title: { zh: "用户与权限", en: "Users & Permissions" },
    path: "/admin",
  },
  {
    icon: BookA,
    title: { zh: "五级词库", en: "Leveled Word Source" },
    path: "/admin/vocablevels",
  },
  {
    icon: ShieldCheck,
    title: { zh: "授权台账", en: "License Ledger" },
    path: "/admin/vocabulary-licenses",
  },
  {
    icon: UsersRound,
    title: { zh: "课堂管理", en: "Classrooms" },
    path: "/admin/classrooms",
  },
  {
    icon: School,
    title: { zh: "学校管理", en: "Schools" },
    path: "/admin/schools",
  },
]

// 校级管理员：学校业务（成员管理），课程内容入口已按课程归组到上方。
const schoolAdminItems: Item[] = [
  {
    icon: UserRoundCog,
    title: { zh: "教师管理", en: "Teacher Accounts" },
    path: "/school/members",
  },
]

export function AppSidebar() {
  const { t } = useI18n()
  const { user: currentUser } = useAuth()
  const hasChangelogNew = useChangelogHasNew()
  const role = cachedRole()
  const isOperator = role === "operator"
  // 双值兼容：旧会话缓存/旧 token 的 admin 直到重登（C5b 改名过渡）
  const isSchoolAdmin = role === "school_admin" || role === "admin"
  const isSchoolStaff = role === "teacher" || isSchoolAdmin
  const exportJobs = useExports(isSchoolStaff)
  const unseenExports = exportJobs.data?.unseen_ready ?? 0
  const { hasModule } = useModules(isSchoolStaff)
  const filterByModule = (entries: Item[]) =>
    filterItemsByModule(entries, hasModule)
  const currentPath = useRouterState({
    select: (state) => state.location.pathname,
  })

  const changelogItem: Item = {
    icon: Megaphone,
    title: { zh: "平台更新", en: "What's New" },
    path: "/changelog",
    dot: hasChangelogNew,
  }

  // 课程板块：按已购课程分组渲染；未开通的整块隐藏（不是置灰占位）。
  const speakingCourseNav = filterByModule([
    ...speakingItems.map((item) =>
      item.path === "/exports" && unseenExports > 0
        ? { ...item, badge: unseenExports }
        : item,
    ),
    ...(isSchoolAdmin ? speakingAdminItems : []),
  ])
  const vocabularyCourseNav = isSchoolAdmin
    ? filterByModule(vocabularyItems)
    : []

  const teachingNav = isSchoolStaff
    ? [...baseItems, changelogItem]
    : isOperator
      ? [changelogItem]
      : baseItems

  const adminSectionItems = isOperator
    ? adminOnlyItems
    : isSchoolAdmin
      ? schoolAdminItems
      : []

  const isAdminActive =
    adminSectionItems.some((item) => isItemActive(item.path, currentPath)) ||
    [...speakingAdminItems, ...vocabularyItems].some((item) =>
      isItemActive(item.path, currentPath),
    )

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-5 py-7 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-0">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent className="gap-4 pb-4 group-data-[collapsible=icon]:overflow-y-auto">
        <Main
          items={teachingNav}
          label={
            isOperator ? TERMS.learningHub : { zh: "教学", en: "Teaching" }
          }
        />
        {speakingCourseNav.length > 0 && (
          <Main items={speakingCourseNav} label={COURSES.speaking.name} />
        )}
        {vocabularyCourseNav.length > 0 && (
          <Main items={vocabularyCourseNav} label={COURSES.vocabulary.name} />
        )}
        <p className="mx-5 border-l border-sidebar-border pl-3 text-[11px] leading-6 text-muted-foreground group-data-[collapsible=icon]:hidden">
          {t({
            zh: "口语课练开口，单词课练积累，共用同一个班级。",
            en: "Speaking builds expression, vocabulary builds range — one class, many courses.",
          })}
        </p>
        {adminSectionItems.length > 0 && (
          <div className="mt-4 border-t border-sidebar-border pt-4">
            {/* 新的管理页面默认展开，原生 details 仍允许手动收起。 */}
            <details
              key={currentPath}
              open={isAdminActive}
              className="group/admin group-data-[collapsible=icon]:hidden"
            >
              <summary className="mx-2 mb-2 flex cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-muted-foreground outline-none transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring [&::-webkit-details-marker]:hidden">
                <span className={isAdminActive ? "text-primary" : undefined}>
                  {isOperator
                    ? t({ zh: "平台设置", en: "Platform Settings" })
                    : t({ zh: "校内管理", en: "School Settings" })}
                </span>
                <span className="text-[10px] font-normal text-muted-foreground">
                  {isOperator
                    ? t({ zh: "运营", en: "Operator" })
                    : t({ zh: "管理员", en: "Admin" })}
                </span>
                <ChevronDown
                  aria-hidden="true"
                  className="ml-auto size-3.5 -rotate-90 transition-transform group-open/admin:rotate-0 motion-reduce:transition-none"
                />
              </summary>
              <Main items={adminSectionItems} />
            </details>
            <div className="hidden group-data-[collapsible=icon]:block">
              <Main items={adminSectionItems} />
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
