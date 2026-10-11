import { createFileRoute } from "@tanstack/react-router"
import { RoundResultPage } from "@/components/Practice/RoundResultPage"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/exam/$code/result")({
  component: RoundResultPage,
  validateSearch: (
    search: Record<string, unknown>,
  ): { explore?: string; session?: string } => {
    // session：练习页在录音/完成时钉住的实际会话，结果绑定该轮而非当前活动计划
    if (typeof search.session === "string") return { session: search.session }
    if (typeof search.explore === "string") return { explore: search.explore }
    return {}
  },
  head: () => ({
    meta: [{ title: `本轮结果 / Round Results - ${APP_NAME}` }],
  }),
})
