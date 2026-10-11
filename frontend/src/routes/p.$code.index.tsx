import { createFileRoute } from "@tanstack/react-router"
import { PracticeSessionPage } from "@/components/Practice/PracticeSessionPage"
import { APP_NAME } from "@/config"

export const Route = createFileRoute("/p/$code/")({
  component: () => <PracticeSessionPage mode="practice" />,
  validateSearch: (
    search: Record<string, unknown>,
  ): {
    focus?: string
    next?: boolean
    explore?: string
    session?: string
  } => {
    // 只序列化真值，避免 URL 出现 ?focus=undefined&next=false
    const result: {
      focus?: string
      next?: boolean
      explore?: string
      session?: string
    } = {}
    if (typeof search.focus === "string") result.focus = search.focus
    if (search.next === true) result.next = true
    if (typeof search.explore === "string") result.explore = search.explore
    if (typeof search.session === "string") result.session = search.session
    return result
  },
  head: () => ({
    meta: [{ title: `今日练习 / Today's Practice - ${APP_NAME}` }],
  }),
})
