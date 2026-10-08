import { useMutation } from "@tanstack/react-query"
import { toast } from "sonner"
import { VocabularyService } from "@/client"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { TERMS } from "@/lib/terms"

/** 主动交卷按钮（测验）：终结答卷，幂等 */
export function SubmitQuizButton({
  sessionId,
  disabled,
  onDone,
}: {
  sessionId: string | null
  disabled?: boolean
  onDone: () => void
}) {
  const { t } = useI18n()
  const submit = useMutation({
    mutationFn: () =>
      VocabularyService.submitQuizSession({ sessionId: sessionId as string }),
    onSuccess: () => {
      toast.success(t({ zh: "已交卷。", en: "Submitted." }))
      onDone()
    },
    onError: () => {
      toast.error(
        t({ zh: "交卷失败，请重试。", en: "Submit failed — please retry." }),
      )
    },
  })
  return (
    <Button
      size="sm"
      disabled={disabled || submit.isPending}
      onClick={() => submit.mutate()}
    >
      {submit.isPending
        ? t({ zh: "交卷中…", en: "Submitting…" })
        : t(TERMS.submitQuiz)}
    </Button>
  )
}
