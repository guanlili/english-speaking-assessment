import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"

import { UsersService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"
import { extractErrorMessage } from "@/utils"

interface DeleteUserProps {
  id: string
  /** 展示用账号标识（学号/邮箱），警示文案指名道姓 */
  label?: string
  onSuccess: () => void
}

const DeleteUser = ({ id, label, onSuccess }: DeleteUserProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const [password, setPassword] = useState("")
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { t } = useI18n()
  const { handleSubmit } = useForm()

  const mutation = useMutation({
    mutationFn: (targetId: string) =>
      UsersService.deleteUser({
        user_id: targetId,
        userDeleteRequest: { password },
      }),
    onSuccess: () => {
      showSuccessToast(t({ zh: "账号已删除", en: "User deleted successfully" }))
      setIsOpen(false)
      setPassword("")
      onSuccess()
    },
    onError: (error) => showErrorToast(extractErrorMessage(error)),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const onSubmit = async () => {
    mutation.mutate(id)
  }

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(next) => {
        setIsOpen(next)
        if (!next) setPassword("")
      }}
    >
      <DropdownMenuItem
        variant="destructive"
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
      >
        <Trash2 />
        {t({ zh: "删除账号", en: "Delete User" })}
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit(onSubmit)}>
          <DialogHeader>
            <DialogTitle>
              {t({ zh: "删除账号？", en: "Delete this user?" })}
            </DialogTitle>
            <DialogDescription>
              {label ? `${label} — ` : ""}
              {t({
                zh: "将永久删除该账号及其在所有班级的档案、作答记录与成绩，此操作不可恢复。如只是暂时停用，请改用「禁用账号」。",
                en: 'This permanently deletes the account, its profiles in every classroom, and all answer history — this cannot be undone. To suspend temporarily, use "Disable" instead.',
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="delete-user-password">
              {t({
                zh: "输入管理员密码以确认",
                en: "Enter your admin password to confirm",
              })}
            </Label>
            <Input
              id="delete-user-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <DialogFooter className="mt-4">
            <DialogClose asChild>
              <Button variant="outline" disabled={mutation.isPending}>
                {t({ zh: "取消", en: "Cancel" })}
              </Button>
            </DialogClose>
            <LoadingButton
              variant="destructive"
              type="submit"
              disabled={!password}
              loading={mutation.isPending}
            >
              {t({ zh: "永久删除", en: "Delete Permanently" })}
            </LoadingButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default DeleteUser
