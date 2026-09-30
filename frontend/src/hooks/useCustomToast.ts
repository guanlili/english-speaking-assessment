import { useCallback } from "react"
import { toast } from "sonner"
import { useI18n } from "@/lib/i18n"

const useCustomToast = () => {
  const { t } = useI18n()
  const showSuccessToast = useCallback(
    (description: string) => {
      toast.success(t({ zh: "操作成功", en: "Done" }), { description })
    },
    [t],
  )

  const showErrorToast = useCallback(
    (description: string) => {
      toast.error(t({ zh: "操作未完成", en: "Action failed" }), { description })
    },
    [t],
  )

  return { showSuccessToast, showErrorToast }
}

export default useCustomToast
