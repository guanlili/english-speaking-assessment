import type { PlanItem } from "@/client"
import { useI18n } from "@/lib/i18n"
import { ITEM_TYPE_LABELS } from "@/lib/terms"

export default function ExamGroupedProgress({
  items,
  currentIndex,
}: {
  items: PlanItem[]
  currentIndex: number
}) {
  const { t } = useI18n()
  const types = ["passage", "repeat", "question"] as const
  return (
    <fieldset
      className="grid gap-3 sm:grid-cols-3"
      aria-label={t({ zh: "考试进度", en: "Exam progress" })}
    >
      {types.map((type) => {
        const group = items
          .map((item, index) => ({ item, index }))
          .filter((v) => v.item.type === type)
        if (!group.length) return null
        return (
          <div key={type} className="min-w-0 space-y-2">
            <p className="text-sm">
              {t(ITEM_TYPE_LABELS[type])}{" "}
              {group.filter((v) => v.index < currentIndex).length}/
              {group.length}
            </p>
            <div className="flex flex-wrap gap-1">
              {group.map(({ item, index }) => (
                <span
                  key={item.id}
                  aria-current={index === currentIndex ? "step" : undefined}
                  className={`h-2 w-5 rounded ${index < currentIndex ? "bg-primary" : index === currentIndex ? "bg-primary/50" : "bg-muted"}`}
                />
              ))}
            </div>
          </div>
        )
      })}
    </fieldset>
  )
}
