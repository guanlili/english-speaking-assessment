import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { VocabularyService } from "@/client"
import { useI18n } from "@/lib/i18n"

/**
 * 学生加入 / 退出榜单；成功后失效本班词汇相关查询（首页卡与详情页同步刷新）。
 * 仅教师可见或整班关闭期间后端返回 403，前端映射成双语提示，不透出 detail。
 */
export function useParticipation(code: string) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (joined: boolean) =>
      VocabularyService.updateParticipation({
        code: code.toUpperCase(),
        vocabularyParticipationUpdate: { joined },
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["vocab", code] }),
    onError: () =>
      toast.error(
        t({
          zh: "操作失败，请稍后再试。",
          en: "Couldn't update your participation. Please try again later.",
        }),
      ),
  })
}
