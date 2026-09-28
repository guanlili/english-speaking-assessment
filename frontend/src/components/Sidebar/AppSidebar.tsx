import {
  BookOpen,
  CircleHelp,
  GraduationCap,
  Home,
  Layers,
  ListChecks,
  PenLine,
  School,
  Users,
  UsersRound,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth, { cachedRole } from "@/hooks/useAuth"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Home, title: "教学工作台", path: "/" },
  { icon: School, title: "我的课堂", path: "/classrooms" },
] as Item[]

const createHubItem: Item[] = [
  { icon: PenLine, title: "出题中心", path: "/create" },
]

// 出题四页：教师与管理员都可见（三种题型的出题入口）
const contentItems: Item[] = [
  { icon: BookOpen, title: "篇目与朗读题", path: "/admin/passages" },
  { icon: ListChecks, title: "情景主题", path: "/admin/scenarios" },
  { icon: CircleHelp, title: "问答题库", path: "/admin/questions" },
  { icon: Layers, title: "学习单元", path: "/admin/units" },
]

// 仅管理员：用户/词表/课堂管理
const adminOnlyItems: Item[] = [
  { icon: Users, title: "用户与权限", path: "/admin" },
  { icon: GraduationCap, title: "分级词表", path: "/admin/wordlist" },
  { icon: UsersRound, title: "课堂管理", path: "/admin/classrooms" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const isTeacherSide = currentUser?.is_superuser || cachedRole() === "teacher"
  const items = currentUser?.is_superuser
    ? [...baseItems, ...createHubItem, ...contentItems, ...adminOnlyItems]
    : isTeacherSide
      ? [...baseItems, ...createHubItem, ...contentItems]
      : baseItems

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
