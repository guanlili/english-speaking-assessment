import { createFileRoute } from "@tanstack/react-router"
import { RoundResultPage } from "@/components/Practice/RoundResultPage"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/exam/$code/result")({
  component: RoundResultPage,
  validateSearch: (
    search: Record<string, unknown>,
  ): { explore?: string; session?: string; review?: string } => {
    // session：练习页在录音/完成时钉住的实际会话，结果绑定该轮而非当前活动计划
    // review=1：从历史列表进入，只读回看——禁止再跳回答题页
    if (typeof search.session === "string")
      return {
        session: search.session,
        ...(search.review === "1" ? { review: "1" } : {}),
      }
    if (typeof search.explore === "string") return { explore: search.explore }
    return {}
  },
  head: () => ({
    meta: [{ title: `本轮结果 / Round Results - ${APP_NAME}` }],
  }),
})
