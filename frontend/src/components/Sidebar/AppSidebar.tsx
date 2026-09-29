import { useRouterState } from "@tanstack/react-router"
import {
  ChevronDown,
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
  SidebarMenu,
} from "@/components/ui/sidebar"
import useAuth, { cachedRole } from "@/hooks/useAuth"
import { type Item, isItemActive, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: School, title: "我的课堂", path: "/classrooms" },
]

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
        <Main items={items} label="教学工作台" />
        <p className="mx-5 border-l border-sidebar-border pl-3 text-[11px] leading-6 text-muted-foreground group-data-[collapsible=icon]:hidden">
          课前准备，课堂练习，课后回顾。
          <br />
          把更多时间，留给学生开口。
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
                  平台设置
                </span>
                <span className="text-[10px] font-normal text-muted-foreground">
                  管理员
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
        </SidebarMenu>
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
