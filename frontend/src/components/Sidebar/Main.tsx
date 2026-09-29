import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type Item = {
  icon: LucideIcon
  title: string
  path: string
}

interface MainProps {
  items: Item[]
  label?: string
}

export function isItemActive(itemPath: string, pathname: string) {
  const currentPath = pathname.replace(/\/+$/, "") || "/"
  const matches = (path: string) =>
    currentPath === path || currentPath.startsWith(`${path}/`)

  return (
    currentPath === itemPath ||
    (itemPath !== "/admin" && matches(itemPath)) ||
    (itemPath === "/classrooms" && currentPath.startsWith("/t/")) ||
    (itemPath === "/create" &&
      ["/admin/passages", "/admin/scenarios", "/admin/questions"].some(matches))
  )
}

export function Main({ items, label }: MainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const currentPath = useRouterState({
    select: (state) => state.location.pathname,
  })

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <SidebarGroup>
      {label && (
        <SidebarGroupLabel className="mb-2 px-3 text-[10px] font-medium tracking-widest text-muted-foreground">
          {label}
        </SidebarGroupLabel>
      )}
      <SidebarGroupContent>
        <nav aria-label={label || "平台设置"}>
          <SidebarMenu className="gap-1.5">
            {items.map((item) => {
              const isActive = isItemActive(item.path, currentPath)

              return (
                <SidebarMenuItem key={item.path}>
                  <SidebarMenuButton
                    className="relative h-11 gap-3 rounded-lg px-3 text-sm text-sidebar-foreground/80 transition-colors hover:text-sidebar-foreground data-[active=true]:bg-primary data-[active=true]:font-semibold data-[active=true]:text-primary-foreground data-[active=true]:shadow-sm data-[active=true]:hover:bg-primary/90 data-[active=true]:hover:text-primary-foreground motion-reduce:transition-none"
                    tooltip={item.title}
                    isActive={isActive}
                    asChild
                  >
                    <RouterLink
                      to={item.path}
                      activeOptions={{ exact: item.path === "/admin" }}
                      aria-current={isActive ? "page" : undefined}
                      onClick={handleMenuClick}
                    >
                      <item.icon aria-hidden="true" className="size-4" />
                      <span className="group-data-[collapsible=icon]:sr-only">
                        {item.title}
                      </span>
                    </RouterLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              )
            })}
          </SidebarMenu>
        </nav>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
