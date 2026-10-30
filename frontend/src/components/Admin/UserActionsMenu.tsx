import { useMutation, useQueryClient } from "@tanstack/react-query"
import { EllipsisVertical, Power, PowerOff } from "lucide-react"
import { useState } from "react"

import { type UserPublic, UsersService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"
import DeleteUser from "./DeleteUser"
import EditUser from "./EditUser"

interface UserActionsMenuProps {
  user: UserPublic
}

export const UserActionsMenu = ({ user }: UserActionsMenuProps) => {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const { user: currentUser } = useAuth()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const toggleActiveMutation = useMutation({
    mutationFn: (next: boolean) =>
      UsersService.updateUser({
        user_id: user.id,
        userUpdate: { is_active: next },
      }),
    onSuccess: (_data, next) => {
      showSuccessToast(
        next
          ? t({ zh: "账号已启用", en: "Account enabled" })
          : t({
              zh: "账号已禁用（无法登录；数据保留，可随时启用恢复）",
              en: "Account disabled (cannot sign in; data kept, re-enable anytime)",
            }),
      )
      void queryClient.invalidateQueries({ queryKey: ["users"] })
    },
    onError: (error) => showErrorToast(extractErrorMessage(error)),
  })

  if (user.id === currentUser?.id) {
    return null
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t({
            zh: `用户操作：${user.full_name || user.email}`,
            en: `User actions: ${user.full_name || user.email}`,
          })}
        >
          <EllipsisVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <EditUser user={user} onSuccess={() => setOpen(false)} />
        {user.is_active ? (
          <DropdownMenuItem
            onSelect={(e) => e.preventDefault()}
            onClick={() => toggleActiveMutation.mutate(false)}
          >
            <PowerOff />
            {t({ zh: "禁用账号", en: "Disable" })}
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem
            onSelect={(e) => e.preventDefault()}
            onClick={() => toggleActiveMutation.mutate(true)}
          >
            <Power />
            {t({ zh: "启用账号", en: "Enable" })}
          </DropdownMenuItem>
        )}
        <DeleteUser
          id={user.id}
          label={user.username ?? user.email ?? undefined}
          onSuccess={() => setOpen(false)}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
