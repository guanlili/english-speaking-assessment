import {
  BookOpen,
  GraduationCap,
  Home,
  ListChecks,
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
import useAuth from "@/hooks/useAuth"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [{ icon: Home, title: "Dashboard", path: "/" }]

const adminItems: Item[] = [
  { icon: Users, title: "Admin", path: "/admin" },
  { icon: BookOpen, title: "篇目管理", path: "/admin/passages" },
  { icon: ListChecks, title: "情景与问法", path: "/admin/scenarios" },
  { icon: GraduationCap, title: "分级词表", path: "/admin/wordlist" },
  { icon: UsersRound, title: "课堂码", path: "/admin/classrooms" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const items = currentUser?.is_superuser
    ? [...baseItems, ...adminItems]
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
