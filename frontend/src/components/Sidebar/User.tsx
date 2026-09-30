import { Link as RouterLink } from "@tanstack/react-router"
import { ChevronsUpDown, LogOut, Settings } from "lucide-react"

import type { UserPublic } from "@/client"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"
import { getInitials } from "@/utils"

interface UserInfoProps {
  fullName?: string | null
  email?: string | null
  compact?: boolean
}

function UserInfo({ fullName, email, compact = false }: UserInfoProps) {
  const { t } = useI18n()
  const displayName =
    fullName?.trim() ||
    email?.split("@")[0] ||
    t({ zh: "我的账户", en: "My Account" })

  return (
    <div className="flex w-full min-w-0 items-center gap-2.5">
      <Avatar className="size-8 shrink-0 rounded-lg" aria-hidden="true">
        <AvatarFallback className="rounded-lg border border-primary/10 bg-secondary text-xs font-semibold text-primary">
          {getInitials(displayName)}
        </AvatarFallback>
      </Avatar>
      <div
        className={
          compact ? "sr-only" : "flex min-w-0 flex-col items-start gap-0.5"
        }
      >
        <p className="w-full truncate text-sm font-medium">{displayName}</p>
        <p className="w-full truncate text-xs text-muted-foreground">{email}</p>
      </div>
    </div>
  )
}

export function User({ user }: { user: UserPublic | null | undefined }) {
  const { t } = useI18n()
  const { logout } = useAuth()
  const { isMobile, setOpenMobile, state } = useSidebar()
  const isCompact = state === "collapsed" && !isMobile

  if (!user) return null

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="rounded-lg data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
              aria-label={t({ zh: "账户菜单", en: "Account menu" })}
              tooltip={t({ zh: "账户菜单", en: "Account menu" })}
              data-testid="user-menu"
            >
              <UserInfo
                fullName={user.full_name}
                email={user.email}
                compact={isCompact}
              />
              {!isCompact && (
                <ChevronsUpDown
                  aria-hidden="true"
                  className="ml-auto size-3.5 text-muted-foreground"
                />
              )}
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-60 rounded-xl p-1.5"
            side={isMobile ? "top" : "right"}
            align="end"
            sideOffset={8}
          >
            <DropdownMenuLabel className="p-2 font-normal">
              <UserInfo fullName={user.full_name} email={user.email} />
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild className="rounded-md px-2 py-2.5">
              <RouterLink to="/settings" onClick={handleMenuClick}>
                <Settings aria-hidden="true" />
                {t({ zh: "个人设置", en: "Settings" })}
              </RouterLink>
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={logout}
              variant="destructive"
              className="rounded-md px-2 py-2.5"
            >
              <LogOut aria-hidden="true" />
              {t({ zh: "退出登录", en: "Sign Out" })}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
