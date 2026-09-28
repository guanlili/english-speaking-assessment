import {
  GraduationCap,
  Layers,
  Library,
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
  { icon: School, title: "我的课堂", path: "/classrooms" },
] as Item[]

const createHubItem: Item[] = [
  { icon: Library, title: "题目库", path: "/create" },
]

// 仅管理员：用户/词表/课堂管理
const adminOnlyItems: Item[] = [
  { icon: Layers, title: "单元管理", path: "/admin/units" },
  { icon: Users, title: "用户与权限", path: "/admin" },
  { icon: GraduationCap, title: "分级词表", path: "/admin/wordlist" },
  { icon: UsersRound, title: "课堂管理", path: "/admin/classrooms" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  // 教师只需理解课堂与题目；系统配置收纳在管理员区域。
  const items =
    currentUser?.is_superuser || cachedRole() === "teacher"
      ? [...baseItems, ...createHubItem]
      : baseItems

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
        <p className="px-5 text-xs leading-6 text-muted-foreground group-data-[collapsible=icon]:hidden">
          课堂里安排练习、查看结果。
          <br />
          题目库里准备三种口语题。
        </p>
        {currentUser?.is_superuser && (
          <details className="mt-6 border-t pt-4 group-data-[collapsible=icon]:hidden">
            <summary className="cursor-pointer px-5 text-xs font-medium text-muted-foreground">
              平台设置 · 管理员
            </summary>
            <Main items={adminOnlyItems} />
          </details>
        )}
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
