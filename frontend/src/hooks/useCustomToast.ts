import { useCallback } from "react"
import { toast } from "sonner"

const useCustomToast = () => {
  const showSuccessToast = useCallback((description: string) => {
    toast.success("操作成功", {
      description,
    })
  }, [])

  const showErrorToast = useCallback((description: string) => {
    toast.error("操作未完成", {
      description,
    })
  }, [])

  return { showSuccessToast, showErrorToast }
}

export default useCustomToast
