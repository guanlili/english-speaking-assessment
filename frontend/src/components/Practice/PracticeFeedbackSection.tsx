import { ArrowRight } from "lucide-react"
import type { AttemptPublic, PlanAttempt, PlanItem } from "@/client"
import FeedbackCard from "@/components/Practice/FeedbackCard"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import {
  isAttemptTerminal,
  nextItemIdAfterCompletion,
} from "@/lib/practice-derive"

/**
 * 逐题反馈区（展示组件）：评分完成后按实际作答的 attempt 展示简短反馈。
 * 「下一题/查看详细总反馈」先在当前题单里选定下一道未完成题（派生计算
 * 在 lib/practice-derive，计划缓存未刷新时也能跳对题）；定位/跳转/重置
 * 等副作用经 onNextItem 交回页面。
 */
export default function PracticeFeedbackSection({
  attempt,
  attemptFailed,
  allDone,
  items,
  attemptByItem,
  currentIndex,
  onRepractice,
  onNextItem,
}: {
  attempt: AttemptPublic
  attemptFailed: boolean
  allDone: boolean
  items: PlanItem[]
  attemptByItem: Map<string, PlanAttempt>
  currentIndex: number
  onRepractice: () => void
  /** 下一道未完成题 id；null 表示没有下一道（调用方跳结果页） */
  onNextItem: (nextItemId: string | null) => void
}) {
  const { t } = useI18n()
  const goNext = () => {
    // 先在当前题单里选定下一道未完成题：计划缓存尚未刷新时，
    // 仅清空 pinnedItemId 会再次定位到刚完成的旧题。
    const nextItemId = nextItemIdAfterCompletion(
      items,
      currentIndex,
      (item) =>
        (item.id === attempt.item_id && isAttemptTerminal(attempt.status)) ||
        isAttemptTerminal(attemptByItem.get(item.id)?.status),
    )
    onNextItem(nextItemId)
  }
  return (
    <FeedbackCard
      attempt={attempt}
      itemType={attempt.item_type as "passage" | "repeat" | "question"}
      onRepractice={onRepractice}
      extraActions={
        !attemptFailed && (
          <Button onClick={goNext}>
            {allDone
              ? t({
                  zh: "查看详细总反馈",
                  en: "View detailed feedback",
                })
              : t({ zh: "下一题", en: "Next item" })}
            <ArrowRight />
          </Button>
        )
      }
    />
  )
}
