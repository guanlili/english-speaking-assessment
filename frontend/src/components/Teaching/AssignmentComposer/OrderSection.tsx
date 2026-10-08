import { ChevronDown, ChevronUp } from "lucide-react"
import type {
  AssignmentItemIn,
  InstructionPublic,
  PassageWithSentences,
  ScenarioOut,
  SentenceWithPassage,
} from "@/client"
import { Button } from "@/components/ui/button"
import { assignmentItemKey } from "@/lib/assignment-order"
import { useI18n } from "@/lib/i18n"
import { ITEM_TYPE_LABELS } from "@/lib/terms"

/** 调整作答顺序：上下按钮移动，学生按此顺序练习。 */
export default function OrderSection({
  planItems,
  passages,
  sentences,
  instructions,
  scenarioQuestions,
  onMove,
}: {
  planItems: AssignmentItemIn[]
  passages: PassageWithSentences[]
  sentences: SentenceWithPassage[]
  instructions: InstructionPublic[]
  scenarioQuestions: ScenarioOut["questions"]
  onMove: (index: number, direction: -1 | 1) => void
}) {
  const { t } = useI18n()
  return (
    <section className="space-y-3">
      <h2 className="font-semibold">
        {t({ zh: "调整作答顺序", en: "Arrange Answer Order" })}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t({
          zh: "默认按复述句、问答交替；用上下按钮调整，学生会按此顺序练习。",
          en: "Repeat sentences and Q&A alternate by default. Use the arrows to set the order students follow.",
        })}
      </p>
      <ol className="space-y-2">
        {planItems.map((item, index) => {
          const label =
            item.type === "passage"
              ? passages.find((p) => p.id === item.id)?.title
              : item.type === "repeat"
                ? sentences.find((s) => s.id === item.id)?.text
                : item.type === "instruction"
                  ? (instructions.find((i) => i.id === item.id)?.title ??
                    instructions.find((i) => i.id === item.id)?.text)
                  : scenarioQuestions.find((q) => q.id === item.id)?.text
          return (
            <li
              key={assignmentItemKey(item)}
              className="flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2"
            >
              <span className="w-6 shrink-0 text-sm font-medium">
                {index + 1}.
              </span>
              <span className="min-w-0 flex-1 truncate text-sm">
                {t(
                  ITEM_TYPE_LABELS[item.type] ?? {
                    zh: item.type,
                    en: item.type,
                  },
                )}{" "}
                · {label}
              </span>
              <Button
                variant="outline"
                size="icon-sm"
                disabled={index === 0}
                aria-label={t({
                  zh: `第 ${index + 1} 题上移`,
                  en: `Move item ${index + 1} up`,
                })}
                onClick={() => onMove(index, -1)}
              >
                <ChevronUp />
              </Button>
              <Button
                variant="outline"
                size="icon-sm"
                disabled={index === planItems.length - 1}
                aria-label={t({
                  zh: `第 ${index + 1} 题下移`,
                  en: `Move item ${index + 1} down`,
                })}
                onClick={() => onMove(index, 1)}
              >
                <ChevronDown />
              </Button>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
