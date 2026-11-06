import { Play } from "lucide-react"
import type { PlanAttempt, PlanItem } from "@/client"
import { RubricBlock } from "@/components/Practice/FeedbackCard"
import { SkippedSpans } from "@/components/Practice/SkippedSpans"
import { TeacherFeedbackBlock } from "@/components/Practice/TeacherFeedbackBlock"
import VocabBlock from "@/components/Practice/VocabBlock"
import { WordAlignment } from "@/components/Practice/WordAlignment"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { useI18n } from "@/lib/i18n"
import { ITEM_TYPE_LABELS } from "@/lib/terms"

export function RoundItemCard({
  item,
  attempt,
  index,
  onSaveUpgrades,
  onReplay,
}: {
  item: PlanItem
  attempt: PlanAttempt
  index: number
  onSaveUpgrades?: (texts: string[]) => Promise<boolean>
  onReplay: () => void
}) {
  const { t } = useI18n()
  return (
    <Card key={item.id}>
      <CardHeader>
        <CardDescription>
          {index + 1}.{" "}
          {t(
            ITEM_TYPE_LABELS[item.type] ?? {
              zh: item.type,
              en: item.type,
            },
          )}
          {item.sentence_index != null &&
            item.sentence_total != null &&
            ` · ${t({
              zh: `第 ${item.sentence_index}/${item.sentence_total} 句`,
              en: `Sentence ${item.sentence_index}/${item.sentence_total}`,
            })}`}
        </CardDescription>
        <CardTitle className="text-sm leading-relaxed font-medium whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
          {item.text}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm leading-relaxed">
          <span className="text-muted-foreground">
            {t({ zh: "转写：", en: "Transcript:" })}
          </span>
          {attempt.transcript || t({ zh: "（无）", en: "(none)" })}
        </p>
        {attempt.word_alignment ? (
          <WordAlignment
            reference={attempt.item_text ?? item.text}
            alignment={attempt.word_alignment}
          />
        ) : (
          <SkippedSpans
            reference={attempt.item_text ?? item.text}
            transcript={attempt.transcript}
            itemType={item.type}
          />
        )}
        <Separator />
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <span className="text-2xl font-bold tabular-nums">
            {t({ zh: "参考分", en: "Score" })} {attempt.overall ?? "–"}
          </span>
          {attempt.previous &&
            typeof attempt.previous.overall === "number" &&
            attempt.overall != null && (
              <span
                className={
                  attempt.overall >= attempt.previous.overall
                    ? "text-emerald-600"
                    : "text-red-600"
                }
              >
                {t({ zh: "上次", en: "Last" })}{" "}
                <span className="tabular-nums">{attempt.previous.overall}</span>{" "}
                · {attempt.overall - attempt.previous.overall >= 0 ? "↑" : "↓"}{" "}
                <span className="tabular-nums">
                  {Math.abs(attempt.overall - attempt.previous.overall)}
                </span>
              </span>
            )}
          {item.type !== "question" && (
            <span className="text-muted-foreground">
              {t({ zh: "完整度", en: "Completeness" })}{" "}
              {attempt.completeness ?? "–"} ·{" "}
              {t({ zh: "流利度", en: "Fluency" })} {attempt.fluency ?? "–"}
            </span>
          )}
        </div>
        <TeacherFeedbackBlock attempt={attempt} />
        {attempt.advice && attempt.advice.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {attempt.advice.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
        {item.type === "question" && (
          <>
            <RubricBlock
              rubric={attempt.rubric}
              engine=""
              onSaveUpgrades={onSaveUpgrades}
            />
            <VocabBlock vocab={attempt.vocab} />
          </>
        )}
        {attempt.attempt_id && (
          <Button variant="secondary" size="sm" onClick={onReplay}>
            <Play />
            {t({ zh: "回听这一题", en: "Replay this item" })}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
