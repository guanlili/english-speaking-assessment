import type { PlanItem } from "@/client"
import { useI18n } from "@/lib/i18n"

/** 练习进度步骤条：当前题橙色、已完成主色、未开始边框色。 */
export default function StepProgressBar({
  items,
  currentIndex,
  isItemDone,
}: {
  items: PlanItem[]
  currentIndex: number
  isItemDone: (item: PlanItem) => boolean
}) {
  const { t } = useI18n()
  const questions = items.filter((item) => item.type !== "instruction")
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={questions.length}
      aria-valuenow={questions.filter(isItemDone).length}
      className="flex items-center gap-2"
      aria-label={t({ zh: "练习进度", en: "Practice progress" })}
    >
      {questions.map((item) => {
        const done = isItemDone(item)
        return (
          <span
            key={item.id}
            className={
              item.id === items[currentIndex]?.id
                ? "h-1.5 flex-1 rounded-full bg-orange-400"
                : done
                  ? "h-1.5 flex-1 rounded-full bg-primary"
                  : "h-1.5 flex-1 rounded-full bg-border"
            }
          />
        )
      })}
    </div>
  )
}
