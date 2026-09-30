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
import type { BiString } from "@/lib/bi"
import { useI18n } from "@/lib/i18n"

export type Item = {
  icon: LucideIcon
  title: BiString
  path: string
}

interface MainProps {
  items: Item[]
  label?: BiString
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
  const { t } = useI18n()
  const { isMobile, setOpenMobile } = useSidebar()
  const currentPath = useRouterState({
    select: (state) => state.location.pathname,
  })

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  const labelText = label ? t(label) : undefined

  return (
    <SidebarGroup>
      {labelText && (
        <SidebarGroupLabel className="mb-2 px-3 text-[10px] font-medium tracking-widest text-muted-foreground">
          {labelText}
        </SidebarGroupLabel>
      )}
      <SidebarGroupContent>
        <nav
          aria-label={
            labelText ?? t({ zh: "平台设置", en: "Platform Settings" })
          }
        >
          <SidebarMenu className="gap-1.5">
            {items.map((item) => {
              const isActive = isItemActive(item.path, currentPath)

              return (
                <SidebarMenuItem key={item.path}>
                  <SidebarMenuButton
                    className="relative h-11 gap-3 rounded-lg px-3 text-sm text-sidebar-foreground/80 transition-colors hover:text-sidebar-foreground data-[active=true]:bg-primary data-[active=true]:font-semibold data-[active=true]:text-primary-foreground data-[active=true]:shadow-sm data-[active=true]:hover:bg-primary/90 data-[active=true]:hover:text-primary-foreground motion-reduce:transition-none"
                    tooltip={t(item.title)}
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
                        {t(item.title)}
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
