import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import { useI18n } from "@/lib/i18n"

/**
 * 破坏性操作统一确认框（删除单元/篇目/情景、停用课堂等）。
 * 用法：用 open 受控打开；onConfirm 返回 Promise，确认按钮期间转圈。
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmText,
  cancelText,
  destructive = true,
  onOpenChange,
  onConfirm,
}: {
  open: boolean
  title: string
  description: string
  confirmText?: string
  cancelText?: string
  destructive?: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void | Promise<void>
}) {
  const { t } = useI18n()
  const [pending, setPending] = useState(false)
  const resolvedConfirmText = confirmText ?? t({ zh: "确认", en: "Confirm" })
  const resolvedCancelText = cancelText ?? t({ zh: "取消", en: "Cancel" })

  const handleConfirm = async () => {
    setPending(true)
    try {
      await onConfirm()
      onOpenChange(false)
    } catch {
      // 调用者的 mutation 展示错误；失败时保留确认框，允许重试。
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={pending}
            onClick={() => onOpenChange(false)}
          >
            {resolvedCancelText}
          </Button>
          <LoadingButton
            variant={destructive ? "destructive" : "default"}
            loading={pending}
            onClick={() => void handleConfirm()}
          >
            {resolvedConfirmText}
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
